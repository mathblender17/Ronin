"""Opt-in smoke tests against live providers. They spend quota and are skipped unless RONIN_LIVE_TESTS=1 is set.

Run with:  RONIN_LIVE_TESTS=1 python -m pytest backend/live_tests -q
These live outside backend/tests so the deterministic suite's guard against live requests does not apply here.
"""

import os

import pytest

from backend import ai, ai_providers as providers

pytestmark = pytest.mark.skipif(os.getenv("RONIN_LIVE_TESTS") != "1", reason="Live provider smoke tests are opt-in: set RONIN_LIVE_TESTS=1.")


LIVE_OPENROUTER_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"


@pytest.mark.skipif(not os.getenv("OPENROUTER_API_KEY"), reason="Needs OPENROUTER_API_KEY.")
def test_openrouter_free_model_returns_a_valid_initial_layer(monkeypatch: pytest.MonkeyPatch) -> None:
    # Exactly one approved free model, no fallbacks and no retries: at most one live request.
    providers.approved_openrouter_model(LIVE_OPENROUTER_MODEL, allow_paid=False, named_explicitly=True)
    monkeypatch.setenv("RONIN_AI_PROVIDER_ORDER", "openrouter")
    monkeypatch.setenv("RONIN_AI_PRIMARY_MODEL", LIVE_OPENROUTER_MODEL)
    monkeypatch.setenv("RONIN_AI_FALLBACK_MODELS", "")
    monkeypatch.setenv("RONIN_AI_MAX_RETRIES", "0")
    monkeypatch.setenv("RONIN_AI_ALLOW_PAID_MODELS", "false")
    requested: list[str] = []
    real_request = providers.openrouter_generate_json

    def counting_request(**kwargs):
        requested.append(kwargs["model"])
        return real_request(**kwargs)

    monkeypatch.setattr(providers, "openrouter_generate_json", counting_request)
    layer = ai.generate_initial("Why do people feel lonely in crowded cities?")
    assert requested == [LIVE_OPENROUTER_MODEL]
    assert len(layer.branches) == 5
    assert all(item.summary and item.exploration_question for item in layer.branches)


@pytest.mark.skipif(not os.getenv("GEMINI_API_KEY"), reason="Needs GEMINI_API_KEY.")
def test_gemini_returns_a_valid_initial_layer(monkeypatch: pytest.MonkeyPatch) -> None:
    # One Gemini request at most: no retries. Skip this test while Gemini's quota is exhausted.
    monkeypatch.setenv("RONIN_AI_PROVIDER_ORDER", "gemini")
    monkeypatch.setenv("RONIN_AI_MAX_RETRIES", "0")
    layer = ai.generate_initial("Why do people feel lonely in crowded cities?")
    assert len(layer.branches) == 5
