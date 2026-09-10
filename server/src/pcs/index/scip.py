"""Per-language SCIP indexer integration (FR23b, FR23c, D14).

Each supported family has a SCIP indexer that emits a protobuf ``index.scip``
(https://github.com/sourcegraph/scip). We invoke it as a subprocess in the repo
root, then normalise its output into the same symbol model the tree-sitter
``tags`` fallback fills (:mod:`pcs.index.symbols`).

No indexer binary is bundled. When one is absent or fails, the caller falls back
to tags mode and :func:`pcs.index.service.get_index_status` reports the language
as ``fallback`` (AC23). ``PCS_SCIP_INDEXERS`` overrides binary names/paths.

The protobuf reader here is a minimal, dependency-free decoder for exactly the
SCIP fields we consume (Index → Document → SymbolInformation / Occurrence).
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from pcs.config import get_settings
from pcs.index.chunker import LanguageName

logger = logging.getLogger("pcs")

# language -> (default binary, *args). Args produce ./index.scip in cwd.
SCIP_INDEXERS: dict[LanguageName, tuple[str, ...]] = {
    "typescript": ("scip-typescript", "index", "--output", "index.scip"),
    "tsx": ("scip-typescript", "index", "--output", "index.scip"),
    "javascript": ("scip-typescript", "index", "--output", "index.scip"),
    "python": ("scip-python", "index", "--output", "index.scip", "."),
    "java": ("scip-java", "index", "--output", "index.scip"),
    "go": ("scip-go", "--output", "index.scip"),
    "rust": ("rust-analyzer", "scip", ".", "--output", "index.scip"),
    "csharp": ("scip-dotnet", "index", "--output", "index.scip"),
    "c": ("scip-clang", "--out", "index.scip"),
    "cpp": ("scip-clang", "--out", "index.scip"),
}

SYMBOL_ROLE_DEFINITION = 0x1


def _overrides() -> dict[str, str]:
    raw = get_settings().scip_indexers.strip()
    out: dict[str, str] = {}
    for part in raw.split(","):
        part = part.strip()
        if "=" in part:
            lang, binary = part.split("=", 1)
            out[lang.strip()] = binary.strip()
    return out


def scip_binary_for(language: LanguageName) -> str | None:
    """Resolve the SCIP binary for ``language`` on PATH (or via override), else None."""
    spec = SCIP_INDEXERS.get(language)
    if spec is None:
        return None
    override = _overrides().get(language)
    name = override or spec[0]
    return shutil.which(name)


def scip_available(language: LanguageName) -> bool:
    """Whether this environment can run the SCIP indexer for ``language`` (AC23)."""
    return scip_binary_for(language) is not None


# --------------------------------------------------------------------------- #
# Minimal protobuf wire decoder (only what SCIP needs).
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class _Field:
    """One decoded protobuf field. ``data`` set for wire type 2, else ``num``."""

    no: int
    wire: int
    num: int = 0
    data: bytes = b""

    @property
    def is_bytes(self) -> bool:
        return self.wire == 2


def _read_varint(buf: bytes, pos: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while True:
        byte = buf[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7


def _iter_fields(buf: bytes) -> Iterator[_Field]:
    pos = 0
    while pos < len(buf):
        key, pos = _read_varint(buf, pos)
        field_no = key >> 3
        wire = key & 0x7
        if wire == 0:
            value, pos = _read_varint(buf, pos)
            yield _Field(field_no, wire, num=value)
        elif wire == 2:
            length, pos = _read_varint(buf, pos)
            yield _Field(field_no, wire, data=buf[pos : pos + length])
            pos += length
        elif wire == 1:
            pos += 8
        elif wire == 5:
            pos += 4
        else:  # pragma: no cover - SCIP does not use groups
            raise ValueError(f"unsupported protobuf wire type {wire}")


def _packed_int32(data: bytes) -> list[int]:
    out: list[int] = []
    pos = 0
    while pos < len(data):
        value, pos = _read_varint(data, pos)
        out.append(value)
    return out


@dataclass
class ScipSymbol:
    """Normalised SCIP definition."""

    symbol: str
    display_name: str
    kind: int
    start_line: int
    end_line: int


@dataclass
class ScipDocument:
    relative_path: str
    language: str
    symbols: list[ScipSymbol] = field(default_factory=list)
    # (symbol, is_definition, start_line, end_line)
    occurrences: list[tuple[str, bool, int, int]] = field(default_factory=list)


@dataclass
class ScipIndex:
    documents: list[ScipDocument] = field(default_factory=list)


def _parse_symbol_information(data: bytes) -> tuple[str, str, int]:
    symbol = ""
    display_name = ""
    kind = 0
    for f in _iter_fields(data):
        if f.no == 1 and f.is_bytes:
            symbol = f.data.decode("utf-8", errors="replace")
        elif f.no == 4 and not f.is_bytes:
            kind = f.num
        elif f.no == 5 and f.is_bytes:
            display_name = f.data.decode("utf-8", errors="replace")
    return symbol, display_name, kind


def _parse_occurrence(data: bytes) -> tuple[str, bool, int, int]:
    rng: list[int] = []
    symbol = ""
    roles = 0
    for f in _iter_fields(data):
        if f.no == 1:
            if f.is_bytes:
                rng = _packed_int32(f.data)
            else:
                rng.append(f.num)
        elif f.no == 2 and f.is_bytes:
            symbol = f.data.decode("utf-8", errors="replace")
        elif f.no == 3 and not f.is_bytes:
            roles = f.num
    start_line = rng[0] + 1 if rng else 1
    end_line = (rng[2] if len(rng) >= 3 else rng[0]) + 1 if rng else 1
    return symbol, bool(roles & SYMBOL_ROLE_DEFINITION), start_line, end_line


def _parse_document(data: bytes) -> ScipDocument:
    doc = ScipDocument(relative_path="", language="")
    for f in _iter_fields(data):
        if f.no == 1 and f.is_bytes:
            doc.language = f.data.decode("utf-8", errors="replace")
        elif f.no == 2 and f.is_bytes:
            doc.relative_path = f.data.decode("utf-8", errors="replace")
        elif f.no == 3 and f.is_bytes:
            sym, is_def, s, e = _parse_occurrence(f.data)
            if sym:
                doc.occurrences.append((sym, is_def, s, e))
        elif f.no == 4 and f.is_bytes:
            sym, name, sym_kind = _parse_symbol_information(f.data)
            if sym:
                doc.symbols.append(ScipSymbol(sym, name, sym_kind, 1, 1))
    # Fill definition line ranges from occurrences.
    def_ranges = {sym: (s, e) for sym, is_def, s, e in doc.occurrences if is_def}
    for symbol in doc.symbols:
        if symbol.symbol in def_ranges:
            symbol.start_line, symbol.end_line = def_ranges[symbol.symbol]
    return doc


def parse_scip_index(data: bytes) -> ScipIndex:
    """Decode an ``index.scip`` protobuf into the fields we normalise."""
    index = ScipIndex()
    for f in _iter_fields(data):
        if f.no == 2 and f.is_bytes:
            index.documents.append(_parse_document(f.data))
    return index


async def run_scip_indexer(
    language: LanguageName, root: Path, *, timeout: float = 300.0
) -> ScipIndex | None:
    """Run the SCIP indexer for ``language`` in ``root`` and parse ``index.scip``.

    Returns ``None`` (caller uses the tags fallback) when the binary is missing,
    exits non-zero, times out, or emits no readable index.
    """
    binary = scip_binary_for(language)
    spec = SCIP_INDEXERS.get(language)
    if binary is None or spec is None:
        return None
    args = [binary, *spec[1:]]
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=root,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            proc.kill()
            logger.warning("scip_timeout", extra={"context": {"language": language}})
            return None
    except OSError as exc:
        logger.warning(
            "scip_spawn_failed", extra={"context": {"language": language, "error": str(exc)}}
        )
        return None
    if proc.returncode != 0:
        logger.warning(
            "scip_nonzero",
            extra={"context": {"language": language, "code": proc.returncode}},
        )
        return None
    out_file = root / "index.scip"
    if not out_file.is_file():
        return None
    try:
        return parse_scip_index(out_file.read_bytes())
    except (OSError, ValueError, IndexError) as exc:
        logger.warning(
            "scip_parse_failed", extra={"context": {"language": language, "error": str(exc)}}
        )
        return None
    finally:
        out_file.unlink(missing_ok=True)
