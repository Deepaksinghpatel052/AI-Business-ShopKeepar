from fastapi import APIRouter, status, Depends, UploadFile, File, HTTPException
from utils.database import get_db
from utils.auth import get_current_user
from models.shop_owner import ShopOwner
from typing import Annotated
from sqlalchemy.orm import Session
import os
from dotenv import load_dotenv
from models.document import Document
import uuid
from datetime import datetime, timezone

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
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File type not allowed. Allowed: pdf, doc, docx, csv, xls, xlsx, png, jpeg"
        )

    # File content pado
    file_bytes = await file.read()

    # File size check
    if len(file_bytes) > MAX_FILE_SIZE:
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
            }
            for doc in documents
        ]
    }

