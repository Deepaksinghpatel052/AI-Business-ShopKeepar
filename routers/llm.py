import logging

from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel, Field

from models.shop_owner import ShopOwner, UserType
from utils.auth import get_current_user
import services.llm_manager as llm_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/llm", tags=["LLM"])


# ── Schemas ────────────────────────────────────────────────────────────────────

class ActiveLLMResponse(BaseModel):
    provider: str
    model: str


class ProviderInfo(BaseModel):
    provider: str
    type: str
    available: bool
    default_model: str
    models: list[str]


class ProvidersResponse(BaseModel):
    active: ActiveLLMResponse
    providers: list[ProviderInfo]


class SetActiveLLMRequest(BaseModel):
    provider: str = Field(min_length=2, max_length=50, examples=["ollama"])
    model: str | None = Field(default=None, max_length=100, examples=["phi3:mini"])


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/providers", response_model=ProvidersResponse)
async def get_providers(current_user: ShopOwner = Depends(get_current_user)):
    """Supported LLM providers, unke models, availability aur currently active LLM."""
    active = llm_manager.get_active_llm()
    return ProvidersResponse(
        active=ActiveLLMResponse(provider=active.provider, model=active.model),
        providers=[ProviderInfo(**p) for p in llm_manager.list_providers()],
    )


@router.get("/active", response_model=ActiveLLMResponse)
async def get_active(current_user: ShopOwner = Depends(get_current_user)):
    """Abhi kaunsa LLM use ho raha hai."""
    active = llm_manager.get_active_llm()
    return ActiveLLMResponse(provider=active.provider, model=active.model)


@router.put("/active", response_model=ActiveLLMResponse)
async def set_active(
    payload: SetActiveLLMRequest,
    current_user: ShopOwner = Depends(get_current_user),
):
    """
    Active LLM badlo (admin only — ye setting poore app ke liye hai).
    - provider: "ollama" (local, default) ya "openai"
    - model: optional — na do to provider ka default model (e.g. phi3:mini / gpt-4o-mini)
    """
    if current_user.user_type != UserType.ADMIN:
        logger.warning(f"Non-admin tried to change LLM — user_id={current_user.id}")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")

    try:
        active = llm_manager.set_active_llm(payload.provider, payload.model, user_id=current_user.id)
    except llm_manager.LLMConfigError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    return ActiveLLMResponse(provider=active.provider, model=active.model)
