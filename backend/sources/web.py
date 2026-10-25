"""Web discovery through Gemini's Google Search grounding.

Grounding links are short-lived Google redirect URLs, so each one is resolved to its final address before it is kept.
"""
import os

import httpx

from . import Found, SourceUnavailable


def _generate(query: str):
    from google.genai import types

    from ..ai import _client, _model

    client = _client()
    try:
        return client.models.generate_content(
            model=_model(), contents=f"Search the web for primary sources, archives and first-hand accounts about: {query}",
            config=types.GenerateContentConfig(tools=[types.Tool(google_search=types.GoogleSearch())]),
        )
    finally:
        client.close()


def _resolve(client: httpx.Client, uri: str) -> str | None:
    try:
        response = client.head(uri)
        if response.status_code == 405:
            response = client.get(uri)
    except httpx.HTTPError:
        return None
    return str(response.url) if response.status_code < 400 else None


def search(query: str, *, limit: int = 8, transport: httpx.BaseTransport | None = None, generate=None) -> list[Found]:
    if not os.getenv("GEMINI_API_KEY", "").strip():
        raise SourceUnavailable("no key")
    response = (generate or _generate)(query)
    try:
        metadata = response.candidates[0].grounding_metadata
        chunks = list(getattr(metadata, "grounding_chunks", None) or [])
    except (AttributeError, IndexError, TypeError):
        return []
    found = []
    with httpx.Client(timeout=15, follow_redirects=True, transport=transport) as client:
        for chunk in chunks[:limit]:
            web = getattr(chunk, "web", None)
            uri, title = str(getattr(web, "uri", "") or ""), str(getattr(web, "title", "") or "")
            if not uri.startswith(("https://", "http://")):
                continue
            final = _resolve(client, uri)
            if final is None:
                continue
            host = final.split("//", 1)[-1].split("/", 1)[0].removeprefix("www.")
            found.append(Found(title or host, final, "page", host, None, ""))
    return found
