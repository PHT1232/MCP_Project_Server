"""Keyword / structural search over indexed chunks (FR20 keyword half, FR21, FR29).

This is the internal API T04 wraps with hybrid ranking. No embeddings here.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from pcs.context.service import get_section, resolve_project
from pcs.context.types import SECTION_FOCUS
from pcs.index.ignore import PathTraversalError, resolve_project_root, resolve_under_root
from pcs.index.schema import ensure_index_schema

MatchedMode = Literal["exact", "fuzzy", "symbol", "fts", "glob", "semantic", "hybrid"]
SearchScopeName = Literal["project", "subtree", "files", "focus"]

_PATH_TOKEN = re.compile(
    r"(?:`([^`]+)`)|"
    r"((?:[\w.-]+/)+[\w.-]+)|"
    r"([\w.-]+\.(?:py|ts|tsx|js|jsx|mjs|cjs|java|go|rs|cs|c|h|cc|cpp|hpp|md|json|toml|yml|yaml))"
)
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_GLOB_CHARS = re.compile(r"[*?]")


@dataclass(frozen=True)
class SearchHit:
    """One keyword/structural hit (FR21)."""

    path: str
    start_line: int
    end_line: int
    snippet: str
    score: float
    matched_mode: MatchedMode
    stale: bool
    symbol: str | None
    kind: str
    language: str | None
    git_blob: str | None
    git_commit: str | None
    content: str = ""


@dataclass(frozen=True)
class SearchResult:
    """Keyword-only search payload. T04 adds semantic hits on top of this."""

    hits: list[SearchHit]
    semantic_available: bool
    mode: str
    total_matches: int = 0


def _like_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _glob_to_like(pattern: str) -> str:
    """Convert a filepath glob into SQL LIKE, keeping user wildcards."""
    out: list[str] = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("%")
            i += 3
            continue
        ch = pattern[i]
        if ch == "*":
            out.append("%")
        elif ch == "?":
            out.append("_")
        elif ch in {"%", "_", "\\"}:
            out.append("\\" + ch)
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def make_snippet(content: str, query: str, max_len: int = 240) -> str:
    """Window around the first case-insensitive match of ``query`` in ``content``."""
    needle = query.strip()
    if not needle or _GLOB_CHARS.search(needle):
        text = content.strip()
        return text if len(text) <= max_len else text[: max_len - 1] + "…"
    lower = content.lower()
    idx = lower.find(needle.lower())
    if idx < 0:
        idx = 0
    start = max(0, idx - 40)
    end = min(len(content), start + max_len)
    snippet = content[start:end].strip("\n")
    if start > 0:
        snippet = "…" + snippet
    if end < len(content):
        snippet = snippet + "…"
    return snippet


def _file_digest(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _extract_focus_paths(texts: list[str]) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for blob in texts:
        for match in _PATH_TOKEN.finditer(blob):
            token = next((g for g in match.groups() if g), None)
            if token is None:
                continue
            cleaned = token.strip().lstrip("./")
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                found.append(cleaned)
    return found


def _scope_sql(
    *,
    scope: SearchScopeName,
    subtree: str | None,
    files: list[str] | None,
    focus_paths: list[str],
) -> tuple[str, dict[str, object]]:
    if scope == "project":
        return "", {}
    if scope == "subtree":
        if not subtree or not subtree.strip():
            raise ValueError("scope='subtree' requires subtree=")
        prefix = subtree.strip().strip("/")
        return (
            "AND (c.path = :subtree OR c.path LIKE :subtree_like ESCAPE '\\')",
            {"subtree": prefix, "subtree_like": _like_escape(prefix) + "/%"},
        )
    if scope == "files":
        names = [p.strip().lstrip("./") for p in (files or []) if p.strip()]
        if not names:
            raise ValueError("scope='files' requires a non-empty files list")
        return "AND c.path IN :file_set", {"file_set": names}
    # focus
    if not focus_paths:
        return "AND FALSE", {}
    return "AND c.path IN :file_set", {"file_set": focus_paths}


@dataclass(frozen=True)
class ScopeClause:
    """Reusable ``WHERE`` fragments for chunk queries (keyword *and* semantic, FR29)."""

    scope_sql: str
    scope_params: dict[str, object]
    glob_sql: str
    glob_params: dict[str, object]
    root: Path | None

    @property
    def all_params(self) -> dict[str, object]:
        return {**self.scope_params, **self.glob_params}

    @property
    def has_file_set(self) -> bool:
        return "file_set" in self.scope_params


async def resolve_search_scope(
    session: AsyncSession,
    *,
    project_row: object,
    scope: SearchScopeName,
    subtree: str | None,
    files: list[str] | None,
    globs: list[str] | None,
    query: str,
) -> ScopeClause:
    """Turn scope/glob options into SQL fragments over alias ``c`` with path safety (FR29, NFR5).

    Shared by :func:`keyword_search` and the semantic path so the FTS SQL is never
    duplicated (T03 review, notes for T04).
    """
    row = project_row  # a Project ORM row
    root: Path | None
    try:
        root = resolve_project_root(row.root_path)  # type: ignore[attr-defined]
    except FileNotFoundError:
        root = None

    if subtree:
        if root is None:
            raise PathTraversalError("cannot resolve subtree without a readable project root")
        resolve_under_root(root, subtree)
    if files:
        if root is None:
            raise PathTraversalError("cannot resolve file scope without a readable project root")
        for rel in files:
            resolve_under_root(root, rel)

    focus_paths: list[str] = []
    if scope == "focus":
        entries = await get_section(
            session,
            project=row.id,  # type: ignore[attr-defined]
            section=SECTION_FOCUS,
        )
        focus_paths = _extract_focus_paths([f"{e.headline}\n{e.detail}" for e in entries])
        if root is not None:
            safe: list[str] = []
            for rel in focus_paths:
                try:
                    resolve_under_root(root, rel)
                except PathTraversalError:
                    continue
                safe.append(rel)
            focus_paths = safe

    scope_sql, scope_params = _scope_sql(
        scope=scope, subtree=subtree, files=files, focus_paths=focus_paths
    )

    glob_patterns = list(globs or [])
    q = query.strip()
    if _GLOB_CHARS.search(q) and ("/" in q or q.startswith("*.")):
        glob_patterns.append(q)
    glob_sql = ""
    glob_params: dict[str, object] = {}
    if glob_patterns:
        clauses: list[str] = []
        for i, pattern in enumerate(glob_patterns):
            key = f"glob_{i}"
            clauses.append(f"c.path LIKE :{key} ESCAPE '\\'")
            glob_params[key] = _glob_to_like(pattern.lstrip("./"))
        glob_sql = "AND (" + " OR ".join(clauses) + ")"

    return ScopeClause(
        scope_sql=scope_sql,
        scope_params=scope_params,
        glob_sql=glob_sql,
        glob_params=glob_params,
        root=root,
    )


def compute_stale(root: Path | None, path: str, digest: object) -> bool:
    """Working-tree SHA-256 vs indexed hash (NFR9). Shared by keyword + semantic hits."""
    if root is None:
        return digest is not None
    try:
        disk = resolve_under_root(root, path)
    except PathTraversalError:
        return True
    current = _file_digest(disk)
    return current is None or (digest is not None and current != str(digest))


async def keyword_search(
    session: AsyncSession,
    *,
    project: str,
    query: str,
    scope: SearchScopeName = "project",
    subtree: str | None = None,
    files: list[str] | None = None,
    globs: list[str] | None = None,
    limit: int = 20,
    count_matches: bool = True,
    fuzzy: bool = True,
) -> SearchResult:
    """Exact + fuzzy + symbol + glob keyword search (FR20, FR21, FR29).

    T04 should call this and merge semantic hits; do not duplicate the SQL.

    ``count_matches=False`` skips the separate un-LIMITed COUNT(*) query used
    to compute ``total_matches`` (``total_matches`` falls back to
    ``len(hits)``, which is never accurate when results are actually
    truncated). The COUNT re-evaluates the same fuzzy ``similarity()``
    predicates against every row in the project with no LIMIT to short
    -circuit it — for a long free-text query (e.g. a whole task description)
    this can cost well over a second. Only pass ``False`` when the caller
    genuinely never surfaces ``total_matches``/``truncated`` (e.g.
    :func:`pcs.index.hybrid.gather_relevant`'s internal use) — the real
    ``search_code`` surface needs an accurate count and must keep the default.

    ``fuzzy=False`` drops the ``similarity()`` OR-conditions (and their
    contribution to scoring) entirely, keeping only exact/FTS/symbol/path
    matches. ``similarity()`` isn't index-accelerated the way the ``%``
    trigram operator is, so Postgres evaluates it per row for every row that
    reaches the ORDER BY — for a long free-text query this dominates the
    query's cost and, worse, tends to surface incidental noise (text that
    merely resembles the query) over genuinely relevant hits. Only pass
    ``False`` when a stronger relevance signal already covers that job (e.g.
    :func:`pcs.index.hybrid.hybrid_search` when semantic search is available)
    — with no semantic backend, fuzzy matching is the only fallback for
    natural-language queries and must stay on.
    """
    await ensure_index_schema(session)
    row = await resolve_project(session, project)
    q = query.strip()
    if not q:
        raise ValueError("query must not be empty")
    cap = max(1, min(limit, 100))

    clause = await resolve_search_scope(
        session,
        project_row=row,
        scope=scope,
        subtree=subtree,
        files=files,
        globs=globs,
        query=q,
    )
    root = clause.root
    scope_sql, scope_params = clause.scope_sql, clause.scope_params
    glob_sql, glob_params = clause.glob_sql, clause.glob_params

    ident = _IDENT.match(q) is not None
    like = "%" + _like_escape(q) + "%"

    fuzzy_where = (
        """
             OR (c.symbol IS NOT NULL AND similarity(c.symbol, :q) > 0.3)
             OR similarity(c.content, :q) > 0.2"""
        if fuzzy
        else ""
    )
    where_sql = f"""
        c.project_id = :project_id
          {scope_sql}
          {glob_sql}
          AND (
                c.tsv @@ plainto_tsquery('simple', :q)
             OR c.content ILIKE :like ESCAPE '\\'
             OR c.symbol ILIKE :like ESCAPE '\\'
             OR c.path ILIKE :like ESCAPE '\\'{fuzzy_where}
          )
    """

    fuzzy_score = (
        """,
                COALESCE(similarity(c.symbol, :q), 0.0) * 0.9,
                COALESCE(similarity(c.content, :q), 0.0) * 0.7"""
        if fuzzy
        else ""
    )
    fuzzy_case = (
        """
                WHEN similarity(c.symbol, :q) > 0.3 THEN 'symbol'
                WHEN similarity(c.content, :q) > 0.2 THEN 'fuzzy'"""
        if fuzzy
        else ""
    )
    # Unreachable when fuzzy=False: the WHERE clause above only admits
    # tsv/exact/symbol/path matches, and every earlier WHEN already covers
    # those — kept as a safe catchall, never actually hit in that mode.
    else_mode = "'fuzzy'" if fuzzy else "'fts'"

    sql = f"""
        SELECT
            c.path,
            c.start_line,
            c.end_line,
            c.content,
            c.symbol,
            c.kind,
            c.language,
            c.git_blob,
            c.git_commit,
            c.content_hash,
            GREATEST(
                CASE WHEN c.symbol ILIKE :like ESCAPE '\\' THEN 1.0 ELSE 0.0 END,
                CASE WHEN c.content ILIKE :like ESCAPE '\\' THEN 0.85 ELSE 0.0 END,
                CASE WHEN c.path ILIKE :like ESCAPE '\\' THEN 0.5 ELSE 0.0 END,
                COALESCE(ts_rank(c.tsv, plainto_tsquery('simple', :q)), 0.0){fuzzy_score}
            ) AS score,
            CASE
                WHEN c.symbol ILIKE :like ESCAPE '\\' THEN 'symbol'
                WHEN c.content ILIKE :like ESCAPE '\\' THEN 'exact'
                WHEN c.tsv @@ plainto_tsquery('simple', :q) THEN 'fts'{fuzzy_case}
                WHEN c.path ILIKE :like ESCAPE '\\' THEN 'glob'
                ELSE {else_mode}
            END AS matched_mode
        FROM code_index.chunks c
        WHERE {where_sql}
        ORDER BY
            CASE WHEN :ident AND c.symbol ILIKE :like ESCAPE '\\' THEN 0 ELSE 1 END,
            score DESC,
            c.path ASC,
            c.start_line ASC
        LIMIT :limit
    """
    count_sql = f"SELECT COUNT(*) FROM code_index.chunks c WHERE {where_sql}"
    params: dict[str, object] = {
        "project_id": row.id,
        "q": q,
        "like": like,
        "ident": ident,
        "limit": cap,
        **scope_params,
        **glob_params,
    }
    stmt = text(sql)
    count_stmt = text(count_sql)
    if "file_set" in params:
        stmt = stmt.bindparams(bindparam("file_set", expanding=True))
        count_stmt = count_stmt.bindparams(bindparam("file_set", expanding=True))
    result = await session.execute(stmt, params)
    hits: list[SearchHit] = []
    for rec in result.mappings():
        content = str(rec["content"])
        digest = rec["content_hash"]
        stale = False
        if root is not None:
            try:
                disk = resolve_under_root(root, str(rec["path"]))
            except PathTraversalError:
                stale = True
            else:
                current = _file_digest(disk)
                stale = current is None or (digest is not None and current != str(digest))
        elif digest is not None:
            stale = True
        mode_raw = str(rec["matched_mode"])
        allowed: set[str] = {"exact", "fuzzy", "symbol", "fts", "glob"}
        mode = cast(MatchedMode, mode_raw if mode_raw in allowed else "fuzzy")
        hits.append(
            SearchHit(
                path=str(rec["path"]),
                start_line=int(rec["start_line"]),
                end_line=int(rec["end_line"]),
                snippet=make_snippet(content, q),
                score=float(rec["score"]),
                matched_mode=mode,
                stale=stale,
                symbol=str(rec["symbol"]) if rec["symbol"] is not None else None,
                kind=str(rec["kind"]),
                language=str(rec["language"]) if rec["language"] is not None else None,
                git_blob=str(rec["git_blob"]) if rec["git_blob"] is not None else None,
                git_commit=str(rec["git_commit"]) if rec["git_commit"] is not None else None,
                content=content,
            )
        )
    total_matches = len(hits)
    if hits and count_matches:
        count_params = {k: v for k, v in params.items() if k != "limit"}
        total_matches = int((await session.execute(count_stmt, count_params)).scalar_one())
    return SearchResult(
        hits=hits, semantic_available=False, mode="keyword", total_matches=total_matches
    )
