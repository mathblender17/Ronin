import pytest

from backend.story import StoryError, parse_story, render_story

SLUG = "early-japanese-web"
VALID = """---
title: The forgotten worlds of the early Japanese internet
slug: early-japanese-web
published: 2026-11-02
territory: Internet archaeology
drafted_by: deepseek/deepseek-flash
prompt: draft-v1
---
<!-- skipped: reddit: no key -->

## Hook
How can a whole digital world vanish while pieces of it survive?

## Entry
### A Geocities Japan homepage, still mirrored
evidence: fact
why: Where the trail starts.
check: verify before publishing
A fan page for a game nobody remembers.
sources:
- [Wayback capture](https://web.archive.org/web/2003/http://example.jp/) · archive · Internet Archive · 2003-05-01

## Descent
### The guestbook that kept writing back
evidence: claim
why: The homepage's guestbook is where its visitors left traces.
Hundreds of signatures, some from years after the site went dark.
sources:
- [A thread about it](https://www.reddit.com/r/lostmedia/comments/abc/) · reddit · u/someone · 2019-02-03
- [A video essay](https://www.youtube.com/watch?v=xyz) · video

### Mirrors made by strangers
evidence: interpretation
why: The signatures point to people copying the site.
Nobody asked them to.
sources:

## Leap
### The internet keeps what nobody owns
evidence: interpretation
why: Abandoned places survive because strangers adopt them.
A pattern that repeats far beyond Japan.
sources:
- [An essay](https://example.org/essay) · page · Example Org

## Exit
known: The site existed and was mirrored.
open: Who kept signing the guestbook?
"""


def line_of(text: str, needle: str) -> int:
    return next(i for i, line in enumerate(text.split("\n"), start=1) if needle in line)


def test_valid_story_round_trips() -> None:
    story = parse_story(VALID, SLUG)
    assert len(story.descent) == 2
    assert story.leap.evidence == "interpretation"
    assert story.entry.sources[0].medium == "archive"
    assert story.entry.sources[0].date == "2003-05-01"
    assert story.note == "skipped: reddit: no key"
    assert parse_story(render_story(story), SLUG) == story


def test_crlf_and_bom_parse_the_same() -> None:
    assert parse_story("﻿" + VALID.replace("\n", "\r\n"), SLUG) == parse_story(VALID, SLUG)


def test_missing_sections_are_named() -> None:
    text = VALID.split("## Leap")[0]
    with pytest.raises(StoryError) as err:
        parse_story(text, SLUG)
    assert "missing section: Leap" in str(err.value)


CASES = [
    ("renamed leap", lambda t: t.replace("## Leap", "## Leaping"), "## Leaping", "expected section"),
    ("out of order", lambda t: t.replace("## Entry", "## Descent", 1), "## Descent", "expected section"),
    ("two entries", lambda t: t.replace("## Descent\n", "### Second entry\nevidence: open\nwhy: x\n\n## Descent\n"), "### Second entry", "Entry holds exactly one discovery"),
    ("seven descents", lambda t: t.replace("## Leap", "".join(f"### Extra {i}\nevidence: open\nwhy: x\n\n" for i in range(5)) + "## Leap"), "### Extra 4", "Descent holds 1-6"),
    ("bad evidence", lambda t: t.replace("evidence: fact", "evidence: rumour"), "evidence: rumour", "unknown evidence"),
    ("unsourced fact", lambda t: t.replace("evidence: interpretation\nwhy: The signatures", "evidence: fact\nwhy: The signatures"), "### Mirrors made by strangers", "needs a source"),
    ("ftp url", lambda t: t.replace("(https://example.org/essay)", "(ftp://a)"), "(ftp://a)", "http(s)"),
    ("bad medium", lambda t: t.replace("· page ·", "· tv ·"), "· tv ·", "unknown medium"),
    ("slug mismatch", lambda t: t.replace("slug: early-japanese-web", "slug: other"), "slug: other", "slug must match"),
    ("bad date", lambda t: t.replace("published: 2026-11-02", "published: 2026-13-40"), "published: 2026-13-40", "invalid date"),
]


@pytest.mark.parametrize(("name", "mutate", "needle", "fragment"), CASES, ids=[c[0] for c in CASES])
def test_rule_violation_reports_line(name, mutate, needle, fragment) -> None:
    text = mutate(VALID)
    with pytest.raises(StoryError) as err:
        parse_story(text, SLUG)
    assert fragment in str(err.value)
    assert err.value.line == line_of(text, needle)
