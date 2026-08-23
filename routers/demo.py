import os, logging
from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel
from typing import Annotated
from sqlalchemy.orm import Session
from models.shop_owner import ShopOwner
from utils.auth import get_current_user
from utils.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/demo", tags=["Demo Data"])
db_dependency = Annotated[Session, Depends(get_db)]

DEMO_PERSIST_DIR = os.path.join("faiss_store", "demo")


class EnableDemoRequest(BaseModel):
    dataset: str


def _get_available_datasets() -> list[str]:
    """faiss_store/demo/<folder_name>/ me se sirf wo folders jinka faiss.index ban chuka hai."""
    if not os.path.isdir(DEMO_PERSIST_DIR):
        return []

    return sorted(
        f for f in os.listdir(DEMO_PERSIST_DIR)
        if os.path.isfile(os.path.join(DEMO_PERSIST_DIR, f, "faiss.index"))
    )


@router.get("/datasets")
async def list_demo_datasets(current_user: ShopOwner = Depends(get_current_user)):
    """
    Available demo datasets ki list do (e.g. kirana_store, medical_store).
    """
    return {"datasets": _get_available_datasets()}


@router.get("/status")
async def get_demo_status(current_user: ShopOwner = Depends(get_current_user)):
    """
    Current user ka demo mode state.
    """
    return {
        "demo_mode_enabled": current_user.demo_mode_enabled,
        "demo_dataset": current_user.demo_dataset,
    }


@router.post("/enable", status_code=status.HTTP_200_OK)
async def enable_demo_mode(
    payload: EnableDemoRequest,
    db: db_dependency,
    current_user: ShopOwner = Depends(get_current_user),
):
    """
    Current user ke liye demo/dummy data enable karo — sirf usi user ko affect karta hai.
    """
    available = _get_available_datasets()
    if payload.dataset not in available:
        logger.warning(f"Demo enable rejected — invalid dataset '{payload.dataset}': user_id={current_user.id}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid dataset. Available datasets: {available}"
        )

    current_user.demo_mode_enabled = True
    current_user.demo_dataset = payload.dataset
    db.commit()

    logger.info(f"Demo mode enabled — user_id={current_user.id} dataset={payload.dataset}")

    return {
        "message": "Demo mode enabled",
        "demo_mode_enabled": current_user.demo_mode_enabled,
        "demo_dataset": current_user.demo_dataset,
    }


@router.post("/disable", status_code=status.HTTP_200_OK)
async def disable_demo_mode(
    db: db_dependency,
    current_user: ShopOwner = Depends(get_current_user),
):
    """
    Current user ke liye demo/dummy data disable karo.
    """
    current_user.demo_mode_enabled = False
    current_user.demo_dataset = None
    db.commit()

    logger.info(f"Demo mode disabled — user_id={current_user.id}")

    return {
        "message": "Demo mode disabled",
        "demo_mode_enabled": current_user.demo_mode_enabled,
        "demo_dataset": current_user.demo_dataset,
    }
