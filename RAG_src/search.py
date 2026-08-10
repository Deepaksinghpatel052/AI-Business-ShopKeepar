import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from RAG_src.vectorstore import FaissVectorStore
from langchain_openai import ChatOpenAI
from utils.prompets import search_and_summarize_prompt
import json
from models.chat_entry import ChatEntry, ChatStatus
from utils.database import SessionLocal
from datetime import date

load_dotenv()


class RAGSearch:
    def __init__(
        self,
        persist_dir: str = "faiss_store",
        embedding_model: str = "openai",
        llm_model: str = os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini")
    ):
        self.vectorstore = FaissVectorStore(persist_dir, embedding_model)

        # Faiss index already exist karta hai to load karo, warna build karo
        faiss_path = os.path.join(persist_dir, "faiss.index")
        meta_path  = os.path.join(persist_dir, "metadata.pkl")

        if os.path.exists(faiss_path) and os.path.exists(meta_path):
            self.vectorstore.load()
        else:
            print("[WARN] No existing vector store found. Build it first using vectorstore.py")

        # OpenAI LLM
        self.llm = ChatOpenAI(
            model=llm_model,
            api_key=os.getenv("OPENAI_API_KEY")
        )
        print(f"[INFO] OpenAI LLM initialized: {llm_model}")

    def handle_message(self, message: str, user_id: int) -> str:
        import json
        from models.chat_entry import ChatEntry, ChatStatus
        from utils.database import SessionLocal
        # Step 0 — Check karo koi pending entry hai is user ki
        db = SessionLocal()
        try:
            pending_entry = db.query(ChatEntry).filter(
                ChatEntry.user_id == user_id,
                ChatEntry.status == ChatStatus.PENDING
            ).order_by(ChatEntry.created_at.desc()).first()
        finally:
            db.close()

        # Agar pending entry hai to confirm/reject check karo
        if pending_entry:
            msg_lower = message.strip().lower()

            if msg_lower in ["yes", "haan", "haa", "ha", "confirm", "ok", "sahi"]:
                return self._confirm_entry(pending_entry.id)

            elif msg_lower in ["no", "nahi", "nhi", "reject", "galat", "wrong"]:
                return self._reject_entry(pending_entry.id)

        # Step 1 — Intent detect karo
        intent_prompt = f"""You are an intent classifier for a Business AI assistant.

    User message: "{message}"

    Classify the intent as ONE of:
    - "query" — user is asking a question about existing business data
    - "add_data" — user wants to add/save new business data (sales, stock, purchases, expenses etc.)
    - "unclear" — cannot determine intent

    Reply in JSON only:
    {{"intent": "query/add_data/unclear", "reason": "short reason"}}"""

        intent_response = self.llm.invoke([intent_prompt])

        try:
            result = json.loads(intent_response.content)
            intent = result["intent"]
        except:
            intent = "unclear"
        print(f"intent : {intent}")
        # Step 2 — Intent ke hisaab se call karo
        if intent == "query":
            return self.search_and_summarize(message, user_id=user_id)

        elif intent == "add_data":
            return self._extract_and_confirm(message, user_id)

        else:
            return "I'm not sure what you mean. Please ask a business question or provide data to save (e.g. 'Today I sold 5 Titan watches at Rs 3200 each')."

    def _confirm_entry(self, entry_id: int) -> str:
        """Entry confirm karo — status = confirmed."""
        from models.chat_entry import ChatEntry, ChatStatus
        from utils.database import SessionLocal

        db = SessionLocal()
        try:
            entry = db.query(ChatEntry).filter(ChatEntry.id == entry_id).first()
            if not entry:
                return "Entry not found."

            entry.status = ChatStatus.CONFIRMED
            db.commit()
            return f"Data confirmed and saved successfully! It will be processed at end of day."
        finally:
            db.close()
    
    def _reject_entry(self, entry_id: int) -> str:
        """Entry reject karo — DB se delete karo."""
        from models.chat_entry import ChatEntry
        from utils.database import SessionLocal

        db = SessionLocal()
        try:
            entry = db.query(ChatEntry).filter(ChatEntry.id == entry_id).first()
            if not entry:
                return "Entry not found."

            db.delete(entry)
            db.commit()
            return "Data rejected and removed. Please provide the correct information."
        finally:
            db.close()

    def _extract_and_confirm(self, message: str, user_id: int) -> str:

        extract_prompt = f"""Extract business data from this message.

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

        extract_response = self.llm.invoke([extract_prompt])
        print(f"[DEBUG] LLM raw response: {extract_response.content}")

        try:
            raw = extract_response.content.strip()
            raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            extracted = json.loads(raw)
        except Exception as e:
            print(f"[DEBUG] JSON parse error: {e}")
            return "Could not understand the data. Please try again with more details."

        # Confirmation message banao
        confirmation = f"""I understood the following data:

    Product  : {extracted.get('product', 'N/A')}
    Quantity : {extracted.get('quantity', 'N/A')}
    Price    : Rs {extracted.get('price_per_unit', 'N/A')} per unit
    Total    : Rs {extracted.get('total', 'N/A')}
    Type     : {extracted.get('type', 'N/A')}
    Notes    : {extracted.get('notes', 'N/A')}
    Date     : {date.today()}

    Reply 'yes' to confirm and save, or 'no' to reject."""

        db = SessionLocal()
        try:
            entry = ChatEntry(
                user_id=user_id,
                raw_message=message,
                extracted=json.dumps({**extracted, "date": str(date.today())}),  # ← date add
                status=ChatStatus.PENDING
            )
            db.add(entry)
            db.commit()
            db.refresh(entry)
            print(f"[DEBUG] Entry saved with ID: {entry.id}")
        finally:
            db.close()

        return confirmation


    def search_and_summarize(self, query: str, top_k: int = 5, user_id: int = None) -> str:
        # Query me aaj ki date add karo
        enhanced_query = f"{query} (today's date is {date.today()})"
        
        results = self.vectorstore.query(enhanced_query, top_k=top_k, user_id=user_id)
        
        texts = [r["metadata"].get("text", "") for r in results if r["metadata"]]
        
        # Source 2 — chat_entries table se confirmed entries lo
        db = SessionLocal()
        try:
            confirmed_entries = db.query(ChatEntry).filter(
                ChatEntry.user_id == user_id,
                ChatEntry.status == ChatStatus.CONFIRMED
            ).all()

            for entry in confirmed_entries:
                try:
                    data = json.loads(entry.extracted)
                    text = f"Chat entry: Product={data.get('product')}, Quantity={data.get('quantity')}, Price per unit=Rs {data.get('price_per_unit')}, Total=Rs {data.get('total')}, Type={data.get('type')}, Notes={data.get('notes')}"
                    texts.append(text)
                except:
                    pass
        finally:
            db.close()
        
        context = "\n\n".join(texts)

        if not context:
            return "No relevant documents found."

        prompt = search_and_summarize_prompt(query, context)

        response = self.llm.invoke([prompt])
        return response.content


# Example usage
if __name__ == "__main__":
    rag = RAGSearch()
    query = "Which product has low stock?"
    answer = rag.search_and_summarize(query, top_k=3)
    print("Answer:", answer)