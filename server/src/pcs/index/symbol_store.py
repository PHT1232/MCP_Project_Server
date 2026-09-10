"""Persist the normalised SCIP-style symbol model (FR23b, FR23c, D14, AC23).

One code path fills ``code_index.symbols`` / ``symbol_refs`` / ``symbol_edges``
whether the rows came from a real SCIP indexer or the tree-sitter ``tags``
fallback; every row carries ``mode`` so :func:`get_index_status` can report it.
"""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from pcs.index.chunker import LanguageName, language_for
from pcs.index.models import IndexFile, IndexSymbol, IndexSymbolEdge, IndexSymbolRef
from pcs.index.scip import ScipDocument, run_scip_indexer, scip_available
from pcs.index.symbols import extract_definitions, extract_imports, resolve_import_target

logger = logging.getLogger("pcs")

_SCIP_KIND = {
    6: "function",
    9: "class",
    26: "class",
    21: "function",
    17: "field",
}


def _read_text(path: Path) -> str | None:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in data[:8192]:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


async def refresh_symbols(
    session: AsyncSession,
    *,
    project_id: str,
    root: Path,
    only: set[str] | None,
) -> tuple[dict[str, str], int]:
    """(Re)build symbol rows for the project. ``only`` limits it to changed paths.

    Returns ``({language: 'scip'|'fallback'}, symbol_count)``.
    """
    file_rows = (
        (
            await session.execute(
                select(IndexFile).where(
                    IndexFile.project_id == project_id, IndexFile.skipped.is_(False)
                )
            )
        )
        .scalars()
        .all()
    )
    known_paths = {f.path for f in file_rows}
    targets = [
        f for f in file_rows if (only is None or f.path in only) and language_for(root / f.path)
    ]

    if only is None:
        await session.execute(delete(IndexSymbol).where(IndexSymbol.project_id == project_id))
        await session.execute(delete(IndexSymbolRef).where(IndexSymbolRef.project_id == project_id))
        await session.execute(
            delete(IndexSymbolEdge).where(IndexSymbolEdge.project_id == project_id)
        )
    else:
        paths = {f.path for f in targets}
        if paths:
            await session.execute(
                delete(IndexSymbol).where(
                    IndexSymbol.project_id == project_id, IndexSymbol.path.in_(paths)
                )
            )
            await session.execute(
                delete(IndexSymbolRef).where(
                    IndexSymbolRef.project_id == project_id, IndexSymbolRef.path.in_(paths)
                )
            )
            await session.execute(
                delete(IndexSymbolEdge).where(
                    IndexSymbolEdge.project_id == project_id,
                    IndexSymbolEdge.src_path.in_(paths),
                )
            )

    langs: set[LanguageName] = set()
    for f in targets:
        lang = language_for(root / f.path)
        if lang is not None:
            langs.add(lang)

    modes: dict[str, str] = {}
    scip_docs: dict[str, ScipDocument] = {}
    for lang in sorted(langs):
        if scip_available(lang):
            index = await run_scip_indexer(lang, root)
            if index is not None and index.documents:
                modes[lang] = "scip"
                for scip_doc in index.documents:
                    scip_docs[scip_doc.relative_path] = scip_doc
                continue
        modes[lang] = "fallback"

    by_path = {f.path: f for f in targets}
    symbol_count = 0
    for rel, file_row in by_path.items():
        lang = language_for(root / rel)
        text = _read_text(root / rel)
        if text is None:
            continue
        mode = modes.get(str(lang), "fallback")
        doc = scip_docs.get(rel)
        if doc is not None:
            symbol_count += _store_scip(session, project_id, file_row, doc)
        else:
            symbol_count += _store_fallback(
                session, project_id, file_row, Path(rel), text, str(lang)
            )
        for edge in extract_imports(Path(rel), text):
            dst = resolve_import_target(rel, edge.module, known_paths)
            session.add(
                IndexSymbolEdge(
                    project_id=project_id,
                    src_path=rel,
                    dst_path=dst,
                    dst_module=edge.module,
                    kind="import",
                    language=str(lang) if lang else None,
                    mode=mode,
                )
            )
    return modes, symbol_count


def _store_fallback(
    session: AsyncSession,
    project_id: str,
    file_row: IndexFile,
    rel: Path,
    text: str,
    language: str,
) -> int:
    count = 0
    for definition in extract_definitions(rel, text):
        session.add(
            IndexSymbol(
                project_id=project_id,
                file_id=file_row.id,
                path=file_row.path,
                scip_symbol=definition.scip_symbol,
                name=definition.name,
                kind=definition.kind,
                language=language,
                start_line=definition.start_line,
                end_line=definition.end_line,
                signature=definition.signature,
                mode="fallback",
            )
        )
        session.add(
            IndexSymbolRef(
                project_id=project_id,
                file_id=file_row.id,
                path=file_row.path,
                scip_symbol=definition.scip_symbol,
                name=definition.name,
                start_line=definition.start_line,
                end_line=definition.end_line,
                is_definition=True,
                language=language,
                mode="fallback",
            )
        )
        count += 1
    return count


def _store_scip(
    session: AsyncSession,
    project_id: str,
    file_row: IndexFile,
    doc: ScipDocument,
) -> int:
    count = 0
    for sym in doc.symbols:
        session.add(
            IndexSymbol(
                project_id=project_id,
                file_id=file_row.id,
                path=file_row.path,
                scip_symbol=sym.symbol,
                name=sym.display_name or sym.symbol.rsplit("/", 1)[-1].strip("().#"),
                kind=_SCIP_KIND.get(sym.kind, "symbol"),
                language=doc.language or None,
                start_line=sym.start_line,
                end_line=sym.end_line,
                signature=None,
                mode="scip",
            )
        )
        count += 1
    for symbol, is_def, start, end in doc.occurrences:
        session.add(
            IndexSymbolRef(
                project_id=project_id,
                file_id=file_row.id,
                path=file_row.path,
                scip_symbol=symbol,
                name=symbol.rsplit("/", 1)[-1].strip("().#"),
                start_line=start,
                end_line=end,
                is_definition=is_def,
                language=doc.language or None,
                mode="scip",
            )
        )
    return count
