"""
Chat LLM ka ek central manager — local Ollama (default) aur OpenAI ke beech switch karne ke liye.

Ollama ka OpenAI-compatible API (`<OLLAMA_BASE_URL>/v1`) use hota hai, isliye dono providers
ke liye wahi ChatOpenAI / OpenAI client chalta hai — sirf base_url, api_key aur model badalte hain.

Active (provider, model) llm_settings table me save hota hai (restart ke baad bhi wahi rahe),
aur process me cache hota hai taaki har LLM call pe DB na padhna pade.
Note: embeddings abhi bhi OpenAI se hi bante hain — sirf chat/completion LLM switch hota hai.
"""
import json
import logging
import os
import threading
import urllib.request
from dataclasses import dataclass

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from openai import OpenAI

import utils.database as database
from models.llm_setting import LLMSetting

load_dotenv()

logger = logging.getLogger(__name__)

PROVIDER_OLLAMA = "ollama"
PROVIDER_OPENAI = "openai"
SUPPORTED_PROVIDERS = (PROVIDER_OLLAMA, PROVIDER_OPENAI)

OLLAMA_BASE_URL   = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
OLLAMA_CHAT_MODEL = os.getenv("OLLAMA_CHAT_MODEL", "phi3:mini")
OPENAI_CHAT_MODEL = os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini")
LLM_TIMEOUT       = float(os.getenv("LLM_TIMEOUT_SECONDS", "120"))  # local CPU model slow ho sakta hai

DEFAULT_PROVIDER = os.getenv("DEFAULT_LLM_PROVIDER", PROVIDER_OLLAMA)


@dataclass(frozen=True)
class ActiveLLM:
    provider: str
    model: str


class LLMConfigError(ValueError):
    """Invalid provider/model choice — router ise 400 me convert karta hai."""


def default_model_for(provider: str) -> str:
    return OLLAMA_CHAT_MODEL if provider == PROVIDER_OLLAMA else OPENAI_CHAT_MODEL


def _default_llm() -> ActiveLLM:
    provider = DEFAULT_PROVIDER if DEFAULT_PROVIDER in SUPPORTED_PROVIDERS else PROVIDER_OLLAMA
    return ActiveLLM(provider, default_model_for(provider))


_lock = threading.Lock()
_active: ActiveLLM | None = None          # None = abhi DB se load nahi hua
_chat_cache: dict[ActiveLLM, ChatOpenAI] = {}
_client_cache: dict[str, OpenAI] = {}


def _connection_kwargs(provider: str) -> dict:
    if provider == PROVIDER_OLLAMA:
        # Ollama api_key check nahi karta, par OpenAI SDK ko koi non-empty value chahiye
        return {"base_url": f"{OLLAMA_BASE_URL}/v1", "api_key": "ollama"}
    return {"api_key": os.getenv("OPENAI_API_KEY")}


# ── Active selection ──────────────────────────────────────────────────────────

def get_active_llm() -> ActiveLLM:
    """Current (provider, model). Pehli baar DB se load hota hai; row nahi hai to default (Ollama)."""
    global _active
    if _active is not None:
        return _active

    with _lock:
        if _active is None:
            loaded = _default_llm()
            db = database.SessionLocal()
            try:
                row = db.get(LLMSetting, 1)
                if row and row.provider in SUPPORTED_PROVIDERS:
                    loaded = ActiveLLM(row.provider, row.model)
            except Exception:
                logger.exception("Could not load LLM setting from DB — using default")
            finally:
                db.close()
            _active = loaded
            logger.info(f"Active LLM: provider={_active.provider} model={_active.model}")
    return _active


def set_active_llm(provider: str, model: str | None, user_id: int | None = None) -> ActiveLLM:
    """Provider/model validate karke DB me save karo aur cache update karo."""
    global _active
    provider = provider.strip().lower()
    if provider not in SUPPORTED_PROVIDERS:
        raise LLMConfigError(f"Unsupported provider '{provider}'. Choose one of: {', '.join(SUPPORTED_PROVIDERS)}")

    model = (model or "").strip() or default_model_for(provider)

    if provider == PROVIDER_OLLAMA:
        installed = list_ollama_models()
        if installed is None:
            raise LLMConfigError(f"Ollama is not reachable at {OLLAMA_BASE_URL}. Start it with `ollama serve`.")
        if model not in installed:
            raise LLMConfigError(
                f"Model '{model}' is not pulled in Ollama. Available: {', '.join(installed) or 'none'} "
                f"(run `ollama pull {model}`)."
            )
    elif not os.getenv("OPENAI_API_KEY"):
        raise LLMConfigError("OPENAI_API_KEY is not configured on the server.")

    new_active = ActiveLLM(provider, model)
    db = database.SessionLocal()
    try:
        row = db.get(LLMSetting, 1)
        if row is None:
            row = LLMSetting(id=1, provider=provider, model=model, updated_by=user_id)
            db.add(row)
        else:
            row.provider, row.model, row.updated_by = provider, model, user_id
        db.commit()
    finally:
        db.close()

    with _lock:
        _active = new_active
    logger.info(f"Active LLM changed: provider={provider} model={model} by user_id={user_id}")
    return new_active


# ── Clients ───────────────────────────────────────────────────────────────────

def get_chat_llm() -> ChatOpenAI:
    """Active provider ka LangChain chat model (per provider/model cached)."""
    active = get_active_llm()
    llm = _chat_cache.get(active)
    if llm is None:
        llm = ChatOpenAI(model=active.model, timeout=LLM_TIMEOUT, **_connection_kwargs(active.provider))
        _chat_cache[active] = llm
    return llm


def get_chat_client() -> OpenAI:
    """Active provider ka raw OpenAI SDK client (chat.completions ke liye)."""
    provider = get_active_llm().provider
    client = _client_cache.get(provider)
    if client is None:
        client = OpenAI(timeout=LLM_TIMEOUT, **_connection_kwargs(provider))
        _client_cache[provider] = client
    return client


# ── Discovery ─────────────────────────────────────────────────────────────────

def list_ollama_models() -> list[str] | None:
    """Ollama me pulled models ke naam. Ollama chal nahi raha to None."""
    try:
        with urllib.request.urlopen(f"{OLLAMA_BASE_URL}/api/tags", timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return [m["name"] for m in data.get("models", [])]
    except Exception as e:
        logger.warning(f"Ollama not reachable at {OLLAMA_BASE_URL}: {e}")
        return None


def list_providers() -> list[dict]:
    ollama_models = list_ollama_models()
    return [
        {
            "provider": PROVIDER_OLLAMA,
            "type": "local",
            "available": ollama_models is not None,
            "default_model": OLLAMA_CHAT_MODEL,
            "models": ollama_models or [],
        },
        {
            "provider": PROVIDER_OPENAI,
            "type": "cloud",
            "available": bool(os.getenv("OPENAI_API_KEY")),
            "default_model": OPENAI_CHAT_MODEL,
            "models": [OPENAI_CHAT_MODEL],  # koi bhi valid OpenAI chat model name diya ja sakta hai
        },
    ]
