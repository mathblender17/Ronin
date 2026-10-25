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


def test_web_resolves_redirects_and_drops_dead(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from backend.sources import web

    monkeypatch.setenv("GEMINI_API_KEY", "g")
    chunks = [SimpleNamespace(web=SimpleNamespace(uri=f"https://vertexaisearch.cloud.google.com/grounding-api-redirect/{n}", title=t))
              for n, t in (("live", "example.org"), ("dead", "dead.example"))]
    response = SimpleNamespace(candidates=[SimpleNamespace(grounding_metadata=SimpleNamespace(grounding_chunks=chunks))])

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/live"):
            return httpx.Response(302, headers={"location": "https://www.example.org/page"})
        if request.url.host == "www.example.org":
            return httpx.Response(200)
        return httpx.Response(500)

    found = web.search("q", transport=httpx.MockTransport(handler), generate=lambda _query: response)
    assert found == [Found("example.org", "https://www.example.org/page", "page", "example.org", None, "")]


def test_archive_maps_closest_snapshot() -> None:
    from backend.sources import archive

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"archived_snapshots": {"closest": {
            "available": True, "url": "http://web.archive.org/web/20030501123000/http://example.jp/", "timestamp": "20030501123000",
        }}})

    found = archive.snapshots(["http://example.jp/"], transport=httpx.MockTransport(handler))
    assert found[0].medium == "archive" and found[0].date == "2003-05-01" and found[0].creator == "Internet Archive"
    assert found[0].url.startswith("http://web.archive.org/web/2003")


def test_search_all_dedupes_caps_and_notes_skips(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.sources import archive, search_all

    monkeypatch.setattr(archive, "snapshots", lambda urls, **_kw: [])
    youtube_calls = []

    def no_youtube(query):
        youtube_calls.append(query)
        raise SourceUnavailable("no key")

    page = Found("A page", "https://example.org/a", "page", "example.org", None, "")
    providers = {"web": lambda query: [page, page], "youtube": no_youtube}
    finds, notes = search_all(["q1", "q2", "q3"], providers=providers)
    assert [f.url for f in finds] == ["https://example.org/a"]
    assert notes == ["youtube: no key"] and len(youtube_calls) == 1
    other = Found("B", "https://example.org/b", "page", None, None, "")
    finds, _ = search_all(["q"], providers={"web": lambda query: [page, other]}, cap=1)
    assert len(finds) == 1


def test_search_all_skips_a_provider_that_crashes(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.sources import archive, search_all

    monkeypatch.setattr(archive, "snapshots", lambda urls, **_kw: [])

    def gemini_quota(query):
        raise RuntimeError("429 RESOURCE_EXHAUSTED")  # stands in for google.genai.errors.APIError

    page = Found("A page", "https://example.org/a", "page", "example.org", None, "")
    finds, notes = search_all(["q1", "q2"], providers={"web": gemini_quota, "youtube": lambda query: [page]})
    assert [f.url for f in finds] == ["https://example.org/a"]
    assert notes == ["web: RuntimeError"]
