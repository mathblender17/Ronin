import html
import os

import httpx

from . import Found, SourceUnavailable

SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"


def search(query: str, *, limit: int = 8, transport: httpx.BaseTransport | None = None) -> list[Found]:
    key = os.getenv("YOUTUBE_API_KEY", "").strip()
    if not key:
        raise SourceUnavailable("no key")
    params = {"part": "snippet", "type": "video", "maxResults": limit, "q": query, "key": key}
    with httpx.Client(timeout=20, transport=transport) as client:
        response = client.get(SEARCH_URL, params=params)
    if response.status_code != 200:
        raise SourceUnavailable(f"status {response.status_code}")
    found = []
    for item in response.json().get("items", []):
        video_id, snippet = item.get("id", {}).get("videoId"), item.get("snippet", {})
        if not video_id:
            continue
        found.append(Found(
            title=html.unescape(snippet.get("title", "")), url=f"https://www.youtube.com/watch?v={video_id}", medium="video",
            creator=snippet.get("channelTitle") or None, date=(snippet.get("publishedAt") or "")[:10] or None,
            snippet=html.unescape(snippet.get("description", ""))[:300],
        ))
    return found
