"""Leap evaluation: score every saved trail and write a table for a human to label WHAT / ok / nonsense.

It spends Gemini embedding quota, so it refuses to run unless RONIN_LIVE_BENCHMARK=1.
The ship bar: at least half of the #1 picks are WHAT or ok, and none are nonsense.

Usage:
  RONIN_LIVE_BENCHMARK=1 python -m backend.benchmark.leaps --out spike/out/leaps.md
"""

import argparse
import os
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backend import ai, leaps
from backend.database import SessionLocal
from backend.models import RabbitHole


def report_markdown(rows: list[tuple[str, list[tuple[list[str], leaps.ScoredPath]]]]) -> str:
    lines = ["# Leap evaluation", "", "Label each row WHAT, ok, or nonsense.", ""]
    for question, picks in rows:
        lines += [f"## {question}", ""]
        if not picks:
            lines += ["no eligible node", ""]
            continue
        lines += ["| # | end_distance | weakest_hop | score | path | label |", "|---|---|---|---|---|---|"]
        lines += [
            f"| {rank} | {p.end_distance:.3f} | {p.weakest_hop:.3f} | {p.score:.3f} | {' → '.join(titles)} |  |"
            for rank, (titles, p) in enumerate(picks, start=1)
        ]
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Score every saved trail's leaps for human labelling.")
    parser.add_argument("--out", default="spike/out/leaps.md")
    args = parser.parse_args()
    if os.getenv("RONIN_LIVE_BENCHMARK") != "1":
        raise SystemExit("Refusing to run: set RONIN_LIVE_BENCHMARK=1 to spend Gemini embedding quota deliberately.")
    rows = []
    with SessionLocal() as db:
        for hole in db.scalars(select(RabbitHole).options(selectinload(RabbitHole.nodes))):
            nodes = {
                n.id: leaps.TrailNode(n.id, n.parent_id, n.title, n.summary, n.domain, n.explored_at is not None)
                for n in hole.nodes
            }
            picks = []
            if leaps.eligible_ids(nodes):
                ids = list(nodes)
                vectors = dict(zip(ids, ai.embed_texts([leaps.embed_text(nodes[id]) for id in ids])))
                picks = [([nodes[id].title for id in p.path], p) for p in leaps.shortlist(leaps.score_paths(nodes, vectors))]
            rows.append((hole.question, picks))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report_markdown(rows), encoding="utf-8")
    print(f"Wrote {out} ({len(rows)} trails)")


if __name__ == "__main__":
    main()
