from fastapi import APIRouter, status, Depends, UploadFile, File, HTTPException
from utils.database import get_db
from utils.auth import get_current_user
from models.shop_owner import ShopOwner
from typing import Annotated
from sqlalchemy.orm import Session
import logging
from dotenv import load_dotenv
from models.document import Document, ProcessStatus
import uuid
from datetime import datetime, timezone
import services.s3_storage as s3_storage

logger = logging.getLogger(__name__)

load_dotenv()

router = APIRouter(prefix="/document", tags=["Document"])
db_dependency = Annotated[Session, Depends(get_db)]

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

    # User ka alag S3 key prefix
    now = datetime.now(timezone.utc)
    shop_name = current_user.shop_name or "default"
    shop_name_clean = "".join(c if c.isalnum() else "_" for c in shop_name).lower()
    object_key = f"{current_user.id}/{shop_name_clean}/{now.year}/{str(now.month).zfill(2)}/{str(now.day).zfill(2)}/{stored_name}"

    # S3 pe (private bucket) save karo
    try:
        s3_storage.upload_bytes(object_key, file_bytes, file.content_type)
    except RuntimeError:
        logger.exception(f"Upload failed — could not store file in S3: user_id={current_user.id}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to store document"
        )

    # DB me record save karo
    document = Document(
        user_id=current_user.id,
        original_name=file.filename,
        stored_name=stored_name,
        file_path=object_key,
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
                "stored_name": doc.stored_name,
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


@router.get("/{document_id}/download-url")
async def get_document_download_url(
    document_id: int,
    db: db_dependency,
    current_user: ShopOwner = Depends(get_current_user),
):
    """
    Ek specific document ke liye short-lived presigned S3 download URL do.
    Bucket private hai — file access karne ka yahi ek tarika hai.
    """
    doc = db.query(Document).filter(
        Document.id == document_id,
        Document.user_id == current_user.id
    ).first()

    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )

    try:
        url = s3_storage.generate_presigned_download_url(doc.file_path)
    except RuntimeError:
        logger.exception(f"Presign failed — document_id={document_id} user_id={current_user.id}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate download URL"
        )

    return {
        "document_id": doc.id,
        "original_name": doc.original_name,
        "download_url": url,
        "expires_in": s3_storage.S3_PRESIGNED_URL_EXPIRE_SECONDS,
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

    # Purani file S3 se delete karo (best-effort — orphaned object is low-cost,
    # edit should still succeed even if this cleanup fails)
    try:
        s3_storage.delete_object(doc.file_path)
    except RuntimeError:
        logger.warning(f"Old file delete failed, continuing with edit — document_id={document_id}")

    # Naya file save karo — fresh key, purani key kabhi reuse nahi karte
    file_ext = ALLOWED_MIME_TYPES[file.content_type]
    stored_name = f"{uuid.uuid4().hex}.{file_ext}"
    now = datetime.now(timezone.utc)
    shop_name_clean = "".join(
        c if c.isalnum() else "_"
        for c in (current_user.shop_name or "default")
    ).lower()

    object_key = f"{current_user.id}/{shop_name_clean}/{now.year}/{str(now.month).zfill(2)}/{str(now.day).zfill(2)}/{stored_name}"

    try:
        s3_storage.upload_bytes(object_key, file_bytes, file.content_type)
    except RuntimeError:
        logger.exception(f"Edit failed — could not store file in S3: document_id={document_id}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to store document"
        )

    # Document table update karo
    doc.original_name  = file.filename
    doc.stored_name    = stored_name
    doc.file_path      = object_key
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
