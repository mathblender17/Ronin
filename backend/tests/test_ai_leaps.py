import pytest
from pydantic import ValidationError

from backend import ai
from backend.ai import clean_waypoints
from backend.schemas import LeapCopy, LeapCopyLayer


def test_clean_waypoints_drops_invented_titles() -> None:
    assert clean_waypoints(["Made up", "Status  games"], ["Status games", "Rank signals"]) == ["Status games"]


def test_clean_waypoints_falls_back_to_middle() -> None:
    assert clean_waypoints(["Nope"], ["A", "B", "C"]) == ["B"]


def test_leap_copy_rejects_blank_hook() -> None:
    with pytest.raises(ValidationError):
        LeapCopy(index=0, hook="   ", reframe="ok", waypoints=[])


def test_leap_copy_keeps_overlong_text_for_the_user_to_edit() -> None:
    # Live Gemini wrote a 26-word reframe; rejecting it threw away a usable leap.
    leap = LeapCopy(index=0, hook=" ".join(["w"] * 13), reframe=" ".join(["w"] * 26), waypoints=[])
    assert len(leap.reframe.split()) == 26


def test_generate_leap_copy_filters_waypoints(monkeypatch: pytest.MonkeyPatch) -> None:
    prompts: list[str] = []

    def fake_structured(prompt, schema):
        prompts.append(prompt)
        return LeapCopyLayer(leaps=[LeapCopy(index=0, hook="How rumours became railways", reframe="Both move trust.", waypoints=["Invented"])])

    monkeypatch.setattr(ai, "_structured", fake_structured)
    path = [("Why do rumours spread?", "Start."), ("Gossip networks", "Rumours ride gossip."), ("Trust ledgers", "Gossip tracks trust."), ("Railway timetables", "Timetables standardised trust.")]
    copy = ai.generate_leap_copy("Why do rumours spread?", [path])
    assert copy[0].waypoints == ["Trust ledgers"]
    for title, reason in path:
        assert title in prompts[0] and reason in prompts[0]


def test_embed_texts_without_key_raises_service_error() -> None:
    with pytest.raises(ai.AIServiceError):
        ai.embed_texts(["anything"])
