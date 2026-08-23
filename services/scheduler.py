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
            logger.info("[SCHEDULER] No pending documents found.")
            return

        logger.info(f"[SCHEDULER] Found {len(pending_docs)} pending documents.")

        from collections import defaultdict
        user_docs_map = defaultdict(list)
        for doc in pending_docs:
            user_docs_map[doc.user_id].append(doc)

        for user_id, user_pending_docs in user_docs_map.items():
            store = FaissVectorStore("faiss_store", embedding_model="openai")

            # Har document alag alag process karo
            for d in user_pending_docs:
                logger.info(f"[SCHEDULER] Processing: {d.original_name} (document_id={d.id} user_id={user_id})")

                user_documents = load_all_documents([d.file_path])
                if not user_documents:
                    logger.warning(f"[SCHEDULER] No content loaded from: {d.original_name} (document_id={d.id})")
                    continue

                chunk_ids = store.build_from_documents(user_documents, user_id=user_id)

                d.process = ProcessStatus.DONE
                d.faiss_ids = json.dumps(chunk_ids)
                logger.info(f"[SCHEDULER] Done: {d.original_name} — {len(chunk_ids)} chunks (document_id={d.id})")

        db.commit()
        logger.info("[SCHEDULER] All pending documents processed successfully.")

    except Exception:
        logger.exception("[SCHEDULER] Error processing pending documents")
        db.rollback()
    finally:
        db.close()


def process_demo_documents():
    """
    media/demo/<folder_name>/*.pdf ko folder-wise process karke
    faiss_store/demo/<folder_name>/ me vector store banao.

    Har subfolder ek "demo shop" hai (e.g. kirana_store, medical_store).
    Already-indexed folders (jinka faiss.index already ban chuka hai) skip ho jaate hain,
    to bar-bar chalne pe duplicate chunks nahi bante.
    """
    demo_dir = os.path.join("media", "demo")
    demo_persist_dir = os.path.join("faiss_store", "demo")

    if not os.path.isdir(demo_dir):
        logger.info(f"[DEMO] No demo directory found at {demo_dir}")
        return

    # faiss_store/demo folder create karo agar exist nahi karta
    os.makedirs(demo_persist_dir, exist_ok=True)

    folder_names = sorted(
        f for f in os.listdir(demo_dir)
        if os.path.isdir(os.path.join(demo_dir, f))
    )

    if not folder_names:
        logger.info(f"[DEMO] No folders found in {demo_dir}")
        return

    logger.info(f"[DEMO] Found {len(folder_names)} demo folders.")

    store = FaissVectorStore(demo_persist_dir, embedding_model="openai")

    for folder_name in folder_names:
        folder_path = os.path.join(demo_dir, folder_name)
        index_path = os.path.join(demo_persist_dir, folder_name, "faiss.index")

        if os.path.exists(index_path):
            logger.info(f"[DEMO] Already indexed, skipping: {folder_name}")
            continue

        pdf_paths = [
            os.path.join(folder_path, f)
            for f in sorted(os.listdir(folder_path))
            if f.lower().endswith(".pdf")
        ]

        if not pdf_paths:
            logger.warning(f"[DEMO] No PDF files found in: {folder_name}")
            continue

        logger.info(f"[DEMO] Processing folder: {folder_name} — {len(pdf_paths)} PDF(s)")

        documents = load_all_documents(pdf_paths)
        if not documents:
            logger.warning(f"[DEMO] No content loaded from folder: {folder_name}")
            continue

        # folder_name hi "user_id" ki jagah use hota hai —
        # isliye vector store faiss_store/demo/<folder_name>/ me banta hai
        chunk_ids = store.build_from_documents(documents, user_id=folder_name)
        logger.info(f"[DEMO] Done: {folder_name} — {len(chunk_ids)} chunks")

    logger.info("[DEMO] All demo folders processed.")


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
            logger.info("[VERIFY] No pending documents found.")
            return

        logger.info(f"[VERIFY] Found {len(pending_docs)} pending documents.")

        for doc in pending_docs:
            logger.info(f"[VERIFY] Verifying: {doc.original_name} (document_id={doc.id})")

            is_valid, reason = is_business_document(doc.file_path)

            if is_valid:
                doc.process = ProcessStatus.PROCESS
                logger.info(f"[VERIFY] Accepted: {doc.original_name} — {reason} (document_id={doc.id})")
            else:
                doc.process = ProcessStatus.REJECTED
                logger.info(f"[VERIFY] Rejected: {doc.original_name} — {reason} (document_id={doc.id})")

        db.commit()
        logger.info("[VERIFY] Verification complete.")

    except Exception:
        logger.exception("[VERIFY] Error verifying pending documents")
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
            logger.info("[UPDATE] No documents with UPDATE status found.")
            return

        logger.info(f"[UPDATE] Found {len(update_docs)} documents to update.")

        for doc in update_docs:
            logger.info(f"[UPDATE] Processing: {doc.original_name} (document_id={doc.id})")

            # Purane chunks vector DB se delete karo
            if doc.faiss_ids:
                from utils.helper import delete_document_from_vector_db
                success = delete_document_from_vector_db(doc, user_id=doc.user_id)
                if success:
                    logger.info(f"[UPDATE] Old chunks deleted for: {doc.original_name} (document_id={doc.id})")
                else:
                    logger.warning(f"[UPDATE] Could not delete chunks for: {doc.original_name} (document_id={doc.id})")

            # faiss_ids null karo, status PENDING karo
            doc.faiss_ids = None
            doc.process   = ProcessStatus.PENDING
            logger.info(f"[UPDATE] Reset to PENDING: {doc.original_name} (document_id={doc.id})")

        db.commit()
        logger.info("[UPDATE] All UPDATE documents reset to PENDING successfully.")

    except Exception:
        logger.exception("[UPDATE] Error handling UPDATE documents")
        db.rollback()
    finally:
        db.close()


