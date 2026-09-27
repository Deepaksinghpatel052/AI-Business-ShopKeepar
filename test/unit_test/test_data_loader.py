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


# ── CSV ─────────────────────────────────────────────────────────────────────

def write_csv(tmp_path, content, filename="stock.csv", encoding="utf-8"):
    path = tmp_path / filename
    path.write_bytes(content.encode(encoding))
    return str(path)


def test_load_all_documents_reads_csv_rows_with_column_names(tmp_path):
    """Each CSV row becomes one line that carries its column names, so chunks stay self-describing."""
    csv_path = write_csv(tmp_path, "Product,Qty,Price\nRice,200,45\nSugar,50,40\n")

    docs = load_all_documents([csv_path])

    assert len(docs) == 1
    assert docs[0].page_content.splitlines() == [
        "Product: Rice | Qty: 200 | Price: 45",
        "Product: Sugar | Qty: 50 | Price: 40",
    ]


def test_load_all_documents_csv_skips_blank_rows_and_handles_bom(tmp_path):
    """Excel-style UTF-8 BOM is stripped from the first header and fully blank rows are dropped."""
    csv_path = write_csv(tmp_path, "﻿Item,Stock\nPen,10\n,\nBook,3\n")

    text = load_all_documents([csv_path])[0].page_content

    assert text == "Item: Pen | Stock: 10\nItem: Book | Stock: 3"


def test_load_all_documents_csv_falls_back_to_cp1252(tmp_path):
    """A CSV saved by Windows Excel in cp1252 (not valid UTF-8) still loads."""
    csv_path = write_csv(tmp_path, "Item,Note\nCafé latte,Bestseller\n", encoding="cp1252")

    text = load_all_documents([csv_path])[0].page_content

    assert text == "Item: Café latte | Note: Bestseller"


def test_load_all_documents_header_only_csv_returns_empty(tmp_path):
    """A CSV with only a header row has no data, so nothing is loaded (scheduler then skips it)."""
    csv_path = write_csv(tmp_path, "Product,Qty\n")

    assert load_all_documents([csv_path]) == []


def test_load_all_documents_mixes_pdf_and_csv(make_pdf, tmp_path):
    """PDF and CSV paths can be loaded together in one call — each goes through its own loader."""
    pdf_path = make_pdf(text="PDF sales total.")
    csv_path = write_csv(tmp_path, "Item,Qty\nSoap,12\n")

    combined = " ".join(d.page_content for d in load_all_documents([pdf_path, csv_path]))

    assert "PDF sales total" in combined
    assert "Item: Soap | Qty: 12" in combined


def test_load_all_documents_skips_unsupported_extension(tmp_path):
    """A file type with no registered loader is skipped instead of being fed to the PDF parser."""
    txt_path = tmp_path / "notes.txt"
    txt_path.write_text("hello")

    assert load_all_documents([str(txt_path)]) == []
