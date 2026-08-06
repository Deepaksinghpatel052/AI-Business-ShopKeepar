import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from typing import List, Any
from langchain_text_splitters import RecursiveCharacterTextSplitter
from dotenv import load_dotenv

load_dotenv()


class EmbeddingPipeline:

    def __init__(self, model_name: str = "openai", chunk_size: int = 1000, chunk_overlap: int = 200):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.model_name = model_name

        if model_name == "openai":
            from langchain_openai import OpenAIEmbeddings
            self.model = OpenAIEmbeddings(
                model="text-embedding-3-small",
                api_key=os.getenv("OPENAI_API_KEY")
            )
        else:
            from sentence_transformers import SentenceTransformer
            self._local_model = SentenceTransformer(model_name)
            self.model = None

    def chunk_documents(self, documents: List[Any]) -> List[Any]:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            length_function=len,
            separators=["\n\n", "\n", " ", ""]
        )
        chunks = splitter.split_documents(documents)
        print(f"[INFO] Split {len(documents)} documents into {len(chunks)} chunks.")
        return chunks

    def embed_chunks(self, chunks: List[Any]) -> List[List[float]]:
        texts = [chunk.page_content for chunk in chunks]
        print(f"[INFO] Generating embeddings for {len(texts)} chunks...")

        if self.model_name == "openai":
            embeddings = self.model.embed_documents(texts)
        else:
            embeddings = self._local_model.encode(texts, show_progress_bar=True).tolist()

        print(f"[INFO] Total embeddings: {len(embeddings)}")
        return embeddings


# Example usage
if __name__ == "__main__":
    from RAG_src.data_loader import load_all_documents

    file_paths = [
        'media/testing/01_inventory_report.pdf',
        'media/testing/02_sales_report_june.pdf',
        'media/testing/03_customer_orders.pdf',
        'media/testing/04_product_catalogue.pdf',
        'media/testing/05_monthly_business_report.pdf'
    ]
    docs = load_all_documents(file_paths)
    emb_pipe = EmbeddingPipeline()
    chunks = emb_pipe.chunk_documents(docs)
    embeddings = emb_pipe.embed_chunks(chunks)
    print("[INFO] Example embedding:", embeddings[0] if len(embeddings) > 0 else None)