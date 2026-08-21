import os

import pytest
from langchain_core.documents import Document

from RAG_src.vectorstore import FaissVectorStore


def make_docs(*texts):
    return [Document(page_content=t, metadata={}) for t in texts]


@pytest.fixture()
def store(tmp_path, fake_embeddings):
    # chunk_size large enough that each short test document stays a single chunk,
    # keeping chunk counts predictable in assertions.
    return FaissVectorStore(str(tmp_path), embedding_model="openai", chunk_size=1000, chunk_overlap=0)


def test_build_from_documents_creates_index_and_metadata(store, tmp_path):
    """build_from_documents() writes faiss.index and metadata.pkl under persist_dir/<user_id>/."""
    docs = make_docs("Sales report: total revenue Rs 50000 this month.")
    chunk_ids = store.build_from_documents(docs, user_id=42)

    assert len(chunk_ids) == 1
    user_dir = tmp_path / "42"
    assert (user_dir / "faiss.index").exists()
    assert (user_dir / "metadata.pkl").exists()


def test_build_from_documents_appends_on_second_call(store):
    """Calling build_from_documents() twice for the same user appends to the existing index rather than replacing it."""
    store.build_from_documents(make_docs("first document text"), user_id=7)
    chunk_ids_second = store.build_from_documents(make_docs("second document text"), user_id=7)

    # top_k matches the actual stored count (2) — FAISS pads results with -1 entries
    # when top_k exceeds the index size, which isn't the case being tested here.
    results = store.query("document", top_k=2, user_id=7)
    assert len(results) == 2
    assert chunk_ids_second[0] in {r["metadata"]["chunk_id"] for r in results}


def test_build_from_documents_is_isolated_per_user(store):
    """Chunks built for one user_id never show up in another user_id's query results."""
    store.build_from_documents(make_docs("user A data"), user_id="user_a")
    store.build_from_documents(make_docs("user B data"), user_id="user_b")

    results_a = store.query("data", top_k=1, user_id="user_a")
    results_b = store.query("data", top_k=1, user_id="user_b")

    assert len(results_a) == 1
    assert len(results_b) == 1
    assert results_a[0]["metadata"]["user_id"] == "user_a"
    assert results_b[0]["metadata"]["user_id"] == "user_b"


def test_query_returns_metadata_with_text_and_chunk_id(store):
    """query() results carry the original chunk text, chunk_id, and a distance score."""
    chunk_ids = store.build_from_documents(make_docs("kirana store inventory list"), user_id=1)
    results = store.query("inventory", top_k=1, user_id=1)

    assert len(results) == 1
    metadata = results[0]["metadata"]
    assert metadata["text"] == "kirana store inventory list"
    assert metadata["chunk_id"] == chunk_ids[0]
    assert "distance" in results[0]


def test_query_returns_empty_for_unknown_user(store):
    """Querying a user_id with no index on disk returns an empty list instead of raising."""
    assert store.query("anything", user_id="does-not-exist") == []


def test_query_returns_empty_when_user_id_missing(store):
    """Querying with user_id=None returns an empty list without touching disk."""
    assert store.query("anything", user_id=None) == []


def test_delete_by_ids_removes_only_targeted_chunks(store):
    """delete_by_ids() removes exactly the requested chunk ids and leaves the rest queryable."""
    chunk_ids = store.build_from_documents(
        make_docs("chunk one text", "chunk two text", "chunk three text"),
        user_id=5,
    )
    assert len(chunk_ids) == 3

    deleted = store.delete_by_ids([chunk_ids[0]], user_id=5)

    assert deleted is True
    # top_k matches the 2 remaining chunks — see note in test_build_from_documents_appends_on_second_call.
    remaining = store.query("chunk", top_k=2, user_id=5)
    remaining_ids = {r["metadata"]["chunk_id"] for r in remaining}
    assert len(remaining) == 2
    assert chunk_ids[0] not in remaining_ids
    assert chunk_ids[1] in remaining_ids
    assert chunk_ids[2] in remaining_ids


def test_delete_by_ids_removes_index_files_when_nothing_remains(store, tmp_path):
    """Deleting every chunk for a user removes the faiss.index and metadata.pkl files entirely."""
    chunk_ids = store.build_from_documents(make_docs("only chunk"), user_id=9)

    deleted = store.delete_by_ids(chunk_ids, user_id=9)

    assert deleted is True
    user_dir = tmp_path / "9"
    assert not (user_dir / "faiss.index").exists()
    assert not (user_dir / "metadata.pkl").exists()


def test_delete_by_ids_returns_false_for_unknown_user(store):
    """delete_by_ids() returns False for a user_id that has no index on disk."""
    assert store.delete_by_ids(["some-id"], user_id="ghost") is False
