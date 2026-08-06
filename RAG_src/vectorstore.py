import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import faiss
import numpy as np
import pickle
from typing import List, Any
from dotenv import load_dotenv
from RAG_src.embedding import EmbeddingPipeline

load_dotenv()


class FaissVectorStore:
    def __init__(
        self,
        persist_dir: str = "faiss_store",
        embedding_model: str = "openai",
        chunk_size: int = 1000,
        chunk_overlap: int = 200
    ):
        self.persist_dir = persist_dir
        self.embedding_model = embedding_model
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.index = None
        self.metadata = []

        if embedding_model == "openai":
            from langchain_openai import OpenAIEmbeddings
            self._embed_model = OpenAIEmbeddings(
                model="text-embedding-3-small",
                api_key=os.getenv("OPENAI_API_KEY")
            )
            self._use_openai = True
        else:
            from sentence_transformers import SentenceTransformer
            self._embed_model = SentenceTransformer(embedding_model)
            self._use_openai = False

        print(f"[INFO] Embedding model: {embedding_model}")

    # ── User ka alag folder ───────────────────────────────────────────────────
    def _get_user_dir(self, user_id: int) -> str:
        user_dir = os.path.join(self.persist_dir, str(user_id))
        os.makedirs(user_dir, exist_ok=True)
        return user_dir

    def _get_query_embedding(self, text: str) -> np.ndarray:
        if self._use_openai:
            embedding = self._embed_model.embed_query(text)
            return np.array([embedding]).astype("float32")
        else:
            return self._embed_model.encode([text]).astype("float32")

    # ── Build — user ka alag index ────────────────────────────────────────────
    def build_from_documents(self, documents: List[Any], user_id: int):
        print(f"[INFO] Building index for user {user_id}...")

        emb_pipe = EmbeddingPipeline(
            model_name=self.embedding_model,
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap
        )
        chunks = emb_pipe.chunk_documents(documents)
        embeddings = emb_pipe.embed_chunks(chunks)
        metadatas = [{"text": chunk.page_content, "user_id": user_id} for chunk in chunks]

        embeddings_np = np.array(embeddings).astype("float32")
        dim = embeddings_np.shape[1]

        user_dir = self._get_user_dir(user_id)
        faiss_path = os.path.join(user_dir, "faiss.index")
        meta_path  = os.path.join(user_dir, "metadata.pkl")

        # Existing index load karo — naye chunks add karo
        if os.path.exists(faiss_path):
            index = faiss.read_index(faiss_path)
            with open(meta_path, "rb") as f:
                existing_meta = pickle.load(f)
        else:
            index = faiss.IndexFlatL2(dim)
            existing_meta = []

        index.add(embeddings_np)
        existing_meta.extend(metadatas)

        faiss.write_index(index, faiss_path)
        with open(meta_path, "wb") as f:
            pickle.dump(existing_meta, f)

        print(f"[INFO] Index saved for user {user_id} — total vectors: {index.ntotal}")

    # ── Query — sirf us user ka index ────────────────────────────────────────
    def query(self, query_text: str, top_k: int = 5, user_id: int = None) -> List[dict]:
        if user_id is None:
            print("[WARN] user_id not provided — returning empty results.")
            return []

        user_dir = self._get_user_dir(user_id)
        faiss_path = os.path.join(user_dir, "faiss.index")
        meta_path  = os.path.join(user_dir, "metadata.pkl")

        if not os.path.exists(faiss_path):
            print(f"[WARN] No index found for user {user_id}.")
            return []

        index = faiss.read_index(faiss_path)
        with open(meta_path, "rb") as f:
            metadata = pickle.load(f)

        query_emb = self._get_query_embedding(query_text)
        D, I = index.search(query_emb, top_k)

        results = []
        for idx, dist in zip(I[0], D[0]):
            if idx < len(metadata):
                results.append({
                    "index": idx,
                    "distance": dist,
                    "metadata": metadata[idx]
                })

        print(f"[INFO] Found {len(results)} results for user {user_id}")
        return results