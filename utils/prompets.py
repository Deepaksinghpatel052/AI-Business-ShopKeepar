def search_and_summarize_prompt(query: str, context: str) -> str:
    return f"""You are a helpful business assistant.
            Answer the following question based only on the provided context.
            If the answer is not in the context, say "I don't have enough information."

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