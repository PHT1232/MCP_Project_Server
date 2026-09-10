"""Code-index service: reindex, status, keyword search_code (FR19-FR21, FR24-FR27).

No MCP/HTTP imports — transports wrap these functions (AGENTS.md).
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pcs.context.service import ProjectNotFoundError, resolve_project
from pcs.index.chunker import chunk_source, language_for
from pcs.index.gitutil import blob_for, changed_paths_since, head_commit
from pcs.index.ignore import PathTraversalError, WalkResult, resolve_project_root, walk_repo
from pcs.index.models import IndexChunk, IndexFile, IndexStatus
from pcs.index.schema import ensure_index_schema
from pcs.index.search import SearchHit, SearchResult, SearchScopeName, keyword_search

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
            "semantic_available": False,
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
    blob = await blob_for(root, rel)
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
) -> None:
    await session.execute(delete(IndexFile).where(IndexFile.project_id == project_id))
    for path in walked.files:
        await _index_one_file(
            session, project_id=project_id, root=root, path=path, git_commit=git_commit
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
) -> None:
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
            session, project_id=project_id, root=root, path=current[rel], git_commit=git_commit
        )

    for rel, reason in skipped_map.items():
        if rel not in dirty:
            await _upsert_skipped(
                session, project_id=project_id, rel=rel, reason=reason, git_commit=git_commit
            )

    for rel in existing:
        if rel not in current and rel not in skipped_map and rel not in dirty:
            await _delete_path(session, project_id, rel)


async def reindex(
    session: AsyncSession,
    *,
    project: str,
    incremental: bool = False,
) -> IndexStatusView:
    """Build or refresh the code index (FR24, FR27). First pass is always full."""
    await ensure_index_schema(session)
    row = await resolve_project(session, project, for_update=True)
    root = resolve_project_root(row.root_path)
    status = await _status_row(session, row.id)
    status.state = "running"
    await session.flush()

    walked = walk_repo(root)
    commit = await head_commit(root)
    use_incremental = (
        incremental
        and status.last_full_at is not None
        and status.file_count + status.skipped_count > 0
    )
    try:
        if use_incremental:
            await _incremental_reindex(
                session,
                project_id=row.id,
                root=root,
                walked=walked,
                git_commit=commit,
                last_commit=status.last_commit,
            )
            status.last_incremental_at = _now()
        else:
            await _full_reindex(
                session, project_id=row.id, root=root, walked=walked, git_commit=commit
            )
            status.last_full_at = _now()
            status.last_incremental_at = status.last_full_at
        status.last_commit = commit
        status.state = "idle"
        await _refresh_counts(session, status)
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
            }
        },
    )
    return await get_index_status(session, project=row.id)


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
    )


def _hits_as_dicts(hits: list[SearchHit]) -> list[dict[str, object]]:
    return [
        {
            "path": h.path,
            "start_line": h.start_line,
            "end_line": h.end_line,
            "snippet": h.snippet,
            "score": h.score,
            "matched_mode": h.matched_mode,
            "stale": h.stale,
            "symbol": h.symbol,
            "kind": h.kind,
            "language": h.language,
            "git_blob": h.git_blob,
            "git_commit": h.git_commit,
        }
        for h in hits
    ]


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
    """Keyword-only ``search_code`` (FR20 keyword, FR22 stub until T04 hybrid)."""
    try:
        result: SearchResult = await keyword_search(
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
        "hits": _hits_as_dicts(result.hits),
        "semantic_available": False,
        "mode": "keyword",
        "note": (
            "Semantic search is unavailable until an embedding backend is configured (FR28, AC10)."
        ),
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
