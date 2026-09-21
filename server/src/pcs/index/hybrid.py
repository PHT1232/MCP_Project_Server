"""Hybrid keyword+semantic search orchestration (FR20, FR22).

The single entry point every agent-facing surface calls. Keyword hits come from
:func:`pcs.index.search.keyword_search` (never re-implemented here); semantic hits
are added only when an embedding backend is configured and chunks are embedded
(D7, AC10, AC21).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from pcs.context.service import resolve_project
from pcs.index.embedding import EmbeddingBackend, EmbeddingProviderError, get_embedding_backend
from pcs.index.models import IndexStatus
from pcs.index.schema import ensure_index_schema
from pcs.index.search import (
    SearchHit,
    SearchScopeName,
    keyword_search,
    resolve_search_scope,
)
from pcs.index.semantic import RankedHit, hybrid_rank, semantic_search

logger = logging.getLogger("pcs")


@dataclass(frozen=True)
class HybridResult:
    """Merged, ranked result plus why semantic did or did not run (FR21, AC10)."""

    ranked: list[RankedHit]
    keyword_hits: list[SearchHit]
    semantic_hits: list[SearchHit] = field(default_factory=list)
    semantic_available: bool = False
    semantic_note: str | None = None
    # Total rows the keyword/FTS/fuzzy pool matched, before any LIMIT — lets a
    # caller tell "there were only 3 matches" apart from "there were 30 and
    # you got the top 20" instead of silently guessing.
    keyword_total_matches: int = 0


_UNAVAILABLE = (
    "Semantic search is unavailable: no embedding backend is configured "
    "(set PCS_EMBEDDING_BACKEND) (FR28, D7, AC10)."
)
_NOT_EMBEDDED = (
    "Semantic search is configured but no chunks are embedded yet — run reindex "
    "with the backend enabled."
)
_RUNTIME_UNAVAILABLE = (
    "Semantic query is temporarily unavailable because the embedding provider failed; "
    "results were returned using keyword search."
)
_SAFE_LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/+:-]{0,199}")


def _safe_log_label(value: str) -> str:
    """Keep model/backend identifiers useful without admitting URLs or credentials."""
    if "://" in value or "@" in value or _SAFE_LABEL.fullmatch(value) is None:
        return "<redacted>"
    return value


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
    count_matches: bool = True,
    prefer_semantic_over_fuzzy: bool = False,
) -> HybridResult:
    """Keyword + (optional) semantic search, fused by reciprocal rank (FR20, FR22).

    ``count_matches`` passes through to :func:`keyword_search` — set False
    only when the caller never surfaces ``total_matches``/``truncated``.

    ``prefer_semantic_over_fuzzy=True`` drops keyword_search's fuzzy
    ``similarity()`` tier (``fuzzy=False``) whenever semantic search is
    actually going to run this call (a backend is configured and chunks are
    embedded) — semantic search already covers "resembles this free-text
    query" for natural-language input, and fuzzy-matching a long query
    against every chunk both costs the most of anything in this function and
    tends to rank incidental textual resemblance over real relevance. If
    semantic ends up unavailable for this project, fuzzy stays on regardless
    — it's the only fallback for natural-language queries without it. Default
    False preserves exact current behavior (used by the ``search_code``
    surface, where fuzzy substring/typo tolerance on short explicit queries
    is valuable independent of semantic availability).
    """
    await ensure_index_schema(session)
    row = await resolve_project(session, project)

    backend = backend if backend is not None else await get_embedding_backend(session)
    semantic_ready = False
    if backend is not None:
        status = await session.get(IndexStatus, row.id)
        embedded = (
            status.embedded_chunk_count
            if status is not None and not status.reindex_required
            else 0
        )
        semantic_ready = bool(embedded)

    keyword_result = await keyword_search(
        session,
        project=row.id,
        query=query,
        scope=scope,
        subtree=subtree,
        files=files,
        globs=globs,
        limit=max(limit, 20),
        count_matches=count_matches,
        fuzzy=not (prefer_semantic_over_fuzzy and semantic_ready),
    )
    keyword_hits = keyword_result.hits

    if backend is None:
        ranked = hybrid_rank(keyword_hits, [], limit=limit)
        return HybridResult(
            ranked=ranked,
            keyword_hits=keyword_hits,
            semantic_available=False,
            semantic_note=_UNAVAILABLE,
            keyword_total_matches=keyword_result.total_matches,
        )

    if not semantic_ready:
        ranked = hybrid_rank(keyword_hits, [], limit=limit)
        return HybridResult(
            ranked=ranked,
            keyword_hits=keyword_hits,
            semantic_available=False,
            semantic_note=_NOT_EMBEDDED,
            keyword_total_matches=keyword_result.total_matches,
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
    try:
        semantic_hits = await semantic_search(
            session,
            project_id=row.id,
            query=query,
            backend=backend,
            clause=clause,
            limit=max(limit, 20),
        )
    except EmbeddingProviderError as exc:
        # Do not include the exception message/cause: provider errors may carry
        # request URLs, credentials, or raw response bodies (NFR6, NFR11).
        logger.warning(
            "semantic_query_failed",
            extra={
                "context": {
                    "project": row.id,
                    "model": _safe_log_label(backend.name),
                    "backend": _safe_log_label(type(backend).__name__),
                    "error_type": exc.kind,
                }
            },
        )
        ranked = hybrid_rank(keyword_hits, [], limit=limit)
        return HybridResult(
            ranked=ranked,
            keyword_hits=keyword_hits,
            semantic_available=False,
            semantic_note=_RUNTIME_UNAVAILABLE,
            keyword_total_matches=keyword_result.total_matches,
        )
    ranked = hybrid_rank(keyword_hits, semantic_hits, limit=limit)
    return HybridResult(
        ranked=ranked,
        keyword_hits=keyword_hits,
        semantic_hits=semantic_hits,
        semantic_available=True,
        semantic_note=None,
        keyword_total_matches=keyword_result.total_matches,
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

    Semantic mode handles NL directly — when it's available, the primary
    call passes ``prefer_semantic_over_fuzzy=True`` so keyword_search skips
    its expensive fuzzy ``similarity()`` tier and lets semantic ranking do
    that job (cheaper and more precise for long free-text input; see
    ``hybrid_search``'s docstring). In keyword-only mode (no semantic
    backend, or the embedding provider just failed/timed out) a plain
    ``plainto_tsquery`` of a long sentence AND-matches nothing, so we also
    probe the salient terms individually and fuse the keyword hits.

    This per-term fan-out passes ``fuzzy=False``. Measured live against a
    real 43-term task description with the embedding provider unreachable:
    fuzzy's ``similarity()`` tier averaged ~787ms/term (sequential scan, not
    index-accelerated — see ``keyword_search``'s own docstring) vs ~141ms/term
    without it, a 5.6x difference that turns this fallback into the dominant
    cost of the whole call (the exact scenario most likely to hit it — an
    embedding backend that's down or slow — already pays its own
    ``embedding_timeout_seconds`` before this loop even starts). Exact/prefix
    keyword and FTS matching on these already-salient, dictionary-shaped
    terms covers the common case; fuzzy's marginal recall for typos in a
    human/agent-authored task description isn't worth 5.6x the latency in
    a path whose whole purpose is graceful degradation.
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
        count_matches=False,
        prefer_semantic_over_fuzzy=True,
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
            count_matches=False,
            files=files,
            limit=limit,
            fuzzy=False,
        )
        extra.extend(result.hits)
    ranked = hybrid_rank(extra, [], limit=limit)
    return HybridResult(
        ranked=ranked,
        keyword_hits=extra,
        semantic_available=False,
        semantic_note=primary.semantic_note,
        # Best-effort: primary's own query total, not a true sum across the
        # per-term fan-out below (those overlap, so summing would double-count).
        keyword_total_matches=primary.keyword_total_matches,
    )
