import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
from dotenv import load_dotenv
from RAG_src.vectorstore import FaissVectorStore
from langchain_openai import ChatOpenAI
from utils.prompets import search_and_summarize_prompt, handle_message_intent_prompt
from utils.prompets import extract_and_confirm_confirmation_propmt, extract_and_confirm_extract_prompt
import json
from models.chat_entry import ChatEntry, ChatStatus
from models.shop_owner import ShopOwner
from utils.database import SessionLocal
from datetime import date

DEMO_PERSIST_DIR = os.path.join("faiss_store", "demo")

load_dotenv()

logger = logging.getLogger(__name__)


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
            logger.warning("No existing vector store found at persist_dir root. Build it first using vectorstore.py")

        # OpenAI LLM
        self.llm = ChatOpenAI(
            model=llm_model,
            api_key=os.getenv("OPENAI_API_KEY")
        )
        logger.info(f"OpenAI LLM initialized: {llm_model}")

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
        intent_prompt = handle_message_intent_prompt(message)

        intent_response = self.llm.invoke([intent_prompt])

        try:
            result = json.loads(intent_response.content)
            intent = result["intent"]
        except Exception:
            logger.warning(f"Could not parse intent classification response — user_id={user_id} raw={intent_response.content!r}")
            intent = "unclear"
        logger.info(f"Intent detected: {intent} — user_id={user_id}")
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
                logger.warning(f"Confirm requested for missing chat entry: entry_id={entry_id}")
                return "Entry not found."

            entry.status = ChatStatus.CONFIRMED
            db.commit()
            logger.info(f"Chat entry confirmed: entry_id={entry_id} user_id={entry.user_id}")
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
                logger.warning(f"Reject requested for missing chat entry: entry_id={entry_id}")
                return "Entry not found."

            user_id = entry.user_id
            db.delete(entry)
            db.commit()
            logger.info(f"Chat entry rejected and removed: entry_id={entry_id} user_id={user_id}")
            return "Data rejected and removed. Please provide the correct information."
        finally:
            db.close()

    def _extract_and_confirm(self, message: str, user_id: int) -> str:

        extract_prompt = extract_and_confirm_extract_prompt(message)

        extract_response = self.llm.invoke([extract_prompt])
        logger.debug(f"Extraction LLM raw response — user_id={user_id}: {extract_response.content}")

        try:
            raw = extract_response.content.strip()
            raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            extracted = json.loads(raw)
        except Exception:
            logger.warning(f"Could not parse extracted data JSON — user_id={user_id}")
            return "Could not understand the data. Please try again with more details."

        # Confirmation message banao
        confirmation = extract_and_confirm_confirmation_propmt(extracted)

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
            logger.info(f"Pending chat entry saved — entry_id={entry.id} user_id={user_id}")
        finally:
            db.close()

        return confirmation


    def search_and_summarize(self, query: str, top_k: int = 5, user_id: int = None) -> str:

        # Bas aaj ki date inject karo — baki LLM decide kare
        today = date.today()
        enhanced_query = f"{query} (today's date is {today.strftime('%d %B %Y')})"

        # Vector DB se search karo — demo mode enabled hai to demo dataset se, warna user ke apne store se
        db = SessionLocal()
        try:
            user = db.query(ShopOwner).filter(ShopOwner.id == user_id).first()

            if user and user.demo_mode_enabled and user.demo_dataset:
                logger.info(f"Searching demo dataset '{user.demo_dataset}' — user_id={user_id}")
                demo_store = FaissVectorStore(DEMO_PERSIST_DIR, embedding_model=self.vectorstore.embedding_model)
                results = demo_store.query(enhanced_query, top_k=top_k, user_id=user.demo_dataset)
            else:
                results = self.vectorstore.query(enhanced_query, top_k=top_k, user_id=user_id)

            texts = [r["metadata"].get("text", "") for r in results if r["metadata"]]

            # Source 2 — chat_entries table se confirmed entries lo
            confirmed_entries = db.query(ChatEntry).filter(
                ChatEntry.user_id == user_id,
                ChatEntry.status == ChatStatus.CONFIRMED,
            ).all()
            for entry in confirmed_entries:
                try:
                    data = json.loads(entry.extracted)
                    text = (
                        f"Date={data.get('date', str(today))}, "
                        f"Product={data.get('product')}, "
                        f"Quantity={data.get('quantity')}, "
                        f"Total=Rs {data.get('total')}, "
                        f"Type={data.get('type')}"
                    )
                    texts.append(text)
                except:
                    pass
        finally:
            db.close()

        context = "\n\n".join(texts)
        logger.debug(f"Context for summarization — user_id={user_id}: {context[:500]}...")
        if not context:
            logger.info(f"No relevant context found for query — user_id={user_id}")
            return "No relevant data found."

        prompt = search_and_summarize_prompt(query, context)
        response = self.llm.invoke([prompt])
        return response.content


# Example usage
if __name__ == "__main__":
    rag = RAGSearch()
    query = "Which product has low stock?"
    answer = rag.search_and_summarize(query, top_k=3)
    print("Answer:", answer)