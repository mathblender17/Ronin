"""Deterministic tests for the provider-independent AI layer. Every provider is mocked; no test needs a quota or a network."""

import json
import logging
from collections.abc import Generator
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from google.genai import errors
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend import ai, ai_providers
from backend.database import Base
from backend.main import app, get_db
from backend.schemas import ExpansionLayer, GeneratedConcept, InitialLayer

# Captured before conftest replaces the module attribute with a guard, so the adapter itself can be tested over a mock transport.
real_openrouter_generate_json = ai_providers.openrouter_generate_json
PRIMARY = "nvidia/nemotron-3-super-120b-a12b:free"
FALLBACK = "google/gemma-4-26b-a4b-it:free"
SECRET = "or-SECRET-VALUE-123"


def concept(title: str) -> GeneratedConcept:
    return GeneratedConcept(
        title=title,
        summary=f"A concise explanation of {title.lower()} and the forces around it.",
        connection_reason=f"{title} offers a distinct way to understand the question.",
        exploration_question=f"What shaped {title.lower()}?",
        domain="History",
    )


# Titles are deliberately dissimilar: Ronin's deduplication would drop near-identical titles and make the fixtures invalid.
INITIAL_TITLES = ["Status games", "Power and institutions", "Evolutionary roots", "Moral authority", "Economic dependence"]
EXPANSION_TITLES = ["Mechanism of rivalry", "Case of the reformers", "Surprising consequence"]


def initial_json() -> str:
    branches = [concept(title) for title in INITIAL_TITLES]
    return InitialLayer(root_summary="A question about motives, systems, and human relationships.", branches=branches).model_dump_json()


def expansion_json() -> str:
    return ExpansionLayer(branches=[concept(title) for title in EXPANSION_TITLES]).model_dump_json()


