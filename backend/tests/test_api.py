from collections.abc import Generator
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend import ai
from backend.database import Base
from backend.main import app, get_db
from backend.schemas import GeneratedConcept, InitialLayer


@pytest.fixture()
def client() -> Generator[TestClient, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def concept(title: str, domain: str = "History") -> GeneratedConcept:
    return GeneratedConcept(
        title=title,
        summary=f"A concise explanation of {title.lower()} and the forces around it.",
        connection_reason=f"{title} offers a distinct way to understand the original question.",
        exploration_question=f"What shaped {title.lower()}?",
        domain=domain,
    )


def initial_layer() -> ai.LayerResult:
    concepts = [
        concept("Status games", "Psychology"),
        concept("Power and institutions", "Politics"),
        concept("Evolutionary roots", "Biology"),
        concept("Moral authority", "Philosophy"),
        concept("Economic dependence", "Economics"),
    ]
    sources = {ai.title_key(concepts[0].title): [{
        "title": "A real research page", "url": "https://example.org/research",
        "publisher": "example.org", "citation_text": "A grounded citation excerpt.",
    }], ai.title_key(concepts[1].title): [{
        "title": "A real research page", "url": "https://example.org/research",
        "publisher": "example.org", "citation_text": "A grounded citation excerpt.",
    }]}
    return ai.LayerResult(branches=concepts, root_summary="A question about motives, systems, and human relationships.", source_map=sources)


def test_create_persists_graph_metrics_and_grounded_sources(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ai, "generate_initial", lambda _question: initial_layer())
    response = client.post("/api/rabbit-holes", json={"question": "Why do humans seek power?"})
    assert response.status_code == 201
    graph = response.json()
    assert len(graph["nodes"]) == 6
    assert graph["metrics"]["node_count"] == 6
    assert graph["metrics"]["max_depth"] == 1
    assert graph["metrics"]["first_level_branches"] == 5
    assert graph["metrics"]["unique_sources"] == 1
    assert graph["metrics"]["domain_count"] == 5
    assert graph["metrics"]["explored_nodes"] == 1
    assert graph["metrics"]["most_explored_branch"] is None
    root = next(node for node in graph["nodes"] if node["parent_id"] is None)
    children = [node for node in graph["nodes"] if node["parent_id"] == root["id"]]
    assert len(children) == 5
    assert len({node["title"].casefold() for node in children}) == 5
    assert root["sources"] == []
    sourced_child_titles = {node["title"] for node in children if node["sources"]}
    assert sourced_child_titles == {"Status games", "Power and institutions"}
    assert all(node["sources"][0]["url"] == "https://example.org/research" for node in children if node["sources"])
    assert len(graph["edges"]) == 5
    assert {(edge["source"], edge["target"]) for edge in graph["edges"]} == {
        (root["id"], node["id"]) for node in children
    }
    assert all(edge["relationship_note"] for edge in graph["edges"])

    hole_id = graph["id"]
    saved = client.get(f"/api/rabbit-holes/{hole_id}").json()
    archive = client.get("/api/rabbit-holes").json()
    original_nodes = {node["id"]: node for node in graph["nodes"]}
    saved_nodes = {node["id"]: node for node in saved["nodes"]}
    assert saved_nodes.keys() == original_nodes.keys()
    for node_id, node in original_nodes.items():
        assert saved_nodes[node_id]["title"] == node["title"]
        assert saved_nodes[node_id]["parent_id"] == node["parent_id"]
        assert saved_nodes[node_id]["summary"] == node["summary"]
        assert [source["url"] for source in saved_nodes[node_id]["sources"]] == [source["url"] for source in node["sources"]]
    assert saved["edges"] == graph["edges"]
    assert archive[0]["node_count"] == 6
    assert archive[0]["first_level_branches"] == 5
    assert len(next(node for node in children if node["title"] == "Status games")["sources"]) == 1
    assert len(next(node for node in children if node["title"] == "Power and institutions")["sources"]) == 1
    assert graph["metrics"]["unique_sources"] == 1

    visited = client.post(f"/api/rabbit-holes/{hole_id}/nodes/{children[0]['id']}/visit").json()
    assert visited["metrics"]["explored_nodes"] == 2
    assert visited["metrics"]["most_explored_branch"] == children[0]["title"]


def test_expansion_links_children_and_reuses_existing_layer(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ai, "generate_initial", lambda _question: initial_layer())
    response = client.post("/api/rabbit-holes", json={"question": "Why do humans seek power?"})
    graph = response.json()
    hole_id = graph["id"]
    parent = next(node for node in graph["nodes"] if node["parent_id"] == graph["nodes"][0]["id"])
    calls = []

    def make_expansion(**_kwargs):
        calls.append(True)
        return ai.LayerResult(branches=[concept("Coalition building"), concept("Reciprocal exchange"), concept("Reputation signals")])

    monkeypatch.setattr(ai, "generate_expansion", make_expansion)
    first = client.post(f"/api/rabbit-holes/{hole_id}/nodes/{parent['id']}/expand", json={})
    second = client.post(f"/api/rabbit-holes/{hole_id}/nodes/{parent['id']}/expand", json={})
    assert first.status_code == second.status_code == 200
    assert first.json()["reused"] is False
    assert second.json()["reused"] is True
    assert len(calls) == 1

    saved = client.get(f"/api/rabbit-holes/{hole_id}").json()
    assert saved["metrics"]["node_count"] == 9
    assert saved["metrics"]["max_depth"] == 2
    assert saved["metrics"]["first_level_branches"] == 5
    child_nodes = [node for node in saved["nodes"] if node["id"] in first.json()["node_ids"]]
    assert len(child_nodes) == 3
    assert all(node["parent_id"] == parent["id"] for node in child_nodes)
    child_edges = [edge for edge in saved["edges"] if edge["target"] in first.json()["node_ids"]]
    assert len(child_edges) == 3
    assert {edge["source"] for edge in child_edges} == {parent["id"]}


def test_failed_expansion_keeps_the_saved_graph(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ai, "generate_initial", lambda _question: initial_layer())
    graph = client.post("/api/rabbit-holes", json={"question": "What makes a memory feel real?"}).json()
    parent = graph["nodes"][1]

    def fail(**_kwargs):
        raise ai.AIServiceError("A temporary model failure.")

    monkeypatch.setattr(ai, "generate_expansion", fail)
    response = client.post(f"/api/rabbit-holes/{graph['id']}/nodes/{parent['id']}/expand", json={})
    assert response.status_code == 503
    assert client.get(f"/api/rabbit-holes/{graph['id']}").json()["metrics"]["node_count"] == 6


def test_empty_question_and_incomplete_ai_schema_are_rejected(client: TestClient) -> None:
    response = client.post("/api/rabbit-holes", json={"question": "  \n  "})
    assert response.status_code == 422
    with pytest.raises(ValidationError):
        InitialLayer.model_validate({"root_summary": "A root summary without branches", "branches": []})
    with pytest.raises(ValidationError):
        InitialLayer.model_validate({"root_summary": initial_layer().root_summary, "branches": initial_layer().branches[:4]})


def test_structured_ai_output_is_parsed_and_validated(monkeypatch: pytest.MonkeyPatch) -> None:
    layer = initial_layer()

    class FakeClient:
        def __init__(self, text: str):
            self.models = SimpleNamespace(generate_content=lambda **_kwargs: SimpleNamespace(text=text))

        def close(self):
            pass

    payload = InitialLayer(root_summary=layer.root_summary, branches=layer.branches).model_dump_json()
    monkeypatch.setattr(ai, "_client", lambda: FakeClient(payload))
    parsed = ai._structured("test prompt", InitialLayer)
    assert parsed.root_summary == layer.root_summary
    assert len(parsed.branches) == 5

    monkeypatch.setattr(ai, "_client", lambda: FakeClient('{"root_summary":"missing branches"}'))
    with pytest.raises(ai.AIServiceError, match="incomplete exploration layer"):
        ai._structured("test prompt", InitialLayer)


def test_initial_generation_retries_near_duplicates_and_returns_five_distinct_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    layer = initial_layer()
    repeated = concept("Status games")
    responses = [
        InitialLayer(root_summary=layer.root_summary, branches=[*layer.branches[:4], repeated]),
        InitialLayer(root_summary=layer.root_summary, branches=layer.branches),
    ]
    prompts: list[str] = []

    def structured(prompt: str, _schema):
        prompts.append(prompt)
        return responses[len(prompts) - 1]

    monkeypatch.setattr(ai, "_structured", structured)
    monkeypatch.setattr(ai, "_grounded_sources", lambda _question, _concepts: {})
    generated = ai.generate_initial("Why do humans seek power?")
    assert len(generated.branches) == 5
    assert len({ai.title_key(item.title) for item in generated.branches}) == 5
    assert len(prompts) == 2
    assert "exactly five unique concepts" in prompts[1]


def test_initial_generation_retries_an_incomplete_structured_response(monkeypatch: pytest.MonkeyPatch) -> None:
    layer = initial_layer()
    calls = 0

    def structured(_prompt: str, _schema):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ai.AIServiceError("Gemini returned an incomplete exploration layer. Please retry.")
        return InitialLayer(root_summary=layer.root_summary, branches=layer.branches)

    monkeypatch.setattr(ai, "_structured", structured)
    monkeypatch.setattr(ai, "_grounded_sources", lambda _question, _concepts: {})
    generated = ai.generate_initial("Why do humans seek power?")
    assert calls == 2
    assert len(generated.branches) == 5


def test_incomplete_initial_layer_is_not_persisted(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    layer = initial_layer()
    monkeypatch.setattr(ai, "generate_initial", lambda _question: ai.LayerResult(layer.branches[:4], layer.root_summary))
    response = client.post("/api/rabbit-holes", json={"question": "Why do humans seek power?"})
    assert response.status_code == 503
    assert "exactly 5" in response.json()["detail"]
    assert client.get("/api/rabbit-holes").json() == []


def test_missing_gemini_key_has_a_clear_configuration_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "")
    with pytest.raises(ai.AIConfigurationError, match="GEMINI_API_KEY"):
        ai._client()


def test_delete_removes_hole_from_archive(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ai, "generate_initial", lambda _question: initial_layer())
    graph = client.post("/api/rabbit-holes", json={"question": "How do maps shape thought?"}).json()
    deleted = client.delete(f"/api/rabbit-holes/{graph['id']}")
    assert deleted.status_code == 204
    assert client.get("/api/rabbit-holes").json() == []
    assert client.get(f"/api/rabbit-holes/{graph['id']}").status_code == 404


def test_grounded_sources_follow_concept_headings_and_report_the_real_publisher(monkeypatch: pytest.MonkeyPatch) -> None:
    concepts = initial_layer().branches[:2]
    redirect = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/abc"
    metadata = SimpleNamespace(
        grounding_chunks=[
            SimpleNamespace(web=SimpleNamespace(uri=redirect, title="www.britannica.com")),
            SimpleNamespace(web=SimpleNamespace(uri="https://example.org/page", title="Example page")),
        ],
        grounding_supports=[
            # Little word overlap with either summary, but the heading names the second concept exactly.
            SimpleNamespace(segment=SimpleNamespace(text="## Power and institutions\nCourts and parliaments constrain rulers."), grounding_chunk_indices=[0]),
            SimpleNamespace(segment=SimpleNamespace(text="Status games shape a concise explanation of status games."), grounding_chunk_indices=[1]),
        ],
    )

    class FakeClient:
        models = SimpleNamespace(generate_content=lambda **_kwargs: SimpleNamespace(candidates=[SimpleNamespace(grounding_metadata=metadata)]))

        def close(self):
            pass

    monkeypatch.setattr(ai, "_client", lambda: FakeClient())
    sources = ai._grounded_sources("Why do humans seek power?", concepts)
    institutions = sources[ai.title_key("Power and institutions")]
    assert [item["url"] for item in institutions] == [redirect]
    assert institutions[0]["publisher"] == "britannica.com"
    assert institutions[0]["citation_text"] == "Courts and parliaments constrain rulers."
    status = sources[ai.title_key("Status games")]
    assert [(item["url"], item["publisher"]) for item in status] == [("https://example.org/page", "example.org")]


def test_source_metrics_distinguish_unique_sources_from_sourced_concepts(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ai, "generate_initial", lambda _question: initial_layer())
    graph = client.post("/api/rabbit-holes", json={"question": "Why do humans seek power?"}).json()
    stored_urls = {source["url"] for node in graph["nodes"] for source in node["sources"]}
    assert graph["metrics"]["unique_sources"] == len(stored_urls) == 1
    assert graph["metrics"]["sourced_nodes"] == sum(1 for node in graph["nodes"] if node["sources"]) == 2


def test_read_only_showcase_serves_graphs_but_refuses_changes(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from backend import main

    monkeypatch.setattr(ai, "generate_initial", lambda _question: initial_layer())
    graph = client.post("/api/rabbit-holes", json={"question": "Why do humans seek power?"}).json()
    child = next(node for node in graph["nodes"] if node["parent_id"])

    def no_ai(**_kwargs):
        raise AssertionError("read-only mode must not call the AI")

    monkeypatch.setattr(main, "READ_ONLY", True)
    monkeypatch.setattr(ai, "generate_initial", no_ai)
    monkeypatch.setattr(ai, "generate_expansion", no_ai)
    assert client.get("/api/health").json()["read_only"] is True
    assert client.post("/api/rabbit-holes", json={"question": "Another question"}).status_code == 403
    assert client.post(f"/api/rabbit-holes/{graph['id']}/nodes/{child['id']}/expand", json={}).status_code == 403
    assert client.delete(f"/api/rabbit-holes/{graph['id']}").status_code == 403
    assert client.post(f"/api/rabbit-holes/{graph['id']}/leaps", json={}).status_code == 403
    visited = client.post(f"/api/rabbit-holes/{graph['id']}/nodes/{child['id']}/visit")
    assert visited.status_code == 200
    assert visited.json()["metrics"]["explored_nodes"] == graph["metrics"]["explored_nodes"]
    assert client.get(f"/api/rabbit-holes/{graph['id']}").json()["metrics"]["node_count"] == 6


def leap_trail(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> tuple[dict, str, str]:
    """A trail with one visited depth-2 node. Returns (graph, eligible node id, unvisited depth-2 node id)."""
    from backend.schemas import LeapCopy

    monkeypatch.setattr(ai, "generate_initial", lambda _question: initial_layer())
    graph = client.post("/api/rabbit-holes", json={"question": "Why do humans seek power?"}).json()
    child = next(node for node in graph["nodes"] if node["parent_id"])
    monkeypatch.setattr(ai, "generate_expansion", lambda **_kwargs: ai.LayerResult(
        branches=[concept("Court rituals"), concept("Peacock feathers", "Biology"), concept("Office floor plans", "Design")], source_map={}))
    new_ids = client.post(f"/api/rabbit-holes/{graph['id']}/nodes/{child['id']}/expand", json={}).json()["node_ids"]
    graph = client.post(f"/api/rabbit-holes/{graph['id']}/nodes/{new_ids[0]}/visit").json()
    monkeypatch.setattr(ai, "embed_texts", lambda texts: [[float(i), 1.0, float(i % 3)] for i in range(len(texts))])
    monkeypatch.setattr(ai, "generate_leap_copy", lambda _question, paths: [
        LeapCopy(index=i, hook="From power to court rituals", reframe="Rituals make rank visible.", waypoints=[path[1][0]])
        for i, path in enumerate(paths)])
    return graph, new_ids[0], new_ids[1]


def test_leaps_returns_ranked_candidates(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    graph, _eligible, _unvisited = leap_trail(client, monkeypatch)
    response = client.post(f"/api/rabbit-holes/{graph['id']}/leaps", json={})
    assert response.status_code == 200
    body = response.json()
    assert body["ranked"] is True
    assert 1 <= len(body["candidates"]) <= 3
    candidate = body["candidates"][0]
    assert candidate["path"][0] == graph["question"]
    assert candidate["hops"] == len(candidate["path"]) - 1
    assert candidate["waypoints"] == [candidate["path"][1]]


def test_leaps_shallow_trail_is_400(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ai, "generate_initial", lambda _question: initial_layer())
    graph = client.post("/api/rabbit-holes", json={"question": "Why do humans seek power?"}).json()
    response = client.post(f"/api/rabbit-holes/{graph['id']}/leaps", json={})
    assert response.status_code == 400
    assert response.json()["detail"] == "Go one layer deeper to find a leap."


def test_leaps_embedding_failure_is_unranked(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    graph, _eligible, _unvisited = leap_trail(client, monkeypatch)

    def fail(_texts):
        raise ai.AIServiceError("x")

    monkeypatch.setattr(ai, "embed_texts", fail)
    response = client.post(f"/api/rabbit-holes/{graph['id']}/leaps", json={})
    assert response.status_code == 200
    assert response.json() == {"ranked": False, "candidates": []}


def test_leaps_node_override_skips_embeddings(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    graph, eligible, _unvisited = leap_trail(client, monkeypatch)

    def never(_texts):
        raise AssertionError("a chosen node must not be embedded")

    monkeypatch.setattr(ai, "embed_texts", never)
    body = client.post(f"/api/rabbit-holes/{graph['id']}/leaps", json={"node_id": eligible}).json()
    assert body["ranked"] is False
    assert [c["node_id"] for c in body["candidates"]] == [eligible]
    assert body["candidates"][0]["score"] is None


def test_leaps_rejects_ineligible_node(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    graph, _eligible, unvisited = leap_trail(client, monkeypatch)
    root = next(node for node in graph["nodes"] if node["parent_id"] is None)
    for node_id in (root["id"], unvisited, "00000000-0000-0000-0000-000000000000"):
        assert client.post(f"/api/rabbit-holes/{graph['id']}/leaps", json={"node_id": node_id}).status_code == 400


def test_leaps_bad_copy_indexes_is_503(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.schemas import LeapCopy

    graph, _eligible, _unvisited = leap_trail(client, monkeypatch)
    monkeypatch.setattr(ai, "generate_leap_copy", lambda _question, _paths: [LeapCopy(index=7, hook="h", reframe="r", waypoints=[])])
    response = client.post(f"/api/rabbit-holes/{graph['id']}/leaps", json={})
    assert response.status_code == 503


def import_authored(client: TestClient) -> dict:
    from backend import studio
    from backend.story import parse_story
    from backend.tests.test_story import SLUG, VALID

    db = next(app.dependency_overrides[get_db]())
    hole = studio.import_story(db, parse_story(VALID, SLUG))
    return client.get(f"/api/rabbit-holes/{hole.id}").json()


def test_authored_trail_exposes_stage_evidence_and_source_meta(client: TestClient) -> None:
    graph = import_authored(client)
    by_parent = {node["parent_id"]: node for node in graph["nodes"]}
    stages, parent = [], None
    while parent in by_parent:
        stages.append(by_parent[parent]["stage"])
        parent = by_parent[parent]["id"]
    assert stages == ["hook", "entry", "descent", "descent", "leap", "exit"]
    leap = next(node for node in graph["nodes"] if node["stage"] == "leap")
    entry = next(node for node in graph["nodes"] if node["stage"] == "entry")
    assert leap["evidence"] == "interpretation"
    assert entry["sources"][0]["medium"] == "archive" and entry["sources"][0]["published"] == "2003-05-01"
    assert graph["slug"] == "early-japanese-web" and graph["territory"] == "Internet archaeology"
    assert not any(node["explored"] for node in graph["nodes"])


def test_check_note_never_in_api(client: TestClient) -> None:
    graph = import_authored(client)
    response = client.get(f"/api/rabbit-holes/{graph['id']}")
    assert "verify before publishing" not in response.text
