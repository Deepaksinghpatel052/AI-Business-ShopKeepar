from datetime import datetime, timezone
import enum
from sqlalchemy import Integer, String, Float, Boolean, DateTime, ForeignKey, Enum, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from models.shop_owner import Base


class MembershipStatus(str, enum.Enum):
    ACTIVE    = "active"
    EXPIRED   = "expired"
    CANCELLED = "cancelled"


class MembershipPlan(Base):
    __tablename__ = "membership_plans"

    id                  : Mapped[int]        = mapped_column(Integer, primary_key=True)
    name                : Mapped[str]        = mapped_column(String(50), unique=True, nullable=False)   # slug, e.g. "free", "premium"
    display_name        : Mapped[str]        = mapped_column(String(100), nullable=False)
    description         : Mapped[str | None] = mapped_column(Text, nullable=True)
    price               : Mapped[float]      = mapped_column(Float, default=0.0, nullable=False)
    duration_days       : Mapped[int | None] = mapped_column(Integer, nullable=True)   # None = never expires (e.g. free plan)
    max_documents       : Mapped[int | None] = mapped_column(Integer, nullable=True)   # None = unlimited
    max_queries_per_day : Mapped[int | None] = mapped_column(Integer, nullable=True)   # None = unlimited
    is_active           : Mapped[bool]       = mapped_column(Boolean, default=True, nullable=False)
    created_at          : Mapped[datetime]   = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class Membership(Base):
    __tablename__ = "memberships"

    id           : Mapped[int]             = mapped_column(Integer, primary_key=True)
    user_id      : Mapped[int]             = mapped_column(Integer, ForeignKey("shop_owners.id"), nullable=False)
    plan_id      : Mapped[int]             = mapped_column(Integer, ForeignKey("membership_plans.id"), nullable=False)
    status       : Mapped[MembershipStatus] = mapped_column(Enum(MembershipStatus), default=MembershipStatus.ACTIVE, nullable=False)
    started_at   : Mapped[datetime]        = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    expires_at   : Mapped[datetime | None] = mapped_column(DateTime, nullable=True)   # None = never expires
    cancelled_at : Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    plan: Mapped["MembershipPlan"] = relationship("MembershipPlan")
