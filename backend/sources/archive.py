"""Wayback Machine: find the closest archived snapshot of pages the other providers surfaced."""
import httpx

from . import Found

AVAILABLE_URL = "https://archive.org/wayback/available"


def snapshots(urls: list[str], *, transport: httpx.BaseTransport | None = None) -> list[Found]:
    found = []
    with httpx.Client(timeout=20, transport=transport) as client:
        for url in urls[:20]:
            try:
                response = client.get(AVAILABLE_URL, params={"url": url})
                closest = response.json().get("archived_snapshots", {}).get("closest") or {}
            except (httpx.HTTPError, ValueError):
                continue
            if not closest.get("available") or not closest.get("url"):
                continue
            stamp = str(closest.get("timestamp", ""))
            when = f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}" if len(stamp) >= 8 else None
            found.append(Found(f"Archived: {url}", closest["url"], "archive", "Internet Archive", when, url))
    return found
