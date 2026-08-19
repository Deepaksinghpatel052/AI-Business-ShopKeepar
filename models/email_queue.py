import enum
from datetime import datetime, timezone
from sqlalchemy import Integer, String, Text, DateTime, ForeignKey, Enum
from sqlalchemy.orm import Mapped, mapped_column
from models.shop_owner import Base


class EmailStatus(str, enum.Enum):
    PENDING = "pending"
    SENT    = "sent"
    FAILED  = "failed"


class EmailQueue(Base):
    __tablename__ = "email_queue"

    id          : Mapped[int]            = mapped_column(Integer, primary_key=True)
    user_id     : Mapped[int]            = mapped_column(ForeignKey("shop_owners.id"), nullable=False)
    to_email    : Mapped[str]            = mapped_column(String(255), nullable=False)
    subject     : Mapped[str]            = mapped_column(String(255), nullable=False)
    report_type : Mapped[str]            = mapped_column(String(50), nullable=False)   # weekly/monthly
    pdf_path    : Mapped[str]            = mapped_column(Text, nullable=False)
    status      : Mapped[EmailStatus]    = mapped_column(Enum(EmailStatus), default=EmailStatus.PENDING)
    created_at  : Mapped[datetime]       = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    sent_at     : Mapped[datetime | None]= mapped_column(DateTime, nullable=True)
    error       : Mapped[str | None]     = mapped_column(Text, nullable=True)   # agar fail ho to reason