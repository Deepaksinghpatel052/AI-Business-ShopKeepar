import logging
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from models.shop_owner import ShopOwner, UserType
from models.membership import MembershipPlan, Membership, MembershipStatus
from utils.auth import get_current_user
from utils.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/membership", tags=["Membership"])
db_dependency = Annotated[Session, Depends(get_db)]


def _utcnow() -> datetime:
    # SQLite drops tzinfo on round-trip — keep every membership timestamp naive UTC for consistent comparisons.
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _require_admin(current_user: ShopOwner) -> None:
    if current_user.user_type != UserType.ADMIN:
        logger.warning(f"Admin-only membership action blocked — user_id={current_user.id} user_type={current_user.user_type}")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")


# ── Schemas ────────────────────────────────────────────────────────────────────

class PlanResponse(BaseModel):
    id: int
    name: str
    display_name: str
    description: str | None
    price: float
    duration_days: int | None
    max_documents: int | None
    max_queries_per_day: int | None
    is_active: bool
    model_config = {"from_attributes": True}


class PlanCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=50)
    display_name: str = Field(min_length=2, max_length=100)
    description: str | None = None
    price: float = Field(ge=0)
    duration_days: int | None = Field(default=None, ge=1)
    max_documents: int | None = Field(default=None, ge=0)
    max_queries_per_day: int | None = Field(default=None, ge=0)


class PlanUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=2, max_length=100)
    description: str | None = None
    price: float | None = Field(default=None, ge=0)
    duration_days: int | None = Field(default=None, ge=1)
    max_documents: int | None = Field(default=None, ge=0)
    max_queries_per_day: int | None = Field(default=None, ge=0)
    is_active: bool | None = None


class SubscribeRequest(BaseModel):
    plan_name: str


class MembershipResponse(BaseModel):
    id: int
    status: MembershipStatus
    started_at: datetime
    expires_at: datetime | None
    cancelled_at: datetime | None
    plan: PlanResponse
    model_config = {"from_attributes": True}


# ── Plan catalog ───────────────────────────────────────────────────────────────

@router.get("/plans", response_model=list[PlanResponse])
async def list_plans(db: db_dependency):
    """Sabhi active membership plans list karo — public endpoint, auth ki zaroorat nahi (pricing page ke liye)."""
    plans = db.query(MembershipPlan).filter(
        MembershipPlan.is_active == True
    ).order_by(MembershipPlan.price).all()
    return plans


@router.post("/plans", response_model=PlanResponse, status_code=status.HTTP_201_CREATED)
async def create_plan(
    payload: PlanCreateRequest,
    db: db_dependency,
    current_user: ShopOwner = Depends(get_current_user),
):
    """Naya membership plan banao — admin only."""
    _require_admin(current_user)

    if db.query(MembershipPlan).filter(MembershipPlan.name == payload.name).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A plan with this name already exists"
        )

    plan = MembershipPlan(**payload.model_dump())
    db.add(plan)
    db.commit()
    db.refresh(plan)

    logger.info(f"Membership plan created — plan_id={plan.id} name={plan.name} by user_id={current_user.id}")

    return plan


@router.put("/plans/{plan_id}", response_model=PlanResponse)
async def update_plan(
    plan_id: int,
    payload: PlanUpdateRequest,
    db: db_dependency,
    current_user: ShopOwner = Depends(get_current_user),
):
    """Existing membership plan update karo — admin only."""
    _require_admin(current_user)

    plan = db.query(MembershipPlan).filter(MembershipPlan.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plan not found")

    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(plan, field, value)

    db.commit()
    db.refresh(plan)

    logger.info(f"Membership plan updated — plan_id={plan.id} by user_id={current_user.id}")

    return plan


@router.delete("/plans/{plan_id}", status_code=status.HTTP_200_OK)
async def delete_plan(
    plan_id: int,
    db: db_dependency,
    current_user: ShopOwner = Depends(get_current_user),
):
    """Membership plan delete karo — admin only."""
    _require_admin(current_user)

    plan = db.query(MembershipPlan).filter(MembershipPlan.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plan not found")

    if db.query(Membership).filter(Membership.plan_id == plan_id).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete a plan that has existing memberships. Mark it inactive instead."
        )

    db.delete(plan)
    db.commit()

    logger.info(f"Membership plan deleted — plan_id={plan_id} by user_id={current_user.id}")

    return {"message": "Plan deleted successfully"}


# ── Current user's membership ───────────────────────────────────────────────────

@router.get("/my", response_model=MembershipResponse | None)
async def get_my_membership(db: db_dependency, current_user: ShopOwner = Depends(get_current_user)):
    """Current user ki active membership do — koi active membership nahi to null."""
    membership = db.query(Membership).filter(
        Membership.user_id == current_user.id,
        Membership.status == MembershipStatus.ACTIVE,
    ).order_by(Membership.started_at.desc()).first()

    return membership


@router.get("/history", response_model=list[MembershipResponse])
async def get_membership_history(db: db_dependency, current_user: ShopOwner = Depends(get_current_user)):
    """Current user ki saari membership history do (active + cancelled + expired), naye se purane."""
    memberships = db.query(Membership).filter(
        Membership.user_id == current_user.id
    ).order_by(Membership.started_at.desc()).all()

    return memberships


@router.post("/subscribe", response_model=MembershipResponse, status_code=status.HTTP_201_CREATED)
async def subscribe(
    payload: SubscribeRequest,
    db: db_dependency,
    current_user: ShopOwner = Depends(get_current_user),
):
    """
    Current user ko diye gaye plan me subscribe karo.
    Purani active membership (agar hai) automatically cancel ho jaati hai.
    """
    plan = db.query(MembershipPlan).filter(
        MembershipPlan.name == payload.plan_name,
        MembershipPlan.is_active == True,
    ).first()
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Plan not found or not available"
        )

    now = _utcnow()

    # Purani active membership cancel karo — ek time pe sirf ek active membership honi chahiye
    existing = db.query(Membership).filter(
        Membership.user_id == current_user.id,
        Membership.status == MembershipStatus.ACTIVE,
    ).first()
    if existing:
        existing.status = MembershipStatus.CANCELLED
        existing.cancelled_at = now

    expires_at = now + timedelta(days=plan.duration_days) if plan.duration_days else None

    membership = Membership(
        user_id=current_user.id,
        plan_id=plan.id,
        status=MembershipStatus.ACTIVE,
        started_at=now,
        expires_at=expires_at,
    )
    db.add(membership)
    db.commit()
    db.refresh(membership)

    logger.info(f"User subscribed to plan — user_id={current_user.id} plan={plan.name} membership_id={membership.id}")

    return membership


@router.post("/cancel", response_model=MembershipResponse)
async def cancel_membership(db: db_dependency, current_user: ShopOwner = Depends(get_current_user)):
    """Current active membership cancel karo."""
    membership = db.query(Membership).filter(
        Membership.user_id == current_user.id,
        Membership.status == MembershipStatus.ACTIVE,
    ).first()
    if not membership:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active membership found")

    membership.status = MembershipStatus.CANCELLED
    membership.cancelled_at = _utcnow()
    db.commit()
    db.refresh(membership)

    logger.info(f"Membership cancelled — user_id={current_user.id} membership_id={membership.id}")

    return membership
