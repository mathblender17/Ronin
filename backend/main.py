from collections import Counter, defaultdict
from datetime import timezone
import os
from threading import Lock
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from . import ai
from .database import ROOT_DIR, Base, SessionLocal, engine
from .models import Edge, Node, RabbitHole, Source, utcnow
from .schemas import (
    CreateRequest,
    ExpandRequest,
    ExpansionOut,
    GraphEdgeOut,
    GraphOut,
    MetricsOut,
    NodeOut,
    RabbitHoleSummary,
    SourceOut,
)

Base.metadata.create_all(bind=engine)
app = FastAPI(title="Ronin API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)
_expansion_lock = Lock()
# Showcase deployments serve a saved snapshot: browsing works, but nothing can be created,
# expanded or deleted, so no AI calls are made and visitors cannot change the data.
READ_ONLY = os.getenv("RONIN_READ_ONLY", "").strip().lower() in {"1", "true", "yes"}


def _require_writable() -> None:
    if READ_ONLY:
        raise HTTPException(status_code=403, detail="This Ronin is a read-only showcase. Run it locally to start your own trails.")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _node_out(node: Node) -> NodeOut:
    return NodeOut(
        id=node.id,
        parent_id=node.parent_id,
        title=node.title,
        summary=node.summary,
        connection_reason=node.connection_reason,
        exploration_question=node.exploration_question,
        domain=node.domain,
        explored=node.explored_at is not None or bool(node.children),
        created_at=node.created_at,
        sources=[SourceOut.model_validate(source) for source in node.sources],
    )


def _metrics(hole: RabbitHole) -> MetricsOut:
    by_parent: dict[str | None, list[Node]] = defaultdict(list)
    for node in hole.nodes:
        by_parent[node.parent_id].append(node)
    root = next((node for node in hole.nodes if node.parent_id is None), None)
    first_level = by_parent.get(root.id, []) if root else []
    deepest_path: list[str] = []

    def visit(node: Node, path: list[str]) -> None:
        nonlocal deepest_path
        current = path + [node.title]
        if len(current) > len(deepest_path):
            deepest_path = current
        for child in by_parent.get(node.id, []):
            visit(child, current)

    if root:
        visit(root, [])

    branch_counts: Counter[str] = Counter()
    nodes_by_id = {node.id: node for node in hole.nodes}
    for node in hole.nodes:
        if root is None or node.id == root.id:
            continue
        ancestor = node
        seen: set[str] = set()
        while ancestor.parent_id and ancestor.parent_id != root.id:
            if ancestor.id in seen:
                break
            seen.add(ancestor.id)
            ancestor = nodes_by_id.get(ancestor.parent_id)
            if ancestor is None:
                break
        if ancestor and ancestor.parent_id == root.id and (node.explored_at is not None or bool(node.children)):
            branch_counts[ancestor.title] += 1
    most_explored = branch_counts.most_common(1)[0][0] if branch_counts else None
    source_ids = {source.id for node in hole.nodes for source in node.sources}
    domains = sorted({node.domain.strip() for node in hole.nodes if node.parent_id is not None and node.domain.strip()})
    return MetricsOut(
        node_count=len(hole.nodes),
        max_depth=max(0, len(deepest_path) - 1),
        first_level_branches=len(first_level),
        explored_nodes=sum(1 for node in hole.nodes if node.explored_at is not None or node.children),
        unique_sources=len(source_ids),
        sourced_nodes=sum(1 for node in hole.nodes if node.sources),
        domain_count=len(domains),
        deepest_path=deepest_path,
        most_explored_branch=most_explored,
        domains=domains,
    )


def _graph(hole: RabbitHole) -> GraphOut:
    def created_at_key(node: Node):
        created_at = node.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        return created_at.astimezone(timezone.utc), node.id

    nodes = sorted(hole.nodes, key=created_at_key)
    edges = sorted(hole.edges, key=lambda edge: (edge.parent_node_id, edge.child_node_id))
    return GraphOut(
        id=hole.id,
        title=hole.title,
        question=hole.question,
        created_at=hole.created_at,
        updated_at=hole.updated_at,
        nodes=[_node_out(node) for node in nodes],
        edges=[
            GraphEdgeOut(
                id=edge.id,
                source=edge.parent_node_id,
                target=edge.child_node_id,
                relationship_note=edge.relationship_note,
            )
            for edge in edges
        ],
        metrics=_metrics(hole),
    )


def _load_hole(db: Session, hole_id: str) -> RabbitHole:
    hole = db.scalar(
        select(RabbitHole)
        .where(RabbitHole.id == hole_id)
        .options(
            selectinload(RabbitHole.nodes).selectinload(Node.sources),
            selectinload(RabbitHole.nodes).selectinload(Node.children),
            selectinload(RabbitHole.edges),
        )
    )
    if not hole:
        raise HTTPException(status_code=404, detail="This rabbit hole could not be found.")
    return hole


def _db_sources(db: Session, concept: ai.GeneratedConcept, source_map: dict[str, list[dict[str, str]]] | None) -> list[Source]:
    from .ai import title_key

    saved: list[Source] = []
    for data in (source_map or {}).get(title_key(concept.title), []):
        source = db.scalar(select(Source).where(Source.url == data["url"]))
        if source is None:
            source = Source(id=str(uuid4()), **data)
            db.add(source)
        saved.append(source)
    return saved


def _save_concept(db: Session, hole: RabbitHole, parent: Node, concept: ai.GeneratedConcept, source_map) -> Node:
    node = Node(
        id=str(uuid4()),
        rabbit_hole_id=hole.id,
        parent_id=parent.id,
        title=concept.title,
        title_key=ai.title_key(concept.title),
        summary=concept.summary,
        connection_reason=concept.connection_reason,
        exploration_question=concept.exploration_question,
        domain=concept.domain,
        sources=_db_sources(db, concept, source_map),
    )
    db.add(node)
    db.flush()
    db.add(Edge(
        id=str(uuid4()), rabbit_hole_id=hole.id, parent_node_id=parent.id,
        child_node_id=node.id, relationship_note=concept.connection_reason,
    ))
    return node


@app.get("/api/health")
def health():
    return {"status": "ok", "ai_configured": ai.any_provider_configured(), "read_only": READ_ONLY, "ai": ai.diagnostics()}


@app.get("/api/rabbit-holes", response_model=list[RabbitHoleSummary])
def list_rabbit_holes(db: Session = Depends(get_db)):
    holes = db.scalars(select(RabbitHole).order_by(RabbitHole.updated_at.desc()).options(selectinload(RabbitHole.nodes))).all()
    results = []
    for hole in holes:
        metrics = _metrics(hole)
        results.append(RabbitHoleSummary(
            id=hole.id, title=hole.title, question=hole.question, created_at=hole.created_at,
            updated_at=hole.updated_at, node_count=metrics.node_count,
            max_depth=metrics.max_depth, first_level_branches=metrics.first_level_branches,
        ))
    return results


@app.post("/api/rabbit-holes", response_model=GraphOut, status_code=status.HTTP_201_CREATED)
def create_rabbit_hole(body: CreateRequest, db: Session = Depends(get_db)):
    _require_writable()
    try:
        layer = ai.generate_initial(body.question)
    except ai.AIServiceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    branches = ai.unique_concepts(layer.branches, [body.question])
    if len(branches) != 5:
        raise HTTPException(
            status_code=503,
            detail=f"The initial map is incomplete: the AI returned {len(branches)} distinct first paths, but Ronin needs exactly 5. Please retry.",
        )
    now = utcnow()
    hole = RabbitHole(id=str(uuid4()), question=body.question, title=body.question[:117] + ("…" if len(body.question) > 120 else ""), created_at=now, updated_at=now)
    root = Node(
        id=str(uuid4()), rabbit_hole_id=hole.id, parent_id=None,
        title=body.question[:180], title_key=ai.title_key(body.question)[:180],
        summary=layer.root_summary or body.question,
        connection_reason="The question that opened this trail.",
        exploration_question="Which direction feels most alive to you?",
        domain="Starting point", explored_at=now,
    )
    db.add(hole)
    db.add(root)
    try:
        db.flush()
        for concept in branches:
            _save_concept(db, hole, root, concept, layer.source_map)
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="The exploration could not be saved. Your existing archive is unchanged.")
    return _graph(_load_hole(db, hole.id))


