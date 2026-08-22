"""
A single broad end-to-end scenario: two independent users each run the full
app lifecycle (signup, document upload + processing, chat-based data entry) in
the same test run, and every surface (documents list, search answers, chat
entries) is checked for zero cross-contamination between them.
"""
import io
import json

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from models.shop_owner import ShopOwner
from models.chat_entry import ChatEntry, ChatStatus
import services.scheduler as scheduler_module
from RAG_src.search import RAGSearch


def get_user_id(db_session, email):
    return db_session.query(ShopOwner).filter(ShopOwner.email == email).first().id


def pdf_bytes(text: str) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.drawString(72, 700, text)
    c.save()
    return buf.getvalue()


def test_two_users_full_lifecycle_never_cross_contaminates(
    app_client, auth_headers, db_session, fake_document_verdict, fake_embeddings, fake_chat_llm,
):
    """Documents, search results, and chat entries all stay strictly per-user across a full parallel lifecycle."""
    headers_alice = auth_headers(email="alice@example.com", password="Passw0rd", name="Alice")
    headers_bob = auth_headers(email="bob@example.com", password="Passw0rd", name="Bob")
    alice_id = get_user_id(db_session, "alice@example.com")
    bob_id = get_user_id(db_session, "bob@example.com")

    # Each uploads a document with clearly distinct content.
    app_client.post(
        "/document/upload-file", headers=headers_alice,
        files={"file": ("alice.pdf", pdf_bytes("Alice's bakery: 40 loaves of bread."), "application/pdf")},
    )
    app_client.post(
        "/document/upload-file", headers=headers_bob,
        files={"file": ("bob.pdf", pdf_bytes("Bob's hardware store: 12 hammers."), "application/pdf")},
    )

    scheduler_module.verify_pending_documents()
    scheduler_module.process_pending_documents()

    # Each has exactly one of their own documents in their own file list.
    alice_files = app_client.get("/document/my-files", headers=headers_alice).json()
    bob_files = app_client.get("/document/my-files", headers=headers_bob).json()
    assert alice_files["total"] == 1
    assert alice_files["files"][0]["original_name"] == "alice.pdf"
    assert bob_files["total"] == 1
    assert bob_files["files"][0]["original_name"] == "bob.pdf"

    # Each also adds a chat entry and confirms it.
    rag = RAGSearch()
    fake_chat_llm.append(json.dumps({"intent": "add_data"}))
    fake_chat_llm.append(json.dumps({"product": "Bread", "quantity": 40, "total": 400, "type": "sale"}))
    rag.handle_message("Sold 40 loaves of bread", user_id=alice_id)
    rag.handle_message("yes", user_id=alice_id)

    fake_chat_llm.append(json.dumps({"intent": "add_data"}))
    fake_chat_llm.append(json.dumps({"product": "Hammer", "quantity": 12, "total": 600, "type": "sale"}))
    rag.handle_message("Sold 12 hammers", user_id=bob_id)
    rag.handle_message("yes", user_id=bob_id)

    alice_entries = db_session.query(ChatEntry).filter(
        ChatEntry.user_id == alice_id, ChatEntry.status == ChatStatus.CONFIRMED,
    ).all()
    bob_entries = db_session.query(ChatEntry).filter(
        ChatEntry.user_id == bob_id, ChatEntry.status == ChatStatus.CONFIRMED,
    ).all()
    assert len(alice_entries) == 1
    assert json.loads(alice_entries[0].extracted)["product"] == "Bread"
    assert len(bob_entries) == 1
    assert json.loads(bob_entries[0].extracted)["product"] == "Hammer"

    # Vector search never crosses users, for either the document content or the chat context.
    alice_vector_hits = rag.vectorstore.query("bread hardware", top_k=5, user_id=alice_id)
    bob_vector_hits = rag.vectorstore.query("bread hardware", top_k=5, user_id=bob_id)
    assert all(hit["metadata"]["user_id"] == alice_id for hit in alice_vector_hits)
    assert all(hit["metadata"]["user_id"] == bob_id for hit in bob_vector_hits)

    # The nightly report only ever bundles a user's own confirmed entries.
    scheduler_module.generate_daily_pdf()
    assert db_session.query(ChatEntry).filter(ChatEntry.user_id == alice_id).count() == 0
    assert db_session.query(ChatEntry).filter(ChatEntry.user_id == bob_id).count() == 0

    from models.document import Document
    alice_docs = db_session.query(Document).filter(Document.user_id == alice_id).count()
    bob_docs = db_session.query(Document).filter(Document.user_id == bob_id).count()
    assert alice_docs == 2  # original upload + the new daily report
    assert bob_docs == 2
