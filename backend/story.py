"""The story file: one markdown dossier per rabbit hole, the editorial source of truth. The graph is compiled from it.

Format (see docs/superpowers/specs/2026-10-25-authored-rabbit-holes-design.md): front-matter, then
## Hook, ## Entry, ## Descent, ## Leap, ## Exit. Discoveries are `### title` blocks with evidence/why/check fields,
body text and a `sources:` list. Parsing is pure: strings in, dataclasses out, errors carry a 1-based line number.
"""
import re
from dataclasses import dataclass, field
from datetime import date

EVIDENCE = ("fact", "claim", "interpretation", "speculation", "open")
MEDIUMS = ("video", "page", "archive", "reddit")
SECTIONS = ("Hook", "Entry", "Descent", "Leap", "Exit")
FRONT_KEYS = ("title", "slug", "published", "territory", "drafted_by", "prompt")
SOURCE_LINE = re.compile(r"^- \[(?P<title>.+?)\]\((?P<url>\S+)\)(?P<rest>.*)$")


@dataclass
class SourceRef:
    title: str
    url: str
    medium: str
    creator: str | None = None
    date: str | None = None


@dataclass
class Discovery:
    title: str
    evidence: str
    why: str
    body: str
    sources: list[SourceRef] = field(default_factory=list)
    check: str | None = None


@dataclass
class Story:
    slug: str
    title: str
    hook: str
    entry: Discovery
    descent: list[Discovery]
    leap: Discovery
    known: str
    open: str
    published: date | None = None
    territory: str | None = None
    drafted_by: str | None = None
    prompt: str | None = None
    note: str | None = None


class StoryError(ValueError):
    def __init__(self, line: int, message: str):
        super().__init__(f"line {line}: {message}")
        self.line = line


def _iso(value: str, line: int) -> str:
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise StoryError(line, f"invalid date '{value}', use YYYY-MM-DD") from None


def _source(text: str, line: int) -> SourceRef:
    match = SOURCE_LINE.match(text)
    if not match:
        raise StoryError(line, "a source is '- [title](url) · medium · creator · date'")
    url = match["url"]
    if not url.startswith(("https://", "http://")):
        raise StoryError(line, f"source URL must be http(s): {url}")
    parts = [part.strip() for part in match["rest"].split("·")][1:]
    if not parts or parts[0] not in MEDIUMS:
        raise StoryError(line, f"unknown medium '{parts[0] if parts else ''}', use one of {', '.join(MEDIUMS)}")
    creator = parts[1] if len(parts) > 1 and parts[1] else None
    when = _iso(parts[2], line) if len(parts) > 2 and parts[2] else None
    return SourceRef(match["title"].strip(), url, parts[0], creator, when)


class _Draft:
    """A discovery while its lines are still being read."""

    def __init__(self, title: str, line: int):
        self.title, self.line = title, line
        self.evidence: str | None = None
        self.why: str | None = None
        self.check: str | None = None
        self.body: list[str] = []
        self.sources: list[SourceRef] = []
        self.in_sources = False

    def finish(self) -> Discovery:
        if not self.title:
            raise StoryError(self.line, "a discovery needs a title")
        if self.evidence is None:
            raise StoryError(self.line, f"'{self.title}' is missing evidence:")
        if not self.why:
            raise StoryError(self.line, f"'{self.title}' is missing why:")
        if self.evidence in ("fact", "claim") and not self.sources:
            raise StoryError(self.line, f"'{self.title}' is a {self.evidence} and needs a source")
        if self.evidence == "fact" and all(source.medium == "reddit" for source in self.sources):
            raise StoryError(self.line, f"'{self.title}' cites only Reddit: an anonymous anecdote is a claim, not a fact")
        return Discovery(self.title, self.evidence, self.why, "\n".join(self.body), self.sources, self.check)


