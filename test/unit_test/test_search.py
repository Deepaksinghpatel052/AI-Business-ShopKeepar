import json

import pytest

import RAG_src.search as search_module
import utils.database as database_module
from models.chat_entry import ChatEntry, ChatStatus


class FakeLLMResponse:
    def __init__(self, content):
        self.content = content


class FakeLLM:
    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.calls = []

    def invoke(self, messages):
        self.calls.append(messages)
        if self.responses:
            return FakeLLMResponse(self.responses.pop(0))
        return FakeLLMResponse("")


class FakeFaissVectorStore:
    instances = []

    def __init__(self, persist_dir, embedding_model="openai"):
        self.persist_dir = persist_dir
        self.embedding_model = embedding_model
        self.query_calls = []
        # Non-empty by default so a freshly-constructed store (e.g. the demo store
        # search_and_summarize builds on the fly) has something to return unless a
        # test explicitly overrides it to [] to exercise the "no data" path.
        self.query_result = [{"metadata": {"text": "fake vector result"}}]
        FakeFaissVectorStore.instances.append(self)

    def load(self):
        pass

    def query(self, query_text, top_k=5, user_id=None):
        self.query_calls.append((query_text, top_k, user_id))
        return self.query_result


@pytest.fixture()
def rag_instance(monkeypatch, db_session_factory):
    FakeFaissVectorStore.instances = []
    monkeypatch.setattr(search_module, "FaissVectorStore", FakeFaissVectorStore)
    monkeypatch.setattr(search_module, "ChatOpenAI", lambda **kwargs: FakeLLM())
    # handle_message/_confirm_entry/_reject_entry re-import SessionLocal locally on every
    # call (rather than using the module-level import), so the module-level patch alone
    # doesn't reach them — patch the real utils.database.SessionLocal too, since that's
    # what those local imports resolve fresh from at call time.
    monkeypatch.setattr(search_module, "SessionLocal", db_session_factory)
    monkeypatch.setattr(database_module, "SessionLocal", db_session_factory)

    rag = search_module.RAGSearch()
    rag.llm = FakeLLM()
    return rag


# ── handle_message routing ─────────────────────────────────────────────────

def test_handle_message_routes_query_intent(rag_instance, monkeypatch):
    """handle_message() routes a "query" intent to search_and_summarize() and returns its result."""
    rag_instance.llm.responses = [json.dumps({"intent": "query"})]
    monkeypatch.setattr(rag_instance, "search_and_summarize", lambda msg, user_id: "the answer")

    result = rag_instance.handle_message("How much did I sell today?", user_id=1)

    assert result == "the answer"


def test_handle_message_routes_add_data_intent(rag_instance, monkeypatch):
    """handle_message() routes an "add_data" intent to _extract_and_confirm() and returns its result."""
    rag_instance.llm.responses = [json.dumps({"intent": "add_data"})]
    monkeypatch.setattr(rag_instance, "_extract_and_confirm", lambda msg, user_id: "please confirm")

    result = rag_instance.handle_message("Sold 5 watches at 3200 each", user_id=1)

    assert result == "please confirm"


def test_handle_message_unclear_intent_returns_fallback(rag_instance):
    """An "unclear" intent returns the generic "not sure what you mean" fallback message."""
    rag_instance.llm.responses = [json.dumps({"intent": "unclear"})]

    result = rag_instance.handle_message("hello there", user_id=1)

    assert "not sure" in result.lower()


def test_handle_message_malformed_llm_response_falls_back(rag_instance):
    """If the intent-classification LLM response isn't valid JSON, handle_message() falls back gracefully."""
    rag_instance.llm.responses = ["not valid json at all"]

    result = rag_instance.handle_message("hello there", user_id=1)

    assert "not sure" in result.lower()


def test_handle_message_confirms_pending_entry_on_yes(rag_instance, db_session):
    """Replying "yes" while a pending entry exists confirms that entry instead of running intent detection."""
    entry = ChatEntry(
        user_id=5, raw_message="sold stuff",
        extracted=json.dumps({"product": "Widget"}), status=ChatStatus.PENDING,
    )
    db_session.add(entry)
    db_session.commit()
    db_session.refresh(entry)

    result = rag_instance.handle_message("yes", user_id=5)

    assert "confirmed" in result.lower()
    db_session.refresh(entry)
    assert entry.status == ChatStatus.CONFIRMED


def test_handle_message_confirms_pending_entry_on_hinglish_yes(rag_instance, db_session):
    """Hinglish affirmatives like "haan" also confirm a pending entry, not just English "yes"."""
    entry = ChatEntry(
        user_id=6, raw_message="sold stuff",
        extracted=json.dumps({"product": "Widget"}), status=ChatStatus.PENDING,
    )
    db_session.add(entry)
    db_session.commit()

    result = rag_instance.handle_message("haan", user_id=6)

    assert "confirmed" in result.lower()
    db_session.refresh(entry)
    assert entry.status == ChatStatus.CONFIRMED


def test_handle_message_rejects_pending_entry_on_no(rag_instance, db_session):
    """Replying "no" while a pending entry exists deletes that entry instead of running intent detection."""
    entry = ChatEntry(
        user_id=7, raw_message="sold stuff",
        extracted=json.dumps({"product": "Widget"}), status=ChatStatus.PENDING,
    )
    db_session.add(entry)
    db_session.commit()
    entry_id = entry.id

    result = rag_instance.handle_message("no", user_id=7)

    assert "rejected" in result.lower()
    assert db_session.query(ChatEntry).filter(ChatEntry.id == entry_id).first() is None


