"""Tree-sitter ``tags``-style symbol + import extraction (FR23c fallback, D14, AC23).

Used for any language whose SCIP indexer is missing or failed. Lower fidelity
than SCIP (no cross-file reference resolution, no generics), but definitions,
local references, and import/include dependency edges are enough for structural
search and T05's code map.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tree_sitter import Query, QueryCursor
from tree_sitter_language_pack import get_language, get_parser

from pcs.index.chunker import LanguageName, chunk_source, language_for

_DEF_KINDS = {"function", "class", "module"}

# Per-language import/include capture. Each query binds one @module node whose
# text (quotes stripped) is the raw dependency target.
_IMPORT_QUERY: dict[LanguageName, str] = {
    "python": """
        (import_statement (dotted_name) @module)
        (import_statement (aliased_import (dotted_name) @module))
        (import_from_statement module_name: (dotted_name) @module)
        (import_from_statement module_name: (relative_import) @module)
    """,
    "javascript": """
        (import_statement source: (string) @module)
    """,
    "typescript": """
        (import_statement source: (string) @module)
    """,
    "tsx": """
        (import_statement source: (string) @module)
    """,
    "go": """
        (import_spec path: (interpreted_string_literal) @module)
        (import_spec (interpreted_string_literal) @module)
    """,
    "rust": """
        (use_declaration argument: (scoped_identifier) @module)
        (use_declaration argument: (identifier) @module)
        (use_declaration argument: (scoped_use_list path: (_) @module))
        (use_declaration argument: (use_wildcard (_) @module))
    """,
    "java": """
        (import_declaration (scoped_identifier) @module)
        (import_declaration (identifier) @module)
    """,
    "csharp": """
        (using_directive (qualified_name) @module)
        (using_directive (identifier_name) @module)
    """,
    "c": """
        (preproc_include path: (string_literal) @module)
        (preproc_include path: (system_lib_string) @module)
    """,
    "cpp": """
        (preproc_include path: (string_literal) @module)
        (preproc_include path: (system_lib_string) @module)
    """,
}


@dataclass(frozen=True)
class SymbolDef:
    """One definition site (FR23b)."""

    name: str
    kind: str
    start_line: int
    end_line: int
    signature: str | None
    scip_symbol: str


@dataclass(frozen=True)
class ImportEdge:
    """One raw import/include target from a source file (FR32 dependency edge)."""

    module: str


def _synthetic_symbol(path: str, name: str, start_line: int) -> str:
    # SCIP-shaped local symbol id: `local <descriptor>`; unique per (file, name, line).
    return f"local {path}#{name}:{start_line}"


def extract_definitions(path: Path, text: str) -> list[SymbolDef]:
    """Definitions via the shared chunker's boundary nodes (consistent with FR23a)."""
    rel = path.as_posix()
    out: list[SymbolDef] = []
    for chunk in chunk_source(path, text):
        if chunk.symbol is None or chunk.kind not in _DEF_KINDS:
            continue
        signature = chunk.content.splitlines()[0].strip()[:200] if chunk.content else None
        out.append(
            SymbolDef(
                name=chunk.symbol,
                kind=chunk.kind,
                start_line=chunk.start_line,
                end_line=chunk.end_line,
                signature=signature,
                scip_symbol=_synthetic_symbol(rel, chunk.symbol, chunk.start_line),
            )
        )
    return out


def _strip_quotes(raw: str) -> str:
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] in "\"'<`" and raw[-1] in "\"'>`":
        return raw[1:-1]
    return raw


def extract_imports(path: Path, text: str) -> list[ImportEdge]:
    """Import/include targets for the dependency graph (FR32, tags fallback)."""
    language = language_for(path)
    if language is None:
        return []
    query_src = _IMPORT_QUERY.get(language)
    if query_src is None:
        return []
    try:
        ts_language = get_language(language)
        parser = get_parser(language)
    except LookupError:
        return []
    source = text.encode("utf-8")
    tree = parser.parse(source)
    try:
        query = Query(ts_language, query_src)
    except Exception:
        # A grammar/query mismatch must never break indexing — fall back to no edges.
        return []
    cursor = QueryCursor(query)
    captures = cursor.captures(tree.root_node)
    seen: set[str] = set()
    edges: list[ImportEdge] = []
    for name, nodes in captures.items():
        if name != "module":
            continue
        for node in nodes:
            raw = source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")
            module = _strip_quotes(raw)
            if module and module not in seen:
                seen.add(module)
                edges.append(ImportEdge(module=module))
    return edges


def resolve_import_target(src_path: str, module: str, known_paths: set[str]) -> str:
    """Best-effort map an import string onto an indexed file path, else ``""``.

    Handles relative JS/TS imports and Python dotted modules; anything external
    (``react``, ``fmt``, ``<stdio.h>``) stays unresolved — still a valid edge.
    """
    if not module:
        return ""
    if module.startswith("."):
        base = Path(src_path).parent
        target = (base / module).as_posix()
        target = str(Path(target))
        for ext in ("", ".ts", ".tsx", ".js", ".jsx", ".py", "/index.ts", "/index.js"):
            candidate = f"{target}{ext}".lstrip("./")
            if candidate in known_paths:
                return candidate
        return ""
    dotted = module.replace(".", "/")
    for ext in (".py", "/__init__.py"):
        candidate = f"{dotted}{ext}"
        if candidate in known_paths:
            return candidate
        for known in known_paths:
            if known.endswith(f"/{candidate}"):
                return known
    return ""