def parse_story(text: str, slug: str) -> Story:
    lines = text.lstrip("﻿").replace("\r\n", "\n").split("\n")
    if not lines or lines[0].strip() != "---":
        raise StoryError(1, "a story starts with '---' front-matter")
    front: dict[str, tuple[str, int]] = {}
    index = 1
    while index < len(lines) and lines[index].strip() != "---":
        number, raw = index + 1, lines[index].strip()
        index += 1
        if not raw:
            continue
        key, sep, value = raw.partition(":")
        if not sep or key.strip() not in FRONT_KEYS:
            raise StoryError(number, f"unknown front-matter line '{raw}'")
        front[key.strip()] = (value.strip(), number)
    if index >= len(lines):
        raise StoryError(len(lines), "front-matter is not closed with '---'")
    for key in ("title", "slug"):
        if not front.get(key, ("", 0))[0]:
            raise StoryError(index + 1, f"front-matter needs {key}:")
    story_slug, slug_line = front["slug"]
    if not re.fullmatch(r"[a-z0-9-]+", story_slug) or story_slug != slug:
        raise StoryError(slug_line, f"slug must match the file name '{slug}' and use a-z, 0-9 and -")
    published = None
    if "published" in front and front["published"][0]:
        published = date.fromisoformat(_iso(*front["published"]))

    note = None
    section_index = -1
    hook: list[str] = []
    groups: dict[str, list[tuple[Discovery, int]]] = {"Entry": [], "Descent": [], "Leap": []}
    exit_fields: dict[str, str] = {}
    current: _Draft | None = None

    def close() -> None:
        nonlocal current
        if current is not None:
            groups[SECTIONS[section_index]].append((current.finish(), current.line))
            current = None

    for offset, raw in enumerate(lines[index + 1:], start=index + 2):
        line = raw.strip()
        if line.startswith("<!--") and line.endswith("-->"):
            if note is None and section_index < 0:
                note = line[4:-3].strip() or None
            continue
        if line.startswith("## "):
            close()
            expected = SECTIONS[section_index + 1] if section_index + 1 < len(SECTIONS) else None
            if line[3:].strip() != expected:
                raise StoryError(offset, f"expected section '## {expected}', found '{line}'" if expected else f"unexpected section '{line}' after Exit")
            section_index += 1
            continue
        if not line:
            continue
        if section_index < 0:
            raise StoryError(offset, "text before '## Hook'")
        section = SECTIONS[section_index]
        if section == "Hook":
            hook.append(line)
        elif section == "Exit":
            key, sep, value = line.partition(":")
            if not sep or key not in ("known", "open"):
                raise StoryError(offset, "Exit holds 'known:' and 'open:' lines")
            exit_fields[key] = value.strip()
        elif line.startswith("### "):
            close()
            count = len(groups[section]) + 1
            if section in ("Entry", "Leap") and count > 1:
                raise StoryError(offset, f"{section} holds exactly one discovery")
            if section == "Descent" and count > 6:
                raise StoryError(offset, "Descent holds 1-6 discoveries")
            current = _Draft(line[4:].strip(), offset)
        elif current is None:
            raise StoryError(offset, f"text in {section} before its '### ' discovery")
        elif current.in_sources:
            current.sources.append(_source(line, offset))
        elif line == "sources:":
            current.in_sources = True
        elif current.body and line.startswith(("evidence:", "why:", "check:")):
            # Loud, not silent: a body line read as a field would replace the reframe or hide text as a private note.
            raise StoryError(offset, f"'{line.partition(':')[0]}:' lines go before the body text; rephrase a body line that starts this way")
        elif line.startswith("evidence:"):
            value = line.partition(":")[2].strip()
            if value not in EVIDENCE:
                raise StoryError(offset, f"unknown evidence '{value}', use one of {', '.join(EVIDENCE)}")
            current.evidence = value
        elif line.startswith("why:"):
            current.why = line.partition(":")[2].strip()
        elif line.startswith("check:"):
            current.check = line.partition(":")[2].strip() or None
        else:
            current.body.append(line)
    close()

    last = len(lines)
    if section_index < len(SECTIONS) - 1:
        raise StoryError(last, f"missing section: {SECTIONS[section_index + 1]}")
    if not hook:
        raise StoryError(last, "Hook needs its question")
    for section in ("Entry", "Descent", "Leap"):
        if not groups[section]:
            raise StoryError(last, f"{section} needs a discovery")
    if "known" not in exit_fields or "open" not in exit_fields:
        raise StoryError(last, "Exit needs 'known:' and 'open:'")
    return Story(
        slug=slug, title=front["title"][0], hook="\n".join(hook),
        entry=groups["Entry"][0][0], descent=[item for item, _line in groups["Descent"]], leap=groups["Leap"][0][0],
        known=exit_fields["known"], open=exit_fields["open"], published=published,
        territory=front.get("territory", ("", 0))[0] or None, drafted_by=front.get("drafted_by", ("", 0))[0] or None,
        prompt=front.get("prompt", ("", 0))[0] or None, note=note,
    )


def _render_discovery(item: Discovery) -> list[str]:
    lines = [f"### {item.title}", f"evidence: {item.evidence}", f"why: {item.why}"]
    if item.check:
        lines.append(f"check: {item.check}")
    if item.body:
        lines += item.body.split("\n")
    if item.sources:
        lines.append("sources:")
        for source in item.sources:
            extras = [source.medium, source.creator or "", source.date or ""]
            while extras and not extras[-1]:
                extras.pop()
            lines.append(f"- [{source.title}]({source.url}) · " + " · ".join(extras))
    return lines + [""]


def render_story(story: Story) -> str:
    front = {"title": story.title, "slug": story.slug, "published": story.published.isoformat() if story.published else None,
             "territory": story.territory, "drafted_by": story.drafted_by, "prompt": story.prompt}
    lines = ["---", *(f"{key}: {value}" for key, value in front.items() if value), "---"]
    if story.note:
        lines.append(f"<!-- {story.note} -->")
    lines += ["", "## Hook", *story.hook.split("\n"), "", "## Entry", *_render_discovery(story.entry), "## Descent"]
    for item in story.descent:
        lines += _render_discovery(item)
    lines += ["## Leap", *_render_discovery(story.leap), "## Exit", f"known: {story.known}", f"open: {story.open}", ""]
    return "\n".join(lines)
