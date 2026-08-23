from fastapi import APIRouter, status, Depends, UploadFile, File, HTTPException
from utils.database import get_db
from utils.auth import get_current_user
from models.shop_owner import ShopOwner
from typing import Annotated
from sqlalchemy.orm import Session
import os, logging
from dotenv import load_dotenv
from models.document import Document, ProcessStatus
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

load_dotenv()

router = APIRouter(prefix="/document", tags=["Document"])
db_dependency = Annotated[Session, Depends(get_db)]

UPLOAD_DIR = os.getenv("UPLOAD_DIR", "./uploaded_files")
os.makedirs(UPLOAD_DIR, exist_ok=True)

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB

ALLOWED_MIME_TYPES = {
    "application/pdf": "pdf"
}


@router.post("/upload-file", status_code=status.HTTP_201_CREATED)
async def file_upload(
    db: db_dependency, 
    current_user: ShopOwner = Depends(get_current_user),
    file: UploadFile = File(...)):
    """
    File upload endpoint.
    Ye endpoint authenticated users ke liye hai.
    """

    # File type check
    if file.content_type not in ALLOWED_MIME_TYPES:
        logger.warning(f"Upload rejected — disallowed content type '{file.content_type}': user_id={current_user.id}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File type not allowed. Allowed: pdf, doc, docx, csv, xls, xlsx, png, jpeg"
        )

    # File content pado
    file_bytes = await file.read()

    # File size check
    if len(file_bytes) > MAX_FILE_SIZE:
        logger.warning(f"Upload rejected — file too large ({len(file_bytes)} bytes): user_id={current_user.id}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File size exceeds 10 MB limit"
        )

    # Unique naam generate karo
    file_ext = ALLOWED_MIME_TYPES[file.content_type]
    stored_name = f"{uuid.uuid4().hex}.{file_ext}"

    # User ka alag folder
    now = datetime.now(timezone.utc)
    shop_name = current_user.shop_name or "default"
    shop_name_clean = "".join(c if c.isalnum() else "_" for c in shop_name).lower()
    user_folder = f"{UPLOAD_DIR}/{current_user.id}/{shop_name_clean}/{now.year}/{str(now.month).zfill(2)}/{str(now.day).zfill(2)}"
    os.makedirs(user_folder, exist_ok=True)

    # File disk pe save karo
    with open(f"{user_folder}/{stored_name}", "wb") as f:
        f.write(file_bytes)

    file_path_clean = f"{user_folder}/{stored_name}"

    # DB me record save karo
    document = Document(
        user_id=current_user.id,
        original_name=file.filename,
        stored_name=stored_name,
        file_path=file_path_clean,
        file_type=file_ext,
        mime_type=file.content_type,
        file_size=len(file_bytes),
    )
    db.add(document)
    db.commit()
    db.refresh(document)

    logger.info(
        f"Document uploaded — document_id={document.id} user_id={current_user.id} "
        f"name={document.original_name} size={document.file_size}"
    )

    return {
        "id": document.id,
        "original_name": document.original_name,
        "file_type": document.file_type,
        "file_size": document.file_size,
        "uploaded_at": document.uploaded_at,
        "message": "File uploaded successfully"
    }


@router.get("/my-files")
async def get_my_files(
    db: db_dependency,
    current_user: ShopOwner = Depends(get_current_user),
):
    """
    Current user ki saari uploaded files return karo.
    """
    documents = db.query(Document).filter(
        Document.user_id == current_user.id
    ).order_by(Document.uploaded_at.desc()).all()

    return {
        "total": len(documents),
        "files": [
            {
                "id": doc.id,
                "original_name": doc.original_name,
                "file_path": doc.file_path,
                "file_type": doc.file_type,
                "file_size_kb": round(doc.file_size / 1024, 2),
                "uploaded_at": doc.uploaded_at,
                "process_status": doc.process.value,
                "faiss_ids": doc.faiss_ids
            }
            for doc in documents
        ]
    }


@router.put("/edit/{document_id}", status_code=status.HTTP_200_OK)
async def edit_document(
    document_id: int,
    db: db_dependency,
    current_user: ShopOwner = Depends(get_current_user),
    file: UploadFile = File(...),
):
    """
    Document edit endpoint.
    Naya file upload karo — purana vector DB se delete hoga, naya process hoga.
    """
    # Document dhundo
    doc = db.query(Document).filter(
        Document.id == document_id,
        Document.user_id == current_user.id
    ).first()

    if not doc:
        logger.warning(f"Edit rejected — document not found or not owned: document_id={document_id} user_id={current_user.id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )

    # File type check
    if file.content_type not in ALLOWED_MIME_TYPES:
        logger.warning(f"Edit rejected — disallowed content type '{file.content_type}': document_id={document_id}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File type not allowed"
        )

    file_bytes = await file.read()

    # File size check
    if len(file_bytes) > MAX_FILE_SIZE:
        logger.warning(f"Edit rejected — file too large ({len(file_bytes)} bytes): document_id={document_id}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File size exceeds 10 MB limit"
        )

    # Purani file delete karo disk se
    if doc.file_path and os.path.exists(doc.file_path):
        os.remove(doc.file_path)

    # Naya file save karo
    file_ext = ALLOWED_MIME_TYPES[file.content_type]
    stored_name = f"{uuid.uuid4().hex}.{file_ext}"
    now = datetime.now(timezone.utc)
    shop_name_clean = "".join(
        c if c.isalnum() else "_"
        for c in (current_user.shop_name or "default")
    ).lower()

    user_folder = f"{UPLOAD_DIR}/{current_user.id}/{shop_name_clean}/{now.year}/{str(now.month).zfill(2)}/{str(now.day).zfill(2)}"
    os.makedirs(user_folder, exist_ok=True)

    file_path = f"{user_folder}/{stored_name}"
    with open(file_path, "wb") as f:
        f.write(file_bytes)

    # Document table update karo
    doc.original_name  = file.filename
    doc.stored_name    = stored_name
    doc.file_path      = file_path
    doc.file_type      = file_ext
    doc.mime_type      = file.content_type
    doc.file_size      = len(file_bytes)
    doc.process        = ProcessStatus.UPDATE   # ← UPDATE status
    doc.uploaded_at    = now

    db.commit()
    db.refresh(doc)

    logger.info(f"Document edited — document_id={doc.id} user_id={current_user.id} name={doc.original_name}")

    return {
        "message": "Document updated successfully. Processing will start shortly.",
        "document_id": doc.id,
        "original_name": doc.original_name,
        "process_status": doc.process,
    }
