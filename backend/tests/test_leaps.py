import pytest

from backend.leaps import ScoredPath, TrailNode, eligible_ids, score_paths, shortlist


def node(id: str, parent: str | None, explored: bool = True) -> TrailNode:
    return TrailNode(id=id, parent_id=parent, title=id.upper(), summary=f"About {id}.", domain=f"D-{id}", explored=explored)


def trail(**overrides: bool) -> dict[str, TrailNode]:
    """root r; first level a, b; a → a1 → a2; b → b1 (b1 unvisited unless overridden)."""
    spec = [("r", None), ("a", "r"), ("b", "r"), ("a1", "a"), ("a2", "a1"), ("b1", "b")]
    return {id: node(id, parent, overrides.get(id, id != "b1")) for id, parent in spec}


def balanced(nodes: dict[str, TrailNode], vectors: dict[str, list[float]]) -> tuple[dict, dict]:
    """Add an unvisited first-level node whose vector cancels the rest, so mean-centring changes nothing."""
    total = [sum(column) for column in zip(*vectors.values())]
    return {**nodes, "z": node("z", "r", explored=False)}, {**vectors, "z": [-x for x in total]}


def test_eligible_requires_visit_and_depth_two() -> None:
    assert eligible_ids(trail()) == ["a1", "a2"]
    assert eligible_ids(trail(b1=True)) == ["a1", "a2", "b1"]


def test_incoherent_hop_ranks_below_smooth_path() -> None:
    nodes = {n.id: n for n in [node("r", None), node("a", "r"), node("a1", "a"), node("b", "r"), node("b1", "b")]}
    vectors = {"r": [1, 0, 0], "a": [0.7, 0.7, 0], "a1": [0, 1, 0], "b": [0, 0, 1], "b1": [0, 1, 0]}
    scored = {p.node_id: p for p in score_paths(*balanced(nodes, vectors))}
    assert scored["a1"].end_distance == pytest.approx(scored["b1"].end_distance)
    assert scored["a1"].score > scored["b1"].score
    assert scored["b1"].weakest_hop < 0.2


def test_depth_alone_does_not_win() -> None:
    nodes = {n.id: n for n in [node("r", None), node("c", "r"), node("c1", "c"), node("c2", "c1"), node("d", "r"), node("d1", "d")]}
    vectors = {"r": [1, 0, 0], "c": [0.9, 0.44, 0], "c1": [0.7, 0.7, 0], "c2": [0.7, 0.7, 0], "d": [0.5, 0, 0.87], "d1": [0, 0, 1]}
    ranked = score_paths(*balanced(nodes, vectors))
    scored = {p.node_id: p for p in ranked}
    assert scored["c2"].score == pytest.approx(scored["c1"].score)
    assert ranked[0].node_id == "d1"


def test_shortlist_spreads_branches() -> None:
    scored = [
        ScoredPath("a1", ["r", "a", "a1"], 0.9, 0.9, 0.81),
        ScoredPath("a2", ["r", "a", "a1", "a2"], 0.8, 0.9, 0.72),
        ScoredPath("b1", ["r", "b", "b1"], 0.5, 0.9, 0.45),
    ]
    assert [p.node_id for p in shortlist(scored)] == ["a1", "b1", "a2"]
    assert [p.node_id for p in shortlist(scored, k=2)] == ["a1", "b1"]


def test_zero_vector_does_not_crash() -> None:
    vectors = {id: [0.3, 0.3, 0.3] for id in trail()}
    scored = score_paths(trail(), vectors)
    assert [p.score for p in scored] == [0.0, 0.0]
