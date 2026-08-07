import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
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
    db = SessionLocal()
    try:
        pending_docs = db.query(Document).filter(
            Document.process == ProcessStatus.PROCESS
        ).limit(2).all()

        if not pending_docs:
            print("[SCHEDULER] No pending documents found.")
            return

        print(f"[SCHEDULER] Found {len(pending_docs)} pending documents.")

        # User ke hisaab se group karo
        from collections import defaultdict
        user_docs_map = defaultdict(list)
        for doc in pending_docs:
            user_docs_map[doc.user_id].append(doc)

        for user_id, user_pending_docs in user_docs_map.items():
            user_file_paths = [d.file_path for d in user_pending_docs]
            print(f"[SCHEDULER] Processing {len(user_file_paths)} files for user {user_id}")

            user_documents = load_all_documents(user_file_paths)
            if not user_documents:
                continue

            store = FaissVectorStore("faiss_store", embedding_model="openai")
            store.build_from_documents(user_documents, user_id=user_id)

            for d in user_pending_docs:
                d.process = ProcessStatus.DONE
                print(f"[SCHEDULER] Processed: {d.original_name}")

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
        ).limit(2).all()

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