from datetime import datetime, timezone
from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from models.shop_owner import Base


class LLMSetting(Base):
    """
    App-wide active chat LLM — sirf ek row (id=1) rehti hai. Row nahi hai to
    services.llm_manager ka default (local Ollama) use hota hai.
    """
    __tablename__ = "llm_settings"

    id         : Mapped[int]         = mapped_column(Integer, primary_key=True)
    provider   : Mapped[str]         = mapped_column(String(50), nullable=False)   # "ollama" / "openai"
    model      : Mapped[str]         = mapped_column(String(100), nullable=False)  # e.g. "phi3:mini"
    updated_by : Mapped[int | None]  = mapped_column(ForeignKey("shop_owners.id"), nullable=True)
    updated_at : Mapped[datetime]    = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
