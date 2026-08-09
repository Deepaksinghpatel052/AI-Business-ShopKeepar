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


def process_pending_documents():
    """
    Pending documents ko process karo.
    """
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



def handle_update_documents():
    """
    UPDATE status wale documents ko handle karo.
    1. Purane chunks vector DB se delete karo
    2. faiss_ids = null karo
    3. Status = PENDING karo
    Baaki kaam existing scheduler karega (verify → process → embed)
    """
    db = SessionLocal()
    try:
        update_docs = db.query(Document).filter(
            Document.process == ProcessStatus.UPDATE
        ).limit(10).all()

        if not update_docs:
            print("[UPDATE] No documents with UPDATE status found.")
            return

        print(f"[UPDATE] Found {len(update_docs)} documents to update.")

        for doc in update_docs:
            print(f"[UPDATE] Processing: {doc.original_name}")

            # Purane chunks vector DB se delete karo
            if doc.faiss_ids:
                from utils.helper import delete_document_from_vector_db
                success = delete_document_from_vector_db(doc, user_id=doc.user_id)
                if success:
                    print(f"[UPDATE] Old chunks deleted for: {doc.original_name}")
                else:
                    print(f"[UPDATE] Could not delete chunks for: {doc.original_name}")

            # faiss_ids null karo, status PENDING karo
            doc.faiss_ids = None
            doc.process   = ProcessStatus.PENDING
            print(f"[UPDATE] Reset to PENDING: {doc.original_name}")

        db.commit()
        print("[UPDATE] All UPDATE documents reset to PENDING successfully.")

    except Exception as e:
        print(f"[UPDATE] Error: {e}")
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
    scheduler.add_job(
        handle_update_documents,
        trigger=IntervalTrigger(minutes=10),
        id="handle_update_documents",
        replace_existing=True,
    )

    scheduler.start()
    print("[SCHEDULER] Background scheduler started — runs every 5 minutes.")
    return scheduler


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown()
        print("[SCHEDULER] Scheduler stopped.")