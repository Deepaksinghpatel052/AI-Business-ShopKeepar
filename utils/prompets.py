from datetime import date



def extract_and_confirm_confirmation_propmt(extracted: dict) -> str:
    return f"""I understood the following data:

        Product  : {extracted.get('product', 'N/A')}
        Quantity : {extracted.get('quantity', 'N/A')}
        Price    : Rs {extracted.get('price_per_unit', 'N/A')} per unit
        Total    : Rs {extracted.get('total', 'N/A')}
        Type     : {extracted.get('type', 'N/A')}
        Notes    : {extracted.get('notes', 'N/A')}
        Date     : {date.today()}

        Reply 'yes' to confirm and save, or 'no' to reject."""


def extract_and_confirm_extract_prompt(message: str) -> str:
    return f"""Extract business data from this message.
        Message: "{message}"

        Reply in JSON only, no extra text:
        {{
        "product": "product name",
        "quantity": number,
        "price_per_unit": number,
        "total": number,
        "type": "sale/purchase/expense/stock",
        "notes": "any additional info"
        }}

        If any field is not mentioned, set it to null."""

def handle_message_intent_prompt(message: str) -> str:
    return f"""You are an intent classifier for a Business AI assistant.
            User message: "{message}"

            Classify the intent as ONE of:
            - "query" — user is asking a question about existing business data, purchases, sales, expenses, stock
            - "add_data" — user wants to add/save NEW business data
            - "unclear" — casual chat, greetings only

            IMPORTANT: Any question about past purchases, sales, expenses, or stock is ALWAYS "query".
            Examples of "query": 
            - "How many X did I buy?"
            - "What did I sell today?"
            - "How much did I spend?"

            Reply in JSON only:
            {{"intent": "query/add_data/unclear", "reason": "short reason"}}"""



def search_and_summarize_prompt(query: str, context: str) -> str:
    today = date.today()
    return f"""You are a helpful business assistant.
        Answer the  following question based ONLY on the provided context.

        Today's date is {today.strftime('%d %B %Y')}.
        Use this to understand relative dates like "today", "yesterday", "last week" etc.

        Question: {query}

        Context:
        {context}

        Answer:"""

def document_verification_prompt(text: str) -> str:
    return f"""You are a document classifier for a Business AI assistant.
Check if the document is REAL business data — not fictional, academic, or creative content.

ALLOWED (must be real business data):
- Sales reports, invoices, inventory records
- Customer orders, purchase orders
- Product catalogues, price lists
- Financial reports, profit/loss statements
- HR documents, employee records

NOT ALLOWED:
- Personal documents (diary, letters, ID cards)
- Academic/college projects (even if they use business terms)
- Movie scripts, screenplays, stories (look for: FADE IN, INT., EXT., character names in CAPS, dialogue format)
- News articles, blogs
- Medical records
- Any fictional or hypothetical business data

IMPORTANT: If the document contains screenplay elements like "FADE IN:", "INT.", "EXT.", 
character dialogue, or "Written by:" with a script version — it is a MOVIE SCRIPT, not a business document.

Document content (first 500 chars):
{text[:500]}

Reply in JSON only:
{{"is_business": true/false, "reason": "short reason"}}"""