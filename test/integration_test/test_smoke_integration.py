"""
Sanity checks for the integration harness itself before building real scenarios on
top of it: real app + real DB writes land in the mock in-memory DB, real FaissVectorStore
writes land inside tmp_path (never the real project's faiss_store/), and the class-level
LLM/embedding patches actually intercept calls made through the pre-built RAGSearch
singleton in routers/query.py.
"""
import json
import os

from models.shop_owner import ShopOwner
from RAG_src.vectorstore import FaissVectorStore
from langchain_core.documents import Document


def test_app_client_uses_mock_db_not_real_one(app_client, db_session):
    """Signing up through the real endpoint only touches the in-memory mock DB."""
    resp = app_client.post("/auth/signup", json={
        "name": "Smoke Test", "email": "smoke@example.com", "password": "Passw0rd",
    })
    assert resp.status_code == 201
    assert db_session.query(ShopOwner).filter(ShopOwner.email == "smoke@example.com").count() == 1


def test_mock_db_is_isolated_between_tests(db_session):
    """A fresh test gets an empty mock DB — proves no state leaked from the previous test."""
    assert db_session.query(ShopOwner).count() == 0


def test_real_faiss_writes_land_in_tmp_path_not_real_project(tmp_path, fake_embeddings):
    """A real FaissVectorStore build writes only inside the isolated tmp_path cwd."""
    store = FaissVectorStore(str(tmp_path / "faiss_store"), embedding_model="openai")
    store.build_from_documents([Document(page_content="test content", metadata={})], user_id=999)

    assert (tmp_path / "faiss_store" / "999" / "faiss.index").exists()


def test_fake_chat_llm_intercepts_the_real_router_singleton(app_client, auth_headers, fake_chat_llm, fake_embeddings):
    """
    fake_chat_llm patches ChatOpenAI at the class level, so it also controls the
    RAGSearch singleton constructed at app-import time in routers/query.py — proving
    the real /rag/search endpoint can be driven end-to-end without any real OpenAI call.
    """
    headers = auth_headers(email="rag-smoke@example.com", password="Passw0rd")

    fake_chat_llm.append(json.dumps({"intent": "unclear", "reason": "just chatting"}))

    resp = app_client.post("/rag/search", json={"query": "hello there"}, headers=headers)

    assert resp.status_code == 200
    assert "not sure" in resp.json()["answer"].lower()


def test_fake_document_verdict_intercepts_real_helper_call(fake_document_verdict, make_pdf):
    """fake_document_verdict controls utils.helper.is_business_document()'s LLM call only."""
    from utils.helper import is_business_document

    pdf_path = make_pdf(text="Some real extractable text.")
    is_valid, reason = is_business_document(pdf_path)

    assert is_valid is True
    assert reason == fake_document_verdict["reason"]


def test_isolated_environment_keeps_real_project_dirs_untouched(tmp_path):
    """cwd is redirected to tmp_path for the duration of the test."""
    assert os.getcwd() == str(tmp_path)
