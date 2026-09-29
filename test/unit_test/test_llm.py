import pytest

import RAG_src.search as search_module
import services.llm_manager as llm_manager
import utils.database as database_module
from models.llm_setting import LLMSetting
from models.shop_owner import UserType


@pytest.fixture()
def llm_db(monkeypatch, db_session_factory):
    """Point llm_manager's SessionLocal at the in-memory test DB and fake the Ollama model list."""
    monkeypatch.setattr(database_module, "SessionLocal", db_session_factory)
    monkeypatch.setattr(llm_manager, "list_ollama_models", lambda: ["phi3:mini", "llama3:8b"])
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    return db_session_factory


# ── llm_manager ────────────────────────────────────────────────────────────────

def test_default_llm_is_local_ollama(monkeypatch, llm_db):
    """With no saved setting, the active LLM falls back to local Ollama phi3:mini."""
    monkeypatch.setattr(llm_manager, "_active", None)

    active = llm_manager.get_active_llm()

    assert active.provider == "ollama"
    assert active.model == llm_manager.OLLAMA_CHAT_MODEL


def test_saved_setting_is_loaded_from_db(monkeypatch, llm_db, db_session):
    """A persisted llm_settings row wins over the default on first load."""
    db_session.add(LLMSetting(id=1, provider="openai", model="gpt-4o"))
    db_session.commit()
    monkeypatch.setattr(llm_manager, "_active", None)

    active = llm_manager.get_active_llm()

    assert (active.provider, active.model) == ("openai", "gpt-4o")


def test_set_active_llm_persists_and_updates_cache(llm_db, db_session):
    active = llm_manager.set_active_llm("openai", "gpt-4o", user_id=None)

    assert llm_manager.get_active_llm() == active
    row = db_session.get(LLMSetting, 1)
    assert (row.provider, row.model) == ("openai", "gpt-4o")


def test_set_active_llm_without_model_uses_provider_default(llm_db):
    active = llm_manager.set_active_llm("ollama", None)
    assert active.model == llm_manager.OLLAMA_CHAT_MODEL


@pytest.mark.parametrize("provider,model,error", [
    ("gemini", None, "Unsupported provider"),
    ("ollama", "mistral:7b", "not pulled"),
])
def test_set_active_llm_rejects_invalid_choice(llm_db, provider, model, error):
    with pytest.raises(llm_manager.LLMConfigError, match=error):
        llm_manager.set_active_llm(provider, model)


def test_set_ollama_fails_when_ollama_not_running(monkeypatch, llm_db):
    monkeypatch.setattr(llm_manager, "list_ollama_models", lambda: None)
    with pytest.raises(llm_manager.LLMConfigError, match="not reachable"):
        llm_manager.set_active_llm("ollama", "phi3:mini")


def test_set_openai_requires_api_key(monkeypatch, llm_db):
    monkeypatch.delenv("OPENAI_API_KEY")
    with pytest.raises(llm_manager.LLMConfigError, match="OPENAI_API_KEY"):
        llm_manager.set_active_llm("openai", None)


def test_get_chat_llm_points_ollama_at_local_openai_compatible_api():
    llm = llm_manager.get_chat_llm()
    assert llm.model_name == llm_manager.OLLAMA_CHAT_MODEL
    assert llm.openai_api_base == f"{llm_manager.OLLAMA_BASE_URL}/v1"


# ── JSON parsing of small-model replies ──────────────────────────────────────

@pytest.mark.parametrize("content", [
    '{"intent": "query"}',
    '```json\n{"intent": "query"}\n```',
    'Sure! Here is the result:\n{"intent": "query", "reason": "asks about sales"}\nHope this helps.',
])
def test_parse_llm_json_tolerates_fences_and_extra_text(content):
    assert search_module._parse_llm_json(content)["intent"] == "query"


# ── /llm router ───────────────────────────────────────────────────────────────

def test_get_active_llm_endpoint(app_client, auth_headers):
    resp = app_client.get("/llm/active", headers=auth_headers())
    assert resp.status_code == 200
    assert resp.json() == {"provider": "ollama", "model": llm_manager.OLLAMA_CHAT_MODEL}


def test_providers_endpoint_lists_ollama_models(app_client, auth_headers, llm_db):
    resp = app_client.get("/llm/providers", headers=auth_headers())

    assert resp.status_code == 200
    body = resp.json()
    assert body["active"]["provider"] == "ollama"
    ollama = next(p for p in body["providers"] if p["provider"] == "ollama")
    assert ollama["available"] is True
    assert "phi3:mini" in ollama["models"]


def test_member_cannot_change_llm(app_client, auth_headers, llm_db):
    resp = app_client.put("/llm/active", json={"provider": "openai"}, headers=auth_headers())
    assert resp.status_code == 403


def test_admin_can_switch_llm(app_client, auth_headers, llm_db):
    headers = auth_headers(email="admin@example.com", user_type=UserType.ADMIN)

    resp = app_client.put("/llm/active", json={"provider": "openai", "model": "gpt-4o"}, headers=headers)

    assert resp.status_code == 200
    assert resp.json() == {"provider": "openai", "model": "gpt-4o"}
    assert app_client.get("/llm/active", headers=headers).json()["provider"] == "openai"


def test_admin_invalid_model_returns_400(app_client, auth_headers, llm_db):
    headers = auth_headers(email="admin@example.com", user_type=UserType.ADMIN)
    resp = app_client.put("/llm/active", json={"provider": "ollama", "model": "nope:1b"}, headers=headers)
    assert resp.status_code == 400
    assert "not pulled" in resp.json()["detail"]