def generate_daily_pdf():
    """
    Din ke end me confirmed chat entries ki PDF banao.
    PDF ko documents table me add karo status=PENDING.
    Chat entries delete karo.
    Roz raat 11 baje chalega.
    """
    from models.chat_entry import ChatEntry, ChatStatus
    from models.document import Document, ProcessStatus
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from collections import defaultdict
    from datetime import datetime, timezone
    import json

    db = SessionLocal()
    try:
        confirmed_entries = db.query(ChatEntry).filter(
            ChatEntry.status == ChatStatus.CONFIRMED
        ).limit(50).all()

        if not confirmed_entries:
            logger.info("[DAILY PDF] No confirmed entries found.")
            return

        logger.info(f"[DAILY PDF] Found {len(confirmed_entries)} confirmed entries.")

        user_entries = defaultdict(list)
        for entry in confirmed_entries:
            user_entries[entry.user_id].append(entry)

        for user_id, entries in user_entries.items():
            today = datetime.now(timezone.utc)

            user_dir = f"media/uploads/{user_id}/chat_data/{today.year}/{str(today.month).zfill(2)}/{str(today.day).zfill(2)}"
            os.makedirs(user_dir, exist_ok=True)
            pdf_filename = f"daily_chat_{today.strftime('%Y%m%d_%H%M%S')}.pdf"
            pdf_path = f"{user_dir}/{pdf_filename}"

            story = []

            def P(t, s): return Paragraph(str(t), s)
            def sp(h=4): return Spacer(1, h * mm)

            title_s = ParagraphStyle("t", fontSize=14, textColor=colors.white,
                                     fontName="Helvetica-Bold", alignment=TA_CENTER)
            body_s  = ParagraphStyle("b", fontSize=9, textColor=colors.HexColor("#202124"),
                                     fontName="Helvetica", leading=14)
            header_s = ParagraphStyle("h", fontSize=8, textColor=colors.white,
                                      fontName="Helvetica-Bold", alignment=TA_CENTER)

            header = Table([[P(f"Daily Chat Data — {today.strftime('%d %B %Y')}", title_s)]],
                           colWidths=[170 * mm])
            header.setStyle(TableStyle([
                ("BACKGROUND",    (0, 0), (-1, -1), colors.HexColor("#1E3A5F")),
                ("TOPPADDING",    (0, 0), (-1, -1), 12),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
            ]))
            story.append(header)
            story.append(sp(6))

            # Table headers — Date column add kiya
            table_data = [[
                P("Product",    header_s),
                P("Date",       header_s),
                P("Qty",        header_s),
                P("Price/Unit", header_s),
                P("Total",      header_s),
                P("Type",       header_s),
                P("Notes",      header_s),
            ]]

            for entry in entries:
                try:
                    data = json.loads(entry.extracted)
                except:
                    data = {}

                table_data.append([
                    P(str(data.get("product", "N/A")), body_s),
                    P(str(data.get("date", str(entry.created_at.date()))), body_s),  # ← date
                    P(str(data.get("quantity", "N/A")), body_s),
                    P(f"Rs {data.get('price_per_unit', 'N/A')}", body_s),
                    P(f"Rs {data.get('total', 'N/A')}", body_s),
                    P(str(data.get("type", "N/A")), body_s),
                    P(str(data.get("notes", "")), body_s),
                ])

            data_table = Table(table_data,
                               colWidths=[32*mm, 22*mm, 12*mm, 22*mm, 22*mm, 22*mm, 38*mm])
            data_table.setStyle(TableStyle([
                ("BACKGROUND",    (0, 0), (-1, 0),  colors.HexColor("#1E3A5F")),
                ("GRID",          (0, 0), (-1, -1),  0.4, colors.HexColor("#DADCE0")),
                ("TOPPADDING",    (0, 0), (-1, -1),  4),
                ("BOTTOMPADDING", (0, 0), (-1, -1),  4),
                ("LEFTPADDING",   (0, 0), (-1, -1),  5),
                ("ROWBACKGROUNDS",(0, 1), (-1, -1),  [colors.white, colors.HexColor("#F4F6F8")]),
            ]))
            story.append(data_table)

            doc = SimpleDocTemplate(pdf_path, pagesize=A4,
                                    leftMargin=20*mm, rightMargin=20*mm,
                                    topMargin=20*mm, bottomMargin=20*mm)
            doc.build(story)
            logger.info(f"[DAILY PDF] PDF created: {pdf_path} (user_id={user_id})")

            # Documents table me add karo
            new_doc = Document(
                user_id=user_id,
                original_name=pdf_filename,
                stored_name=pdf_filename,
                file_path=pdf_path,
                file_type="pdf",
                mime_type="application/pdf",
                file_size=os.path.getsize(pdf_path),
                process=ProcessStatus.PENDING,
            )
            db.add(new_doc)

            # Chat entries delete karo
            for entry in entries:
                db.delete(entry)

        db.commit()
        logger.info("[DAILY PDF] Done — PDF added to documents, chat entries cleared.")

    except Exception:
        logger.exception("[DAILY PDF] Error generating daily PDF")
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
    scheduler.add_job(
        generate_daily_pdf,
        trigger=IntervalTrigger(hours=6),
        id="generate_daily_pdf",
        replace_existing=True,
    )
    scheduler.add_job(
        process_demo_documents,
        trigger=IntervalTrigger(minutes=30),
        id="process_demo_documents",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("[SCHEDULER] Background scheduler started — runs every 5 minutes.")
    return scheduler


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown()
        logger.info("[SCHEDULER] Scheduler stopped.")
