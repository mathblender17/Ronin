import sqlite3
from collections.abc import Generator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend import studio
from backend.database import Base, add_missing_columns
from backend.models import Edge, Node, RabbitHole, Source
from backend.story import parse_story
from backend.tests.test_story import SLUG, VALID

STAGES = ["hook", "entry", "descent", "descent", "leap", "exit"]


@pytest.fixture()
def db() -> Generator[Session, None, None]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    yield session
    session.close()
    engine.dispose()


def story_b():
    return parse_story(VALID.replace(f"slug: {SLUG}", "slug: other-story"), "other-story")


def chain(db: Session, hole: RabbitHole) -> list[Node]:
    nodes = {node.parent_id: node for node in db.scalars(select(Node).where(Node.rabbit_hole_id == hole.id))}
    ordered, parent = [], None
    while parent in nodes:
        ordered.append(nodes[parent])
        parent = ordered[-1].id
    return ordered


def test_import_builds_one_chain(db: Session) -> None:
    hole = studio.import_story(db, parse_story(VALID, SLUG))
    nodes = chain(db, hole)
    assert [node.stage for node in nodes] == STAGES
    assert len(db.scalars(select(Node)).all()) == 6
    assert len(db.scalars(select(Edge)).all()) == 5
    assert hole.slug == SLUG and hole.question.startswith("How can a whole digital world")
    assert nodes[1].evidence == "fact" and nodes[1].check_note == "verify before publishing"
    assert nodes[-1].summary == "The site existed and was mirrored."
    assert nodes[1].sources[0].medium == "archive" and nodes[1].sources[0].published == "2003-05-01"


def test_reimport_replaces_not_duplicates(db: Session) -> None:
    studio.import_story(db, parse_story(VALID, SLUG))
    studio.import_story(db, parse_story(VALID, SLUG))
    assert len(db.scalars(select(RabbitHole).where(RabbitHole.slug == SLUG)).all()) == 1
    assert len(db.scalars(select(Node)).all()) == 6


def test_shared_source_survives_other_story_reimport(db: Session) -> None:
    studio.import_story(db, parse_story(VALID, SLUG))
    other = studio.import_story(db, story_b())
    studio.import_story(db, parse_story(VALID, SLUG))
    url = "https://web.archive.org/web/2003/http://example.jp/"
    source = db.scalars(select(Source).where(Source.url == url)).one()
    assert any(node.rabbit_hole_id == other.id for node in source.nodes)


def test_add_missing_columns_backfills_old_db(tmp_path: Path) -> None:
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as raw:
        raw.execute("CREATE TABLE nodes (id VARCHAR(36) PRIMARY KEY, title VARCHAR(180))")
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    add_missing_columns(engine)
    engine.dispose()
    with sqlite3.connect(path) as raw:
        columns = {row[1] for row in raw.execute("PRAGMA table_info(nodes)")}
    assert {"stage", "evidence", "check_note"} <= columns


def test_cli_reports_story_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "bad.md").write_text("---\ntitle: x\nslug: bad\n---\n## Hook\nq\n", encoding="utf-8")
    assert studio.main(["import", "bad"], stories_dir=tmp_path) == 1
    assert "bad.md: line" in capsys.readouterr().out
