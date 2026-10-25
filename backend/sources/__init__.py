"""Research source adapters. Each one turns a search query into `Found` records with their provenance.

Sources supply material and leads; they never decide what is true. That is the author's job in the story file.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Found:
    title: str
    url: str
    medium: str  # video, page, archive, reddit
    creator: str | None
    date: str | None  # YYYY-MM-DD
    snippet: str


class SourceUnavailable(Exception):
    """The provider is not configured or refused the request; the search carries on without it."""


def search_all(queries: list[str], *, providers: dict | None = None, cap: int = 60) -> tuple[list[Found], list[str]]:
    """Run every query through every provider, then look up archived copies of the pages found.

    Returns (finds, notes): finds deduplicated by URL and capped; notes name each provider that was skipped, once.
    """

    from . import archive, reddit, web, youtube

    providers = providers if providers is not None else {"web": web.search, "youtube": youtube.search, "reddit": reddit.search}
    finds: list[Found] = []
    notes: list[str] = []
    skipped: set[str] = set()
    for query in queries:
        for name, provider in providers.items():
            if name in skipped:
                continue
            try:
                finds += provider(query)
            except SourceUnavailable as exc:
                skipped.add(name)
                notes.append(f"{name}: {exc}")
            except Exception as exc:  # any provider failure (HTTP, quota, bad JSON) skips that provider, never the draft
                skipped.add(name)
                notes.append(f"{name}: {type(exc).__name__}")
    finds += archive.snapshots([item.url for item in finds if item.medium == "page"])
    unique: dict[str, Found] = {}
    for item in finds:
        unique.setdefault(item.url, item)
    return list(unique.values())[:cap], notes
