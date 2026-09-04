"""
Shared fixtures for the whole test suite.

Design notes:
- Every test gets a fresh in-memory SQLite DB (function-scoped fixtures), so tests
  never share state and can run in any order.
- External services (OpenAI, SMTP) are never called for real — tests either mock
  the network-facing call directly, or monkeypatch the class used by the module
  under test.
- Fixtures that touch the filesystem use pytest's built-in tmp_path so nothing is
  written into the real project folders (media/, faiss_store/).
"""
import contextlib
import io
import os
import sys
import uuid

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
import services.s3_storage as s3_storage_module

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ── Fake S3 (never make real AWS calls in tests) ────────────────────────────

@pytest.fixture(autouse=True)
def fake_s3(monkeypatch, tmp_path):
    """
    Replaces services.s3_storage's functions with an in-memory dict-backed
    fake, so document upload/edit/download-url and the scheduler's S3-backed
    processing never touch real AWS. Returns the backing dict (object key ->
    bytes) so tests can assert on what got "uploaded", or seed content for a
    key before exercising code that downloads it.
    """
    store = {}

    def fake_upload_bytes(key, data, content_type):
        store[key] = data

    def fake_delete_object(key):
        store.pop(key, None)

    def fake_generate_presigned_download_url(key, expires_in=None):
        ttl = expires_in or s3_storage_module.S3_PRESIGNED_URL_EXPIRE_SECONDS
        return f"https://fake-s3.test/{key}?expires_in={ttl}"

    @contextlib.contextmanager
    def fake_s3_tempfile(key, suffix=".pdf"):
        local_path = tmp_path / f"s3_tmp_{uuid.uuid4().hex}{suffix}"
        local_path.write_bytes(store.get(key, b""))
        try:
            yield str(local_path)
        finally:
            local_path.unlink(missing_ok=True)

    monkeypatch.setattr(s3_storage_module, "upload_bytes", fake_upload_bytes)
    monkeypatch.setattr(s3_storage_module, "delete_object", fake_delete_object)
    monkeypatch.setattr(s3_storage_module, "generate_presigned_download_url", fake_generate_presigned_download_url)
    monkeypatch.setattr(s3_storage_module, "s3_tempfile", fake_s3_tempfile)
    return store


# ── Database ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def db_engine():
    """Fresh in-memory SQLite engine per test, with all tables created."""
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


@pytest.fixture()
def app_client(db_session_factory):
    """FastAPI TestClient with the real get_db dependency swapped for the test DB."""
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


# ── Users / auth ──────────────────────────────────────────────────────────────

@pytest.fixture()
def make_user(db_session):
    """Factory — insert a ShopOwner row directly into the test DB."""

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
    """Factory — create a user (if not already present) and sign in for a bearer token."""

    def _auth_headers(email="owner@example.com", password="Passw0rd", **user_kwargs):
        make_user(email=email, password=password, **user_kwargs)
        resp = app_client.post("/auth/signin", json={"email": email, "password": password})
        assert resp.status_code == 200, resp.text
        token = resp.json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    return _auth_headers


# ── PDF fixtures ──────────────────────────────────────────────────────────────

def _build_pdf_bytes(text: str) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.drawString(72, 700, text)
    c.save()
    return buf.getvalue()


@pytest.fixture()
def make_pdf(tmp_path):
    """Factory — write a small real PDF to disk and return its path."""

    def _make_pdf(filename="sample.pdf", text="Hello from a test PDF. Total sales: Rs 5000."):
        path = tmp_path / filename
        path.write_bytes(_build_pdf_bytes(text))
        return str(path)

    return _make_pdf


@pytest.fixture()
def sample_pdf_bytes():
    return _build_pdf_bytes("Sample invoice. Product: Widget. Quantity: 10. Total: Rs 1000.")


# ── Fake embeddings (avoid real OpenAI network calls) ──────────────────────────

@pytest.fixture()
def fake_embeddings(monkeypatch):
    """
    Patch OpenAIEmbeddings so embed_documents/embed_query return small deterministic
    vectors instead of calling the OpenAI API.
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
