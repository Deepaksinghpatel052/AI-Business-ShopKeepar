import io
import json
import os

import pytest
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

import services.scheduler as scheduler_module
import utils.helper as helper_module
from models.document import Document, ProcessStatus
from models.chat_entry import ChatEntry, ChatStatus


@pytest.fixture(autouse=True)
def isolate_cwd(monkeypatch, tmp_path):
    """
    Several scheduler functions hardcode relative paths ("faiss_store", "media/demo",
    "media/uploads/...") instead of taking a configurable directory. Running every test
    in this file from a throwaway cwd guarantees none of them can ever touch the real
    project's media/ or faiss_store/ directories — including through a fake FaissVectorStore
    that writes wherever it's told to, which is exactly what silently corrupted real user
    data the first time this suite was written without this fixture.
    """
    monkeypatch.chdir(tmp_path)


@pytest.fixture(autouse=True)
def patch_scheduler_db(monkeypatch, db_session_factory):
    """Every scheduler function opens its own SessionLocal() — point that at the test DB."""
    monkeypatch.setattr(scheduler_module, "SessionLocal", db_session_factory)


def make_document(db_session, **overrides):
    defaults = dict(
        user_id=1,
        original_name="report.pdf",
        stored_name="stored.pdf",
        file_path="media/uploads/1/stored.pdf",
        file_type="pdf",
        mime_type="application/pdf",
        file_size=1234,
        process=ProcessStatus.PENDING,
    )
    defaults.update(overrides)
    doc = Document(**defaults)
    db_session.add(doc)
    db_session.commit()
    db_session.refresh(doc)
    return doc


def write_tiny_pdf(path, text="Demo content"):
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.drawString(72, 700, text)
    c.save()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(buf.getvalue())


class FakeFaissVectorStore:
    build_calls = []

    def __init__(self, persist_dir, embedding_model="openai"):
        self.persist_dir = persist_dir

    def build_from_documents(self, documents, user_id):
        FakeFaissVectorStore.build_calls.append((self.persist_dir, user_id, len(documents)))
        user_dir = os.path.join(self.persist_dir, str(user_id))
        os.makedirs(user_dir, exist_ok=True)
        with open(os.path.join(user_dir, "faiss.index"), "wb") as f:
            f.write(b"fake-index")
        return [f"chunk-{user_id}-{i}" for i in range(len(documents))]


@pytest.fixture(autouse=True)
def reset_fake_store_calls():
    FakeFaissVectorStore.build_calls = []


# ── process_pending_documents ──────────────────────────────────────────────

def test_process_pending_documents_marks_done_with_chunk_ids(db_session, monkeypatch):
    """A PROCESS-status document gets embedded, marked DONE, and its faiss_ids saved as JSON."""
    doc = make_document(db_session, user_id=1, process=ProcessStatus.PROCESS)

    monkeypatch.setattr(scheduler_module, "FaissVectorStore", FakeFaissVectorStore)
    monkeypatch.setattr(scheduler_module, "load_all_documents", lambda paths: [object()])

    scheduler_module.process_pending_documents()

    db_session.refresh(doc)
    assert doc.process == ProcessStatus.DONE
    assert json.loads(doc.faiss_ids) == ["chunk-1-0"]


def test_process_pending_documents_groups_by_user(db_session, monkeypatch):
    """Pending documents from different users are all processed, each under their own user_id."""
    doc_a = make_document(db_session, user_id=1, process=ProcessStatus.PROCESS)
    doc_b = make_document(db_session, user_id=2, process=ProcessStatus.PROCESS)

    monkeypatch.setattr(scheduler_module, "FaissVectorStore", FakeFaissVectorStore)
    monkeypatch.setattr(scheduler_module, "load_all_documents", lambda paths: [object()])

    scheduler_module.process_pending_documents()

    db_session.refresh(doc_a)
    db_session.refresh(doc_b)
    assert doc_a.process == ProcessStatus.DONE
    assert doc_b.process == ProcessStatus.DONE
    user_ids_processed = {call[1] for call in FakeFaissVectorStore.build_calls}
    assert user_ids_processed == {1, 2}