@app.get("/api/rabbit-holes/{hole_id}", response_model=GraphOut)
def get_rabbit_hole(hole_id: str, db: Session = Depends(get_db)):
    return _graph(_load_hole(db, hole_id))


@app.post("/api/rabbit-holes/{hole_id}/nodes/{node_id}/visit", response_model=GraphOut)
def visit_node(hole_id: str, node_id: str, db: Session = Depends(get_db)):
    hole = _load_hole(db, hole_id)
    node = next((node for node in hole.nodes if node.id == node_id), None)
    if not node:
        raise HTTPException(status_code=404, detail="This concept no longer exists in the rabbit hole.")
    if node.explored_at is None and not READ_ONLY:
        node.explored_at = utcnow()
        hole.updated_at = utcnow()
        db.commit()
    return _graph(_load_hole(db, hole_id))


@app.post("/api/rabbit-holes/{hole_id}/nodes/{node_id}/expand", response_model=ExpansionOut)
def expand_node(hole_id: str, node_id: str, body: ExpandRequest | None = None, db: Session = Depends(get_db)):
    _require_writable()
    direction = body.direction if body else None
    with _expansion_lock:
        hole = _load_hole(db, hole_id)
        node = next((item for item in hole.nodes if item.id == node_id), None)
        if not node:
            raise HTTPException(status_code=404, detail="This concept no longer exists in the rabbit hole.")
        existing = sorted(node.children, key=lambda child: child.created_at)
        if existing and direction is None:
            return ExpansionOut(node_ids=[item.id for item in existing], reused=True)
        ancestors: list[Node] = []
        parent = node
        while parent:
            ancestors.append(parent)
            parent = parent.parent
        selected = ai.GeneratedConcept(
            title=node.title, summary=node.summary, connection_reason=node.connection_reason,
            exploration_question=node.exploration_question, domain=node.domain,
        )
        try:
            layer = ai.generate_expansion(
                question=hole.question,
                selected=selected,
                ancestors=[item.title for item in reversed(ancestors)],
                graph_context=[item.title for item in hole.nodes],
                direction=direction,
            )
        except ai.AIServiceError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        current_keys = {item.title_key for item in hole.nodes}
        concepts = [item for item in layer.branches if ai.title_key(item.title) not in current_keys]
        if len(concepts) < 3:
            raise HTTPException(status_code=503, detail="These suggestions were too close to existing concepts. Try a different direction.")
        node.explored_at = node.explored_at or utcnow()
        try:
            children = [_save_concept(db, hole, node, concept, layer.source_map) for concept in concepts]
            hole.updated_at = utcnow()
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            refreshed = _load_hole(db, hole_id)
            parent_node = next(item for item in refreshed.nodes if item.id == node_id)
            return ExpansionOut(node_ids=[item.id for item in parent_node.children], reused=True)
        except Exception as exc:
            db.rollback()
            raise HTTPException(status_code=500, detail="The new layer could not be saved. Your existing graph is unchanged.") from exc
        return ExpansionOut(node_ids=[item.id for item in children])


@app.delete("/api/rabbit-holes/{hole_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rabbit_hole(hole_id: str, db: Session = Depends(get_db)):
    _require_writable()
    hole = db.get(RabbitHole, hole_id)
    if not hole:
        raise HTTPException(status_code=404, detail="This rabbit hole could not be found.")
    db.delete(hole)
    db.commit()


# In the deployed container the built frontend is served by the API itself (one service, one URL).
# Locally, Vite serves the frontend and dist/ may not exist.
if (ROOT_DIR / "dist" / "index.html").exists():
    app.mount("/", StaticFiles(directory=ROOT_DIR / "dist", html=True), name="frontend")
