from collections import deque

import pytest

from backend import ai, ai_providers

AI_ENVIRONMENT = (
    "GEMINI_API_KEY",
    "GEMINI_MODEL",
    "OPENROUTER_API_KEY",
    "RONIN_AI_PROVIDER_ORDER",
    "RONIN_AI_PRIMARY_MODEL",
    "RONIN_AI_FALLBACK_MODELS",
    "RONIN_AI_TIMEOUT_SECONDS",
    "RONIN_AI_MAX_RETRIES",
    "RONIN_AI_MAX_OUTPUT_TOKENS",
    "RONIN_AI_ALLOW_PAID_MODELS",
)


@pytest.fixture(autouse=True)
def isolated_ai(monkeypatch: pytest.MonkeyPatch):
    """Every test starts with no AI configuration, no cooldowns, and no waiting.

    Live OpenRouter calls are blocked: an unexpected request fails the test instead of spending quota.
    """
    for name in AI_ENVIRONMENT:
        monkeypatch.delenv(name, raising=False)

    def forbidden_request(**_kwargs):
        raise AssertionError("A deterministic test attempted a live OpenRouter request.")

    monkeypatch.setattr(ai_providers, "openrouter_generate_json", forbidden_request)
    monkeypatch.setattr(ai, "_sleep", lambda _seconds: None)
    monkeypatch.setattr(ai, "_cooldowns", {})
    monkeypatch.setattr(ai, "_last_success", None)
    monkeypatch.setattr(ai, "_recent_failures", deque(maxlen=10))
    yield