def test_process_pending_documents_skips_docs_with_no_loadable_content(db_session, monkeypatch):
    """A document whose file loads no content stays unprocessed instead of being marked DONE."""
    doc = make_document(db_session, user_id=1, process=ProcessStatus.PROCESS)

    monkeypatch.setattr(scheduler_module, "FaissVectorStore", FakeFaissVectorStore)
    monkeypatch.setattr(scheduler_module, "load_all_documents", lambda paths: [])

    scheduler_module.process_pending_documents()

    db_session.refresh(doc)
    assert doc.process == ProcessStatus.PROCESS  # unchanged, not marked DONE
    assert FakeFaissVectorStore.build_calls == []


def test_process_pending_documents_ignores_other_statuses(db_session, monkeypatch):
    """Documents not in PROCESS status (e.g. still PENDING) are left untouched."""
    doc = make_document(db_session, user_id=1, process=ProcessStatus.PENDING)
    monkeypatch.setattr(scheduler_module, "FaissVectorStore", FakeFaissVectorStore)
    monkeypatch.setattr(scheduler_module, "load_all_documents", lambda paths: [object()])

    scheduler_module.process_pending_documents()  # should be a no-op

    db_session.refresh(doc)
    assert doc.process == ProcessStatus.PENDING
    assert FakeFaissVectorStore.build_calls == []


def test_process_pending_documents_empty_is_noop(db_session, monkeypatch):
    """With no PROCESS-status documents at all, the function returns without error or side effects."""
    monkeypatch.setattr(scheduler_module, "FaissVectorStore", FakeFaissVectorStore)
    scheduler_module.process_pending_documents()  # must not raise
    assert FakeFaissVectorStore.build_calls == []


# ── verify_pending_documents ────────────────────────────────────────────────

def test_verify_pending_documents_accepts_and_rejects(db_session, monkeypatch):
    """PENDING documents are moved to PROCESS or REJECTED based on the business-document verdict."""
    good_doc = make_document(db_session, file_path="good.pdf", process=ProcessStatus.PENDING)
    bad_doc = make_document(db_session, file_path="bad.pdf", process=ProcessStatus.PENDING)

    def fake_is_business_document(file_path):
        if file_path == "good.pdf":
            return True, "Looks like a sales report"
        return False, "Looks like a diary"

    monkeypatch.setattr(scheduler_module, "is_business_document", fake_is_business_document)

    scheduler_module.verify_pending_documents()

    db_session.refresh(good_doc)
    db_session.refresh(bad_doc)
    assert good_doc.process == ProcessStatus.PROCESS
    assert bad_doc.process == ProcessStatus.REJECTED


def test_verify_pending_documents_empty_is_noop(monkeypatch):
    """With no PENDING documents, the function returns without error."""
    monkeypatch.setattr(scheduler_module, "is_business_document", lambda p: (True, "n/a"))
    scheduler_module.verify_pending_documents()  # must not raise


# ── handle_update_documents ─────────────────────────────────────────────────

def test_handle_update_documents_deletes_old_chunks_and_resets_status(db_session, monkeypatch):
    """An UPDATE-status document has its old vector chunks deleted and is reset to PENDING with faiss_ids cleared."""
    doc = make_document(
        db_session, process=ProcessStatus.UPDATE, faiss_ids=json.dumps(["a", "b"]),
    )
    calls = []

    def fake_delete(document, user_id):
        calls.append((document.id, user_id))
        return True

    monkeypatch.setattr(helper_module, "delete_document_from_vector_db", fake_delete)

    scheduler_module.handle_update_documents()

    db_session.refresh(doc)
    assert doc.process == ProcessStatus.PENDING
    assert doc.faiss_ids is None
    assert calls == [(doc.id, doc.user_id)]


def test_handle_update_documents_skips_deletion_when_no_faiss_ids(db_session, monkeypatch):
    """An UPDATE-status document with no faiss_ids yet skips the vector-delete call but is still reset to PENDING."""
    doc = make_document(db_session, process=ProcessStatus.UPDATE, faiss_ids=None)
    calls = []
    monkeypatch.setattr(helper_module, "delete_document_from_vector_db", lambda d, user_id: calls.append(1) or True)

    scheduler_module.handle_update_documents()

    db_session.refresh(doc)
    assert doc.process == ProcessStatus.PENDING
    assert calls == []


