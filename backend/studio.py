"""Ronin Studio: the local newsroom. Compiles story files into trails.

Usage:
  python -m backend.studio import <slug>
"""
import argparse
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import ai
from .database import ROOT_DIR, Base, SessionLocal, add_missing_columns, engine
from .models import Edge, Node, RabbitHole, Source, utcnow
from .story import Discovery, SourceRef, Story, StoryError, parse_story

STORIES_DIR = ROOT_DIR / "stories"


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


def main(argv: list[str] | None = None, stories_dir: Path = STORIES_DIR) -> int:
    parser = argparse.ArgumentParser(prog="python -m backend.studio", description="Ronin Studio: draft, import and publish rabbit holes.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("import", help="Compile one story file into the local database.").add_argument("slug")
    args = parser.parse_args(argv)
    try:
        if args.command == "import":
            story = load_story(args.slug, stories_dir)
            Base.metadata.create_all(bind=engine)
            add_missing_columns(engine)
            with SessionLocal() as db:
                import_story(db, story)
            print(f"Imported {args.slug}: {len(story.descent) + 2} discoveries")
    except StoryError as exc:
        print(f"stories/{args.slug}.md: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
