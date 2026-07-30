from datetime import datetime, timezone
from sqlalchemy import Integer, String, DateTime, ForeignKey, BigInteger
from sqlalchemy.orm import Mapped, mapped_column, relationship
from models.shop_owner import Base

class Document(Base):
    __tablename__ = "documents"

    id           : Mapped[int]      = mapped_column(Integer, primary_key=True)
    user_id      : Mapped[int]      = mapped_column(Integer, ForeignKey("shop_owners.id"), nullable=False)
    
    original_name: Mapped[str]      = mapped_column(String(255), nullable=False)  # user ka original file naam
    stored_name  : Mapped[str]      = mapped_column(String(255), nullable=False)  # disk pe save naam (unique)
    file_path    : Mapped[str]      = mapped_column(String(512), nullable=False)  # full path
    file_type    : Mapped[str]      = mapped_column(String(50),  nullable=False)  # pdf, docx, csv, etc
    mime_type    : Mapped[str]      = mapped_column(String(100), nullable=False)  # application/pdf etc
    file_size    : Mapped[int]      = mapped_column(BigInteger,  nullable=False)  # bytes me
    
    uploaded_at  : Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))