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

MatchedMode = Literal["exact", "fuzzy", "symbol", "fts", "glob"]
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


@dataclass(frozen=True)
class SearchResult:
    """Keyword-only search payload. T04 adds semantic hits on top of this."""

    hits: list[SearchHit]
    semantic_available: bool
    mode: str


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
) -> SearchResult:
    """Exact + fuzzy + symbol + glob keyword search (FR20, FR21, FR29).

    T04 should call this and merge semantic hits; do not duplicate the SQL.
    """
    await ensure_index_schema(session)
    row = await resolve_project(session, project)
    q = query.strip()
    if not q:
        raise ValueError("query must not be empty")
    cap = max(1, min(limit, 100))

    root: Path | None
    try:
        root = resolve_project_root(row.root_path)
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
        entries = await get_section(session, project=row.id, section=SECTION_FOCUS)
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

    ident = _IDENT.match(q) is not None
    like = "%" + _like_escape(q) + "%"

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
                COALESCE(similarity(c.symbol, :q), 0.0) * 0.9,
                COALESCE(similarity(c.content, :q), 0.0) * 0.7,
                COALESCE(ts_rank(c.tsv, plainto_tsquery('simple', :q)), 0.0)
            ) AS score,
            CASE
                WHEN c.symbol ILIKE :like ESCAPE '\\' THEN 'symbol'
                WHEN c.content ILIKE :like ESCAPE '\\' THEN 'exact'
                WHEN c.tsv @@ plainto_tsquery('simple', :q) THEN 'fts'
                WHEN similarity(c.symbol, :q) > 0.3 THEN 'symbol'
                WHEN similarity(c.content, :q) > 0.2 THEN 'fuzzy'
                WHEN c.path ILIKE :like ESCAPE '\\' THEN 'glob'
                ELSE 'fuzzy'
            END AS matched_mode
        FROM code_index.chunks c
        WHERE c.project_id = :project_id
          {scope_sql}
          {glob_sql}
          AND (
                c.tsv @@ plainto_tsquery('simple', :q)
             OR c.content ILIKE :like ESCAPE '\\'
             OR c.symbol ILIKE :like ESCAPE '\\'
             OR c.path ILIKE :like ESCAPE '\\'
             OR (c.symbol IS NOT NULL AND similarity(c.symbol, :q) > 0.3)
             OR similarity(c.content, :q) > 0.2
          )
        ORDER BY
            CASE WHEN :ident AND c.symbol ILIKE :like ESCAPE '\\' THEN 0 ELSE 1 END,
            score DESC,
            c.path ASC,
            c.start_line ASC
        LIMIT :limit
    """
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
    if "file_set" in params:
        stmt = stmt.bindparams(bindparam("file_set", expanding=True))
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
            )
        )
    return SearchResult(hits=hits, semantic_available=False, mode="keyword")