def test_handle_message_ignores_unrelated_reply_when_pending_entry_exists(rag_instance, db_session, monkeypatch):
    """A reply that isn't yes/no falls through to normal intent handling and leaves the pending entry untouched."""
    entry = ChatEntry(
        user_id=8, raw_message="sold stuff",
        extracted=json.dumps({"product": "Widget"}), status=ChatStatus.PENDING,
    )
    db_session.add(entry)
    db_session.commit()

    rag_instance.llm.responses = [json.dumps({"intent": "query"})]
    monkeypatch.setattr(rag_instance, "search_and_summarize", lambda msg, user_id: "the answer")

    result = rag_instance.handle_message("What did I sell last week?", user_id=8)

    assert result == "the answer"
    db_session.refresh(entry)
    assert entry.status == ChatStatus.PENDING  # untouched


# ── _extract_and_confirm ───────────────────────────────────────────────────

def test_extract_and_confirm_creates_pending_entry(rag_instance, db_session):
    """A valid JSON extraction from the LLM creates a PENDING ChatEntry with that data."""
    rag_instance.llm.responses = [json.dumps({
        "product": "Titan Watch", "quantity": 5, "price_per_unit": 3200,
        "total": 16000, "type": "sale", "notes": None,
    })]

    confirmation = rag_instance._extract_and_confirm("Sold 5 Titan watches at 3200 each", user_id=3)

    assert "Titan Watch" in confirmation
    entry = db_session.query(ChatEntry).filter(ChatEntry.user_id == 3).first()
    assert entry is not None
    assert entry.status == ChatStatus.PENDING
    assert json.loads(entry.extracted)["product"] == "Titan Watch"


def test_extract_and_confirm_handles_markdown_fenced_json(rag_instance, db_session):
    """A JSON response wrapped in ```json fences is still parsed and saved correctly."""
    rag_instance.llm.responses = ["```json\n" + json.dumps({"product": "Pen", "quantity": 1}) + "\n```"]

    confirmation = rag_instance._extract_and_confirm("Sold a pen", user_id=4)

    assert "Pen" in confirmation
    assert db_session.query(ChatEntry).filter(ChatEntry.user_id == 4).count() == 1


def test_extract_and_confirm_handles_malformed_json(rag_instance, db_session):
    """A non-JSON LLM response returns an error message and creates no ChatEntry."""
    rag_instance.llm.responses = ["this is not json"]

    result = rag_instance._extract_and_confirm("garbled message", user_id=10)

    assert "could not understand" in result.lower()
    assert db_session.query(ChatEntry).filter(ChatEntry.user_id == 10).count() == 0


# ── search_and_summarize ───────────────────────────────────────────────────

def test_search_and_summarize_uses_own_vectorstore_when_demo_disabled(rag_instance, make_user):
    """With demo mode off, search_and_summarize() queries the user's own vector store, not a demo one."""
    user = make_user(email="ownstore@example.com")
    rag_instance.vectorstore.query_result = [
        {"metadata": {"text": "Sold 10 units of Widget for Rs 5000"}}
    ]
    rag_instance.llm.responses = ["Here is your answer."]

    answer = rag_instance.search_and_summarize("How much did I sell?", user_id=user.id)

    assert answer == "Here is your answer."
    assert rag_instance.vectorstore.query_calls[0][2] == user.id
    # No demo store should have been created.
    assert len(FakeFaissVectorStore.instances) == 1


def test_search_and_summarize_uses_demo_store_when_enabled(rag_instance, make_user):
    """With demo mode on, search_and_summarize() queries a separate demo store keyed by the chosen dataset."""
    user = make_user(email="demouser@example.com", demo_mode_enabled=True, demo_dataset="kirana_store")
    rag_instance.llm.responses = ["Demo answer."]

    # The real self.vectorstore should return nothing relevant; only the demo store has data.
    rag_instance.vectorstore.query_result = []

    answer = rag_instance.search_and_summarize("What's in stock?", user_id=user.id)

    assert answer == "Demo answer."
    assert rag_instance.vectorstore.query_calls == []  # own store never queried

    demo_store = FakeFaissVectorStore.instances[-1]
    assert demo_store is not rag_instance.vectorstore
    query_text, top_k, queried_user_id = demo_store.query_calls[0]
    assert queried_user_id == "kirana_store"


def test_search_and_summarize_returns_no_data_message_when_context_empty(rag_instance, make_user):
    """When neither the vector store nor confirmed chat entries have anything relevant, the LLM is skipped entirely."""
    user = make_user(email="emptycontext@example.com")
    rag_instance.vectorstore.query_result = []

    answer = rag_instance.search_and_summarize("Anything interesting?", user_id=user.id)

    assert answer == "No relevant data found."
    assert rag_instance.llm.calls == []  # LLM never invoked when there's nothing to summarize


def test_search_and_summarize_includes_confirmed_chat_entries(rag_instance, make_user, db_session):
    """Confirmed ChatEntry rows for the user are folded into the LLM prompt as extra context."""
    user = make_user(email="withentries@example.com")
    entry = ChatEntry(
        user_id=user.id, raw_message="sold widgets",
        extracted=json.dumps({"product": "Widget", "quantity": 3, "total": 900, "type": "sale"}),
        status=ChatStatus.CONFIRMED,
    )
    db_session.add(entry)
    db_session.commit()

    rag_instance.vectorstore.query_result = []
    rag_instance.llm.responses = ["Summary with widget data."]

    answer = rag_instance.search_and_summarize("What did I sell?", user_id=user.id)

    assert answer == "Summary with widget data."
    prompt_text = rag_instance.llm.calls[0]
    assert "Widget" in str(prompt_text)
