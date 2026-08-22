import json

import pytest

import utils.helper as helper


class FakeChoiceMessage:
    def __init__(self, content):
        self.content = content


class FakeChoice:
    def __init__(self, content):
        self.message = FakeChoiceMessage(content)


class FakeChatResponse:
    def __init__(self, content):
        self.choices = [FakeChoice(content)]


def mock_openai_verdict(monkeypatch, is_business, reason, calls=None):
    def fake_create(**kwargs):
        if calls is not None:
            calls.append(kwargs)
        return FakeChatResponse(json.dumps({"is_business": is_business, "reason": reason}))

    monkeypatch.setattr(helper.client.chat.completions, "create", fake_create)


def test_is_business_document_true_case(monkeypatch, make_pdf):
    """is_business_document() returns (True, reason) when the LLM verdict says it's a business document."""
    mock_openai_verdict(monkeypatch, True, "Looks like a sales report")
    pdf_path = make_pdf(text="Monthly sales report with totals.")

    is_valid, reason = helper.is_business_document(pdf_path)

    assert is_valid is True
    assert reason == "Looks like a sales report"


def test_is_business_document_false_case(monkeypatch, make_pdf):
    """is_business_document() returns (False, reason) when the LLM verdict rejects the document."""
    mock_openai_verdict(monkeypatch, False, "This is a personal diary")
    pdf_path = make_pdf(text="Dear diary, today I felt happy.")

    is_valid, reason = helper.is_business_document(pdf_path)

    assert is_valid is False
    assert reason == "This is a personal diary"


def test_is_business_document_handles_llm_exception(monkeypatch, make_pdf):
    """If the LLM call raises, is_business_document() returns (False, "Verification failed: ...") instead of crashing."""
    def fake_create(**kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr(helper.client.chat.completions, "create", fake_create)
    pdf_path = make_pdf(text="Some content that extracts fine.")

    is_valid, reason = helper.is_business_document(pdf_path)

    assert is_valid is False
    assert "network down" in reason


def test_is_business_document_missing_file_returns_false(monkeypatch, tmp_path):
    """A nonexistent file path returns (False, "Verification failed: ...") without ever calling the LLM."""
    calls = []
    mock_openai_verdict(monkeypatch, True, "irrelevant", calls=calls)

    is_valid, reason = helper.is_business_document(str(tmp_path / "missing.pdf"))

    assert is_valid is False
    assert "Verification failed" in reason
    assert calls == []  # never reached the LLM call


def test_is_business_document_non_pdf_text_file(monkeypatch, tmp_path):
    """Non-PDF files are read as plain text and still get verified through the same LLM path."""
    mock_openai_verdict(monkeypatch, True, "Looks like a business note")
    txt_path = tmp_path / "note.txt"
    txt_path.write_text("Stock count: 50 units of item A.")

    is_valid, reason = helper.is_business_document(str(txt_path))

    assert is_valid is True
    assert reason == "Looks like a business note"


class FakeFaissVectorStore:
    last_instance = None

    def __init__(self, persist_dir, embedding_model="openai"):
        self.persist_dir = persist_dir
        self.embedding_model = embedding_model
        self.delete_calls = []
        FakeFaissVectorStore.last_instance = self

    def delete_by_ids(self, chunk_ids, user_id):
        self.delete_calls.append((chunk_ids, user_id))
        return True


def test_delete_document_from_vector_db_no_faiss_ids_is_noop(monkeypatch):
    """delete_document_from_vector_db() returns False and never touches the vector store when faiss_ids is None."""
    monkeypatch.setattr(helper, "FaissVectorStore", FakeFaissVectorStore)
    FakeFaissVectorStore.last_instance = None

    class FakeDoc:
        faiss_ids = None
        original_name = "doc.pdf"

    result = helper.delete_document_from_vector_db(FakeDoc(), user_id=1)

    assert result is False
    assert FakeFaissVectorStore.last_instance is None  # store never constructed


def test_delete_document_from_vector_db_deletes_matching_chunks(monkeypatch):
    """delete_document_from_vector_db() parses faiss_ids and deletes exactly those chunk ids for the given user."""
    monkeypatch.setattr(helper, "FaissVectorStore", FakeFaissVectorStore)

    class FakeDoc:
        faiss_ids = json.dumps(["id-1", "id-2"])
        original_name = "doc.pdf"

    result = helper.delete_document_from_vector_db(FakeDoc(), user_id=99)

    assert result is True
    store = FakeFaissVectorStore.last_instance
    assert store.delete_calls == [(["id-1", "id-2"], 99)]
