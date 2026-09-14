"""Embedding pipeline + semantic search + hybrid ranking (FR20, FR22, FR28, NFR10).

Semantic hits are merged with :func:`pcs.index.search.keyword_search` output by
reciprocal-rank fusion. Nothing here re-implements the FTS/trigram SQL.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from pcs.index.embedding import EmbeddingBackend, EmbeddingProviderError
from pcs.index.search import (
    ScopeClause,
    SearchHit,
    compute_stale,
    make_snippet,
)

logger = logging.getLogger("pcs")

_RRF_K = 60


def _vec_literal(values: list[float]) -> str:
    return "[" + ",".join(repr(float(v)) for v in values) + "]"


async def embed_pending_chunks(
    session: AsyncSession,
    *,
    project_id: str,
    backend: EmbeddingBackend,
    batch_size: int = 64,
) -> tuple[int, int]:
    """Embed chunks whose content hash has no vector for ``backend.name`` (NFR10).

    Returns ``(embedded_this_run, embedded_total_for_project)``. Unchanged chunks
    are skipped because their ``chunk_hash`` already has a cache row.
    """
    missing = await session.execute(
        text(
            """
            SELECT DISTINCT c.chunk_hash, c.content
            FROM code_index.chunks c
            LEFT JOIN code_index.embeddings e
              ON e.chunk_hash = c.chunk_hash AND e.model = :model
            WHERE c.project_id = :pid
              AND c.chunk_hash IS NOT NULL
              AND e.chunk_hash IS NULL
            """
        ),
        {"pid": project_id, "model": backend.name},
    )
    rows = [(str(h), str(body)) for h, body in missing.all()]
    embedded = 0
    for start in range(0, len(rows), max(1, batch_size)):
        batch = rows[start : start + max(1, batch_size)]
        vectors = await backend.embed([body for _, body in batch])
        for (chunk_hash, _body), vector in zip(batch, vectors, strict=True):
            await session.execute(
                text(
                    """
                    INSERT INTO code_index.embeddings (chunk_hash, model, dim, embedding)
                    VALUES (:h, :model, :dim, CAST(:vec AS vector))
                    ON CONFLICT (chunk_hash, model) DO NOTHING
                    """
                ),
                {
                    "h": chunk_hash,
                    "model": backend.name,
                    "dim": len(vector),
                    "vec": _vec_literal(vector),
                },
            )
            embedded += 1

    total = await session.execute(
        text(
            """
            SELECT count(DISTINCT c.chunk_hash)
            FROM code_index.chunks c
            JOIN code_index.embeddings e
              ON e.chunk_hash = c.chunk_hash AND e.model = :model
            WHERE c.project_id = :pid
            """
        ),
        {"pid": project_id, "model": backend.name},
    )
    return embedded, int(total.scalar_one())


async def semantic_search(
    session: AsyncSession,
    *,
    project_id: str,
    query: str,
    backend: EmbeddingBackend,
    clause: ScopeClause,
    limit: int,
) -> list[SearchHit]:
    """Vector search over embedded chunks, scoped like keyword search (FR20, FR29)."""
    try:
        # Keep the provider catch at the exact adapter boundary. Database and
        # result-processing errors below must remain visible (NFR8).
        vectors = await backend.embed([query])
    except EmbeddingProviderError:
        raise
    except TimeoutError as exc:
        raise EmbeddingProviderError("timeout") from exc
    except ConnectionError as exc:
        raise EmbeddingProviderError("connection") from exc
    if not vectors:
        return []
    qvec = _vec_literal(vectors[0])
    sql = f"""
        SELECT c.path, c.start_line, c.end_line, c.content, c.symbol, c.kind,
               c.language, c.git_blob, c.git_commit, c.content_hash,
               (e.embedding <=> CAST(:qvec AS vector)) AS distance
        FROM code_index.chunks c
        JOIN code_index.embeddings e
          ON e.chunk_hash = c.chunk_hash AND e.model = :model
        WHERE c.project_id = :pid
          {clause.scope_sql}
          {clause.glob_sql}
        ORDER BY distance ASC, c.path ASC, c.start_line ASC
        LIMIT :limit
    """
    params: dict[str, object] = {
        "pid": project_id,
        "model": backend.name,
        "qvec": qvec,
        "limit": max(1, min(limit, 100)),
        **clause.all_params,
    }
    stmt = text(sql)
    if clause.has_file_set:
        stmt = stmt.bindparams(bindparam("file_set", expanding=True))
    result = await session.execute(stmt, params)
    hits: list[SearchHit] = []
    for rec in result.mappings():
        distance = float(rec["distance"])
        hits.append(
            SearchHit(
                path=str(rec["path"]),
                start_line=int(rec["start_line"]),
                end_line=int(rec["end_line"]),
                snippet=make_snippet(str(rec["content"]), query),
                score=max(0.0, 1.0 - distance),
                matched_mode="semantic",
                stale=compute_stale(clause.root, str(rec["path"]), rec["content_hash"]),
                symbol=str(rec["symbol"]) if rec["symbol"] is not None else None,
                kind=str(rec["kind"]),
                language=str(rec["language"]) if rec["language"] is not None else None,
                git_blob=str(rec["git_blob"]) if rec["git_blob"] is not None else None,
                git_commit=str(rec["git_commit"]) if rec["git_commit"] is not None else None,
                content=str(rec["content"]),
            )
        )
    return hits


@dataclass(frozen=True)
class RankedHit:
    """A hit plus which retrieval modes contributed and the fused score (FR21)."""

    hit: SearchHit
    modes: tuple[str, ...]
    fused_score: float

    @property
    def mode_label(self) -> str:
        """``hybrid`` when both matched, else the single contributing mode (FR21)."""
        if "keyword" in self.modes and "semantic" in self.modes:
            return "hybrid"
        if self.modes == ("semantic",):
            return "semantic"
        return self.hit.matched_mode


def _key(hit: SearchHit) -> tuple[str, int, int]:
    return (hit.path, hit.start_line, hit.end_line)


def hybrid_rank(
    keyword_hits: list[SearchHit],
    semantic_hits: list[SearchHit],
    *,
    limit: int,
) -> list[RankedHit]:
    """Reciprocal-rank fusion of the two hit lists (FR20 "combinable", FR22)."""
    fused: dict[tuple[str, int, int], RankedHit] = {}
    for source, hits in (("keyword", keyword_hits), ("semantic", semantic_hits)):
        for rank, hit in enumerate(hits):
            contribution = 1.0 / (_RRF_K + rank + 1)
            key = _key(hit)
            existing = fused.get(key)
            if existing is None:
                fused[key] = RankedHit(hit=hit, modes=(source,), fused_score=contribution)
            else:
                # Prefer the keyword hit (has an exact snippet) when both matched.
                base = existing.hit if source == "semantic" else hit
                fused[key] = RankedHit(
                    hit=base,
                    modes=(*existing.modes, source),
                    fused_score=existing.fused_score + contribution,
                )
    ranked = sorted(
        fused.values(),
        key=lambda r: (-r.fused_score, r.hit.path, r.hit.start_line),
    )
    return ranked[: max(1, limit)]