def test_handle_update_documents_empty_is_noop(monkeypatch):
    """With no UPDATE-status documents, the function returns without error."""
    monkeypatch.setattr(helper_module, "delete_document_from_vector_db", lambda d, user_id: True)
    scheduler_module.handle_update_documents()  # must not raise


# ── generate_daily_pdf ───────────────────────────────────────────────────────

def test_generate_daily_pdf_creates_document_and_clears_entries(db_session):
    """Confirmed chat entries for a user are rendered into a PDF, saved as a PENDING Document, and then cleared."""
    entry1 = ChatEntry(
        user_id=55, raw_message="sold 2 pens",
        extracted=json.dumps({"product": "Pen", "quantity": 2, "price_per_unit": 10, "total": 20, "type": "sale"}),
        status=ChatStatus.CONFIRMED,
    )
    entry2 = ChatEntry(
        user_id=55, raw_message="sold 1 book",
        extracted=json.dumps({"product": "Book", "quantity": 1, "price_per_unit": 200, "total": 200, "type": "sale"}),
        status=ChatStatus.CONFIRMED,
    )
    db_session.add_all([entry1, entry2])
    db_session.commit()

    scheduler_module.generate_daily_pdf()

    remaining_entries = db_session.query(ChatEntry).filter(ChatEntry.user_id == 55).all()
    assert remaining_entries == []

    new_doc = db_session.query(Document).filter(Document.user_id == 55).first()
    assert new_doc is not None
    assert new_doc.process == ProcessStatus.PENDING
    assert new_doc.file_type == "pdf"
    assert os.path.exists(new_doc.file_path)


def test_generate_daily_pdf_empty_is_noop(db_session):
    """With no confirmed chat entries for any user, no PDF or Document row is created."""
    scheduler_module.generate_daily_pdf()  # must not raise

    assert db_session.query(Document).count() == 0


# ── process_demo_documents ──────────────────────────────────────────────────

def test_process_demo_documents_indexes_each_folder(monkeypatch, tmp_path):
    """Each subfolder under media/demo/ is indexed into faiss_store/demo/<folder_name>/."""
    monkeypatch.setattr(scheduler_module, "FaissVectorStore", FakeFaissVectorStore)

    write_tiny_pdf(str(tmp_path / "media" / "demo" / "kirana_store" / "a.pdf"), "Kirana inventory")
    write_tiny_pdf(str(tmp_path / "media" / "demo" / "medical_store" / "b.pdf"), "Medical inventory")

    scheduler_module.process_demo_documents()

    user_ids_processed = {call[1] for call in FakeFaissVectorStore.build_calls}
    assert user_ids_processed == {"kirana_store", "medical_store"}
    assert (tmp_path / "faiss_store" / "demo" / "kirana_store" / "faiss.index").exists()


def test_process_demo_documents_skips_already_indexed_folders(monkeypatch, tmp_path):
    """A demo folder that already has a faiss.index is skipped on a subsequent run, avoiding duplicate work."""
    monkeypatch.setattr(scheduler_module, "FaissVectorStore", FakeFaissVectorStore)

    write_tiny_pdf(str(tmp_path / "media" / "demo" / "kirana_store" / "a.pdf"), "Kirana inventory")

    scheduler_module.process_demo_documents()
    assert len(FakeFaissVectorStore.build_calls) == 1

    # Second run should skip the now-indexed folder entirely.
    scheduler_module.process_demo_documents()
    assert len(FakeFaissVectorStore.build_calls) == 1


def test_process_demo_documents_missing_media_dir_is_noop(monkeypatch):
    """If media/demo doesn't exist at all, the function returns without error."""
    monkeypatch.setattr(scheduler_module, "FaissVectorStore", FakeFaissVectorStore)

    scheduler_module.process_demo_documents()  # no media/demo at all — must not raise

    assert FakeFaissVectorStore.build_calls == []


def test_process_demo_documents_folder_without_pdfs_is_skipped(monkeypatch, tmp_path):
    """A demo subfolder containing no PDF files is skipped rather than indexed empty."""
    monkeypatch.setattr(scheduler_module, "FaissVectorStore", FakeFaissVectorStore)

    empty_folder = tmp_path / "media" / "demo" / "empty_shop"
    empty_folder.mkdir(parents=True)

    scheduler_module.process_demo_documents()

    assert FakeFaissVectorStore.build_calls == []
