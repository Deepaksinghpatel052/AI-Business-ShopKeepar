import os
import io
import json
from openai import OpenAI
from dotenv import load_dotenv
from utils.prompets import document_verification_prompt

load_dotenv()

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
        # print(f"[INFO] Extracted text from {file_path}: {text[:100]}...")  # Debugging
        if not text.strip():
            return False, "Could not extract text from document"

        prompt = document_verification_prompt(text)
 
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=100,
            temperature=0,          # ← consistent results ke liye
            response_format={"type": "json_object"},  # ← guaranteed JSON
        )

        result = json.loads(response.choices[0].message.content)
        return result["is_business"], result["reason"]

    except Exception as e:
        return False, f"Verification failed: {str(e)}"

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