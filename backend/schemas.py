from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class SourceOut(BaseModel):
    id: str
    title: str
    url: HttpUrl
    publisher: str
    citation_text: str = ""

    model_config = ConfigDict(from_attributes=True)


class NodeOut(BaseModel):
    id: str
    parent_id: str | None
    title: str
    summary: str
    connection_reason: str
    exploration_question: str
    domain: str
    explored: bool
    created_at: datetime
    sources: list[SourceOut] = Field(default_factory=list)


class MetricsOut(BaseModel):
    node_count: int
    max_depth: int
    first_level_branches: int
    explored_nodes: int
    unique_sources: int
    sourced_nodes: int
    domain_count: int
    deepest_path: list[str]
    most_explored_branch: str | None
    domains: list[str]


class GraphEdgeOut(BaseModel):
    id: str
    source: str
    target: str
    relationship_note: str


class GraphOut(BaseModel):
    id: str
    title: str
    question: str
    created_at: datetime
    updated_at: datetime
    nodes: list[NodeOut]
    edges: list[GraphEdgeOut]
    metrics: MetricsOut


class RabbitHoleSummary(BaseModel):
    id: str
    title: str
    question: str
    created_at: datetime
    updated_at: datetime
    node_count: int
    max_depth: int
    first_level_branches: int


class CreateRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)

    @field_validator("question")
    @classmethod
    def clean_question(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("Enter a question or idea to begin.")
        return value


class ExpandRequest(BaseModel):
    direction: str | None = Field(default=None, max_length=500)

    @field_validator("direction")
    @classmethod
    def clean_direction(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        return normalized or None


class ExpansionOut(BaseModel):
    node_ids: list[str]
    reused: bool = False


class GeneratedConcept(BaseModel):
    title: str = Field(min_length=2, max_length=180, description="A specific, intriguing 2-7 word title that hooks curiosity, not a broad category label.")
    summary: str = Field(min_length=10, max_length=700, description="One or two sentences carrying the most interesting claim or tension, not a definition.")
    connection_reason: str = Field(min_length=10, max_length=700, description="Explain the concrete relationship between this concept and its parent.")
    exploration_question: str = Field(min_length=5, max_length=500, description="A specific question or direction that would lead to a useful next layer.")
    domain: str = Field(min_length=2, max_length=100, description="The most relevant subject area for this concept.")

    @field_validator("title", "summary", "connection_reason", "exploration_question", "domain")
    @classmethod
    def trim_text(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("Generated text fields cannot be blank.")
        return value


class InitialLayer(BaseModel):
    root_summary: str = Field(min_length=10, max_length=700, description="A brief, balanced explanation of the starting question.")
    branches: list[GeneratedConcept] = Field(
        min_length=5,
        max_length=5,
        description="Exactly five distinct first-level concepts, each a separate entry point connected directly to the starting question.",
    )


class ExpansionLayer(BaseModel):
    branches: list[GeneratedConcept] = Field(
        min_length=3,
        max_length=5,
        description="Three to five distinct child concepts attached to the selected parent.",
    )


class LeapCopy(BaseModel):
    index: int
    hook: str = Field(description="At most 12 words: the 'wait, what?' line about how the first title led to the last.")
    reframe: str = Field(description="At most 25 words: why the leap makes sense, phrased as an interpretation.")
    waypoints: list[str] = Field(description="Two or three titles copied exactly from the path's middle steps.")

    @field_validator("hook", "reframe")
    @classmethod
    def trim_text(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("Leap text cannot be blank.")
        return value

    @field_validator("hook")
    @classmethod
    def short_hook(cls, value: str) -> str:
        if len(value.split()) > 12:
            raise ValueError("A hook is at most 12 words.")
        return value

    @field_validator("reframe")
    @classmethod
    def short_reframe(cls, value: str) -> str:
        if len(value.split()) > 25:
            raise ValueError("A reframe is at most 25 words.")
        return value


class LeapCopyLayer(BaseModel):
    leaps: list[LeapCopy] = Field(min_length=1, max_length=3)


class LeapRequest(BaseModel):
    node_id: str | None = None


class LeapCandidateOut(BaseModel):
    node_id: str
    path: list[str]
    waypoints: list[str]
    hook: str
    reframe: str
    score: float | None
    hops: int
    domains: int


class LeapsOut(BaseModel):
    ranked: bool
    candidates: list[LeapCandidateOut]
