"""Rebuild the ``code_index`` schema if it was dropped (AC15, NFR12)."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def ensure_index_schema(session: AsyncSession) -> None:
    """Create extension/schema/tables/indexes if missing. Idempotent (AC15)."""
    await session.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    await session.execute(text("CREATE SCHEMA IF NOT EXISTS code_index"))
    await session.execute(
        text(
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
            """
        )
    )
    await session.execute(
        text(
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
                indexed_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
    )
    await session.execute(
        text(
            """
            ALTER TABLE code_index.chunks
            ADD COLUMN IF NOT EXISTS tsv tsvector
            GENERATED ALWAYS AS (
                to_tsvector('simple', coalesce(symbol, '') || ' ' || content)
            ) STORED
            """
        )
    )
    await session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS code_index.status (
                project_id VARCHAR(36) PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
                last_full_at TIMESTAMPTZ,
                last_incremental_at TIMESTAMPTZ,
                last_commit VARCHAR(64),
                file_count INTEGER NOT NULL DEFAULT 0,
                chunk_count INTEGER NOT NULL DEFAULT 0,
                skipped_count INTEGER NOT NULL DEFAULT 0,
                state VARCHAR(16) NOT NULL DEFAULT 'idle'
            )
            """
        )
    )
    await session.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_code_index_files_project_id "
            "ON code_index.files (project_id)"
        )
    )
    await session.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_code_index_chunks_project_id "
            "ON code_index.chunks (project_id)"
        )
    )
    await session.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_code_index_chunks_file_id ON code_index.chunks (file_id)"
        )
    )
    await session.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_code_index_chunks_tsv "
            "ON code_index.chunks USING GIN (tsv)"
        )
    )
    await session.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_code_index_chunks_content_trgm "
            "ON code_index.chunks USING GIN (content gin_trgm_ops)"
        )
    )
    await session.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_code_index_chunks_symbol_trgm "
            "ON code_index.chunks USING GIN (symbol gin_trgm_ops)"
        )
    )
    await session.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_code_index_chunks_path_trgm "
            "ON code_index.chunks USING GIN (path gin_trgm_ops)"
        )
    )
