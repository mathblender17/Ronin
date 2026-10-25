"""Reddit discovery through an approved OAuth app (read-only).

Policy: keep the permalink, title and author only. Post text is never read, stored or sent to a model.
"""
import os
from datetime import datetime, timezone

import httpx

from . import Found, SourceUnavailable

TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
SEARCH_URL = "https://oauth.reddit.com/search"
USER_AGENT = "ronin-studio/1.0 (local research tool)"


def search(query: str, *, limit: int = 8, transport: httpx.BaseTransport | None = None) -> list[Found]:
    client_id, secret = os.getenv("REDDIT_CLIENT_ID", "").strip(), os.getenv("REDDIT_CLIENT_SECRET", "").strip()
    if not client_id or not secret:
        raise SourceUnavailable("no key")
    headers = {"User-Agent": USER_AGENT}
    with httpx.Client(timeout=20, transport=transport, headers=headers) as client:
        token = client.post(TOKEN_URL, data={"grant_type": "client_credentials"}, auth=(client_id, secret))
        if token.status_code != 200:
            raise SourceUnavailable(f"status {token.status_code}")
        response = client.get(SEARCH_URL, params={"q": query, "limit": limit, "sort": "relevance", "type": "link"},
                              headers={"Authorization": f"bearer {token.json()['access_token']}"})
    if response.status_code != 200:
        raise SourceUnavailable(f"status {response.status_code}")
    found = []
    for child in response.json().get("data", {}).get("children", []):
        post = child.get("data", {})
        if not post.get("permalink"):
            continue
        created = post.get("created_utc")
        found.append(Found(
            title=post.get("title", ""), url="https://www.reddit.com" + post["permalink"], medium="reddit",
            creator=f"u/{post['author']}" if post.get("author") else None,
            date=datetime.fromtimestamp(created, timezone.utc).date().isoformat() if created else None,
            snippet=f"r/{post.get('subreddit', '')}",
        ))
    return found
