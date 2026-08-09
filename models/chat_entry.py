import enum
from datetime import datetime, timezone
from sqlalchemy import Integer, String, Text, DateTime, ForeignKey, Enum
from sqlalchemy.orm import Mapped, mapped_column
from models.shop_owner import Base


class ChatStatus(str, enum.Enum):
    PENDING       = "pending"
    CONFIRMED     = "confirmed"
    PDF_GENERATED = "pdf_generated"


class ChatEntry(Base):
    __tablename__ = "chat_entries"

    id          : Mapped[int]      = mapped_column(Integer, primary_key=True)
    user_id     : Mapped[int]      = mapped_column(ForeignKey("shop_owners.id"), nullable=False)
    raw_message : Mapped[str]      = mapped_column(Text, nullable=False)   # user ne kya bola
    extracted   : Mapped[str]      = mapped_column(Text, nullable=True)    # LLM ne kya nikala (JSON)
    status      : Mapped[str]      = mapped_column(
                                        Enum(ChatStatus),
                                        default=ChatStatus.PENDING,
                                        nullable=False
                                     )
    created_at  : Mapped[datetime] = mapped_column(
                                        DateTime,
                                        default=lambda: datetime.now(timezone.utc)
                                     )