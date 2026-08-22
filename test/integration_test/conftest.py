"""
Shared fixtures for the integration test suite.

Unlike the unit tests (test/unit_test/), these tests wire real components together
through the real FastAPI app and real routers/services/RAG_src modules, and only mock
the true external network boundaries: OpenAI (embeddings + chat completions) and SMTP.
Everything else -- FastAPI routing, SQLAlchemy models, FAISS index read/write, PDF
generation, the scheduler functions -- runs for real.

Database: every test gets its own fresh **in-memory SQLite** database via
db_session_factory/app_client. The real bizinsight.db is never opened, and no
fixture here reads or writes it -- all seed data comes from mock fixtures
(make_user, make_pdf, fake_embeddings, fake_chat_llm, fake_document_verdict).

Filesystem safety: several production functions use *relative* paths instead of a
configurable directory ("faiss_store", "faiss_store/demo", "media/demo",
"media/uploads/..."). Relative paths resolve against the process's current working
directory at the moment a file is actually opened, not at import/construction time.
The autouse isolated_environment fixture below chdir()s into a throwaway tmp_path
before every test body runs, which keeps ALL such writes -- even from objects built
before the fixture ran, like the RAGSearch singleton in routers/query.py -- safely
inside tmp_path. This is required after a real incident where a test without this
kind of isolation overwrote real per-user FAISS index files.
"""
import io
import json
from types import SimpleNamespace

import pytest
from passlib.context import CryptContext
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from models.shop_owner import Base, ShopOwner
from models.document import Document, ProcessStatus  # noqa: F401 (registers table with Base)
from models.chat_entry import ChatEntry, ChatStatus  # noqa: F401 (registers table with Base)
from utils.database import get_db
import utils.database as database_module
import utils.helper as helper_module
import services.scheduler as scheduler_module
import RAG_src.search as search_module
import routers.document as document_module

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ── Database (mock / in-memory only — never the real bizinsight.db) ───────────

@pytest.fixture()
def db_engine():
    """Fresh in-memory SQLite engine per test, with all tables created. Not the real DB."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture()
def db_session_factory(db_engine):
    return sessionmaker(autocommit=False, autoflush=False, bind=db_engine)


@pytest.fixture()
def db_session(db_session_factory):
    session = db_session_factory()
    yield session
    session.close()


# ── Filesystem + module wiring safety net ──────────────────────────────────────

@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch, tmp_path, db_session_factory):
    """
    Runs every integration test from a throwaway cwd and points every module-level
    SessionLocal / UPLOAD_DIR at the in-memory test DB and tmp folders. See module
    docstring above for why this is mandatory and not optional per-file.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(scheduler_module, "SessionLocal", db_session_factory)
    monkeypatch.setattr(search_module, "SessionLocal", db_session_factory)
    monkeypatch.setattr(database_module, "SessionLocal", db_session_factory)
    monkeypatch.setattr(document_module, "UPLOAD_DIR", str(tmp_path / "media" / "uploads"))
    return tmp_path


# ── FastAPI app + auth helpers ──────────────────────────────────────────────────

@pytest.fixture()
def app_client(db_session_factory):
    """Real FastAPI TestClient, real routers — only get_db is swapped for the mock test DB."""
    from main import app

    def _override_get_db():
        session = db_session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _override_get_db
    from fastapi.testclient import TestClient
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


@pytest.fixture()
def make_user(db_session):
    """Factory — insert a mock ShopOwner row directly into the in-memory test DB."""

    def _make_user(
        email="owner@example.com",
        password="Passw0rd",
        name="Test Owner",
        username=None,
        shop_name="Test Shop",
        is_active=True,
        **extra,
    ):
        user = ShopOwner(
            name=name,
            email=email,
            username=username,
            password_hash=pwd_context.hash(password),
            shop_name=shop_name,
            auth_provider="local",
            is_active=is_active,
            **extra,
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)
        return user

    return _make_user


