"""
End-to-end chat-based data entry: a freeform message gets classified, extracted,
confirmed by the user, rolled into the nightly PDF report, and then re-enters the
normal document pipeline (verify -> process) to become searchable again — the
full loop the app is designed around, exercised with real scheduler functions
and a real RAGSearch instance against the mock in-memory DB.
"""
import json

from models.chat_entry import ChatEntry, ChatStatus
from models.document import Document, ProcessStatus
import services.scheduler as scheduler_module
from RAG_src.search import RAGSearch


def test_add_data_confirm_daily_pdf_and_reprocess_full_loop(
    make_user, db_session, fake_chat_llm, fake_embeddings, fake_document_verdict,
):
    """Chat "sold X" -> confirm -> nightly PDF -> that PDF re-enters and completes the document pipeline."""
    user = make_user(email="chatflow@example.com")
    rag = RAGSearch()

    fake_chat_llm.append(json.dumps({"intent": "add_data"}))
    fake_chat_llm.append(json.dumps({
        "product": "Pen", "quantity": 5, "price_per_unit": 10,
        "total": 50, "type": "sale", "notes": None,
    }))
    extraction = rag.handle_message("Sold 5 pens at 10 each", user_id=user.id)
    assert "Pen" in extraction
    pending = db_session.query(ChatEntry).filter(ChatEntry.user_id == user.id).first()
    assert pending.status == ChatStatus.PENDING

    confirmation = rag.handle_message("yes", user_id=user.id)
    assert "confirmed" in confirmation.lower()
    db_session.refresh(pending)
    assert pending.status == ChatStatus.CONFIRMED

    scheduler_module.generate_daily_pdf()

    assert db_session.query(ChatEntry).filter(ChatEntry.user_id == user.id).count() == 0
    report_doc = db_session.query(Document).filter(Document.user_id == user.id).first()
    assert report_doc is not None
    assert report_doc.process == ProcessStatus.PENDING

    # The generated report now flows back through the normal document pipeline.
    scheduler_module.verify_pending_documents()
    db_session.refresh(report_doc)
    assert report_doc.process == ProcessStatus.PROCESS

    scheduler_module.process_pending_documents()
    db_session.refresh(report_doc)
    assert report_doc.process == ProcessStatus.DONE
    assert report_doc.faiss_ids is not None

    fake_chat_llm.append("You sold 5 pens.")
    answer = rag.search_and_summarize("What did I sell?", user_id=user.id)
    assert answer == "You sold 5 pens."


def test_reject_data_entry_leaves_nothing_for_the_daily_pdf(make_user, db_session, fake_chat_llm):
    """Replying "no" deletes the extracted entry, so the nightly job has nothing to report for that user."""
    user = make_user(email="chatreject@example.com")
    rag = RAGSearch()

    fake_chat_llm.append(json.dumps({"intent": "add_data"}))
    fake_chat_llm.append(json.dumps({"product": "Notebook", "quantity": 2, "total": 40, "type": "sale"}))
    rag.handle_message("Sold 2 notebooks for 40", user_id=user.id)

    rejection = rag.handle_message("no", user_id=user.id)
    assert "rejected" in rejection.lower()
    assert db_session.query(ChatEntry).filter(ChatEntry.user_id == user.id).count() == 0

    scheduler_module.generate_daily_pdf()

    assert db_session.query(Document).filter(Document.user_id == user.id).count() == 0


def test_multiple_confirmed_entries_combine_into_a_single_daily_pdf(make_user, db_session, fake_chat_llm):
    """Two separate confirmed chat entries for the same user are combined into exactly one report document."""
    user = make_user(email="chatmulti@example.com")
    rag = RAGSearch()

    for product, total in [("Pen", 50), ("Notebook", 80)]:
        fake_chat_llm.append(json.dumps({"intent": "add_data"}))
        fake_chat_llm.append(json.dumps({"product": product, "quantity": 1, "total": total, "type": "sale"}))
        rag.handle_message(f"Sold a {product.lower()}", user_id=user.id)
        rag.handle_message("yes", user_id=user.id)

    assert db_session.query(ChatEntry).filter(
        ChatEntry.user_id == user.id, ChatEntry.status == ChatStatus.CONFIRMED,
    ).count() == 2

    scheduler_module.generate_daily_pdf()

    assert db_session.query(ChatEntry).filter(ChatEntry.user_id == user.id).count() == 0
    assert db_session.query(Document).filter(Document.user_id == user.id).count() == 1
