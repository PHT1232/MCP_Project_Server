"""T04 tests: SCIP-style symbols, embeddings, hybrid search, prepare_task.

Covers AC8, AC10, AC21, AC23, AC19, AC24 plus the F1/F2/F4 follow-ups. Runs on
the real Postgres (pgvector) testcontainer via the shared fixtures.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy import select, text

from pcs.context import service as context_service
from pcs.db.base import session_scope
from pcs.index import retrieval, service
from pcs.index.chunker import chunk_source
from pcs.index.embedding import HashingEmbeddingBackend, set_embedding_backend_override
from pcs.index.scip import ScipIndex, parse_scip_index

pytestmark = pytest.mark.usefixtures("clean_db")

PROJECT = "acme-semantic"
OVERVIEW = "Sample repo for symbol + semantic retrieval tests."


def _sample_repo(root: Path) -> None:
    (root / "shop").mkdir()
    (root / "shop" / "cart.py").write_text(
        "from shop.pricing import unit_price\n\n"
        "def cart_total(items):\n"
        '    """Compute the total price of every item in the shopping cart."""\n'
        "    return sum(unit_price(item) for item in items)\n",
        encoding="utf-8",
    )
    (root / "shop" / "pricing.py").write_text(
        "def unit_price(item):\n    return item.price * item.quantity\n",
        encoding="utf-8",
    )
    (root / "shop" / "auth.py").write_text(
        "def login(username, password):\n"
        '    """Authenticate a user and start a session."""\n'
        "    return username == 'admin'\n",
        encoding="utf-8",
    )
    (root / "shop" / "greeting.py").write_text(
        "def greet(name):\n    return f'hello {name}'\n",
        encoding="utf-8",
    )
    (root / "README.md").write_text("# Shop\nA tiny store.\n", encoding="utf-8")


async def _register_and_index(root: Path, *, incremental: bool = False) -> service.IndexStatusView:
    _sample_repo(root)
    async with session_scope() as session:
        await context_service.register_project(
            session, name=PROJECT, root_path=str(root), overview=OVERVIEW
        )
    async with session_scope() as session:
        return await service.reindex(session, project=PROJECT, incremental=incremental)


@pytest.fixture
def hashing_backend() -> Iterator[None]:
    """Force the bundled offline hashing embedding backend for this test."""
    set_embedding_backend_override(HashingEmbeddingBackend(dimensions=256, model="hashing-test"))
    try:
        yield
    finally:
        set_embedding_backend_override(None, active=False)


@pytest.fixture
def no_backend() -> Iterator[None]:
    """Force "no embedding backend configured" (D7)."""
    set_embedding_backend_override(None, active=True)
    try:
        yield
    finally:
        set_embedding_backend_override(None, active=False)


# --------------------------------------------------------------------------- #
# F4 — chunker overlap dedupe
# --------------------------------------------------------------------------- #


def test_f4_chunker_dedupes_overlapping_nested_chunks() -> None:
    source = (
        "export function foo() {\n  return 1;\n}\n\n"
        "export class Bar {\n  baz() {\n    return 2;\n  }\n}\n"
    )
    chunks = chunk_source(Path("x.ts"), source)
    spans = [(c.start_line, c.end_line) for c in chunks]
    assert len(spans) == len(set(spans)), f"duplicate spans: {spans}"
    # `export function foo` must be one chunk, not the wrapper + the declaration.
    foo = [c for c in chunks if c.symbol == "foo"]
    assert len(foo) == 1
    assert foo[0].kind == "function"


# --------------------------------------------------------------------------- #
# AC23 — supported language, no SCIP indexer → tags fallback + status mode
# --------------------------------------------------------------------------- #


async def test_ac23_tags_fallback_symbol_mode(tmp_path: Path) -> None:
    status = await _register_and_index(tmp_path)
    assert status.symbol_count > 0
    assert "python" in status.symbol_modes
    if shutil.which("scip-python") is None:
        assert status.symbol_modes["python"] == "fallback"
    else:  # pragma: no cover - depends on the host toolchain
        assert status.symbol_modes["python"] in {"scip", "fallback"}

    async with session_scope() as session:
        from pcs.index.models import IndexSymbol, IndexSymbolEdge

        row = await context_service.resolve_project(session, PROJECT)
        names = {
            s.name
            for s in (
                await session.execute(select(IndexSymbol).where(IndexSymbol.project_id == row.id))
            ).scalars()
        }
        edges = (
            (
                await session.execute(
                    select(IndexSymbolEdge).where(IndexSymbolEdge.project_id == row.id)
                )
            )
            .scalars()
            .all()
        )
    assert {"cart_total", "unit_price", "login", "greet"} <= names
    # cart.py imports shop.pricing → a dependency edge, resolved to the file.
    pricing_edges = [e for e in edges if e.src_path == "shop/cart.py"]
    assert any(e.dst_module.startswith("shop.pricing") for e in pricing_edges)
    assert any(e.dst_path == "shop/pricing.py" for e in pricing_edges)


async def test_ac23_status_dict_reports_modes(tmp_path: Path) -> None:
    await _register_and_index(tmp_path)
    async with session_scope() as session:
        payload = (await service.get_index_status(session, project=PROJECT)).as_dict()
    assert isinstance(payload["symbol_modes"], dict)
    assert payload["symbol_modes"].get("python") in {"fallback", "scip"}


# --------------------------------------------------------------------------- #
# AC10 / AC21 — no embedding backend → keyword results + explicit "unavailable"
# --------------------------------------------------------------------------- #


async def test_ac10_no_backend_keyword_results_and_note(tmp_path: Path, no_backend: None) -> None:
    await _register_and_index(tmp_path)
    async with session_scope() as session:
        payload = await service.search_code(session, project=PROJECT, query="cart_total")
    assert payload["semantic_available"] is False
    assert payload["mode"] == "keyword"
    assert payload["note"] and "embedding backend" in str(payload["note"])
    hits = cast(list[dict[str, object]], payload["hits"])
    assert hits and any(h["path"] == "shop/cart.py" for h in hits)


async def test_ac21_status_shows_semantic_unavailable(tmp_path: Path, no_backend: None) -> None:
    status = await _register_and_index(tmp_path)
    payload = status.as_dict()
    assert payload["semantic_available"] is False
    assert payload["semantic_model"] is None
    assert payload["embedded_chunk_count"] == 0
    assert "unavailable" in str(payload["semantic_note"]).lower()


# --------------------------------------------------------------------------- #
# AC8 — NL query returns the right file + symbol on an unseen repo
# --------------------------------------------------------------------------- #


async def test_ac8_natural_language_query_finds_file_and_symbol(
    tmp_path: Path, hashing_backend: None
) -> None:
    status = await _register_and_index(tmp_path)
    assert status.semantic_available is True
    assert status.embedded_chunk_count > 0

    async with session_scope() as session:
        payload = await service.search_code(
            session,
            project=PROJECT,
            query="how do we calculate the total price of the shopping cart",
            limit=5,
        )
    assert payload["semantic_available"] is True
    assert payload["mode"] == "hybrid"
    hits = cast(list[dict[str, object]], payload["hits"])
    assert hits
    top = hits[0]
    assert top["path"] == "shop/cart.py"
    assert top["symbol"] == "cart_total"
    assert top["matched_mode"] in {"semantic", "hybrid"}


async def test_nfr10_unchanged_chunks_not_re_embedded(
    tmp_path: Path, hashing_backend: None
) -> None:
    await _register_and_index(tmp_path)

    async def _created_at() -> dict[str, str]:
        async with session_scope() as session:
            rows = (
                await session.execute(
                    text("SELECT chunk_hash, created_at FROM code_index.embeddings")
                )
            ).all()
        return {str(h): str(ts) for h, ts in rows}

    before = await _created_at()
    assert before

    # Touch one file only; the other files' chunks keep their content hash.
    (tmp_path / "shop" / "greeting.py").write_text(
        "def greet(name):\n    return f'hi there {name}'\n", encoding="utf-8"
    )
    async with session_scope() as session:
        await service.reindex(session, project=PROJECT, incremental=True)

    after = await _created_at()
    unchanged = {h for h in before if h in after}
    assert unchanged, "expected shared chunk hashes across reindex"
    for h in unchanged:
        assert after[h] == before[h], "an unchanged chunk was re-embedded (NFR10)"


# --------------------------------------------------------------------------- #
# AC19 / AC24 — prepare_task split reported and adapts to small context
# --------------------------------------------------------------------------- #


async def test_ac19_prepare_task_reports_split_within_budget(tmp_path: Path) -> None:
    await _register_and_index(tmp_path)
    async with session_scope() as session:
        await context_service.set_current_focus(
            session, project=PROJECT, text="Rework cart_total in shop/cart.py for discounts"
        )
        result = await retrieval.prepare_task(
            session, project=PROJECT, task="add discount handling to the cart total"
        )
    split = cast(dict[str, int], result["split"])
    assert split["budget"] == 4000
    assert split["context_tokens"] <= split["context_cap"]
    assert split["context_tokens"] + split["code_tokens"] <= split["budget"]
    assert result["briefing"]
    assert result["code_chunks"]
    # code floored at 30% of budget when chunks exist
    assert split["code_budget"] >= split["code_floor"]


async def test_ac24_small_context_expands_code_pack(tmp_path: Path) -> None:
    await _register_and_index(tmp_path)
    task = "explain how pricing and cart total work together"

    async with session_scope() as session:
        small = await retrieval.prepare_task(session, project=PROJECT, task=task, max_tokens=2000)
    small_split = cast(dict[str, int], small["split"])

    # Add a lot of curated context so the briefing grows.
    async with session_scope() as session:
        for i in range(12):
            await context_service.add_entry(
                session,
                project=PROJECT,
                section="decisions",
                headline=f"Decision {i}: a long headline describing an architectural choice",
                detail="context " * 40,
            )
        big = await retrieval.prepare_task(session, project=PROJECT, task=task, max_tokens=2000)
    big_split = cast(dict[str, int], big["split"])

    # Small curated context → more of the budget went to code than in the busy case.
    assert small_split["code_tokens"] >= big_split["code_tokens"]
    # And the code pack always keeps at least its 30% floor worth of budget.
    assert small_split["code_budget"] >= small_split["code_floor"]
    assert big_split["context_tokens"] <= big_split["context_cap"]


# --------------------------------------------------------------------------- #
# SCIP protobuf decoder + real-binary gate
# --------------------------------------------------------------------------- #


def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def _tag(field: int, wire: int) -> bytes:
    return _varint((field << 3) | wire)


def _ld(field: int, payload: bytes) -> bytes:
    return _tag(field, 2) + _varint(len(payload)) + payload


def test_parse_scip_index_decodes_documents_and_symbols() -> None:
    # SymbolInformation{ symbol=1, kind=4, display_name=5 }
    sym_info = _ld(1, b"scip-python python . foo/bar#") + _tag(4, 0) + _varint(6) + _ld(5, b"bar")
    # Occurrence{ range=1 (packed), symbol=2, symbol_roles=3 }
    packed_range = _varint(10) + _varint(0) + _varint(14)
    occ = _ld(1, packed_range) + _ld(2, b"scip-python python . foo/bar#") + _tag(3, 0) + _varint(1)
    # Document{ language=1, relative_path=2, occurrences=3, symbols=4 }
    doc = _ld(1, b"python") + _ld(2, b"foo.py") + _ld(3, occ) + _ld(4, sym_info)
    index_bytes = _ld(2, doc)

    index: ScipIndex = parse_scip_index(index_bytes)
    assert len(index.documents) == 1
    d = index.documents[0]
    assert d.relative_path == "foo.py"
    assert d.language == "python"
    assert len(d.symbols) == 1
    assert d.symbols[0].display_name == "bar"
    assert d.symbols[0].start_line == 11  # 0-based 10 -> 1-based 11
    assert d.occurrences[0][1] is True  # is_definition


def test_scip_real_binary_path_or_documented_skip(tmp_path: Path) -> None:
    """Exercise a real SCIP indexer if installed; otherwise skip loudly (not xfail)."""
    if shutil.which("scip-python") is None:
        pytest.skip(
            "scip-python not installed in this environment — the SCIP subprocess path "
            "is unverified here; the tree-sitter tags fallback is covered by "
            "test_ac23_* instead. See tasks/T04-index-semantic.md Handoff."
        )
    import asyncio

    from pcs.index.scip import run_scip_indexer  # pragma: no cover - host-dependent

    _sample_repo(tmp_path)
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\nversion='0'\n", encoding="utf-8")
    index = asyncio.get_event_loop().run_until_complete(run_scip_indexer("python", tmp_path))
    assert index is not None and index.documents
