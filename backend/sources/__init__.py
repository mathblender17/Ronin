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
