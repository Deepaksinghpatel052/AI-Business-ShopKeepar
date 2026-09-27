import csv
import logging
from pathlib import Path
from typing import List, Any
from langchain_core.documents import Document
from langchain_community.document_loaders import PyPDFLoader

logger = logging.getLogger(__name__)

# Excel/Windows se export hui CSV aksar utf-8 (BOM ke saath) ya cp1252 hoti hai
CSV_ENCODINGS = ("utf-8-sig", "cp1252")


def read_csv_as_text(file_path: str, max_rows: int | None = None) -> str:
    """
    CSV ko text me convert karo — har row ek line, "column: value | column: value" format me,
    taaki har chunk me column ka naam bhi rahe aur LLM/embedding ko context mile.
    max_rows diya ho to sirf utni rows padho (verification ke liye kaafi hai).
    """
    for encoding in CSV_ENCODINGS:
        try:
            with open(file_path, newline="", encoding=encoding) as f:
                reader = csv.reader(f)
                header = next(reader, None)
                if not header:
                    return ""
                header = [h.strip() or f"column_{i + 1}" for i, h in enumerate(header)]

                lines = []
                for row in reader:
                    if max_rows is not None and len(lines) >= max_rows:
                        break
                    if not any(cell.strip() for cell in row):
                        continue
                    lines.append(" | ".join(
                        f"{col}: {value.strip()}" for col, value in zip(header, row)
                    ))
                return "\n".join(lines)
        except UnicodeDecodeError:
            logger.debug(f"CSV not decodable as {encoding}, trying next: {file_path}")

    raise ValueError(f"Could not decode CSV file: {file_path}")


def load_pdf_documents(file_path: str) -> List[Any]:
    """PDF ke har page ka ek LangChain Document."""
    return PyPDFLoader(file_path).load()


def load_csv_documents(file_path: str) -> List[Any]:
    """
    Poori CSV ka ek LangChain Document — rows newline se alag hain, to text splitter
    chunks ko row boundary pe hi todta hai (ek row do chunks me nahi bantti).
    """
    text = read_csv_as_text(file_path)
    if not text.strip():
        return []
    return [Document(page_content=text, metadata={"source": file_path})]


LOADERS = {
    ".pdf": load_pdf_documents,
    ".csv": load_csv_documents,
}


def load_all_documents(file_paths: List[str]) -> List[Any]:
    """
    Load all supported files and convert to LangChain document structure.
    Supported: PDF, CSV — file extension se loader choose hota hai.
    """
    documents = []

    logger.debug(f"Found {len(file_paths)} files: {[str(f) for f in file_paths]}")
    for file_path in file_paths:
        file_path = Path(file_path).resolve()
        loader = LOADERS.get(file_path.suffix.lower())
        if loader is None:
            logger.warning(f"Unsupported file type, skipping: {file_path}")
            continue

        logger.debug(f"Loading {file_path.suffix} file: {file_path}")
        try:
            documents.extend(loader(str(file_path)))
        except Exception:
            logger.exception(f"Failed to load {file_path}")

    logger.debug(f"Total loaded documents: {len(documents)}")
    return documents

# Example usage
if __name__ == "__main__":
    file_paths = [
        'media/testing/01_inventory_report.pdf',
        'media/testing/02_sales_report_june.pdf',
        'media/testing/03_customer_orders.pdf',
        'media/testing/04_product_catalogue.pdf',
        'media/testing/05_monthly_business_report.pdf'
    ]
    docs = load_all_documents(file_paths)
    print(f"Loaded {len(docs)} documents.")
    print("Example document:", docs[0] if docs else None)
