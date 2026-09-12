"""Hybrid keyword+semantic search orchestration (FR20, FR22).

The single entry point every agent-facing surface calls. Keyword hits come from
:func:`pcs.index.search.keyword_search` (never re-implemented here); semantic hits
are added only when an embedding backend is configured and chunks are embedded
(D7, AC10, AC21).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from pcs.context.service import resolve_project
from pcs.index.embedding import EmbeddingBackend, get_embedding_backend
from pcs.index.models import IndexStatus
from pcs.index.schema import ensure_index_schema
from pcs.index.search import (
    SearchHit,
    SearchScopeName,
    keyword_search,
    resolve_search_scope,
)
from pcs.index.semantic import RankedHit, hybrid_rank, semantic_search


@dataclass(frozen=True)
class HybridResult:
    """Merged, ranked result plus why semantic did or did not run (FR21, AC10)."""

    ranked: list[RankedHit]
    keyword_hits: list[SearchHit]
    semantic_hits: list[SearchHit] = field(default_factory=list)
    semantic_available: bool = False
    semantic_note: str | None = None


_UNAVAILABLE = (
    "Semantic search is unavailable: no embedding backend is configured "
    "(set PCS_EMBEDDING_BACKEND) (FR28, D7, AC10)."
)
_NOT_EMBEDDED = (
    "Semantic search is configured but no chunks are embedded yet — run reindex "
    "with the backend enabled."
)


async def hybrid_search(
    session: AsyncSession,
    *,
    project: str,
    query: str,
    scope: SearchScopeName = "project",
    subtree: str | None = None,
    files: list[str] | None = None,
    globs: list[str] | None = None,
    limit: int = 20,
    backend: EmbeddingBackend | None = None,
) -> HybridResult:
    """Keyword + (optional) semantic search, fused by reciprocal rank (FR20, FR22)."""
    await ensure_index_schema(session)
    row = await resolve_project(session, project)

    keyword_result = await keyword_search(
        session,
        project=row.id,
        query=query,
        scope=scope,
        subtree=subtree,
        files=files,
        globs=globs,
        limit=max(limit, 20),
    )
    keyword_hits = keyword_result.hits

    backend = backend if backend is not None else await get_embedding_backend(session)
    if backend is None:
        ranked = hybrid_rank(keyword_hits, [], limit=limit)
        return HybridResult(
            ranked=ranked,
            keyword_hits=keyword_hits,
            semantic_available=False,
            semantic_note=_UNAVAILABLE,
        )

    status = await session.get(IndexStatus, row.id)
    embedded = (
        status.embedded_chunk_count if status is not None and not status.reindex_required else 0
    )
    if not embedded:
        ranked = hybrid_rank(keyword_hits, [], limit=limit)
        return HybridResult(
            ranked=ranked,
            keyword_hits=keyword_hits,
            semantic_available=False,
            semantic_note=_NOT_EMBEDDED,
        )

    clause = await resolve_search_scope(
        session,
        project_row=row,
        scope=scope,
        subtree=subtree,
        files=files,
        globs=globs,
        query=query,
    )
    semantic_hits = await semantic_search(
        session,
        project_id=row.id,
        query=query,
        backend=backend,
        clause=clause,
        limit=max(limit, 20),
    )
    ranked = hybrid_rank(keyword_hits, semantic_hits, limit=limit)
    return HybridResult(
        ranked=ranked,
        keyword_hits=keyword_hits,
        semantic_hits=semantic_hits,
        semantic_available=True,
        semantic_note=None,
    )


_STOP_TEXT = (
    "the a an of to in on for and or is are how do we does can with into that this "
    "add explain implement handle handling use using work works make from what where"
)
_STOPWORDS = frozenset(_STOP_TEXT.split())
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")


async def gather_relevant(
    session: AsyncSession,
    *,
    project: str,
    task: str,
    scope: SearchScopeName = "project",
    subtree: str | None = None,
    files: list[str] | None = None,
    limit: int = 40,
    backend: EmbeddingBackend | None = None,
) -> HybridResult:
    """Relevance for a whole task description (FR22).

    Semantic mode handles NL directly. In keyword-only mode a plain
    ``plainto_tsquery`` of a long sentence AND-matches nothing, so we also probe
    the salient terms individually and fuse the keyword hits.
    """
    primary = await hybrid_search(
        session,
        project=project,
        query=task,
        scope=scope,
        subtree=subtree,
        files=files,
        limit=limit,
        backend=backend,
    )
    if primary.semantic_available or len(primary.ranked) >= 3:
        return primary

    terms = [w.lower() for w in _WORD.findall(task) if w.lower() not in _STOPWORDS]
    seen: set[str] = set()
    extra: list[SearchHit] = list(primary.keyword_hits)
    for term in terms:
        if term in seen:
            continue
        seen.add(term)
        result = await keyword_search(
            session,
            project=project,
            query=term,
            scope=scope,
            subtree=subtree,
            files=files,
            limit=limit,
        )
        extra.extend(result.hits)
    ranked = hybrid_rank(extra, [], limit=limit)
    return HybridResult(
        ranked=ranked,
        keyword_hits=extra,
        semantic_available=False,
        semantic_note=primary.semantic_note,
    )