@pytest.fixture()
def auth_headers(app_client, make_user):
    """Factory — create a mock user and sign in through the real endpoint for a bearer token."""

    def _auth_headers(email="owner@example.com", password="Passw0rd", **user_kwargs):
        make_user(email=email, password=password, **user_kwargs)
        resp = app_client.post("/auth/signin", json={"email": email, "password": password})
        assert resp.status_code == 200, resp.text
        token = resp.json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    return _auth_headers


# ── Mock PDFs ────────────────────────────────────────────────────────────────

def _build_pdf_bytes(text: str) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.drawString(72, 700, text)
    c.save()
    return buf.getvalue()


@pytest.fixture()
def make_pdf(tmp_path):
    """Factory — write a small real (mock-content) PDF to disk and return its path."""

    def _make_pdf(filename="sample.pdf", text="Hello from a test PDF. Total sales: Rs 5000."):
        path = tmp_path / "_source_pdfs" / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_build_pdf_bytes(text))
        return str(path)

    return _make_pdf


@pytest.fixture()
def sample_pdf_bytes():
    return _build_pdf_bytes("Sample invoice. Product: Widget. Quantity: 10. Total: Rs 1000.")


# ── Mocked external network boundaries (OpenAI, only) ──────────────────────────

@pytest.fixture()
def fake_embeddings(monkeypatch):
    """
    Deterministic small vectors instead of real OpenAI embedding API calls.
    Patched at the class level, so it covers every OpenAIEmbeddings instance —
    including ones already constructed (e.g. inside the RAGSearch singleton
    created at app-import time in routers/query.py).
    """
    from langchain_openai import OpenAIEmbeddings

    dim = 8

    def _vector_for(text: str):
        seed = sum(ord(ch) for ch in text) % 97
        return [(seed + i) / 97.0 for i in range(dim)]

    def fake_embed_documents(self, texts):
        return [_vector_for(t) for t in texts]

    def fake_embed_query(self, text):
        return _vector_for(text)

    monkeypatch.setattr(OpenAIEmbeddings, "embed_documents", fake_embed_documents)
    monkeypatch.setattr(OpenAIEmbeddings, "embed_query", fake_embed_query)
    return dim


@pytest.fixture()
def fake_chat_llm(monkeypatch):
    """
    Queue-based fake for ChatOpenAI.invoke(), patched at the class level so it
    intercepts calls from ANY ChatOpenAI instance, including the RAGSearch
    singleton in routers/query.py that was already constructed at app-import time.

    Usage: fake_chat_llm.append("response text") before triggering a call that
    invokes the LLM; queued responses are consumed in FIFO order. An empty queue
    yields an empty-content response (mirrors a real "unclear" / unparseable reply).
    """
    from langchain_openai import ChatOpenAI

    responses = []

    def fake_invoke(self, messages):
        content = responses.pop(0) if responses else ""
        return SimpleNamespace(content=content)

    monkeypatch.setattr(ChatOpenAI, "invoke", fake_invoke)
    return responses


@pytest.fixture()
def fake_document_verdict(monkeypatch):
    """
    Mocks the LLM verdict inside utils.helper.is_business_document() — the real
    text-extraction (PyPDF) still runs for real, only the OpenAI verdict call is
    faked. Defaults to accepting every document; flip verdict["is_business"] to
    False (and set a reason) before calling verify_pending_documents() to test
    rejection.
    """
    verdict = {"is_business": True, "reason": "Looks like a valid business document"}

    class FakeMessage:
        def __init__(self, content):
            self.content = content

    class FakeChoice:
        def __init__(self, content):
            self.message = FakeMessage(content)

    class FakeResponse:
        def __init__(self, content):
            self.choices = [FakeChoice(content)]

    def fake_create(**kwargs):
        return FakeResponse(json.dumps(verdict))

    monkeypatch.setattr(helper_module.client.chat.completions, "create", fake_create)
    return verdict
