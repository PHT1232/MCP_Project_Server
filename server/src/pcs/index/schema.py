"""Rebuild the ``code_index`` schema if it was dropped (AC15, NFR12).

F1 (T03 review): the previous version re-ran ~10 ``… IF NOT EXISTS`` statements
on *every* reindex / status / search call and kept a second hand-written copy of
the migration DDL. This version:

* does one cheap ``to_regclass`` probe per call and returns immediately when the
  schema is intact (the normal case), and
* keeps a single ``_DDL`` list that is the authoritative rebuild path used only
  when the schema is genuinely missing (the AC15 "someone dropped it" case).

Migrations ``0003`` / ``0004`` own the forward/backward DDL for a normal
``alembic upgrade``; this module only heals a live database whose ``code_index``
schema was dropped out from under an already-stamped Alembic version.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Objects that must exist for the index to work. Order matters (FKs).
_DDL: tuple[str, ...] = (
    "CREATE EXTENSION IF NOT EXISTS pg_trgm",
    "CREATE EXTENSION IF NOT EXISTS vector",
    "CREATE SCHEMA IF NOT EXISTS code_index",
    """
    CREATE TABLE IF NOT EXISTS code_index.files (
        id VARCHAR(36) PRIMARY KEY,
        project_id VARCHAR(36) NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        path TEXT NOT NULL,
        language VARCHAR(32),
        git_blob VARCHAR(64),
        git_commit VARCHAR(64),
        content_hash VARCHAR(64),
        size_bytes INTEGER NOT NULL DEFAULT 0,
        skipped BOOLEAN NOT NULL DEFAULT FALSE,
        skip_reason TEXT,
        indexed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_code_index_files_project_path UNIQUE (project_id, path)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS code_index.chunks (
        id VARCHAR(36) PRIMARY KEY,
        project_id VARCHAR(36) NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        file_id VARCHAR(36) NOT NULL REFERENCES code_index.files(id) ON DELETE CASCADE,
        path TEXT NOT NULL,
        start_line INTEGER NOT NULL,
        end_line INTEGER NOT NULL,
        language VARCHAR(32),
        kind VARCHAR(32) NOT NULL DEFAULT 'text',
        symbol TEXT,
        content TEXT NOT NULL,
        git_blob VARCHAR(64),
        git_commit VARCHAR(64),
        content_hash VARCHAR(64),
        chunk_hash VARCHAR(64),
        indexed_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    ALTER TABLE code_index.chunks
    ADD COLUMN IF NOT EXISTS tsv tsvector
    GENERATED ALWAYS AS (
        to_tsvector('simple', coalesce(symbol, '') || ' ' || content)
    ) STORED
    """,
    """
    CREATE TABLE IF NOT EXISTS code_index.symbols (
        id VARCHAR(36) PRIMARY KEY,
        project_id VARCHAR(36) NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        file_id VARCHAR(36) NOT NULL REFERENCES code_index.files(id) ON DELETE CASCADE,
        path TEXT NOT NULL,
        scip_symbol TEXT NOT NULL,
        name TEXT NOT NULL,
        kind VARCHAR(32) NOT NULL DEFAULT 'symbol',
        language VARCHAR(32),
        start_line INTEGER NOT NULL,
        end_line INTEGER NOT NULL,
        signature TEXT,
        mode VARCHAR(16) NOT NULL DEFAULT 'fallback',
        indexed_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS code_index.symbol_refs (
        id VARCHAR(36) PRIMARY KEY,
        project_id VARCHAR(36) NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        file_id VARCHAR(36) NOT NULL REFERENCES code_index.files(id) ON DELETE CASCADE,
        path TEXT NOT NULL,
        scip_symbol TEXT NOT NULL,
        name TEXT NOT NULL,
        start_line INTEGER NOT NULL,
        end_line INTEGER NOT NULL,
        is_definition BOOLEAN NOT NULL DEFAULT FALSE,
        language VARCHAR(32),
        mode VARCHAR(16) NOT NULL DEFAULT 'fallback',
        indexed_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS code_index.symbol_edges (
        id VARCHAR(36) PRIMARY KEY,
        project_id VARCHAR(36) NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        src_path TEXT NOT NULL,
        dst_path TEXT NOT NULL DEFAULT '',
        dst_module TEXT NOT NULL DEFAULT '',
        kind VARCHAR(16) NOT NULL DEFAULT 'import',
        language VARCHAR(32),
        mode VARCHAR(16) NOT NULL DEFAULT 'fallback',
        indexed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_code_index_symbol_edges
            UNIQUE (project_id, src_path, dst_path, dst_module, kind)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS code_index.embeddings (
        chunk_hash VARCHAR(64) NOT NULL,
        model VARCHAR(128) NOT NULL,
        dim INTEGER NOT NULL,
        embedding vector,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (chunk_hash, model)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS code_index.status (
        project_id VARCHAR(36) PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
        last_full_at TIMESTAMPTZ,
        last_incremental_at TIMESTAMPTZ,
        last_commit VARCHAR(64),
        file_count INTEGER NOT NULL DEFAULT 0,
        chunk_count INTEGER NOT NULL DEFAULT 0,
        skipped_count INTEGER NOT NULL DEFAULT 0,
        state VARCHAR(16) NOT NULL DEFAULT 'idle',
        symbol_modes JSONB NOT NULL DEFAULT '{}',
        symbol_count INTEGER NOT NULL DEFAULT 0,
        semantic_model VARCHAR(128),
        embedded_chunk_count INTEGER NOT NULL DEFAULT 0,
        semantic_provider VARCHAR(32),
        semantic_base_url TEXT,
        semantic_dimensions INTEGER,
        reindex_required BOOLEAN NOT NULL DEFAULT FALSE
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_code_index_files_project_id ON code_index.files (project_id)",
    "CREATE INDEX IF NOT EXISTS ix_code_index_chunks_project_id ON code_index.chunks (project_id)",
    "CREATE INDEX IF NOT EXISTS ix_code_index_chunks_file_id ON code_index.chunks (file_id)",
    "CREATE INDEX IF NOT EXISTS ix_code_index_chunks_chunk_hash ON code_index.chunks (chunk_hash)",
    "CREATE INDEX IF NOT EXISTS ix_code_index_chunks_tsv ON code_index.chunks USING GIN (tsv)",
    "CREATE INDEX IF NOT EXISTS ix_code_index_chunks_content_trgm "
    "ON code_index.chunks USING GIN (content gin_trgm_ops)",
    "CREATE INDEX IF NOT EXISTS ix_code_index_chunks_symbol_trgm "
    "ON code_index.chunks USING GIN (symbol gin_trgm_ops)",
    "CREATE INDEX IF NOT EXISTS ix_code_index_chunks_path_trgm "
    "ON code_index.chunks USING GIN (path gin_trgm_ops)",
    "CREATE INDEX IF NOT EXISTS ix_code_index_symbols_project_id "
    "ON code_index.symbols (project_id)",
    "CREATE INDEX IF NOT EXISTS ix_code_index_symbols_file_id ON code_index.symbols (file_id)",
    "CREATE INDEX IF NOT EXISTS ix_code_index_symbols_scip ON code_index.symbols (scip_symbol)",
    "CREATE INDEX IF NOT EXISTS ix_code_index_symbol_refs_project_id "
    "ON code_index.symbol_refs (project_id)",
    "CREATE INDEX IF NOT EXISTS ix_code_index_symbol_refs_file_id "
    "ON code_index.symbol_refs (file_id)",
    "CREATE INDEX IF NOT EXISTS ix_code_index_symbol_refs_scip "
    "ON code_index.symbol_refs (scip_symbol)",
    "CREATE INDEX IF NOT EXISTS ix_code_index_symbol_edges_project_id "
    "ON code_index.symbol_edges (project_id)",
    """
    CREATE TABLE IF NOT EXISTS code_index.file_notes (
        project_id VARCHAR(36) NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        path TEXT NOT NULL,
        summary TEXT NOT NULL,
        content_hash VARCHAR(64) NOT NULL,
        updated_by TEXT NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (project_id, path)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_code_index_file_notes_project_id "
    "ON code_index.file_notes (project_id)",
)

_lock = asyncio.Lock()


async def ensure_index_schema(session: AsyncSession) -> None:
    """Recreate the ``code_index`` schema only if it is missing. Idempotent (AC15).

    The happy path is two cheap ``to_regclass`` lookups (embeddings + file_notes).
    Returning after embeddings alone would skip healing ``file_notes`` (INV-GUIDE-7).
    """
    if await _schema_intact(session):
        return
    async with _lock:
        if await _schema_intact(session):
            return
        for statement in _DDL:
            await session.execute(text(statement))


async def _schema_intact(session: AsyncSession) -> bool:
    embeddings = await session.execute(text("SELECT to_regclass('code_index.embeddings')"))
    notes = await session.execute(text("SELECT to_regclass('code_index.file_notes')"))
    return embeddings.scalar() is not None and notes.scalar() is not None
