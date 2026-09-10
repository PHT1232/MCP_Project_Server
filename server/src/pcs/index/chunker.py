"""tree-sitter chunking on function/class/module boundaries (FR23, FR23a)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, cast

from tree_sitter_language_pack import get_parser

LanguageName = Literal[
    "python",
    "javascript",
    "typescript",
    "tsx",
    "java",
    "go",
    "rust",
    "csharp",
    "c",
    "cpp",
]

# FR23a: seven families. Keys are tree-sitter-language-pack names.
_EXT_LANG: dict[str, LanguageName] = {
    ".py": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".cs": "csharp",
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".hh": "cpp",
}

# Node types that start a chunk, per language.
_BOUNDARY: dict[LanguageName, frozenset[str]] = {
    "python": frozenset({"function_definition", "class_definition"}),
    "javascript": frozenset(
        {
            "function_declaration",
            "function_expression",
            "arrow_function",
            "class_declaration",
            "method_definition",
            "export_statement",
        }
    ),
    "typescript": frozenset(
        {
            "function_declaration",
            "function_expression",
            "arrow_function",
            "class_declaration",
            "method_definition",
            "export_statement",
            "interface_declaration",
            "type_alias_declaration",
        }
    ),
    "tsx": frozenset(
        {
            "function_declaration",
            "function_expression",
            "arrow_function",
            "class_declaration",
            "method_definition",
            "export_statement",
            "interface_declaration",
        }
    ),
    "java": frozenset(
        {
            "class_declaration",
            "interface_declaration",
            "enum_declaration",
            "method_declaration",
            "constructor_declaration",
        }
    ),
    "go": frozenset({"function_declaration", "method_declaration", "type_declaration"}),
    "rust": frozenset(
        {
            "function_item",
            "impl_item",
            "struct_item",
            "enum_item",
            "trait_item",
            "mod_item",
        }
    ),
    "csharp": frozenset(
        {
            "class_declaration",
            "interface_declaration",
            "struct_declaration",
            "enum_declaration",
            "method_declaration",
            "constructor_declaration",
        }
    ),
    "c": frozenset({"function_definition", "struct_specifier", "enum_specifier"}),
    "cpp": frozenset(
        {
            "function_definition",
            "class_specifier",
            "struct_specifier",
            "enum_specifier",
            "namespace_definition",
        }
    ),
}

_KIND: dict[str, str] = {
    "function_definition": "function",
    "function_declaration": "function",
    "function_expression": "function",
    "arrow_function": "function",
    "function_item": "function",
    "method_definition": "function",
    "method_declaration": "function",
    "constructor_declaration": "function",
    "class_definition": "class",
    "class_declaration": "class",
    "class_specifier": "class",
    "interface_declaration": "class",
    "enum_declaration": "class",
    "enum_specifier": "class",
    "struct_declaration": "class",
    "struct_specifier": "class",
    "struct_item": "class",
    "enum_item": "class",
    "trait_item": "class",
    "impl_item": "class",
    "type_declaration": "class",
    "type_alias_declaration": "class",
    "mod_item": "module",
    "namespace_definition": "module",
    "export_statement": "module",
}

PLAINTEXT_WINDOW = 80


class _TSNode(Protocol):
    """Minimal tree-sitter node surface used by the chunker."""

    type: str
    start_byte: int
    end_byte: int
    start_point: Sequence[int]
    end_point: Sequence[int]
    children: list[_TSNode]

    def child_by_field_name(self, name: str) -> _TSNode | None: ...


@dataclass(frozen=True)
class Chunk:
    """One indexable span (FR21)."""

    start_line: int
    end_line: int
    kind: str
    symbol: str | None
    content: str
    language: str | None


def language_for(path: Path) -> LanguageName | None:
    """Map a file suffix onto a tree-sitter language name, if supported (FR23a)."""
    return _EXT_LANG.get(path.suffix.lower())


def _node_text(source: bytes, node: _TSNode) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _symbol_name(node: _TSNode, source: bytes) -> str | None:
    name = node.child_by_field_name("name")
    if name is not None:
        text = _node_text(source, name).strip()
        return text or None
    for child in node.children:
        if child.type in {"identifier", "type_identifier", "property_identifier"}:
            text = _node_text(source, child).strip()
            return text or None
    return None


def _walk_boundaries(
    node: _TSNode, source: bytes, types: frozenset[str], out: list[Chunk], language: str
) -> None:
    if node.type in types:
        start = int(node.start_point[0]) + 1
        end = int(node.end_point[0]) + 1
        out.append(
            Chunk(
                start_line=start,
                end_line=end,
                kind=_KIND.get(node.type, "code"),
                symbol=_symbol_name(node, source),
                content=_node_text(source, node),
                language=language,
            )
        )
    for child in node.children:
        _walk_boundaries(child, source, types, out, language)


def _plaintext_chunks(text: str, language: str | None) -> list[Chunk]:
    lines = text.splitlines()
    if not lines:
        return []
    chunks: list[Chunk] = []
    for i in range(0, len(lines), PLAINTEXT_WINDOW):
        window = lines[i : i + PLAINTEXT_WINDOW]
        start = i + 1
        end = i + len(window)
        chunks.append(
            Chunk(
                start_line=start,
                end_line=end,
                kind="text",
                symbol=None,
                content="\n".join(window),
                language=language,
            )
        )
    return chunks


def _line_count(text: str) -> int:
    if not text:
        return 1
    return text.count("\n") + (0 if text.endswith("\n") else 1)


def chunk_source(path: Path, text: str) -> list[Chunk]:
    """Split ``text`` into chunks. tree-sitter for FR23a languages, else plaintext (FR23)."""
    language = language_for(path)
    if language is None:
        return _plaintext_chunks(text, None)
    try:
        parser = get_parser(language)
    except LookupError:
        return _plaintext_chunks(text, language)
    source = text.encode("utf-8")
    tree = parser.parse(source)
    types = _BOUNDARY.get(language, frozenset())
    out: list[Chunk] = []
    if types:
        _walk_boundaries(cast(_TSNode, tree.root_node), source, types, out, language)
    if not out:
        end = _line_count(text)
        out.append(
            Chunk(
                start_line=1,
                end_line=max(1, end),
                kind="module",
                symbol=path.stem,
                content=text,
                language=language,
            )
        )
        if end > PLAINTEXT_WINDOW * 2:
            out.extend(_plaintext_chunks(text, language))
    return out
