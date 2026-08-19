import enum
from datetime import datetime, timezone, date
from sqlalchemy import Integer, String, Float, Date, DateTime, ForeignKey, Enum, Text
from sqlalchemy.orm import Mapped, mapped_column
from models.shop_owner import Base


class TransactionType(str, enum.Enum):
    SALE     = "sale"
    PURCHASE = "purchase"
    EXPENSE  = "expense"
    STOCK    = "stock"


class TransactionSource(str, enum.Enum):
    CHAT = "chat"
    PDF  = "pdf"


class Transaction(Base):
    __tablename__ = "transactions"

    id          : Mapped[int]        = mapped_column(Integer, primary_key=True)
    user_id     : Mapped[int]        = mapped_column(ForeignKey("shop_owners.id"), nullable=False)
    document_id : Mapped[int|None]   = mapped_column(ForeignKey("documents.id"), nullable=True)
    date        : Mapped[date]       = mapped_column(Date, nullable=False)
    product     : Mapped[str]        = mapped_column(String(255), nullable=False)
    type        : Mapped[TransactionType]   = mapped_column(Enum(TransactionType), nullable=False)
    quantity    : Mapped[float|None] = mapped_column(Float, nullable=True)
    unit        : Mapped[str|None]   = mapped_column(String(50), nullable=True)
    rate        : Mapped[float|None] = mapped_column(Float, nullable=True)
    total       : Mapped[float]      = mapped_column(Float, nullable=False)
    notes       : Mapped[str|None]   = mapped_column(Text, nullable=True)
    source      : Mapped[TransactionSource] = mapped_column(Enum(TransactionSource), default=TransactionSource.CHAT, nullable=False)
    created_at  : Mapped[datetime]   = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))