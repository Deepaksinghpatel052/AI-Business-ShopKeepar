from langchain_core.documents import Document

from RAG_src.embedding import EmbeddingPipeline


def test_chunk_documents_keeps_short_document_as_single_chunk():
    """A document shorter than chunk_size is returned as exactly one unchanged chunk."""
    pipeline = EmbeddingPipeline(chunk_size=1000, chunk_overlap=200)
    docs = [Document(page_content="Short text.", metadata={})]

    chunks = pipeline.chunk_documents(docs)

    assert len(chunks) == 1
    assert chunks[0].page_content == "Short text."


def test_chunk_documents_splits_long_document_into_multiple_chunks():
    """A document much longer than chunk_size is split into several chunks, each roughly bounded by chunk_size."""
    pipeline = EmbeddingPipeline(chunk_size=20, chunk_overlap=5)
    long_text = " ".join(["word"] * 100)  # far longer than chunk_size
    docs = [Document(page_content=long_text, metadata={})]

    chunks = pipeline.chunk_documents(docs)

    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk.page_content) <= 40  # some slack over chunk_size, splitter is soft-bounded


def test_embed_chunks_returns_one_vector_per_chunk(fake_embeddings):
    """embed_chunks() returns exactly one embedding vector per input chunk."""
    pipeline = EmbeddingPipeline(model_name="openai")
    chunks = [
        Document(page_content="chunk one", metadata={}),
        Document(page_content="chunk two", metadata={}),
        Document(page_content="chunk three", metadata={}),
    ]

    embeddings = pipeline.embed_chunks(chunks)

    assert len(embeddings) == 3
    for vector in embeddings:
        assert len(vector) == fake_embeddings  # fake_embeddings fixture returns its vector dim
