"""
End-to-end demo/dummy-data mode: real demo PDFs get indexed by the real
process_demo_documents() scheduler job, discovered through the real /demo/*
endpoints, and toggling them for a user actually changes what a real
RAGSearch.search_and_summarize() call returns — all against the mock in-memory
DB and an isolated tmp filesystem.
"""
import io

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from models.shop_owner import ShopOwner
import services.scheduler as scheduler_module
from RAG_src.search import RAGSearch


def get_user_id(db_session, email):
    return db_session.query(ShopOwner).filter(ShopOwner.email == email).first().id


def write_demo_pdf(tmp_path, dataset, filename, text):
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.drawString(72, 700, text)
    c.save()

    path = tmp_path / "media" / "demo" / dataset / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(buf.getvalue())


def test_enabling_demo_mode_switches_search_to_demo_content(
    tmp_path, app_client, auth_headers, db_session, fake_embeddings, fake_chat_llm,
):
    """A user with an empty store gets real demo content once demo mode is enabled, and loses it once disabled."""
    write_demo_pdf(tmp_path, "kirana_store", "inventory.pdf", "Kirana store rice stock: 200kg.")
    scheduler_module.process_demo_documents()

    headers = auth_headers(email="demoflow@example.com", password="Passw0rd")
    user_id = get_user_id(db_session, "demoflow@example.com")

    datasets = app_client.get("/demo/datasets", headers=headers)
    assert datasets.status_code == 200
    assert "kirana_store" in datasets.json()["datasets"]

    enable = app_client.post("/demo/enable", json={"dataset": "kirana_store"}, headers=headers)
    assert enable.status_code == 200
    assert enable.json()["demo_mode_enabled"] is True

    rag = RAGSearch()
    fake_chat_llm.append("You have 200kg of rice in stock.")
    with_demo = rag.search_and_summarize("What's in stock?", user_id=user_id)
    assert with_demo == "You have 200kg of rice in stock."

    disable = app_client.post("/demo/disable", headers=headers)
    assert disable.status_code == 200

    without_demo = rag.search_and_summarize("What's in stock?", user_id=user_id)
    assert without_demo == "No relevant data found."  # own store is empty, demo mode is off


def test_enable_rejects_a_dataset_that_was_never_indexed(tmp_path, app_client, auth_headers, fake_embeddings):
    """Enabling a dataset name process_demo_documents() never produced is rejected, and status stays disabled."""
    write_demo_pdf(tmp_path, "medical_store", "stock.pdf", "Paracetamol stock: 500 strips.")
    scheduler_module.process_demo_documents()

    headers = auth_headers(email="demobad-integration@example.com", password="Passw0rd")

    resp = app_client.post("/demo/enable", json={"dataset": "not_a_real_dataset"}, headers=headers)
    assert resp.status_code == 400

    status = app_client.get("/demo/status", headers=headers)
    assert status.json() == {"demo_mode_enabled": False, "demo_dataset": None}


def test_demo_mode_toggle_is_isolated_between_two_users(
    tmp_path, app_client, auth_headers, db_session, fake_embeddings, fake_chat_llm,
):
    """Enabling demo mode for one user through the real API never affects another user's search results."""
    write_demo_pdf(tmp_path, "electronics_shop", "catalog.pdf", "Electronics shop: 15 televisions in stock.")
    scheduler_module.process_demo_documents()

    headers_on = auth_headers(email="demo-on@example.com", password="Passw0rd")
    headers_off = auth_headers(email="demo-off@example.com", password="Passw0rd")
    user_id_on = get_user_id(db_session, "demo-on@example.com")
    user_id_off = get_user_id(db_session, "demo-off@example.com")

    app_client.post("/demo/enable", json={"dataset": "electronics_shop"}, headers=headers_on)

    status_on = app_client.get("/demo/status", headers=headers_on).json()
    status_off = app_client.get("/demo/status", headers=headers_off).json()
    assert status_on["demo_mode_enabled"] is True
    assert status_off == {"demo_mode_enabled": False, "demo_dataset": None}

    rag = RAGSearch()
    fake_chat_llm.append("You have 15 televisions.")
    on_answer = rag.search_and_summarize("What's in stock?", user_id=user_id_on)
    assert on_answer == "You have 15 televisions."

    off_answer = rag.search_and_summarize("What's in stock?", user_id=user_id_off)
    assert off_answer == "No relevant data found."  # never touched the demo data
