"""Code-map service: build the dependency/structure graph with level-of-detail.

No MCP/HTTP imports — the tool, resource and HTTP route wrap these functions
(AGENTS.md server conventions).

Design (FR32a / D9): the map is a **stateless projection** over the live code
index, never materialised. ``get_code_map`` reads only the rows under the
requested ``scope`` and aggregates them server-side into a small response:

* default (no scope): the repo's top directory tier + edges aggregated between
  those top nodes.
* ``scope`` = a subtree path: that subtree's children ``depth`` levels down, with
  edges among them and cross-boundary edges collapsed to a sibling node.
* ``scope`` = an indexed file path: that file's key symbols + its file-level
  dependencies/dependents (the node-inspector zoom, FR34 data).

Because nothing is cached, ``reindex`` (FR24/FR27) rebuilding
``code_index.{files,chunks,symbols,symbol_edges}`` is all the regeneration FR39
needs — the next ``get_code_map`` call reflects the new structure. There is no
separate manual diagramming step and nothing to invalidate.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from pcs.context.service import get_section, resolve_project
from pcs.context.types import (
    SECTION_BLOCKERS,
    SECTION_BUGS,
    SECTION_FOCUS,
    SECTION_REQUIREMENTS,
)
from pcs.index.models import IndexStatus
from pcs.index.schema import ensure_index_schema
from pcs.index.search import _extract_focus_paths  # FR33: same heuristic as scope='focus'

logger = logging.getLogger("pcs")

# Level-of-detail guards (D9). A single call reveals at most MAX_DEPTH levels
# below its scope; the default is one.
DEFAULT_DEPTH = 1
MAX_DEPTH = 3

# Overlay sections joined against node paths (FR33). Order = overlay_legend.
OVERLAY_SECTIONS: tuple[str, ...] = (
    SECTION_FOCUS,
    SECTION_BLOCKERS,
    SECTION_BUGS,
    SECTION_REQUIREMENTS,
)

_LIKE_ESCAPE = str.maketrans({"\\": "\\\\", "%": "\\%", "_": "\\_"})


class CodeMapError(ValueError):
    """A bad scope / depth request (surfaced as HTTP 400 / an MCP tool error)."""


@dataclass(frozen=True)
class _FileRow:
    path: str
    size_bytes: int
    language: str | None
    loc: int
    symbol_count: int


@dataclass
class _NodeAcc:
    node_id: str
    kind: str  # 'directory' | 'file' | 'symbol' | 'external'
    path: str
    label: str
    is_dir: bool = False
    outside_scope: bool = False
    languages: Counter[str] = field(default_factory=Counter)
    loc: int = 0
    size_bytes: int = 0
    file_count: int = 0
    symbol_count: int = 0
    fan_in: set[str] = field(default_factory=set)
    fan_out: set[str] = field(default_factory=set)


def _normalize_scope(scope: str | None) -> str:
    """Repo-relative, no leading/trailing slash, no traversal. ``''`` == repo root."""
    if scope is None:
        return ""
    cleaned = scope.strip().strip("/").replace("\\", "/")
    if not cleaned:
        return ""
    parts = cleaned.split("/")
    if any(p in ("", ".", "..") for p in parts):
        raise CodeMapError(f"invalid scope {scope!r}")
    return "/".join(parts)


def _like_prefix(value: str) -> str:
    return value.translate(_LIKE_ESCAPE) + "/%"


def _in_scope(path: str, scope: str) -> bool:
    return scope == "" or path == scope or path.startswith(scope + "/")


def _tier_node(path: str, cutoff: int) -> tuple[str, str, bool]:
    """Map a file path to its node at ``cutoff`` path segments.

    Returns ``(node_id, node_path, is_directory)``. A file with more segments than
    ``cutoff`` collapses into the directory node at that depth; otherwise the file
    is its own leaf node.
    """
    segs = path.split("/")
    if len(segs) <= cutoff:
        return f"file:{path}", path, False
    node_path = "/".join(segs[:cutoff])
    return f"dir:{node_path}", node_path, True


def _boundary_node(path: str, sibling_depth: int) -> tuple[str, str, bool]:
    """Collapse an out-of-scope edge endpoint to a sibling of the current scope."""
    segs = path.split("/")
    n = max(1, min(sibling_depth, len(segs)))
    node_path = "/".join(segs[:n])
    is_dir = n < len(segs)
    return (f"dir:{node_path}" if is_dir else f"file:{node_path}"), node_path, is_dir


def _touch(node_path: str, linked: str) -> bool:
    """True when a context entry's linked path lands on this node's subtree.

    Matches the node exactly, anything inside it, or an ancestor directory of it
    (a blocker linked to ``a/b/c.py`` marks the ``a`` and ``a/b`` nodes; one
    linked to ``a/b`` marks the file node ``a/b/c.py``).
    """
    p = linked.strip().strip("/")
    if not p or not node_path:
        return False
    return p == node_path or p.startswith(node_path + "/") or node_path.startswith(p + "/")


async def _load_files(session: AsyncSession, pid: str, scope: str) -> list[_FileRow]:
    sql = text(
        """
        SELECT f.path AS path,
               COALESCE(f.size_bytes, 0) AS size_bytes,
               f.language AS language,
               COALESCE(cm.loc, 0) AS loc,
               COALESCE(sm.symbol_count, 0) AS symbol_count
        FROM code_index.files f
        LEFT JOIN (
            SELECT path, MAX(end_line) AS loc
            FROM code_index.chunks
            WHERE project_id = :pid
            GROUP BY path
        ) cm ON cm.path = f.path
        LEFT JOIN (
            SELECT path, COUNT(*) AS symbol_count
            FROM code_index.symbols
            WHERE project_id = :pid
            GROUP BY path
        ) sm ON sm.path = f.path
        WHERE f.project_id = :pid
          AND f.skipped = false
          AND (:scope = '' OR f.path = :scope OR f.path LIKE :scope_like ESCAPE '\\')
        ORDER BY f.path
        """
    )
    params = {
        "pid": pid,
        "scope": scope,
        "scope_like": _like_prefix(scope) if scope else "%",
    }
    result = await session.execute(sql, params)
    return [
        _FileRow(
            path=str(r.path),
            size_bytes=int(r.size_bytes),
            language=str(r.language) if r.language is not None else None,
            loc=int(r.loc or 0),
            symbol_count=int(r.symbol_count or 0),
        )
        for r in result
    ]


async def _load_edges(session: AsyncSession, pid: str) -> list[tuple[str, str, str, str]]:
    """All dependency edges: ``(src_path, dst_path, dst_module, kind)`` (T04 shape)."""
    result = await session.execute(
        text(
            "SELECT src_path, dst_path, dst_module, kind "
            "FROM code_index.symbol_edges WHERE project_id = :pid"
        ),
        {"pid": pid},
    )
    return [
        (str(r.src_path), str(r.dst_path or ""), str(r.dst_module or ""), str(r.kind or "import"))
        for r in result
    ]


async def _load_overlay(session: AsyncSession, pid: str) -> dict[str, list[list[str]]]:
    """Per section, the list of path-sets each open entry references (FR33)."""
    out: dict[str, list[list[str]]] = {}
    for section in OVERLAY_SECTIONS:
        entries = await get_section(session, project=pid, section=section)
        if section == SECTION_FOCUS:
            out[section] = [_extract_focus_paths([f"{e.headline}\n{e.detail}"]) for e in entries]
        else:
            out[section] = [[str(p) for p in e.linked_files] for e in entries]
    return out


def _overlay_for(node_path: str, overlay: dict[str, list[list[str]]]) -> dict[str, object]:
    counts: dict[str, object] = {}
    hot = 0
    for section, entry_paths in overlay.items():
        n = sum(1 for paths in entry_paths if any(_touch(node_path, p) for p in paths))
        counts[section] = n
        if section in (SECTION_BLOCKERS, SECTION_BUGS):
            hot += n
    counts["hot"] = hot > 0
    return counts


async def _generated_from(session: AsyncSession, pid: str) -> dict[str, object]:
    status = await session.get(IndexStatus, pid)
    if status is None:
        return {"indexed": False}
    return {
        "indexed": status.last_full_at is not None,
        "last_full_at": status.last_full_at.isoformat() if status.last_full_at else None,
        "last_incremental_at": (
            status.last_incremental_at.isoformat() if status.last_incremental_at else None
        ),
        "last_commit": status.last_commit,
        "symbol_modes": dict(status.symbol_modes or {}),
    }


def _node_dict(acc: _NodeAcc, overlay: dict[str, list[list[str]]]) -> dict[str, object]:
    language = acc.languages.most_common(1)[0][0] if acc.languages else None
    has_children = acc.is_dir or (acc.kind == "file" and acc.symbol_count > 0)
    return {
        "id": acc.node_id,
        "kind": acc.kind,
        "path": acc.path,
        "label": acc.label,
        "language": language,
        "loc": acc.loc,
        "size_bytes": acc.size_bytes,
        "file_count": acc.file_count,
        "symbol_count": acc.symbol_count,
        "fan_in": len(acc.fan_in),
        "fan_out": len(acc.fan_out),
        "has_children": has_children,
        "outside_scope": acc.outside_scope,
        "overlay": _overlay_for(acc.path, overlay),
    }


async def _symbol_map(
    session: AsyncSession,
    *,
    pid: str,
    project_name: str,
    file_path: str,
    overlay: dict[str, list[list[str]]],
    provenance: dict[str, object],
) -> dict[str, object]:
    """``scope`` is an indexed file: return its key symbols + file-level deps (FR34)."""
    sym_rows = await session.execute(
        text(
            "SELECT name, kind, language, start_line, end_line, signature "
            "FROM code_index.symbols WHERE project_id = :pid AND path = :p "
            "ORDER BY start_line"
        ),
        {"pid": pid, "p": file_path},
    )
    nodes: list[dict[str, object]] = []
    for r in sym_rows:
        start = int(r.start_line)
        end = int(r.end_line)
        nodes.append(
            {
                "id": f"sym:{file_path}#{r.name}:{start}",
                "kind": "symbol",
                "path": file_path,
                "label": str(r.name),
                "symbol_kind": str(r.kind),
                "language": str(r.language) if r.language is not None else None,
                "start_line": start,
                "end_line": end,
                "loc": max(1, end - start + 1),
                "signature": str(r.signature) if r.signature is not None else None,
                "has_children": False,
                "outside_scope": False,
                "overlay": _overlay_for(file_path, overlay),
            }
        )

    edges = await _load_edges(session, pid)
    dependencies = sorted(
        {dst or mod for src, dst, mod, _ in edges if src == file_path and (dst or mod)}
    )
    dependents = sorted({src for src, dst, _, _ in edges if dst == file_path})
    return {
        "project": pid,
        "project_name": project_name,
        "scope": file_path,
        "scope_kind": "file",
        "depth": 0,
        "generated_from": provenance,
        "nodes": nodes,
        "edges": [],
        "dependencies": dependencies,
        "dependents": dependents,
        "stats": {
            "node_count": len(nodes),
            "edge_count": 0,
            "truncated": False,
        },
        "overlay_legend": list(OVERLAY_SECTIONS),
    }


async def get_code_map(
    session: AsyncSession,
    *,
    project: str,
    scope: str | None = None,
    depth: int = DEFAULT_DEPTH,
    include_external: bool = False,
) -> dict[str, object]:
    """Aggregated dependency/structure graph for one tier of the project (FR32, FR32a).

    Args:
        project: exact project name or id (D3).
        scope: repo-relative subtree path to expand, or an indexed file path for
            its symbol view. ``None`` / ``""`` = the repo's top directory tier.
        depth: how many levels below ``scope`` to reveal (1..``MAX_DEPTH``).
        include_external: also emit aggregated edges to external packages as
            ``external`` nodes (off by default to keep the default payload tight).

    The response only ever describes the requested tier — expanding a scope never
    re-sends the rest of the graph (D9 / AC20).
    """
    row = await resolve_project(session, project)
    await ensure_index_schema(session)
    pid = row.id
    scope_norm = _normalize_scope(scope)
    depth_c = max(1, min(int(depth), MAX_DEPTH))

    provenance = await _generated_from(session, pid)
    overlay = await _load_overlay(session, pid)

    files = await _load_files(session, pid, scope_norm)
    if scope_norm and not files:
        raise CodeMapError(f"scope {scope_norm!r} has no indexed files in project {row.name!r}")

    is_file_scope = (
        scope_norm != ""
        and any(f.path == scope_norm for f in files)
        and not any(f.path.startswith(scope_norm + "/") for f in files)
    )
    if is_file_scope:
        return await _symbol_map(
            session,
            pid=pid,
            project_name=row.name,
            file_path=scope_norm,
            overlay=overlay,
            provenance=provenance,
        )

    scope_depth = 0 if scope_norm == "" else len(scope_norm.split("/"))
    cutoff = scope_depth + depth_c

    nodes: dict[str, _NodeAcc] = {}
    path_to_node: dict[str, str] = {}

    def _ensure(node_id: str, kind: str, node_path: str, *, outside: bool = False) -> _NodeAcc:
        acc = nodes.get(node_id)
        if acc is None:
            label = node_path.split("/")[-1] if node_path else node_path
            acc = _NodeAcc(
                node_id=node_id,
                kind=kind,
                path=node_path,
                label=label or node_path,
                outside_scope=outside,
            )
            nodes[node_id] = acc
        return acc

    for fr in files:
        node_id, node_path, is_dir = _tier_node(fr.path, cutoff)
        acc = _ensure(node_id, "directory" if is_dir else "file", node_path)
        acc.is_dir = acc.is_dir or is_dir
        acc.file_count += 1
        acc.size_bytes += fr.size_bytes
        acc.loc += fr.loc
        acc.symbol_count += fr.symbol_count
        if fr.language:
            acc.languages[fr.language] += 1
        path_to_node[fr.path] = node_id

    def _endpoint(path: str) -> str | None:
        if _in_scope(path, scope_norm):
            return path_to_node.get(path)
        node_id, node_path, is_dir = _boundary_node(path, scope_depth + 1)
        _ensure(node_id, "directory" if is_dir else "file", node_path, outside=True).is_dir = is_dir
        return node_id

    edge_weights: Counter[tuple[str, str, str]] = Counter()
    raw_edges = await _load_edges(session, pid)
    total_resolved = 0
    for src_path, dst_path, dst_module, kind in raw_edges:
        if dst_path:
            total_resolved += 1
        src_here = _in_scope(src_path, scope_norm)
        dst_here = _in_scope(dst_path, scope_norm) if dst_path else False
        if dst_path:
            if not src_here and not dst_here:
                continue
            src_node = _endpoint(src_path)
            dst_node = _endpoint(dst_path)
        elif include_external and src_here:
            src_node = _endpoint(src_path)
            dst_node = f"ext:{dst_module}" if dst_module else None
            if dst_node is not None:
                _ensure(dst_node, "external", dst_module)
        else:
            continue
        if src_node is None or dst_node is None or src_node == dst_node:
            continue
        edge_weights[(src_node, dst_node, kind)] += 1
        nodes[src_node].fan_out.add(dst_node)
        nodes[dst_node].fan_in.add(src_node)

    node_list = [_node_dict(nodes[k], overlay) for k in sorted(nodes)]
    edge_list = [
        {"source": s, "target": t, "kind": k, "weight": w}
        for (s, t, k), w in sorted(edge_weights.items())
    ]

    total_files = await session.scalar(
        text("SELECT COUNT(*) FROM code_index.files WHERE project_id = :pid AND skipped = false"),
        {"pid": pid},
    )
    return {
        "project": pid,
        "project_name": row.name,
        "scope": scope_norm or None,
        "scope_kind": "directory",
        "depth": depth_c,
        "generated_from": provenance,
        "nodes": node_list,
        "edges": edge_list,
        "stats": {
            "total_files": int(total_files or 0),
            "total_resolved_edges": total_resolved,
            "node_count": len(node_list),
            "edge_count": len(edge_list),
            "truncated": False,
        },
        "overlay_legend": list(OVERLAY_SECTIONS),
    }
