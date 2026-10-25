"""Leap scoring: find the root → visited-node path that ends farthest from where it began while every step stays coherent.

Adapted from spike/drift.py for trees. No AI calls here; vectors come in from the caller.
"""
import math
from dataclasses import dataclass


@dataclass(frozen=True)
class TrailNode:
    id: str
    parent_id: str | None
    title: str
    summary: str
    domain: str
    explored: bool


@dataclass(frozen=True)
class ScoredPath:
    node_id: str
    path: list[str]  # node ids, root first
    end_distance: float
    weakest_hop: float
    score: float


def embed_text(node: TrailNode) -> str:
    return f"{node.title}. {node.summary}"


def path_to(nodes: dict[str, TrailNode], node_id: str) -> list[str]:
    path = [node_id]
    while (parent := nodes[path[-1]].parent_id) is not None:
        path.append(parent)
    return path[::-1]


def eligible_ids(nodes: dict[str, TrailNode]) -> list[str]:
    # path_to includes the root, so depth 2 means a path of three nodes.
    return [id for id, node in nodes.items() if node.explored and len(path_to(nodes, id)) >= 3]


def _cos(a: list[float], b: list[float]) -> float:
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return sum(x * y for x, y in zip(a, b)) / norm if norm else 0.0


def score_paths(nodes: dict[str, TrailNode], vectors: dict[str, list[float]]) -> list[ScoredPath]:
    # Every node in a trail shares the trail's topic; subtract the mean so that shared direction does not swamp distances.
    mean = [sum(column) / len(vectors) for column in zip(*vectors.values())]
    centred = {id: [x - m for x, m in zip(v, mean)] for id, v in vectors.items()}
    scored = []
    for id in eligible_ids(nodes):
        path = path_to(nodes, id)
        end_distance = 1 - _cos(centred[path[0]], centred[id])
        weakest_hop = min(_cos(centred[a], centred[b]) for a, b in zip(path, path[1:]))
        # No depth term: one incoherent hop sinks the leap, and depth alone is not surprise.
        scored.append(ScoredPath(id, path, end_distance, weakest_hop, end_distance * weakest_hop))
    return sorted(scored, key=lambda p: p.score, reverse=True)


def shortlist(scored: list[ScoredPath], k: int = 3) -> list[ScoredPath]:
    picked: list[ScoredPath] = []
    branches: set[str] = set()
    for path in scored:
        if len(picked) < k and path.path[1] not in branches:
            picked.append(path)
            branches.add(path.path[1])
    for path in scored:
        if len(picked) < k and path not in picked:
            picked.append(path)
    return picked
