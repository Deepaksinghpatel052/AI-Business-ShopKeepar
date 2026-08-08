import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import json
import logging
import uuid
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from models.document import Document, ProcessStatus
from RAG_src.data_loader import load_all_documents
from RAG_src.vectorstore import FaissVectorStore
from utils.database import SessionLocal
from dotenv import load_dotenv
from utils.helper import is_business_document

load_dotenv()

logger = logging.getLogger(__name__)
scheduler = BackgroundScheduler()


def def delete_by_ids(self, chunk_ids: list, user_id: int) -> bool:
    """
    Specific chunk IDs ko vector DB se delete karo.
    """
    user_dir = self._get_user_dir(user_id)
    faiss_path = os.path.join(user_dir, "faiss.index")
    meta_path  = os.path.join(user_dir, "metadata.pkl")

    if not os.path.exists(faiss_path):
        print(f"[DELETE] No index found for user {user_id}")
        return False

    # Metadata load karo
    with open(meta_path, "rb") as f:
        metadata = pickle.load(f)

    # chunk_ids jo delete karne hain
    ids_to_delete = set(chunk_ids)

    # Jo chunks delete nahi karne unko rakho
    remaining_meta = [
        m for m in metadata
        if m.get("chunk_id") not in ids_to_delete
    ]

    deleted_count = len(metadata) - len(remaining_meta)
    print(f"[DELETE] Removing {deleted_count} chunks for user {user_id}")

    if not remaining_meta:
        # Koi chunk nahi bacha — index aur metadata delete karo
        os.remove(faiss_path)
        os.remove(meta_path)
        print(f"[DELETE] Index cleared for user {user_id}")
        return True

    # Remaining chunks se naya index banao
    remaining_texts = [m["text"] for m in remaining_meta]
    embeddings = self._embed_model.embed_documents(remaining_texts)
    embeddings_np = np.array(embeddings).astype("float32")

    dim = embeddings_np.shape[1]
    new_index = faiss.IndexFlatL2(dim)
    new_index.add(embeddings_np)

    faiss.write_index(new_index, faiss_path)
    with open(meta_path, "wb") as f:
        pickle.dump(remaining_meta, f)

    print(f"[DELETE] Done — {len(remaining_meta)} chunks remaining")
    return True q():
    db = SessionLocal()
    try:
        pending_docs = db.query(Document).filter(
            Document.process == ProcessStatus.PROCESS
        ).limit(10).all()

        if not pending_docs:
            print("[SCHEDULER] No pending documents found.")
            return

        print(f"[SCHEDULER] Found {len(pending_docs)} pending documents.")

        from collections import defaultdict
        user_docs_map = defaultdict(list)
        for doc in pending_docs:
            user_docs_map[doc.user_id].append(doc)

        for user_id, user_pending_docs in user_docs_map.items():
            store = FaissVectorStore("faiss_store", embedding_model="openai")

            # Har document alag alag process karo
            for d in user_pending_docs:
                print(f"[SCHEDULER] Processing: {d.original_name}")

                user_documents = load_all_documents([d.file_path])
                if not user_documents:
                    print(f"[SCHEDULER] No content loaded from: {d.original_name}")
                    continue

                chunk_ids = store.build_from_documents(user_documents, user_id=user_id)

                d.process = ProcessStatus.DONE
                d.faiss_ids = json.dumps(chunk_ids)
                print(f"[SCHEDULER] Done: {d.original_name} — {len(chunk_ids)} chunks")

        db.commit()
        print("[SCHEDULER] All pending documents processed successfully.")

    except Exception as e:
        print(f"[SCHEDULER] Error: {e}")
        db.rollback()
    finally:
        db.close()

def verify_pending_documents():
    """
    Pending documents ko verify karo — business related hai ya nahi.
    Valid   → status = PROCESS
    Invalid → status = REJECTED
    """
    db = SessionLocal()
    try:
        pending_docs = db.query(Document).filter(
            Document.process == ProcessStatus.PENDING
        ).limit(10).all()

        if not pending_docs:
            print("[VERIFY] No pending documents found.")
            return

        print(f"[VERIFY] Found {len(pending_docs)} pending documents.")

        for doc in pending_docs:
            print(f"[VERIFY] Verifying: {doc.original_name}")

            is_valid, reason = is_business_document(doc.file_path)

            if is_valid:
                doc.process = ProcessStatus.PROCESS
                print(f"[VERIFY] Accepted: {doc.original_name} — {reason}")
            else:
                doc.process = ProcessStatus.REJECTED
                print(f"[VERIFY] Rejected: {doc.original_name} — {reason}")

        db.commit()
        print("[VERIFY] Verification complete.")

    except Exception as e:
        print(f"[VERIFY] Error: {e}")
        db.rollback()
    finally:
        db.close()

def start_scheduler():
    scheduler.add_job(
        verify_pending_documents,
        trigger=IntervalTrigger(minutes=15),
        id="verify_pending_documents",
        replace_existing=True,
    )
    scheduler.add_job(
        process_pending_documents,
        trigger=IntervalTrigger(minutes=30),
        id="process_pending_documents",
        replace_existing=True,
    )

    scheduler.start()
    print("[SCHEDULER] Background scheduler started — runs every 5 minutes.")
    return scheduler


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown()
        print("[SCHEDULER] Scheduler stopped.")