class FakeGemini:
    """Stands in for google-genai. Each outcome is returned text or an exception to raise."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls: list[str] = []
        self.models = self

    def generate_content(self, **kwargs):
        self.calls.append(kwargs["model"])
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return SimpleNamespace(text=outcome)

    def close(self):
        pass


class FakeOpenRouter:
    """Stands in for the OpenRouter adapter. `script` maps a model ID to a list of outcomes, consumed in order."""

    def __init__(self, script: dict[str, list]):
        self.script = {model: list(outcomes) for model, outcomes in script.items()}
        self.calls: list[str] = []

    def __call__(self, *, model, prompt, api_key, timeout, max_tokens, transport=None):
        self.calls.append(model)
        outcome = self.script[model].pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def gemini_error(code: int, message: str) -> errors.APIError:
    return errors.APIError(code, {"error": {"message": message, "status": "RESOURCE_EXHAUSTED"}}, None)


def configure(monkeypatch: pytest.MonkeyPatch, **env: str) -> None:
    for name, value in env.items():
        monkeypatch.setenv(name, value)


def use_gemini(monkeypatch: pytest.MonkeyPatch, outcomes) -> FakeGemini:
    fake = FakeGemini(outcomes)
    monkeypatch.setattr(ai, "_client", lambda: fake)
    return fake


def use_openrouter(monkeypatch: pytest.MonkeyPatch, script: dict[str, list]) -> FakeOpenRouter:
    fake = FakeOpenRouter(script)
    monkeypatch.setattr(ai_providers, "openrouter_generate_json", fake)
    return fake


# ---- Gemini first, OpenRouter as fallback ---------------------------------------------------------

def test_gemini_success_makes_no_fallback_request(monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch, GEMINI_API_KEY="gemini-test-key", OPENROUTER_API_KEY="or-test-key")
    gemini = use_gemini(monkeypatch, [initial_json()])
    openrouter = use_openrouter(monkeypatch, {})
    value, provider = ai._structured_with_provider("prompt", InitialLayer)
    assert provider == "gemini"
    assert len(value.branches) == 5
    assert len(gemini.calls) == 1
    assert openrouter.calls == []


def test_gemini_daily_quota_triggers_openrouter_without_retrying_gemini(monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch, GEMINI_API_KEY="gemini-test-key", OPENROUTER_API_KEY="or-test-key")
    gemini = use_gemini(monkeypatch, [gemini_error(429, "Quota exceeded for metric PerDay")])
    openrouter = use_openrouter(monkeypatch, {PRIMARY: [initial_json()]})
    value, provider = ai._structured_with_provider("prompt", InitialLayer)
    assert provider == "openrouter"
    assert len(value.branches) == 5
    assert len(gemini.calls) == 1
    assert openrouter.calls == [PRIMARY]


def test_gemini_per_minute_rate_limit_moves_on_immediately_with_one_gemini_request(monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch, GEMINI_API_KEY="gemini-test-key", OPENROUTER_API_KEY="or-test-key")
    delays: list[float] = []
    monkeypatch.setattr(ai, "_sleep", delays.append)
    gemini = use_gemini(monkeypatch, [gemini_error(429, "Rate limit exceeded")])
    openrouter = use_openrouter(monkeypatch, {PRIMARY: [initial_json()]})
    _value, provider = ai._structured_with_provider("prompt", InitialLayer)
    # Before this change Gemini received a second request and a backoff sleep. Now it receives exactly one.
    assert provider == "openrouter"
    assert len(gemini.calls) == 1
    assert delays == []
    assert openrouter.calls == [PRIMARY]


def test_gemini_rate_limit_cooldown_prevents_repeat_requests_until_it_expires(monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch, GEMINI_API_KEY="gemini-test-key", OPENROUTER_API_KEY="or-test-key")
    clock = {"now": 1000.0}
    monkeypatch.setattr(ai, "_clock", lambda: clock["now"])
    gemini = use_gemini(monkeypatch, [gemini_error(429, "Rate limit exceeded"), initial_json()])
    openrouter = use_openrouter(monkeypatch, {PRIMARY: [initial_json(), initial_json()]})
    ai._structured_with_provider("prompt", InitialLayer)
    assert len(gemini.calls) == 1
    # Within the cooldown: no Gemini request at all, straight to OpenRouter.
    clock["now"] += 30
    _value, provider = ai._structured_with_provider("prompt", InitialLayer)
    assert provider == "openrouter" and len(gemini.calls) == 1 and len(openrouter.calls) == 2
    # After the cooldown (60 s minimum): Gemini is tried again.
    clock["now"] += 120
    _value, provider = ai._structured_with_provider("prompt", InitialLayer)
    assert provider == "gemini" and len(gemini.calls) == 2


def test_openrouter_is_not_attempted_without_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch, GEMINI_API_KEY="gemini-test-key")
    gemini = use_gemini(monkeypatch, [gemini_error(429, "Rate limit exceeded")])
    openrouter = use_openrouter(monkeypatch, {})
    with pytest.raises(ai.AIServiceError) as raised:
        ai._structured_with_provider("prompt", InitialLayer)
    assert len(gemini.calls) == 1
    assert openrouter.calls == []
    assert "busy right now" in str(raised.value)


# ---- OpenRouter model fallback, retries and policy -----------------------------------------------

def test_openrouter_model_failure_moves_to_the_next_eligible_model(monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch, RONIN_AI_PROVIDER_ORDER="openrouter", OPENROUTER_API_KEY="or-test-key")
    openrouter = use_openrouter(monkeypatch, {
        PRIMARY: [ai_providers.ProviderError(ai_providers.UNAVAILABLE, "down"), ai_providers.ProviderError(ai_providers.UNAVAILABLE, "down")],
        FALLBACK: [initial_json()],
    })
    _value, provider = ai._structured_with_provider("prompt", InitialLayer)
    assert provider == "openrouter"
    assert openrouter.calls == [PRIMARY, PRIMARY, FALLBACK]


def test_all_providers_failing_returns_a_controlled_error_not_a_raw_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch, GEMINI_API_KEY="gemini-test-key", OPENROUTER_API_KEY="or-test-key", RONIN_AI_FALLBACK_MODELS=FALLBACK)
    use_gemini(monkeypatch, [gemini_error(503, "down")] * 2)
    unavailable = ai_providers.ProviderError(ai_providers.UNAVAILABLE, "down")
    use_openrouter(monkeypatch, {PRIMARY: [unavailable] * 2, FALLBACK: [unavailable] * 2})
    with pytest.raises(ai.AIServiceError, match="temporarily unavailable") as raised:
        ai._structured_with_provider("prompt", InitialLayer)
    assert not isinstance(raised.value, ai.AIConfigurationError)
    # Developers see the provider, model and category trail; users never see internal labels.
    assert "gemini/gemini-2.5-flash: unavailable" in raised.value.technical
    assert "openrouter/" in raised.value.technical
    assert "_" not in str(raised.value) and "unavailable:" not in str(raised.value)


def test_daily_free_limit_does_not_retry_or_switch_models_in_a_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch, RONIN_AI_PROVIDER_ORDER="openrouter", OPENROUTER_API_KEY="or-test-key")
    delays: list[float] = []
    monkeypatch.setattr(ai, "_sleep", delays.append)
    daily = ai_providers.ProviderError(ai_providers.DAILY_QUOTA, "daily allowance used up")
    openrouter = use_openrouter(monkeypatch, {PRIMARY: [daily], FALLBACK: [initial_json()]})
    with pytest.raises(ai.AIServiceError, match="free AI allowance for today"):
        ai._structured_with_provider("prompt", InitialLayer)
    # Platform-wide free allowance: switching model IDs cannot bypass it, so the next model is not tried.
    assert openrouter.calls == [PRIMARY]
    assert delays == []
    # Within the cooldown, OpenRouter is not called again at all.
    with pytest.raises(ai.AIServiceError):
        ai._structured_with_provider("prompt", InitialLayer)
    assert openrouter.calls == [PRIMARY]


def test_openrouter_rate_limit_pauses_only_that_model(monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch, RONIN_AI_PROVIDER_ORDER="openrouter", OPENROUTER_API_KEY="or-test-key")
    delays: list[float] = []
    monkeypatch.setattr(ai, "_sleep", delays.append)
    clock = {"now": 0.0}
    monkeypatch.setattr(ai, "_clock", lambda: clock["now"])
    openrouter = use_openrouter(monkeypatch, {
        PRIMARY: [ai_providers.ProviderError(ai_providers.RATE_LIMITED, "slow down", retry_after=2.0)],
        FALLBACK: [initial_json(), initial_json()],
    })
    _value, provider = ai._structured_with_provider("prompt", InitialLayer)
    assert provider == "openrouter"
    assert delays == []  # no retry of the limited model
    assert openrouter.calls == [PRIMARY, FALLBACK]
    # The limited model stays paused, while its sibling keeps working.
    _value, provider = ai._structured_with_provider("prompt", InitialLayer)
    assert openrouter.calls == [PRIMARY, FALLBACK, FALLBACK]


def test_long_retry_after_moves_on_instead_of_waiting(monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch, RONIN_AI_PROVIDER_ORDER="openrouter", OPENROUTER_API_KEY="or-test-key")
    delays: list[float] = []
    monkeypatch.setattr(ai, "_sleep", delays.append)
    openrouter = use_openrouter(monkeypatch, {
        PRIMARY: [ai_providers.ProviderError(ai_providers.RATE_LIMITED, "slow down", retry_after=60.0)],
        FALLBACK: [initial_json()],
    })
    _value, provider = ai._structured_with_provider("prompt", InitialLayer)
    assert provider == "openrouter"
    assert delays == []
    assert openrouter.calls == [PRIMARY, FALLBACK]


def test_auth_failure_is_not_retried_and_skips_the_provider(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    configure(monkeypatch, RONIN_AI_PROVIDER_ORDER="openrouter", OPENROUTER_API_KEY=SECRET)
    openrouter = use_openrouter(monkeypatch, {PRIMARY: [ai_providers.ProviderError(ai_providers.AUTH, "OpenRouter rejected the API key. Check OPENROUTER_API_KEY in the project .env file.")]})
    caplog.set_level(logging.DEBUG, logger="ronin.ai")
    with pytest.raises(ai.AIServiceError) as raised:
        ai._structured_with_provider("prompt", InitialLayer)
    assert openrouter.calls == [PRIMARY]
    assert "rejected its API key" in str(raised.value)
    assert SECRET not in str(raised.value) and SECRET not in caplog.text


def test_bad_request_skips_only_that_model(monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch, RONIN_AI_PROVIDER_ORDER="openrouter", OPENROUTER_API_KEY="or-test-key")
    openrouter = use_openrouter(monkeypatch, {PRIMARY: [ai_providers.ProviderError(ai_providers.BAD_REQUEST, "rejected")], FALLBACK: [initial_json()]})
    _value, provider = ai._structured_with_provider("prompt", InitialLayer)
    assert provider == "openrouter"
    assert openrouter.calls == [PRIMARY, FALLBACK]


# ---- Free-only policy -----------------------------------------------------------------------------

def test_paid_model_is_rejected_when_paid_models_are_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch, RONIN_AI_PROVIDER_ORDER="openrouter", OPENROUTER_API_KEY="or-test-key", RONIN_AI_PRIMARY_MODEL="openai/gpt-4o")
    openrouter = use_openrouter(monkeypatch, {FALLBACK: [initial_json()]})
    _value, provider = ai._structured_with_provider("prompt", InitialLayer)
    assert provider == "openrouter"
    assert openrouter.calls == [FALLBACK]  # the paid model was never requested


def test_paid_model_is_allowed_only_when_enabled_and_named_explicitly(monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch, RONIN_AI_PROVIDER_ORDER="openrouter", OPENROUTER_API_KEY="or-test-key", RONIN_AI_PRIMARY_MODEL="openai/gpt-4o", RONIN_AI_ALLOW_PAID_MODELS="true")
    openrouter = use_openrouter(monkeypatch, {"openai/gpt-4o": [initial_json()]})
    _value, provider = ai._structured_with_provider("prompt", InitialLayer)
    assert provider == "openrouter"
    assert openrouter.calls == ["openai/gpt-4o"]


def test_unknown_free_looking_model_cannot_bypass_the_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch, RONIN_AI_PROVIDER_ORDER="openrouter", OPENROUTER_API_KEY="or-test-key", RONIN_AI_PRIMARY_MODEL="someone/unreviewed-model:free")
    openrouter = use_openrouter(monkeypatch, {FALLBACK: [initial_json()]})
    _value, provider = ai._structured_with_provider("prompt", InitialLayer)
    assert provider == "openrouter"
    assert openrouter.calls == [FALLBACK]


def test_gemini_model_outside_the_approved_list_is_not_called(monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch, GEMINI_API_KEY="gemini-test-key", GEMINI_MODEL="some-paid-model", OPENROUTER_API_KEY="or-test-key")
    gemini = use_gemini(monkeypatch, [])
    use_openrouter(monkeypatch, {PRIMARY: [initial_json()]})
    _value, provider = ai._structured_with_provider("prompt", InitialLayer)
    assert provider == "openrouter"
    assert gemini.calls == []


# ---- Output validation -----------------------------------------------------------------------------

def test_malformed_and_schema_invalid_output_is_rejected_and_the_next_model_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch, GEMINI_API_KEY="gemini-test-key", OPENROUTER_API_KEY="or-test-key")
    use_gemini(monkeypatch, ["this is not json"])
    openrouter = use_openrouter(monkeypatch, {PRIMARY: ['{"root_summary": "missing branches"}'], FALLBACK: [initial_json()]})
    _value, provider = ai._structured_with_provider("prompt", InitialLayer)
    assert provider == "openrouter"
    assert openrouter.calls == [PRIMARY, FALLBACK]


def test_provider_outage_does_not_trigger_a_second_full_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch, RONIN_AI_PROVIDER_ORDER="openrouter", OPENROUTER_API_KEY="or-test-key", RONIN_AI_FALLBACK_MODELS=FALLBACK)
    monkeypatch.setattr(ai, "_grounded_sources", lambda _question, _concepts: {})
    unavailable = ai_providers.ProviderError(ai_providers.UNAVAILABLE, "down")
    openrouter = use_openrouter(monkeypatch, {PRIMARY: [unavailable] * 2, FALLBACK: [unavailable] * 2})
    with pytest.raises(ai.AIServiceError):
        ai.generate_initial("Why do humans seek power?")
    # One pass through the chain: 2 models x (1 attempt + 1 retry). No second full pass for an outage.
    assert len(openrouter.calls) == 4


def test_openrouter_adapter_classifies_http_responses_without_leaking_the_key() -> None:
    def respond(status: int, body: dict | str, headers: dict | None = None):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers["Authorization"] == f"Bearer {SECRET}"
            payload = json.dumps(body) if isinstance(body, dict) else body
            return httpx.Response(status, text=payload, headers=headers or {})
        return httpx.MockTransport(handler)

    def call(transport):
        return real_openrouter_generate_json(
            model=PRIMARY, prompt="p", api_key=SECRET, timeout=5, max_tokens=100, transport=transport,
        )

    with pytest.raises(ai_providers.ProviderError) as daily:
        call(respond(429, {"error": {"message": "Rate limit exceeded: free-models-per-day", "code": 429}}))
    assert daily.value.category == ai_providers.DAILY_QUOTA

    with pytest.raises(ai_providers.ProviderError) as minute:
        call(respond(429, {"error": {"message": "Too many requests"}}, {"retry-after": "3"}))
    assert minute.value.category == ai_providers.RATE_LIMITED and minute.value.retry_after == 3.0

    with pytest.raises(ai_providers.ProviderError) as auth:
        call(respond(401, {"error": {"message": "invalid api key"}}))
    assert auth.value.category == ai_providers.AUTH
    assert SECRET not in auth.value.message

    with pytest.raises(ai_providers.ProviderError) as billing:
        call(respond(402, {"error": {"message": "Insufficient credits"}}))
    assert billing.value.category == ai_providers.BILLING

    with pytest.raises(ai_providers.ProviderError) as broken:
        call(respond(200, {"choices": []}))
    assert broken.value.category == ai_providers.INVALID_OUTPUT

    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    with pytest.raises(ai_providers.ProviderError) as timeout:
        call(httpx.MockTransport(slow))
    assert timeout.value.category == ai_providers.TIMEOUT

    content = call(respond(200, {"choices": [{"message": {"content": initial_json()}}]}))
    assert json.loads(content)["branches"]


def test_provider_order_is_configurable_and_reversible(monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch, RONIN_AI_PROVIDER_ORDER="openrouter,gemini", GEMINI_API_KEY="gemini-test-key", OPENROUTER_API_KEY="or-test-key")
    gemini = use_gemini(monkeypatch, [initial_json()])
    openrouter = use_openrouter(monkeypatch, {PRIMARY: [initial_json()]})
    _value, provider = ai._structured_with_provider("prompt", InitialLayer)
    assert provider == "openrouter"
    assert gemini.calls == []
    assert openrouter.calls == [PRIMARY]


# ---- Sources and configuration -------------------------------------------------------------------

def test_layers_from_openrouter_carry_no_unverified_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch, RONIN_AI_PROVIDER_ORDER="openrouter", OPENROUTER_API_KEY="or-test-key")
    grounding_calls: list[str] = []
    monkeypatch.setattr(ai, "_grounded_sources", lambda *args: grounding_calls.append("called") or {})
    use_openrouter(monkeypatch, {PRIMARY: [initial_json()]})
    layer = ai.generate_initial("Why do humans seek power?")
    assert len(layer.branches) == 5
    assert layer.source_map == {}
    assert grounding_calls == []


def test_layers_from_gemini_still_request_grounded_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch, GEMINI_API_KEY="gemini-test-key")
    use_gemini(monkeypatch, [initial_json()])
    grounding_calls: list[str] = []
    monkeypatch.setattr(ai, "_grounded_sources", lambda *args: grounding_calls.append("called") or {})
    ai.generate_initial("Why do humans seek power?")
    assert grounding_calls == ["called"]


def test_no_provider_configured_says_what_to_add(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ai.AIConfigurationError, match="GEMINI_API_KEY") as raised:
        ai._structured_with_provider("prompt", InitialLayer)
    assert "OPENROUTER_API_KEY" in str(raised.value)


def test_diagnostics_report_eligibility_without_any_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch, GEMINI_API_KEY="gemini-test-key", OPENROUTER_API_KEY=SECRET, RONIN_AI_PRIMARY_MODEL="openai/gpt-4o")
    report = ai.diagnostics()
    text = json.dumps(report)
    assert SECRET not in text and "gemini-test-key" not in text
    openrouter = next(item for item in report["providers"] if item["name"] == "openrouter")
    assert openrouter["configured"] is True
    assert "openai/gpt-4o" not in openrouter["eligible_models"]
    assert FALLBACK in openrouter["eligible_models"]


# ---- API behaviour -------------------------------------------------------------------------------

@pytest.fixture()
def client() -> Generator[TestClient, None, None]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def seed_trail(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> dict:
    layer = InitialLayer.model_validate_json(initial_json())
    monkeypatch.setattr(ai, "generate_initial", lambda _question: ai.LayerResult(layer.branches, layer.root_summary))
    return client.post("/api/rabbit-holes", json={"question": "Why do humans seek power?"}).json()


def test_creating_a_trail_succeeds_through_the_openrouter_fallback(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch, GEMINI_API_KEY="", OPENROUTER_API_KEY="or-test-key")
    monkeypatch.setattr(ai, "_grounded_sources", lambda *args: {})
    use_openrouter(monkeypatch, {PRIMARY: [initial_json()]})
    response = client.post("/api/rabbit-holes", json={"question": "Why do humans seek power?"})
    assert response.status_code == 201
    assert len([node for node in response.json()["nodes"] if node["parent_id"] is not None]) == 5


def test_failed_creation_leaves_no_trail_behind(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch, GEMINI_API_KEY="gemini-test-key", OPENROUTER_API_KEY="or-test-key", RONIN_AI_FALLBACK_MODELS=FALLBACK)
    use_gemini(monkeypatch, [gemini_error(503, "down")] * 2)
    unavailable = ai_providers.ProviderError(ai_providers.UNAVAILABLE, "down")
    use_openrouter(monkeypatch, {PRIMARY: [unavailable] * 2, FALLBACK: [unavailable] * 2})
    response = client.post("/api/rabbit-holes", json={"question": "Why do humans seek power?"})
    assert response.status_code == 503
    assert "unavailable" in response.json()["detail"]
    assert client.get("/api/rabbit-holes").json() == []


def snapshot(client: TestClient, hole_id: str) -> dict:
    graph = client.get(f"/api/rabbit-holes/{hole_id}").json()
    return {
        "nodes": sorted((node["id"], node["title"], node["parent_id"]) for node in graph["nodes"]),
        "edges": sorted((edge["id"], edge["source"], edge["target"]) for edge in graph["edges"]),
    }


def test_failed_expansion_does_not_mutate_the_saved_graph(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    created = seed_trail(client, monkeypatch)
    before = snapshot(client, created["id"])
    leaf = next(node for node in created["nodes"] if node["parent_id"] is not None)
    configure(monkeypatch, GEMINI_API_KEY="gemini-test-key", OPENROUTER_API_KEY="or-test-key", RONIN_AI_FALLBACK_MODELS=FALLBACK)
    use_gemini(monkeypatch, [gemini_error(503, "down")] * 2)
    unavailable = ai_providers.ProviderError(ai_providers.UNAVAILABLE, "down")
    use_openrouter(monkeypatch, {PRIMARY: [unavailable] * 2, FALLBACK: [unavailable] * 2})
    response = client.post(f"/api/rabbit-holes/{created['id']}/nodes/{leaf['id']}/expand", json={"direction": "history"})
    assert response.status_code == 503
    assert snapshot(client, created["id"]) == before


def test_successful_expansion_through_the_fallback_keeps_existing_ids_and_adds_edges(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    created = seed_trail(client, monkeypatch)
    before = snapshot(client, created["id"])
    leaf = next(node for node in created["nodes"] if node["parent_id"] is not None)
    configure(monkeypatch, GEMINI_API_KEY="gemini-test-key", OPENROUTER_API_KEY="or-test-key")
    use_gemini(monkeypatch, [gemini_error(503, "down")] * 2)
    use_openrouter(monkeypatch, {PRIMARY: [expansion_json()]})
    response = client.post(f"/api/rabbit-holes/{created['id']}/nodes/{leaf['id']}/expand", json={"direction": "history"})
    assert response.status_code == 200
    after = snapshot(client, created["id"])
    assert set(before["nodes"]).issubset(set(after["nodes"]))
    assert set(before["edges"]).issubset(set(after["edges"]))
    new_children = [node for node in after["nodes"] if node[2] == leaf["id"]]
    assert len(new_children) == 3
    assert len(response.json()["node_ids"]) == 3


def test_viewing_saved_graphs_needs_no_api_keys(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    created = seed_trail(client, monkeypatch)
    assert client.get("/api/rabbit-holes").status_code == 200
    assert client.get(f"/api/rabbit-holes/{created['id']}").status_code == 200
    health = client.get("/api/health").json()
    assert health["ai_configured"] is False
    assert health["status"] == "ok"


def test_health_diagnostics_never_expose_the_key(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch, OPENROUTER_API_KEY=SECRET)
    body = client.get("/api/health").text
    assert SECRET not in body
    assert "eligible_models" in body


@pytest.mark.parametrize("category", [
    ai_providers.AUTH, ai_providers.BILLING, ai_providers.DAILY_QUOTA, ai_providers.RATE_LIMITED,
    ai_providers.COOLDOWN, ai_providers.INVALID_OUTPUT, ai_providers.BAD_REQUEST, ai_providers.POLICY,
    ai_providers.TIMEOUT, ai_providers.CONNECTION, ai_providers.UNAVAILABLE,
])
def test_every_failure_category_has_a_clear_user_message(category: str) -> None:
    message = ai.USER_MESSAGES[category]
    assert len(message) > 30
    assert "_" not in message and category.upper() not in message
    assert "traceback" not in message.lower() and "sk-" not in message
    # The message must say what happened and what to do, not just that something failed.
    assert any(word in message.lower() for word in ("try", "check", "add", "wait", "choose", "restart", "set up", "stopped"))


def test_priority_prefers_the_most_actionable_problem() -> None:
    failures = [
        ("gemini", "gemini-2.5-flash", ai_providers.ProviderError(ai_providers.UNAVAILABLE, "down")),
        ("openrouter", PRIMARY, ai_providers.ProviderError(ai_providers.AUTH, "bad key")),
    ]
    error = ai._failure_error(failures, reached_provider=True)
    assert error.category == ai_providers.AUTH
    assert str(error) == ai.USER_MESSAGES[ai_providers.AUTH]
    assert "gemini/gemini-2.5-flash: unavailable" in error.technical
