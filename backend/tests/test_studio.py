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
from backend.sources import Found
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


def write_story(directory: Path, slug: str, published: str | None, extra: str = "") -> None:
    text = VALID.replace(f"slug: {SLUG}", f"slug: {slug}")
    text = text.replace("published: 2026-11-02\n", f"published: {published}\n" if published else "")
    (directory / f"{slug}.md").write_text(text + extra, encoding="utf-8")


def test_publish_excludes_drafts_and_future(tmp_path: Path) -> None:
    from datetime import date

    write_story(tmp_path, "live", "2026-10-01")
    write_story(tmp_path, "draft", None)
    write_story(tmp_path, "later", "2026-12-01")
    out = tmp_path / "showcase.db"
    assert studio.publish(tmp_path, out, date(2026, 10, 26)) == ["live"]
    with sqlite3.connect(out) as raw:
        assert raw.execute("SELECT slug FROM rabbit_holes").fetchall() == [("live",)]


def test_publish_strips_private_fields(tmp_path: Path) -> None:
    from datetime import date

    write_story(tmp_path, "live", "2026-10-01")
    out = tmp_path / "showcase.db"
    studio.publish(tmp_path, out, date(2026, 10, 26))
    private = ("verify before publishing", "skipped: reddit: no key", "deepseek/deepseek-flash", "draft-v1")
    with sqlite3.connect(out) as raw:
        assert raw.execute("SELECT COUNT(*) FROM nodes WHERE check_note IS NOT NULL").fetchone() == (0,)
        for (table,) in raw.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
            for row in raw.execute(f"SELECT * FROM {table}"):
                for value in row:
                    assert not any(secret in str(value) for secret in private), (table, value)


def test_publish_failure_keeps_old_snapshot(tmp_path: Path) -> None:
    from datetime import date

    from backend.story import StoryError

    out = tmp_path / "showcase.db"
    out.write_bytes(b"old snapshot")
    write_story(tmp_path, "live", "2026-10-01")
    (tmp_path / "broken.md").write_text("not a story", encoding="utf-8")
    with pytest.raises(StoryError):
        studio.publish(tmp_path, out, date(2026, 10, 26))
    assert out.read_bytes() == b"old snapshot"


def fake_plan():
    from backend.schemas import PlannedQuery, QueryPlan

    return QueryPlan(queries=[PlannedQuery(text=f"q{i}", angle="origin") for i in range(4)])


def fake_draft(entry_sources=(1,), descent_evidence="claim", descent_sources=(1,)):
    from backend.schemas import DraftDiscovery, DraftStory

    def item(title, evidence, sources):
        return DraftDiscovery(title=title, evidence=evidence, why=f"Why {title}.", body=f"Body of {title}.", sources=list(sources))

    return DraftStory(
        title="A forum that vanished", hook="Where did everyone go?",
        entry=item("The last post", "fact", entry_sources), descent=[item("A strange mirror", descent_evidence, descent_sources)],
        leap=item("Nobody owns the past", "interpretation", ()), known="It existed.", open="Who mirrored it?",
    )


FINDS = [Found("A thread", "https://www.reddit.com/r/x/comments/1/", "reddit", "u/a", "2019-01-01", "r/x")]


@pytest.fixture()
def drafting(monkeypatch: pytest.MonkeyPatch) -> dict:
    from backend import ai

    calls: dict = {"write": []}
    monkeypatch.setattr(ai, "plan_queries", lambda seed, only=None: fake_plan())

    def write(seed, finds, only=None):
        calls["write"].append(only)
        return calls.get("draft") or fake_draft()

    monkeypatch.setattr(ai, "write_draft", write)
    monkeypatch.setattr(ai, "last_provider_model", lambda: "deepseek/deepseek-flash")
    return calls


def test_draft_writes_story_and_research(tmp_path: Path, drafting: dict) -> None:
    import json

    path = studio.draft("a vanished forum", "vanished", stories_dir=tmp_path, search=lambda queries: (FINDS, ["youtube: no key"]))
    story = parse_story(path.read_text(encoding="utf-8"), "vanished")
    assert story.drafted_by == "deepseek/deepseek-flash" and story.prompt == "draft-v1" and story.published is None
    assert story.note == "skipped: youtube: no key"
    assert story.entry.sources[0].url == FINDS[0].url and story.entry.check == "verify before publishing"
    assert story.entry.evidence == "claim"  # a fact cited only to Reddit is downgraded
    research = json.loads((tmp_path / ".research" / "vanished.json").read_text(encoding="utf-8"))
    assert research["finds"][0]["url"] == FINDS[0].url and research["skipped"] == ["youtube: no key"]


def test_invented_source_numbers_are_dropped_and_noted(tmp_path: Path, drafting: dict) -> None:
    drafting["draft"] = fake_draft(entry_sources=(1, 99))
    path = studio.draft("seed", "vanished", stories_dir=tmp_path, search=lambda queries: (FINDS, []))
    story = parse_story(path.read_text(encoding="utf-8"), "vanished")
    assert len(story.entry.sources) == 1
    assert "dropped 1" in story.note


def test_unsourced_fact_becomes_speculation(tmp_path: Path, drafting: dict) -> None:
    drafting["draft"] = fake_draft(descent_evidence="fact", descent_sources=())
    path = studio.draft("seed", "vanished", stories_dir=tmp_path, search=lambda queries: (FINDS, []))
    story = parse_story(path.read_text(encoding="utf-8"), "vanished")
    assert story.descent[0].evidence == "speculation"
    assert "needs a source" in story.descent[0].check


def test_draft_refuses_to_overwrite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from backend import ai

    (tmp_path / "vanished.md").write_text("mine", encoding="utf-8")
    monkeypatch.setattr(ai, "plan_queries", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not plan")))
    with pytest.raises(FileExistsError):
        studio.draft("seed", "vanished", stories_dir=tmp_path, search=lambda queries: (FINDS, []))
    assert (tmp_path / "vanished.md").read_text(encoding="utf-8") == "mine"


def test_redraft_reuses_finds_without_search(tmp_path: Path, drafting: dict) -> None:
    studio.draft("seed", "vanished", stories_dir=tmp_path, search=lambda queries: (FINDS, []))
    out = studio.redraft("vanished", model="kimi/kimi-k3.1-pro", out=tmp_path / "b.md", stories_dir=tmp_path)
    assert drafting["write"][-1] == ("kimi", "kimi-k3.1-pro")
    assert parse_story(out.read_text(encoding="utf-8"), "vanished").title == "A forum that vanished"


def test_publish_warns_about_unverified_live_stories(tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    write_story(tmp_path, "live", "2026-10-01")
    write_story(tmp_path, "draft", None)
    monkeypatch.setattr(studio, "SHOWCASE_DB", tmp_path / "showcase.db")
    assert studio.main(["publish"], stories_dir=tmp_path) == 0
    out = capsys.readouterr().out
    assert "live: 1 unchecked" in out and "draft" not in out.split("Warning")[-1]
