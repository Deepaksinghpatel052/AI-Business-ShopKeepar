from RAG_src.data_loader import load_all_documents


def test_load_all_documents_reads_real_pdf_text(make_pdf):
    """load_all_documents() extracts the real text content from a PDF file."""
    pdf_path = make_pdf(text="Total sales this month: Rs 12345.")

    docs = load_all_documents([pdf_path])

    assert len(docs) >= 1
    combined_text = " ".join(d.page_content for d in docs)
    assert "Total sales" in combined_text


def test_load_all_documents_combines_multiple_pdfs(make_pdf):
    """load_all_documents() loads and combines content from multiple PDF paths in one call."""
    pdf_a = make_pdf(filename="a.pdf", text="Document A content.")
    pdf_b = make_pdf(filename="b.pdf", text="Document B content.")

    docs = load_all_documents([pdf_a, pdf_b])

    combined_text = " ".join(d.page_content for d in docs)
    assert "Document A" in combined_text
    assert "Document B" in combined_text


def test_load_all_documents_skips_missing_file_without_raising(tmp_path):
    """A nonexistent PDF path is skipped silently, returning an empty list instead of raising."""
    missing_path = str(tmp_path / "does_not_exist.pdf")

    docs = load_all_documents([missing_path])

    assert docs == []


def test_load_all_documents_skips_only_the_broken_path(make_pdf, tmp_path):
    """Given one missing path and one valid PDF, only the valid PDF's content is returned."""
    good_pdf = make_pdf(text="Readable content here.")
    missing_path = str(tmp_path / "missing.pdf")

    docs = load_all_documents([missing_path, good_pdf])

    assert len(docs) >= 1
    assert "Readable content" in " ".join(d.page_content for d in docs)


def test_load_all_documents_empty_list_returns_empty():
    """Calling load_all_documents() with an empty path list returns an empty list."""
    assert load_all_documents([]) == []
