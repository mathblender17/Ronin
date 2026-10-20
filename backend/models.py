from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RabbitHole(Base):
    __tablename__ = "rabbit_holes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    question: Mapped[str] = mapped_column(String(500), nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    nodes: Mapped[list["Node"]] = relationship(back_populates="rabbit_hole", cascade="all, delete-orphan")
    edges: Mapped[list["Edge"]] = relationship(back_populates="rabbit_hole", cascade="all, delete-orphan")


class Node(Base):
    __tablename__ = "nodes"
    __table_args__ = (
        UniqueConstraint("parent_id", "title_key", name="uq_node_parent_title"),
        Index("ix_nodes_hole_parent", "rabbit_hole_id", "parent_id"),
        Index("uq_nodes_single_root_per_hole", "rabbit_hole_id", unique=True, sqlite_where=text("parent_id IS NULL"), postgresql_where=text("parent_id IS NULL")),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    rabbit_hole_id: Mapped[str] = mapped_column(ForeignKey("rabbit_holes.id", ondelete="CASCADE"), nullable=False, index=True)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("nodes.id", ondelete="CASCADE"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    title_key: Mapped[str] = mapped_column(String(180), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    connection_reason: Mapped[str] = mapped_column(Text, nullable=False)
    exploration_question: Mapped[str] = mapped_column(String(500), nullable=False)
    domain: Mapped[str] = mapped_column(String(100), nullable=False)
    explored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    rabbit_hole: Mapped[RabbitHole] = relationship(back_populates="nodes")
    parent: Mapped["Node | None"] = relationship(remote_side="Node.id", back_populates="children")
    children: Mapped[list["Node"]] = relationship(back_populates="parent", cascade="all, delete-orphan")
    sources: Mapped[list["Source"]] = relationship(secondary="node_sources", back_populates="nodes")


class Edge(Base):
    __tablename__ = "edges"
    __table_args__ = (
        UniqueConstraint("parent_node_id", "child_node_id", name="uq_edge_parent_child"),
        Index("ix_edges_hole_parent", "rabbit_hole_id", "parent_node_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    rabbit_hole_id: Mapped[str] = mapped_column(ForeignKey("rabbit_holes.id", ondelete="CASCADE"), nullable=False)
    parent_node_id: Mapped[str] = mapped_column(ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False)
    child_node_id: Mapped[str] = mapped_column(ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False)
    relationship_note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    rabbit_hole: Mapped[RabbitHole] = relationship(back_populates="edges")


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    url: Mapped[str] = mapped_column(String(2000), unique=True, nullable=False)
    publisher: Mapped[str] = mapped_column(String(200), nullable=False)
    citation_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    nodes: Mapped[list[Node]] = relationship(secondary="node_sources", back_populates="sources")


class NodeSource(Base):
    __tablename__ = "node_sources"

    node_id: Mapped[str] = mapped_column(ForeignKey("nodes.id", ondelete="CASCADE"), primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), primary_key=True)
