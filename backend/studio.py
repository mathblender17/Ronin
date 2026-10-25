"""Ronin Studio: the local newsroom. Compiles story files into trails.

Usage:
  python -m backend.studio import <slug>
  python -m backend.studio publish
"""
import argparse
import os
from dataclasses import replace
from datetime import date
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from . import ai
from .database import ROOT_DIR, Base, SessionLocal, add_missing_columns, engine
from .models import Edge, Node, RabbitHole, Source, utcnow
from .story import Discovery, SourceRef, Story, StoryError, parse_story

STORIES_DIR = ROOT_DIR / "stories"
SHOWCASE_DB = ROOT_DIR / "showcase" / "ronin.db"


def load_story(slug: str, stories_dir: Path = STORIES_DIR) -> Story:
    return parse_story((stories_dir / f"{slug}.md").read_text(encoding="utf-8"), slug)


def _source_rows(db: Session, refs: list[SourceRef]) -> list[Source]:
    rows = []
    for ref in refs:
        row = db.scalar(select(Source).where(Source.url == ref.url))
        if row is None:
            row = Source(id=str(uuid4()), url=ref.url, citation_text="")
            db.add(row)
        host = ref.url.split("//", 1)[-1].split("/", 1)[0].removeprefix("www.")
        row.title, row.medium, row.creator, row.published = ref.title[:300], ref.medium, ref.creator, ref.date
        row.publisher = (ref.creator or host)[:200]
        if row not in rows:
            rows.append(row)
    return rows


def import_story(db: Session, story: Story) -> RabbitHole:
    """Replace the trail for this slug with a single chain: Hook (root) → Entry → Descent… → Leap → Exit."""
    old = db.scalar(select(RabbitHole).where(RabbitHole.slug == story.slug))
    if old is not None:
        db.delete(old)
        db.flush()
    now = utcnow()
    hole = RabbitHole(
        id=str(uuid4()), question=story.hook[:500], title=story.title[:120], created_at=now, updated_at=now,
        slug=story.slug, published_at=story.published, territory=story.territory,
    )
    db.add(hole)
    domain = (story.territory or "Rabbit hole")[:100]

    def add(parent: Node | None, *, stage: str, title: str, summary: str, reason: str, question: str = "",
            evidence: str | None = None, check: str | None = None, sources: list[SourceRef] = ()) -> Node:
        node = Node(
            id=str(uuid4()), rabbit_hole_id=hole.id, parent_id=parent.id if parent else None,
            title=title[:180], title_key=ai.title_key(title)[:180], summary=summary, connection_reason=reason,
            exploration_question=question[:500], domain=domain, stage=stage, evidence=evidence, check_note=check,
            sources=_source_rows(db, list(sources)), created_at=utcnow(),
        )
        db.add(node)
        db.flush()
        if parent is not None:
            db.add(Edge(id=str(uuid4()), rabbit_hole_id=hole.id, parent_node_id=parent.id, child_node_id=node.id, relationship_note=reason))
        return node

    def discovery(parent: Node, stage: str, item: Discovery) -> Node:
        return add(parent, stage=stage, title=item.title, summary=item.body or item.why, reason=item.why,
                   evidence=item.evidence, check=item.check, sources=item.sources)

    node = add(None, stage="hook", title=story.title, summary=story.hook, reason="Where the rabbit hole opens.")
    node = discovery(node, "entry", story.entry)
    for item in story.descent:
        node = discovery(node, "descent", item)
    node = discovery(node, "leap", story.leap)
    add(node, stage="exit", title="What we know", summary=story.known, reason="Where the trail stands.", question=story.open)
    db.commit()
    return hole


def _public(story: Story) -> Story:
    """The publication allowlist: drop every author-only field before a story leaves the studio."""
    def clean(item: Discovery) -> Discovery:
        return replace(item, check=None)
    return replace(story, entry=clean(story.entry), descent=[clean(item) for item in story.descent], leap=clean(story.leap),
                   drafted_by=None, prompt=None, note=None)


def publish(stories_dir: Path, out_path: Path, today: date) -> list[str]:
    """Rebuild the public snapshot from published stories only, then swap it in atomically."""
    stories = []
    for path in sorted(stories_dir.glob("*.md")):
        try:
            stories.append(parse_story(path.read_text(encoding="utf-8"), path.stem))
        except StoryError as exc:
            exc.args = (f"{path.name}: {exc}",)
            raise
    live = [_public(story) for story in stories if story.published and story.published <= today]
    temp = out_path.with_name(out_path.name + ".tmp")
    temp.unlink(missing_ok=True)
    snapshot = create_engine(f"sqlite:///{temp.as_posix()}")
    try:
        Base.metadata.create_all(bind=snapshot)
        with sessionmaker(bind=snapshot, expire_on_commit=False)() as db:
            for story in live:
                import_story(db, story)
    finally:
        snapshot.dispose()
    os.replace(temp, out_path)
    return sorted(story.slug for story in live)


def main(argv: list[str] | None = None, stories_dir: Path = STORIES_DIR) -> int:
    parser = argparse.ArgumentParser(prog="python -m backend.studio", description="Ronin Studio: draft, import and publish rabbit holes.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("import", help="Compile one story file into the local database.").add_argument("slug")
    commands.add_parser("publish", help="Rebuild showcase/ronin.db from published stories only.")
    args = parser.parse_args(argv)
    slug = getattr(args, "slug", "*")
    try:
        if args.command == "import":
            story = load_story(args.slug, stories_dir)
            Base.metadata.create_all(bind=engine)
            add_missing_columns(engine)
            with SessionLocal() as db:
                import_story(db, story)
            print(f"Imported {args.slug}: {len(story.descent) + 2} discoveries")
        elif args.command == "publish":
            slugs = publish(stories_dir, SHOWCASE_DB, date.today())
            print(f"Published {len(slugs)} stories to showcase/ronin.db: {', '.join(slugs) or '(none)'}")
    except StoryError as exc:
        print(f"stories/{slug}.md: {exc}" if args.command == "import" else f"stories/{exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
