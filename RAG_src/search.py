import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from RAG_src.vectorstore import FaissVectorStore
from langchain_openai import ChatOpenAI
from utils.prompets import search_and_summarize_prompt

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

    def search_and_summarize(self, query: str, top_k: int = 5, user_id: int = None) -> str:
        results = self.vectorstore.query(query, top_k=top_k, user_id=user_id)
        texts = [r["metadata"].get("text", "") for r in results if r["metadata"]]
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