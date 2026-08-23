import os
import io
import json
import logging
from openai import OpenAI
from dotenv import load_dotenv
from utils.prompets import document_verification_prompt
from RAG_src.vectorstore import FaissVectorStore
load_dotenv()

logger = logging.getLogger(__name__)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def is_business_document(file_path: str) -> tuple[bool, str]:
    """
    LLM se verify karo ki document business related hai ya nahi.
    Returns: (is_valid, reason)
    """
    try:
        with open(file_path, "rb") as f:
            file_bytes = f.read()

        ext = file_path.split(".")[-1].lower()
        text = ""

        if ext == "pdf":
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(file_bytes))
            for page in reader.pages[:2]:
                text += page.extract_text() or ""
        else:
            text = file_bytes.decode("utf-8", errors="ignore")
        logger.debug(f"Extracted text from {file_path}: {text[:100]}...")
        if not text.strip():
            logger.warning(f"No extractable text in document: {file_path}")
            return False, "Could not extract text from document"

        prompt = document_verification_prompt(text)
 
        response = client.chat.completions.create(
            model=os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini"),
            messages=[{"role": "user", "content": prompt}],
            max_tokens=100,
            temperature=0,          # ← consistent results ke liye
            response_format={"type": "json_object"},  # ← guaranteed JSON
        )

        result = json.loads(response.choices[0].message.content)
        logger.info(f"Document verification for {file_path}: is_business={result['is_business']} reason={result['reason']}")
        return result["is_business"], result["reason"]

    except Exception as e:
        logger.exception(f"Document verification failed: {file_path}")
        return False, f"Verification failed: {str(e)}"


def delete_document_from_vector_db(doc, user_id: int) -> bool:
    """
    Document ke faiss_ids use karke vector DB se chunks delete karo.
    """
    if not doc.faiss_ids:
        logger.warning(f"No faiss_ids found for document: {doc.original_name}")
        return False

    chunk_ids = json.loads(doc.faiss_ids)
    store = FaissVectorStore("faiss_store", embedding_model="openai")
    deleted = store.delete_by_ids(chunk_ids, user_id=user_id)
    logger.info(f"Vector chunks deleted for document: {doc.original_name} — success={deleted}")
    return deleted

if __name__ == "__main__":
    file_paths = [
        'media/testing/01_inventory_report.pdf',
        'media/testing/02_sales_report_june.pdf',
        'media/testing/03_customer_orders.pdf',
        'media/testing/04_product_catalogue.pdf',
        'media/testing/05_monthly_business_report.pdf',
        'media/testing/01_easy_personal_diary.pdf',
        'media/testing/02_medium_college_project.pdf',
        'media/testing/03_hard_movie_script.pdf'
    ]
    
    for file_path in file_paths:
        is_valid, reason = is_business_document(file_path)
        print(f"File: {file_path} | Is Business Document: {is_valid} | Reason: {reason}")