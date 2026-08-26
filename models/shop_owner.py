import enum
from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, Enum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass


class UserType(str, enum.Enum):
    ADMIN  = "admin"
    MEMBER = "member"


class ShopOwner(Base):
    __tablename__ = "shop_owners"

    id               : Mapped[int]         = mapped_column(Integer, primary_key=True)
    name             : Mapped[str]         = mapped_column(String(120), nullable=False)
    email            : Mapped[str]         = mapped_column(String(255), unique=True, index=True, nullable=False)
    username         : Mapped[str | None]  = mapped_column(String(80), unique=True, nullable=True)
    password_hash    : Mapped[str | None]  = mapped_column(String(255), nullable=True)
    phone            : Mapped[str | None]  = mapped_column(String(20), nullable=True)
    shop_name        : Mapped[str | None]  = mapped_column(String(255), nullable=True)
    plan             : Mapped[str]         = mapped_column(Enum('free', 'premium'), default='free')
    is_active        : Mapped[bool]        = mapped_column(Boolean, default=True)
    is_admin         : Mapped[bool]        = mapped_column(Boolean, default=False)
    user_type        : Mapped[UserType]    = mapped_column(Enum(UserType), default=UserType.MEMBER, nullable=False)
    auth_provider    : Mapped[str]         = mapped_column(Enum('local', 'google', 'facebook'), default='local')
    auth_provider_id : Mapped[str | None]  = mapped_column(String(255), nullable=True)
    created_at       : Mapped[datetime]    = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_login_at    : Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # ── Forgot password ──────────────────────────────────────────────────────
    reset_code_hash        : Mapped[str | None]      = mapped_column(String(255), nullable=True)
    reset_code_expires_at  : Mapped[datetime | None]  = mapped_column(DateTime, nullable=True)
    reset_code_attempts    : Mapped[int]              = mapped_column(Integer, default=0, nullable=False)
    reset_code_last_sent_at: Mapped[datetime | None]  = mapped_column(DateTime, nullable=True)

    # ── Demo / dummy data mode ────────────────────────────────────────────────
    demo_mode_enabled: Mapped[bool]        = mapped_column(Boolean, default=False, nullable=False)
    demo_dataset     : Mapped[str | None]  = mapped_column(String(100), nullable=True)