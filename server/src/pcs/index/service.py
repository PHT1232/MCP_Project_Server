"""Code-index service: reindex, status, keyword search_code (FR19-FR21, FR24-FR27).

No MCP/HTTP imports — transports wrap these functions (AGENTS.md).
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from pcs.ai_settings import load_runtime_ai_settings
from pcs.context.service import ProjectNotFoundError, resolve_project
from pcs.index.chunker import chunk_source, language_for
from pcs.index.embedding import get_embedding_backend
from pcs.index.gitutil import blob_map, changed_paths_since, head_commit
from pcs.index.hybrid import HybridResult, hybrid_search
from pcs.index.ignore import PathTraversalError, WalkResult, resolve_project_root, walk_repo
from pcs.index.models import IndexChunk, IndexFile, IndexStatus, IndexSymbol
from pcs.index.schema import ensure_index_schema
from pcs.index.search import SearchScopeName
from pcs.index.semantic import RankedHit, embed_pending_chunks
from pcs.index.symbol_store import refresh_symbols

logger = logging.getLogger("pcs")

_TEXT_SAMPLE = 8192


@dataclass(frozen=True)
class SkippedFile:
    """One path the indexer declined, with reason (FR26)."""

    path: str
    reason: str


@dataclass(frozen=True)
class IndexStatusView:
    """Per-project index counters and timestamps (FR26)."""

    project_id: str
    project_name: str
    state: str
    last_full_at: datetime | None
    last_incremental_at: datetime | None
    last_commit: str | None
    file_count: int
    chunk_count: int
    skipped_count: int
    skipped: list[SkippedFile]
    symbol_modes: dict[str, str] = dataclass_field(default_factory=dict)
    symbol_count: int = 0
    semantic_model: str | None = None
    embedded_chunk_count: int = 0

    @property
    def semantic_available(self) -> bool:
        """True only when a backend is configured AND chunks are embedded (AC21)."""
        return self.semantic_model is not None and self.embedded_chunk_count > 0

    def as_dict(self) -> dict[str, object]:
        """JSON-ready payload for MCP/HTTP."""
        return {
            "project_id": self.project_id,
            "project_name": self.project_name,
            "state": self.state,
            "last_full_at": self.last_full_at.isoformat() if self.last_full_at else None,
            "last_incremental_at": (
                self.last_incremental_at.isoformat() if self.last_incremental_at else None
            ),
            "last_commit": self.last_commit,
            "file_count": self.file_count,
            "chunk_count": self.chunk_count,
            "skipped_count": self.skipped_count,
            "skipped": [{"path": s.path, "reason": s.reason} for s in self.skipped],
            "symbol_count": self.symbol_count,
            "symbol_modes": dict(self.symbol_modes),
            "semantic_available": self.semantic_available,
            "semantic_model": self.semantic_model if self.semantic_available else None,
            "embedded_chunk_count": self.embedded_chunk_count,
            "semantic_note": (
                None
                if self.semantic_available
                else "Semantic search unavailable — set PCS_EMBEDDING_BACKEND and reindex "
                "(FR28, D7, AC10, AC21)."
            ),
        }


def _now() -> datetime:
    return datetime.now(UTC)


def _digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_source(path: Path) -> tuple[str, bytes] | None:
    """Return ``(text, raw)`` or None if the file is binary / unreadable."""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in data[:_TEXT_SAMPLE]:
        return None
    try:
        return data.decode("utf-8"), data
    except UnicodeDecodeError:
        return None


async def _status_row(session: AsyncSession, project_id: str) -> IndexStatus:
    row = await session.get(IndexStatus, project_id)
    if row is None:
        row = IndexStatus(project_id=project_id)
        session.add(row)
        await session.flush()
    return row


async def _delete_path(session: AsyncSession, project_id: str, rel: str) -> None:
    result = await session.execute(
        select(IndexFile).where(IndexFile.project_id == project_id, IndexFile.path == rel)
    )
    file_row = result.scalar_one_or_none()
    if file_row is not None:
        await session.delete(file_row)


async def _upsert_skipped(
    session: AsyncSession,
    *,
    project_id: str,
    rel: str,
    reason: str,
    git_commit: str | None,
) -> None:
    result = await session.execute(
        select(IndexFile).where(IndexFile.project_id == project_id, IndexFile.path == rel)
    )
    file_row = result.scalar_one_or_none()
    if file_row is None:
        file_row = IndexFile(
            project_id=project_id,
            path=rel,
            skipped=True,
            skip_reason=reason,
            git_commit=git_commit,
        )
        session.add(file_row)
        await session.flush()
    else:
        await session.execute(delete(IndexChunk).where(IndexChunk.file_id == file_row.id))
        file_row.skipped = True
        file_row.skip_reason = reason
        file_row.git_commit = git_commit
        file_row.language = None
        file_row.git_blob = None
        file_row.content_hash = None
        file_row.size_bytes = 0
        file_row.indexed_at = _now()


async def _index_one_file(
    session: AsyncSession,
    *,
    project_id: str,
    root: Path,
    path: Path,
    git_commit: str | None,
    blobs: dict[str, str],
) -> str | None:
    """Index one file. Returns a skip reason or None on success."""
    rel = path.resolve().relative_to(root).as_posix()
    parsed = _read_source(path)
    if parsed is None:
        await _upsert_skipped(
            session, project_id=project_id, rel=rel, reason="binary", git_commit=git_commit
        )
        return "binary"
    text, raw = parsed
    digest = _digest_bytes(raw)
    blob = blobs.get(rel)  # F2: one `git ls-tree` per reindex, not per file
    language = language_for(path)
    chunks = chunk_source(path, text)

    result = await session.execute(
        select(IndexFile).where(IndexFile.project_id == project_id, IndexFile.path == rel)
    )
    file_row = result.scalar_one_or_none()
    if file_row is None:
        file_row = IndexFile(project_id=project_id, path=rel)
        session.add(file_row)
        await session.flush()
    else:
        await session.execute(delete(IndexChunk).where(IndexChunk.file_id == file_row.id))

    file_row.language = language
    file_row.git_blob = blob
    file_row.git_commit = git_commit
    file_row.content_hash = digest
    file_row.size_bytes = len(raw)
    file_row.skipped = False
    file_row.skip_reason = None
    file_row.indexed_at = _now()

    for chunk in chunks:
        session.add(
            IndexChunk(
                project_id=project_id,
                file_id=file_row.id,
                path=rel,
                start_line=chunk.start_line,
                end_line=chunk.end_line,
                language=chunk.language,
                kind=chunk.kind,
                symbol=chunk.symbol,
                content=chunk.content,
                git_blob=blob,
                git_commit=git_commit,
                content_hash=digest,
                chunk_hash=_digest_bytes(chunk.content.encode("utf-8")),
                indexed_at=_now(),
            )
        )
    return None


async def _refresh_counts(session: AsyncSession, status: IndexStatus) -> None:
    files = await session.execute(
        select(func.count())
        .select_from(IndexFile)
        .where(IndexFile.project_id == status.project_id, IndexFile.skipped.is_(False))
    )
    skipped = await session.execute(
        select(func.count())
        .select_from(IndexFile)
        .where(IndexFile.project_id == status.project_id, IndexFile.skipped.is_(True))
    )
    chunks = await session.execute(
        select(func.count())
        .select_from(IndexChunk)
        .where(IndexChunk.project_id == status.project_id)
    )
    status.file_count = int(files.scalar_one())
    status.skipped_count = int(skipped.scalar_one())
    status.chunk_count = int(chunks.scalar_one())


def _rel_set(root: Path, files: list[Path]) -> dict[str, Path]:
    return {p.resolve().relative_to(root).as_posix(): p for p in files}


async def _full_reindex(
    session: AsyncSession,
    *,
    project_id: str,
    root: Path,
    walked: WalkResult,
    git_commit: str | None,
    blobs: dict[str, str],
) -> None:
    await session.execute(delete(IndexFile).where(IndexFile.project_id == project_id))
    for path in walked.files:
        await _index_one_file(
            session,
            project_id=project_id,
            root=root,
            path=path,
            git_commit=git_commit,
            blobs=blobs,
        )
    for rel, reason in walked.skipped:
        await _upsert_skipped(
            session, project_id=project_id, rel=rel, reason=reason, git_commit=git_commit
        )


async def _incremental_reindex(
    session: AsyncSession,
    *,
    project_id: str,
    root: Path,
    walked: WalkResult,
    git_commit: str | None,
    last_commit: str | None,
    blobs: dict[str, str],
) -> set[str]:
    """Returns the set of repo-relative paths that were (re)indexed this run."""
    current = _rel_set(root, walked.files)
    skipped_map = dict(walked.skipped)
    existing_result = await session.execute(
        select(IndexFile).where(IndexFile.project_id == project_id)
    )
    existing = {row.path: row for row in existing_result.scalars().all()}

    git_changed = await changed_paths_since(root, last_commit)
    dirty: set[str] = set()
    if git_changed is None:
        dirty.update(current)
        dirty.update(existing)
    else:
        dirty.update(git_changed)
        for rel, row in existing.items():
            if rel in current and not row.skipped and row.content_hash:
                raw_path = current[rel]
                parsed = _read_source(raw_path)
                if parsed is None:
                    dirty.add(rel)
                    continue
                if _digest_bytes(parsed[1]) != row.content_hash:
                    dirty.add(rel)
        for rel in current:
            if rel not in existing:
                dirty.add(rel)

    for rel in sorted(dirty):
        if rel in skipped_map:
            await _upsert_skipped(
                session,
                project_id=project_id,
                rel=rel,
                reason=skipped_map[rel],
                git_commit=git_commit,
            )
            continue
        if rel not in current:
            await _delete_path(session, project_id, rel)
            continue
        await _index_one_file(
            session,
            project_id=project_id,
            root=root,
            path=current[rel],
            git_commit=git_commit,
            blobs=blobs,
        )

    for rel, reason in skipped_map.items():
        if rel not in dirty:
            await _upsert_skipped(
                session, project_id=project_id, rel=rel, reason=reason, git_commit=git_commit
            )

    for rel in existing:
        if rel not in current and rel not in skipped_map and rel not in dirty:
            await _delete_path(session, project_id, rel)

    return {rel for rel in dirty if rel in current and rel not in skipped_map}


async def reindex(
    session: AsyncSession,
    *,
    project: str,
    incremental: bool = False,
) -> IndexStatusView:
    """Build or refresh the code index (FR24, FR27). First pass is always full.

    F5 (T03 review): the index lock is the ``code_index.status`` row, NOT the
    ``projects`` row — a long reindex must not block T01 context writes.
    """
    await ensure_index_schema(session)
    row = await resolve_project(session, project)
    root = resolve_project_root(row.root_path)
    status = await _status_row(session, row.id)
    await session.execute(
        text("SELECT project_id FROM code_index.status WHERE project_id = :pid FOR UPDATE"),
        {"pid": row.id},
    )
    status.state = "running"
    await session.flush()

    walked = walk_repo(root)
    commit = await head_commit(root)
    blobs = await blob_map(root)
    use_incremental = (
        incremental
        and status.last_full_at is not None
        and status.file_count + status.skipped_count > 0
    )
    try:
        changed: set[str] | None
        if use_incremental:
            changed = await _incremental_reindex(
                session,
                project_id=row.id,
                root=root,
                walked=walked,
                git_commit=commit,
                last_commit=status.last_commit,
                blobs=blobs,
            )
            status.last_incremental_at = _now()
        else:
            await _full_reindex(
                session,
                project_id=row.id,
                root=root,
                walked=walked,
                git_commit=commit,
                blobs=blobs,
            )
            status.last_full_at = _now()
            status.last_incremental_at = status.last_full_at
            changed = None
        await session.flush()
        modes, symbol_count = await refresh_symbols(
            session, project_id=row.id, root=root, only=changed
        )
        if changed is None:
            status.symbol_modes = modes
            status.symbol_count = symbol_count
        else:
            merged = dict(status.symbol_modes)
            merged.update(modes)
            status.symbol_modes = merged
        embedding_ok = await _embed_index(
            session, project_id=row.id, status=status, full_reindex=not use_incremental
        )
        status.last_commit = commit
        status.state = "idle" if embedding_ok else "error"
        await _refresh_counts(session, status)
        if changed is not None:
            symbol_total = await session.execute(
                select(func.count())
                .select_from(IndexSymbol)
                .where(IndexSymbol.project_id == row.id)
            )
            status.symbol_count = int(symbol_total.scalar_one())
    except Exception:
        status.state = "error"
        logger.exception("reindex failed", extra={"context": {"project": row.id}})
        raise
    logger.info(
        "reindex",
        extra={
            "context": {
                "project": row.id,
                "incremental": use_incremental,
                "files": status.file_count,
                "chunks": status.chunk_count,
                "symbols": status.symbol_count,
                "embedded": status.embedded_chunk_count,
            }
        },
    )
    return await get_index_status(session, project=row.id)


async def _embed_index(
    session: AsyncSession,
    *,
    project_id: str,
    status: IndexStatus,
    full_reindex: bool,
) -> bool:
    """Embed chunks; return false on a redacted provider failure (INV-AISET-5)."""
    runtime = await load_runtime_ai_settings(session)
    backend = await get_embedding_backend(session)
    if backend is None:
        status.semantic_model = None
        status.embedded_chunk_count = 0
        return True
    try:
        _, total = await embed_pending_chunks(
            session,
            project_id=project_id,
            backend=backend,
            batch_size=runtime.embedding.batch_size or 64,
        )
    except Exception:
        status.reindex_required = True
        logger.warning("embedding_failed", extra={"context": {"project": project_id}})
        return False
    status.semantic_model = backend.name
    status.embedded_chunk_count = total
    chunk_total_result = await session.execute(
        select(func.count()).select_from(IndexChunk).where(IndexChunk.project_id == project_id)
    )
    chunk_total = int(chunk_total_result.scalar_one())
    if full_reindex and total == chunk_total:
        status.semantic_provider = runtime.embedding.backend
        status.semantic_base_url = runtime.embedding.base_url
        status.semantic_dimensions = runtime.embedding.dimensions
        status.reindex_required = False
    return True


async def get_index_status(session: AsyncSession, *, project: str) -> IndexStatusView:
    """Return last build times, counts, and skipped-with-reason (FR26)."""
    await ensure_index_schema(session)
    row = await resolve_project(session, project)
    status = await session.get(IndexStatus, row.id)
    skipped_result = await session.execute(
        select(IndexFile)
        .where(IndexFile.project_id == row.id, IndexFile.skipped.is_(True))
        .order_by(IndexFile.path)
        .limit(200)
    )
    skipped = [
        SkippedFile(path=f.path, reason=f.skip_reason or "ignored")
        for f in skipped_result.scalars()
    ]
    if status is None:
        return IndexStatusView(
            project_id=row.id,
            project_name=row.name,
            state="empty",
            last_full_at=None,
            last_incremental_at=None,
            last_commit=None,
            file_count=0,
            chunk_count=0,
            skipped_count=0,
            skipped=[],
        )
    return IndexStatusView(
        project_id=row.id,
        project_name=row.name,
        state=status.state,
        last_full_at=status.last_full_at,
        last_incremental_at=status.last_incremental_at,
        last_commit=status.last_commit,
        file_count=status.file_count,
        chunk_count=status.chunk_count,
        skipped_count=status.skipped_count,
        skipped=skipped,
        symbol_modes=dict(status.symbol_modes or {}),
        symbol_count=status.symbol_count,
        semantic_model=status.semantic_model,
        embedded_chunk_count=status.embedded_chunk_count,
    )


def _ranked_hit_dict(ranked: RankedHit) -> dict[str, object]:
    h = ranked.hit
    return {
        "path": h.path,
        "start_line": h.start_line,
        "end_line": h.end_line,
        "snippet": h.snippet,
        "score": round(ranked.fused_score, 6),
        "matched_mode": ranked.mode_label,
        "retrieval_modes": list(ranked.modes),
        "stale": h.stale,
        "symbol": h.symbol,
        "kind": h.kind,
        "language": h.language,
        "git_blob": h.git_blob,
        "git_commit": h.git_commit,
    }


async def search_code(
    session: AsyncSession,
    *,
    project: str,
    query: str,
    scope: SearchScopeName = "project",
    subtree: str | None = None,
    files: list[str] | None = None,
    globs: list[str] | None = None,
    limit: int = 20,
) -> dict[str, object]:
    """Hybrid keyword + semantic ``search_code`` (FR20, FR21, FR22).

    Falls back to keyword-only with an explicit note when no embedding backend is
    configured or nothing is embedded yet (AC10, AC21).
    """
    try:
        result: HybridResult = await hybrid_search(
            session,
            project=project,
            query=query,
            scope=scope,
            subtree=subtree,
            files=files,
            globs=globs,
            limit=limit,
        )
    except PathTraversalError as exc:
        raise ValueError(str(exc)) from exc
    return {
        "hits": [_ranked_hit_dict(r) for r in result.ranked],
        "semantic_available": result.semantic_available,
        "mode": "hybrid" if result.semantic_available else "keyword",
        "note": result.semantic_note,
    }


async def index_if_root_exists(
    session: AsyncSession, *, project: str, root_path: str | None = None
) -> None:
    """Full index when the project root is a real directory; no-op otherwise (FR24).

    T01 tests register ``root_path='/repos/acme-web'`` which does not exist —
    this must not raise.
    """
    try:
        row = await resolve_project(session, project)
    except ProjectNotFoundError:
        return
    path = Path(root_path if root_path is not None else row.root_path).expanduser()
    if not path.is_dir():
        return
    await reindex(session, project=row.id, incremental=False)
