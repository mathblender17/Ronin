import json

import httpx
import pytest

from backend.sources import Found, SourceUnavailable, reddit, youtube


def test_youtube_parses_videos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YOUTUBE_API_KEY", "yt-key")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json={"items": [{"id": {"videoId": "abc"}, "snippet": {
            "title": "Lost &amp; found", "channelTitle": "Archivist", "publishedAt": "2012-04-05T10:00:00Z", "description": "d" * 400,
        }}]})

    found = youtube.search("lost forum", transport=httpx.MockTransport(handler))
    assert found == [Found("Lost & found", "https://www.youtube.com/watch?v=abc", "video", "Archivist", "2012-04-05", "d" * 300)]
    assert seen["params"]["key"] == "yt-key" and seen["params"]["q"] == "lost forum"


def test_youtube_without_key_is_unavailable() -> None:
    with pytest.raises(SourceUnavailable):
        youtube.search("anything")


def test_reddit_keeps_permalink_and_drops_body(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REDDIT_CLIENT_ID", "id")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "secret")
    agents = []

    def handler(request: httpx.Request) -> httpx.Response:
        agents.append(request.headers.get("user-agent"))
        if request.url.path == "/api/v1/access_token":
            return httpx.Response(200, json={"access_token": "t"})
        assert request.headers["authorization"] == "bearer t"
        return httpx.Response(200, json={"data": {"children": [{"data": {
            "title": "Anyone remember this site?", "permalink": "/r/lostmedia/comments/x1/anyone/", "author": "digger",
            "created_utc": 1546300800, "subreddit": "lostmedia", "selftext": "SECRET BODY",
        }}]}})

    found = reddit.search("old site", transport=httpx.MockTransport(handler))
    assert found[0].url == "https://www.reddit.com/r/lostmedia/comments/x1/anyone/"
    assert found[0].creator == "u/digger" and found[0].date == "2019-01-01" and found[0].medium == "reddit"
    assert "SECRET BODY" not in repr(found)
    assert agents == [reddit.USER_AGENT, reddit.USER_AGENT]


def test_reddit_without_keys_is_unavailable() -> None:
    with pytest.raises(SourceUnavailable):
        reddit.search("anything")
