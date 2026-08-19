import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import warnings
warnings.filterwarnings("ignore")

from openai import OpenAI
from dotenv import load_dotenv
from datetime import date
from langchain_text_splitters import RecursiveCharacterTextSplitter

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))



def classify_and_extract(text: str, document_date: str = None) -> dict:
    """
    Ek chunk ka text lo — transactions aur narrative alag karo.

    Returns:
    {
        "transactions": [...],
        "narrative": "..."
    }
    """
    today = document_date or str(date.today())

    prompt = f"""
You are a business data extraction system.

Analyze the business document text below and separate the information into:

1. TRANSACTIONS
   Concrete business events involving a sale, purchase, or expense.

2. NARRATIVE
   All non-transaction information such as observations, customer feedback,
   opinions, trends, stock levels, recommendations, business insights,
   weekly/monthly summaries, and general notes.

Today's date: {today}

DOCUMENT TEXT:
{text}

Return ONLY valid JSON in exactly this structure:

{{
  "transactions": [
    {{
      "date": "YYYY-MM-DD",
      "product": "product or item name",
      "type": "sale/purchase/expense",
      "quantity": number or null,
      "unit": "strip/piece/kg/litre/bottle/sachet or null",
      "rate": number or null,
      "total": number or null
    }}
  ],
  "narrative": "all non-transaction text combined here"
}}

========================
TRANSACTION RULES
========================

1. WHAT IS A TRANSACTION
- Extract only concrete business events involving:
  - Sale
  - Purchase
  - Expense
- A transaction must have either:
  - an explicitly mentioned quantity, OR
  - an explicitly mentioned monetary total.
- If both quantity and total are null, do NOT create a transaction.

2. MONEY RULE
- Do not require both quantity and total.
- Examples:
  - "Sold 25 strips" → valid transaction because quantity exists.
  - "Paid shop rent Rs 8,000" → valid transaction because total exists.
- Do not invent missing prices, quantities, or totals.

3. DATE RULE
- Use ONLY dates explicitly written in the document.
- Examples:
  - "July 1" → use the year supported by the document context.
  - "August 8th" → use the year supported by the document context.
- Do NOT invent a date.
- Do NOT use today's date for a missing transaction date.
- Words such as "today", "this week", "this month", "last week",
  "over the weekend" are NOT explicit dates.
- If the transaction has no explicit date, use null.
- Never copy a date from another transaction unless the text explicitly
  states that the date applies to this transaction.

4. PRODUCT RULE
- product must never be null.
- For expenses without a product, use:
  - "Shop Rent"
  - "Staff Salary"
  - "Electricity Bill"
  - "Internet Bill"
  - "GST Payment"
  - or another appropriate expense name explicitly supported by the text.
- Do NOT invent a product name.

5. TYPE RULE
- Sale → "sale"
- Bought/restocked/purchased stock → "purchase"
- Rent, salary, electricity, internet, GST and similar business costs → "expense"
- "Restock", "stock purchase", and "opening stock" → "purchase"

6. ONE REAL-WORLD EVENT = ONE TRANSACTION
- Every real-world business event must produce EXACTLY ONE transaction object.
- Never create two transaction objects from different sentences or phrases
  that describe the SAME business event.
- Additional descriptions of the same event must be added to the "notes"
  field of that ONE transaction.
- Do NOT create a new transaction just because the same event is mentioned
  with additional details.

Example:

Text:
"July 6: Weekly medicine restock — Rs 5,500, including Crocin, ORS,
Disprin, Vicks and bandages."

Correct:
ONE transaction:
date = 2026-07-06
product = "various medicines"
type = "purchase"
total = 5500

Incorrect:
TWO transactions with the same date, type and total.

7. DUPLICATE EVENT RULE
- Before creating a transaction, check whether the information refers to
  an event that has already been extracted from the current document text.
- If two pieces of text refer to the same real-world event, MERGE them.
- Do NOT create a duplicate transaction.
- A shortened or repeated description of an existing event is NOT a new event.

8. IMPORTANT: SAME DATA DOES NOT ALWAYS MEAN DUPLICATE
- Do NOT assume two transactions are duplicates only because their
  product, quantity, date, or amount are identical.
- Example:

  Customer A bought:
  Paracetamol × 3 strips

  Customer B bought:
  Paracetamol × 3 strips

  These may be TWO separate transactions.
- Only merge records when the text indicates they represent the SAME
  real-world event.
- Never delete a potentially genuine separate transaction merely because
  its values are identical to another transaction.

9. AGGREGATED SALES RULE
- Weekly, monthly, multi-day, or period-level summaries are NOT individual
  transactions.
- Examples:
  - "Sold 40 ORS sachets in 4 days"
  - "Week 2 total sales were Rs 3,700"
  - "Crocin had its best week — 25 strips sold"
- These describe aggregated business activity and should normally go into
  NARRATIVE, not TRANSACTIONS.
- Do not convert an aggregated quantity into an individual transaction
  unless the text clearly identifies one specific business event.

10. TOTAL SALES / PERIOD TOTAL RULE
- Skip:
  - Weekly totals
  - Monthly totals
  - Overall sales totals
  - "Total sales around Rs X"
  - "Week 2 sales Rs X"
- These belong in NARRATIVE.

11. MULTIPLE PRODUCTS IN ONE PURCHASE
- If one purchase/restock event mentions multiple products but gives one
  combined total, treat it as ONE transaction.
- Do NOT create separate transactions for each product unless the document
  provides separate transaction information for them.

12. NOTES RULE
- notes must contain only information related to the transaction.
- Notes are supporting information, NOT separate transactions.
- Never create a transaction only because a sentence contains additional
  descriptive information.

13. SKIP THESE FROM TRANSACTIONS
- Inventory reports
- Stock levels
- Reorder suggestions
- "Stock getting critically low"
- Customer opinions
- Customer complaints
- Customer feedback
- Business observations
- Recommendations
- Trends
- Weekly/monthly summaries
- General business sentiment
- Future plans
- Requests or suggestions
- Aggregated multi-day/week/month sales

These belong in NARRATIVE.

========================
NARRATIVE RULES
========================

- Put all non-transaction information into "narrative".
- Preserve the meaning of the original text.
- Do not invent facts.
- Do not convert observations into transactions.
- Include:
  - Customer feedback
  - Customer complaints
  - Business observations
  - Sales trends
  - Stock observations
  - Reorder recommendations
  - Seasonal observations
  - Business insights
  - Weekly/monthly summaries
  - Future plans
  - General notes

========================
IMPORTANT EXTRACTION SAFETY
========================

- Extract ONLY information supported by the document.
- Never hallucinate dates.
- Never hallucinate quantities.
- Never hallucinate prices.
- Never hallucinate customers.
- Never hallucinate transaction IDs.
- Never split one real-world event into multiple transactions.
- Never merge two clearly separate real-world events merely because their
  data looks identical.
- When uncertain whether something is a transaction or narrative,
  prefer NARRATIVE unless the document clearly describes a concrete
  sale, purchase, or expense.
- If no transactions exist, return:
  "transactions": []
- If no narrative exists, return:
  "narrative": ""

Return ONLY valid JSON. Do not add explanations, markdown, comments,
or any text outside the JSON object.
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=4000,
        temperature=0,
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content.strip()
    return json.loads(raw)


def classify_document(chunks: list) -> dict:
    """
    Poore document ka text lo — chunks me split karo — har chunk classify karo.
    Sab transactions aur narratives combine karke return karo.

    Returns:
    {
        "transactions": [...],   # SQL me jayega
        "narratives": [...]      # Vector DB me jayega (paragraph list)
    }
    """
    print(f"[CLASSIFIER] {len(chunks)} chunks to classify")

    all_transactions = []
    all_narratives = []

    for i, chunk in enumerate(chunks):
        print(f"[CLASSIFIER] Chunk {i+1}/{len(chunks)}")
        result = classify_and_extract(text=chunk)

        all_transactions.extend(result.get("transactions", []))

        narrative = result.get("narrative", "").strip()
        if narrative:
            # Paragraph chunks me split karo
            paragraphs = [p.strip() for p in narrative.split("\n\n") if p.strip()]
            all_narratives.extend(paragraphs)

    return {
        "transactions": all_transactions,
        "narratives": all_narratives,
    }


# ── Test ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    from RAG_src.data_loader import load_all_documents
    from RAG_src.embedding import EmbeddingPipeline

    import json

    file_paths = ["media/testing/devnix_store_narrative_jul_aug2026.pdf"]
    docs = load_all_documents(file_paths)

    emb_pipe = EmbeddingPipeline(
        model_name="openai",
        chunk_size=1000,
        chunk_overlap=200
    )
    chunks = emb_pipe.chunk_documents(docs)

    print(f"chunks : {len(chunks)}")

    result = classify_document(chunks)

    # for chunk in chunks:
    #     print(f" chunk ==: {chunk}") 

    with open("classification_result.txt", "w", encoding="utf-8") as f:
        f.write(f"File: media/testing/devnix_store_narrative_jul_aug2026.pdf")
        
        f.write("======== TRANSACTIONS =======\n")
        for t in result["transactions"]:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
        
        f.write("\n======== NARRATIVES =======\n")
        for i, n in enumerate(result["narratives"], 1):
            f.write(f"\n[{i}] {n}\n")

    print("Saved to classification_result.txt")
    # for doc in docs:
    #     print(f"\nFile: {doc['file_path']}")
    #     result = classify_document(doc["text"])

    #     print(f"\n=== TRANSACTIONS ({len(result['transactions'])}) ===")
    #     for t in result["transactions"]:
    #         print(t)

    #     print(f"\n=== NARRATIVE PARAGRAPHS ({len(result['narratives'])}) ===")
    #     for p in result["narratives"]:
    #         print(f"- {p[:100]}")