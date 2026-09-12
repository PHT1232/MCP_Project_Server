"""ORM models for the code index (FR21, FR25, NFR12).

Live in schema ``code_index`` so they can be dropped and rebuilt without
touching curated context (AC15).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pcs.db.base import Base

INDEX_SCHEMA = "code_index"


def _new_id() -> str:
    return str(uuid.uuid4())


class IndexFile(Base):
    """One repo file's index bookkeeping (skip reasons, blob, hash)."""

    __tablename__ = "files"
    __table_args__ = (
        UniqueConstraint("project_id", "path", name="uq_code_index_files_project_path"),
        {"schema": INDEX_SCHEMA},
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    path: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str | None] = mapped_column(String(32), nullable=True)
    git_blob: Mapped[str | None] = mapped_column(String(64), nullable=True)
    git_commit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[bool] = mapped_column(default=False)
    skip_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    indexed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IndexChunk(Base):
    """One searchable chunk of a file (FR21, FR23, FR25)."""

    __tablename__ = "chunks"
    __table_args__ = ({"schema": INDEX_SCHEMA},)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    file_id: Mapped[str] = mapped_column(
        ForeignKey(f"{INDEX_SCHEMA}.files.id", ondelete="CASCADE"), index=True
    )
    path: Mapped[str] = mapped_column(Text, nullable=False)
    start_line: Mapped[int] = mapped_column(Integer, nullable=False)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False)
    language: Mapped[str | None] = mapped_column(String(32), nullable=True)
    kind: Mapped[str] = mapped_column(String(32), default="text")
    symbol: Mapped[str | None] = mapped_column(Text, nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    git_blob: Mapped[str | None] = mapped_column(String(64), nullable=True)
    git_commit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # sha256 of this chunk's own content — the embedding cache key (NFR10, F4).
    chunk_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    indexed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IndexSymbol(Base):
    """One symbol definition, normalised to a SCIP-style model (FR23b, FR23c, D14)."""

    __tablename__ = "symbols"
    __table_args__ = ({"schema": INDEX_SCHEMA},)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    file_id: Mapped[str] = mapped_column(
        ForeignKey(f"{INDEX_SCHEMA}.files.id", ondelete="CASCADE"), index=True
    )
    path: Mapped[str] = mapped_column(Text, nullable=False)
    # SCIP symbol string (`scheme ' ' package ...`) or a synthetic id in fallback mode.
    scip_symbol: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), default="symbol")
    language: Mapped[str | None] = mapped_column(String(32), nullable=True)
    start_line: Mapped[int] = mapped_column(Integer, nullable=False)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False)
    signature: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 'scip' or 'fallback' — the mode this row was produced in (AC23).
    mode: Mapped[str] = mapped_column(String(16), default="fallback")
    indexed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IndexSymbolRef(Base):
    """One reference (use) of a symbol (FR20 'references', FR23c)."""

    __tablename__ = "symbol_refs"
    __table_args__ = ({"schema": INDEX_SCHEMA},)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    file_id: Mapped[str] = mapped_column(
        ForeignKey(f"{INDEX_SCHEMA}.files.id", ondelete="CASCADE"), index=True
    )
    path: Mapped[str] = mapped_column(Text, nullable=False)
    scip_symbol: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    start_line: Mapped[int] = mapped_column(Integer, nullable=False)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False)
    is_definition: Mapped[bool] = mapped_column(Boolean, default=False)
    language: Mapped[str | None] = mapped_column(String(32), nullable=True)
    mode: Mapped[str] = mapped_column(String(16), default="fallback")
    indexed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IndexSymbolEdge(Base):
    """One dependency edge between files/modules — consumed by T05's code map (FR32)."""

    __tablename__ = "symbol_edges"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "src_path",
            "dst_path",
            "dst_module",
            "kind",
            name="uq_code_index_symbol_edges",
        ),
        {"schema": INDEX_SCHEMA},
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    src_path: Mapped[str] = mapped_column(Text, nullable=False)
    # Resolved target file path, or "" when only the module string is known.
    dst_path: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Raw import/include target (module name, header path) — always populated.
    dst_module: Mapped[str] = mapped_column(Text, nullable=False, default="")
    kind: Mapped[str] = mapped_column(String(16), default="import")
    language: Mapped[str | None] = mapped_column(String(32), nullable=True)
    mode: Mapped[str] = mapped_column(String(16), default="fallback")
    indexed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IndexEmbedding(Base):
    """Content-hash-keyed embedding cache (NFR10). Unchanged chunks are never re-embedded."""

    __tablename__ = "embeddings"
    __table_args__ = ({"schema": INDEX_SCHEMA},)

    chunk_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    model: Mapped[str] = mapped_column(String(128), primary_key=True)
    dim: Mapped[int] = mapped_column(Integer, nullable=False)
    # Stored as pgvector `vector`; accessed only via SQL distance operators.
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IndexStatus(Base):
    """Per-project index counters and timestamps (FR26)."""

    __tablename__ = "status"
    __table_args__ = ({"schema": INDEX_SCHEMA},)

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    last_full_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_incremental_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_commit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    file_count: Mapped[int] = mapped_column(Integer, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    state: Mapped[str] = mapped_column(String(16), default="idle")
    # {language: 'scip' | 'fallback'} per language seen in the repo (AC23, FR26).
    symbol_modes: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict, server_default="{}")
    symbol_count: Mapped[int] = mapped_column(Integer, default=0)
    # Embedding backend model name whose vectors are current, or None (AC21).
    semantic_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    semantic_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    semantic_base_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    semantic_dimensions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reindex_required: Mapped[bool] = mapped_column(Boolean, default=False)
    embedded_chunk_count: Mapped[int] = mapped_column(Integer, default=0)
