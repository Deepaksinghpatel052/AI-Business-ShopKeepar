"""
End-to-end document lifecycle: upload through the real API, run the real scheduler
functions (verify -> process, and separately the update/reprocess path), and confirm
the result is genuinely searchable through a real RAGSearch + FaissVectorStore.

Only the OpenAI network calls are mocked (fake_embeddings, fake_chat_llm,
fake_document_verdict); PDF parsing, chunking, FAISS read/write, and the DB
transitions all run for real against the mock in-memory DB.
"""
import io
import json

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from models.shop_owner import ShopOwner
from models.document import Document, ProcessStatus
import services.scheduler as scheduler_module
from RAG_src.search import RAGSearch


def get_user_id(db_session, email):
    return db_session.query(ShopOwner).filter(ShopOwner.email == email).first().id


def pdf_bytes(text: str) -> bytes:
    """A real, parseable PDF (not a fake byte string) — the pipeline's real
    PyPDF-based text extraction (used by both load_all_documents and
    is_business_document) needs genuinely extractable content."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.drawString(72, 700, text)
    c.save()
    return buf.getvalue()


def test_upload_verify_process_then_search_finds_it(
    app_client, auth_headers, db_session, fake_document_verdict, fake_embeddings, fake_chat_llm,
):
    """A newly uploaded, accepted document survives the full pipeline and becomes searchable."""
    headers = auth_headers(email="pipeline-a@example.com", password="Passw0rd")
    user_id = get_user_id(db_session, "pipeline-a@example.com")

    upload = app_client.post(
        "/document/upload-file", headers=headers,
        files={"file": ("report.pdf", pdf_bytes("Sales report content."), "application/pdf")},
    )
    assert upload.status_code == 201
    document_id = upload.json()["id"]

    scheduler_module.verify_pending_documents()
    doc = db_session.query(Document).filter(Document.id == document_id).first()
    assert doc.process == ProcessStatus.PROCESS

    scheduler_module.process_pending_documents()
    db_session.refresh(doc)
    assert doc.process == ProcessStatus.DONE
    assert doc.faiss_ids is not None
    assert json.loads(doc.faiss_ids)  # at least one chunk id

    rag = RAGSearch()  # default persist_dir="faiss_store", resolved safely under the isolated tmp cwd
    fake_chat_llm.append("Here is a summary of your sales report.")
    answer = rag.search_and_summarize("What does my report say?", user_id=user_id)

    assert answer == "Here is a summary of your sales report."


def test_rejected_document_never_gets_processed(
    app_client, auth_headers, db_session, fake_document_verdict, fake_embeddings,
):
    """A document the verifier rejects stays REJECTED and process_pending_documents never touches it."""
    headers = auth_headers(email="pipeline-b@example.com", password="Passw0rd")

    upload = app_client.post(
        "/document/upload-file", headers=headers,
        files={"file": ("diary.pdf", pdf_bytes("Dear diary, today I felt happy."), "application/pdf")},
    )
    document_id = upload.json()["id"]

    fake_document_verdict["is_business"] = False
    fake_document_verdict["reason"] = "This looks like a personal diary"

    scheduler_module.verify_pending_documents()
    doc = db_session.query(Document).filter(Document.id == document_id).first()
    assert doc.process == ProcessStatus.REJECTED

    scheduler_module.process_pending_documents()  # should be a no-op for REJECTED docs
    db_session.refresh(doc)
    assert doc.process == ProcessStatus.REJECTED
    assert doc.faiss_ids is None


def test_edit_reprocesses_document_with_fresh_chunks(
    app_client, auth_headers, db_session, fake_document_verdict, fake_embeddings,
):
    """Editing a fully-processed document runs it back through update -> verify -> process with new faiss_ids."""
    headers = auth_headers(email="pipeline-c@example.com", password="Passw0rd")

    upload = app_client.post(
        "/document/upload-file", headers=headers,
        files={"file": ("v1.pdf", pdf_bytes("Original content."), "application/pdf")},
    )
    document_id = upload.json()["id"]

    scheduler_module.verify_pending_documents()
    scheduler_module.process_pending_documents()
    doc = db_session.query(Document).filter(Document.id == document_id).first()
    original_faiss_ids = doc.faiss_ids
    assert doc.process == ProcessStatus.DONE

    edit = app_client.put(
        f"/document/edit/{document_id}", headers=headers,
        files={"file": ("v2.pdf", pdf_bytes("Updated content, different chunk."), "application/pdf")},
    )
    assert edit.status_code == 200
    db_session.refresh(doc)
    assert doc.process == ProcessStatus.UPDATE

    scheduler_module.handle_update_documents()
    db_session.refresh(doc)
    assert doc.process == ProcessStatus.PENDING
    assert doc.faiss_ids is None

    scheduler_module.verify_pending_documents()
    scheduler_module.process_pending_documents()
    db_session.refresh(doc)
    assert doc.process == ProcessStatus.DONE
    assert doc.faiss_ids is not None
    assert doc.faiss_ids != original_faiss_ids  # fresh chunk ids, not the stale ones


def test_two_users_documents_and_search_stay_isolated_through_full_pipeline(
    app_client, auth_headers, db_session, fake_document_verdict, fake_embeddings, fake_chat_llm,
):
    """Running the shared scheduler over two users' documents never mixes their content in search results."""
    headers_a = auth_headers(email="isolation-a@example.com", password="Passw0rd")
    headers_b = auth_headers(email="isolation-b@example.com", password="Passw0rd")
    user_id_a = get_user_id(db_session, "isolation-a@example.com")
    user_id_b = get_user_id(db_session, "isolation-b@example.com")

    app_client.post(
        "/document/upload-file", headers=headers_a,
        files={"file": ("a.pdf", pdf_bytes("User A confidential sales figures."), "application/pdf")},
    )
    app_client.post(
        "/document/upload-file", headers=headers_b,
        files={"file": ("b.pdf", pdf_bytes("User B confidential inventory list."), "application/pdf")},
    )

    scheduler_module.verify_pending_documents()
    scheduler_module.process_pending_documents()

    docs_a = db_session.query(Document).filter(Document.user_id == user_id_a).all()
    docs_b = db_session.query(Document).filter(Document.user_id == user_id_b).all()
    assert all(d.process == ProcessStatus.DONE for d in docs_a)
    assert all(d.process == ProcessStatus.DONE for d in docs_b)

    rag = RAGSearch()
    fake_chat_llm.append("Answer for A.")
    rag.search_and_summarize("What's in my documents?", user_id=user_id_a)
    # search_and_summarize queries FaissVectorStore.query(..., user_id=user_id_a) internally;
    # confirm the vector store itself only ever returns that user's own chunk metadata.
    results = rag.vectorstore.query("confidential", top_k=5, user_id=user_id_a)
    assert all(r["metadata"]["user_id"] == user_id_a for r in results)

    results_b = rag.vectorstore.query("confidential", top_k=5, user_id=user_id_b)
    assert all(r["metadata"]["user_id"] == user_id_b for r in results_b)
