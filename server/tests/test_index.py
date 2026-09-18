"""Code-index tests: gitignore, keyword search, AC9 freshness, AC15 rebuild."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast
from unittest.mock import patch

import pytest
from mcp.server.fastmcp.exceptions import ToolError
from sqlalchemy import text

from pcs.context import service as context_service
from pcs.db.base import session_scope
from pcs.index.chunker import chunk_source
from pcs.index.hybrid import hybrid_search
from pcs.index.ignore import PathTraversalError, resolve_under_root, walk_repo
from pcs.index.search import keyword_search
from pcs.index.service import get_index_status, reindex, search_code
from pcs.index.symbols import extract_definitions
from pcs.mcp import build_http_app, mcp

pytestmark = pytest.mark.usefixtures("clean_db")

PROJECT = "acme-index"
OVERVIEW = "Sample repo used to prove keyword indexing."


def _sample_repo(root: Path) -> None:
    (root / "src").mkdir()
    (root / "src" / "app.py").write_text(
        "def greet(name: str) -> str:\n    return f'hello {name}'\n\n"
        "class Cart:\n    def total(self) -> int:\n        return 42\n",
        encoding="utf-8",
    )
    (root / "src" / "util.py").write_text("def helper() -> int:\n    return 1\n", encoding="utf-8")
    (root / "docs").mkdir()
    (root / "docs" / "guide.md").write_text("# Guide\ncheckout flow needle\n", encoding="utf-8")
    (root / ".gitignore").write_text("secret.env\nbuild/\n", encoding="utf-8")
    (root / "secret.env").write_text("TOKEN=s3cret\n", encoding="utf-8")
    (root / "build").mkdir()
    (root / "build" / "out.js").write_text("console.log('built')\n", encoding="utf-8")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "pkg.js").write_text("module.exports = 1\n", encoding="utf-8")


async def _register_and_index(root: Path) -> None:
    _sample_repo(root)
    async with session_scope() as session:
        await context_service.register_project(
            session, name=PROJECT, root_path=str(root), overview=OVERVIEW
        )
    async with session_scope() as session:
        await reindex(session, project=PROJECT, incremental=False)


def _tool_text(result: object) -> str:
    if isinstance(result, tuple):
        result = result[0]
    if isinstance(result, list) and result:
        return str(getattr(result[0], "text", result[0]))
    return str(result)


def _tool_payload(result: object) -> dict[str, object]:
    if isinstance(result, tuple):
        _, structured = result
        if isinstance(structured, dict):
            return {str(k): v for k, v in cast(dict[object, object], structured).items()}
    data: object = json.loads(_tool_text(result))
    assert isinstance(data, dict)
    return {str(k): v for k, v in cast(dict[object, object], data).items()}


def test_chunker_splits_python_on_function_and_class_boundaries() -> None:
    path = Path("src/app.py")
    source = (
        "def greet(name: str) -> str:\n    return name\n\n"
        "class Cart:\n    def total(self) -> int:\n        return 1\n"
    )
    chunks = chunk_source(path, source)
    symbols = {c.symbol for c in chunks}
    assert "greet" in symbols
    assert "Cart" in symbols
    greet = next(c for c in chunks if c.symbol == "greet")
    assert greet.kind == "function"
    assert greet.start_line == 1
    assert "return name" in greet.content


def test_chunker_indexes_module_level_content_around_boundaries() -> None:
    """Regression: content outside every function/class body used to be dropped
    entirely (never stored in any chunk) whenever a file had at least one
    boundary node — e.g. EXPECTED_TOOLS-style module constants were invisible
    to search_code even in literal/exact mode, because the text was never
    indexed at all, not because of ranking."""
    path = Path("src/app.py")
    source = (
        '"""Module docstring."""\n'
        "import os\n"
        "\n"
        'EXPECTED_TOOLS = frozenset({"a", "b"})\n'
        "\n"
        "def greet(name: str) -> str:\n"
        "    return name\n"
        "\n"
        "# a comment between defs\n"
        "\n"
        "class Cart:\n"
        "    def total(self) -> int:\n"
        "        return 1\n"
        "\n"
        "TRAILING = 1\n"
    )
    chunks = chunk_source(path, source)

    def _found(needle: str) -> bool:
        return any(needle in c.content for c in chunks)

    assert _found("Module docstring")
    assert _found("EXPECTED_TOOLS")
    assert _found("a comment between defs")
    assert _found("TRAILING")
    assert not any(not c.content.strip() for c in chunks)
    # Every non-blank source line is accounted for in some chunk.
    covered = "\n".join(c.content for c in chunks)
    for line in source.splitlines():
        if line.strip():
            assert line in covered
    # Existing boundary chunks are unaffected by the gap fill.
    greet = next(c for c in chunks if c.symbol == "greet")
    assert greet.kind == "function"
    cart = next(c for c in chunks if c.symbol == "Cart")
    assert cart.kind == "class"


def test_chunker_gap_fill_handles_overlapping_nested_boundaries() -> None:
    """A class chunk and its method chunk legitimately overlap in line range;
    gap computation must treat covered lines as a union, not assume the
    boundary chunks are sorted/disjoint."""
    path = Path("src/app.py")
    source = "class Cart:\n    def total(self) -> int:\n        return 1\n\nTRAILING = 2\n"
    chunks = chunk_source(path, source)
    cart = next(c for c in chunks if c.symbol == "Cart")
    total = next(c for c in chunks if c.symbol == "total")
    assert cart.start_line <= total.start_line <= total.end_line <= cart.end_line
    # No spurious gap chunk duplicating the (overlapping) class/method body.
    module_chunks = [c for c in chunks if c.symbol is None]
    assert all("class Cart" not in c.content for c in module_chunks)
    assert any("TRAILING" in c.content for c in module_chunks)


def test_chunker_indexes_top_level_content_in_other_languages() -> None:
    """The gap-fill is generic across chunk_source's languages, not Python-only."""
    path = Path("main.go")
    source = (
        "package main\n"
        "\n"
        'const GREETING = "hello"\n'
        "\n"
        "func greet(name string) string {\n"
        "\treturn name\n"
        "}\n"
    )
    chunks = chunk_source(path, source)
    assert any("GREETING" in c.content for c in chunks)
    assert any(c.symbol == "greet" for c in chunks)


def test_chunker_gap_chunks_never_pollute_the_symbol_table() -> None:
    """Gap chunks must carry symbol=None: extract_definitions treats any chunk
    with a non-None symbol and kind in {function, class, module} as a symbol
    definition feeding the symbol table / code map."""
    path = Path("src/app.py")
    source = (
        '"""Module docstring."""\n'
        "import os\n"
        "\n"
        'EXPECTED_TOOLS = frozenset({"a", "b"})\n'
        "\n"
        "def greet(name: str) -> str:\n"
        "    return name\n"
        "\n"
        "class Cart:\n"
        "    def total(self) -> int:\n"
        "        return 1\n"
        "\n"
        "TRAILING = 1\n"
    )
    defs = extract_definitions(path, source)
    names = {d.name for d in defs}
    assert names == {"greet", "Cart", "total"}


def test_walk_honours_gitignore_and_default_excludes(tmp_path: Path) -> None:
    _sample_repo(tmp_path)
    walked = walk_repo(tmp_path)
    rels = {p.relative_to(tmp_path).as_posix() for p in walked.files}
    assert "src/app.py" in rels
    assert "docs/guide.md" in rels
    skipped = {path: reason for path, reason in walked.skipped}
    assert skipped.get("secret.env") == "ignored"
    assert skipped.get("build") == "ignored" or skipped.get("build/") == "ignored"
    assert "node_modules" in skipped
    assert all("secret.env" not in r for r in rels)
    assert all(not r.startswith("build/") for r in rels)
    assert all(not r.startswith("node_modules/") for r in rels)


def test_path_traversal_rejected(tmp_path: Path) -> None:
    _sample_repo(tmp_path)
    root = tmp_path.resolve()
    with pytest.raises(PathTraversalError):
        resolve_under_root(root, "../outside.py")
    with pytest.raises(PathTraversalError):
        resolve_under_root(root, "/etc/passwd")


async def test_indexes_sample_repo_status_reports_skipped_with_reason(tmp_path: Path) -> None:
    await _register_and_index(tmp_path)
    async with session_scope() as session:
        status = await get_index_status(session, project=PROJECT)
    assert status.file_count >= 3
    assert status.chunk_count >= 3
    reasons = {s.path: s.reason for s in status.skipped}
    assert any(path.endswith("secret.env") or path == "secret.env" for path in reasons)
    assert any("build" in path for path in reasons)
    assert all(s.reason for s in status.skipped)


async def test_keyword_query_returns_path_line_snippet(tmp_path: Path) -> None:
    await _register_and_index(tmp_path)
    async with session_scope() as session:
        payload = await search_code(session, project=PROJECT, query="greet")
    hits = cast(list[object], payload["hits"])
    assert hits
    hit = cast(dict[str, object], hits[0])
    assert hit["path"] == "src/app.py"
    assert int(str(hit["start_line"])) >= 1
    assert int(str(hit["end_line"])) >= int(str(hit["start_line"]))
    assert "greet" in str(hit["snippet"])
    assert hit["matched_mode"] in {"exact", "symbol", "fts", "fuzzy"}
    assert payload["semantic_available"] is False


async def test_module_level_constant_is_findable_end_to_end(tmp_path: Path) -> None:
    """Real-world repro: a module-level assignment (like EXPECTED_TOOLS in
    test_integration.py) between two functions used to be invisible to
    search_code, even in literal/exact mode, because it was never chunked."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "config.py").write_text(
        "def before() -> None:\n"
        "    pass\n"
        "\n"
        'EXPECTED_TOOLS = frozenset({"add_focus", "add_blocker"})\n'
        "\n"
        "def after() -> None:\n"
        "    pass\n",
        encoding="utf-8",
    )
    async with session_scope() as session:
        await context_service.register_project(
            session, name=PROJECT, root_path=str(tmp_path), overview=OVERVIEW
        )
    async with session_scope() as session:
        await reindex(session, project=PROJECT, incremental=False)
    async with session_scope() as session:
        payload = await search_code(session, project=PROJECT, query="EXPECTED_TOOLS")
    hits = cast(list[object], payload["hits"])
    assert hits
    assert any("EXPECTED_TOOLS" in str(cast(dict[str, object], h)["snippet"]) for h in hits)


async def test_ac9_edit_incremental_fresh_and_stale_flagged(tmp_path: Path) -> None:
    """Edit → stale without reindex; incremental reindex returns fresh content (AC9, NFR9)."""
    await _register_and_index(tmp_path)
    app = tmp_path / "src" / "app.py"
    original = app.read_text(encoding="utf-8")
    app.write_text(
        original.replace("hello {name}", "goodbye {name}"),
        encoding="utf-8",
    )

    async with session_scope() as session:
        stale_payload = await search_code(session, project=PROJECT, query="greet")
    stale_hits = cast(list[object], stale_payload["hits"])
    assert stale_hits
    stale_hit = cast(dict[str, object], stale_hits[0])
    assert stale_hit["stale"] is True
    assert "hello" in str(stale_hit["snippet"])

    async with session_scope() as session:
        await reindex(session, project=PROJECT, incremental=True)

    async with session_scope() as session:
        fresh = await search_code(session, project=PROJECT, query="greet")
    fresh_hit = cast(dict[str, object], cast(list[object], fresh["hits"])[0])
    assert fresh_hit["stale"] is False
    assert "goodbye" in str(fresh_hit["snippet"])

    app.write_text(app.read_text(encoding="utf-8") + "\ndef farewell() -> str:\n    return 'bye'\n")
    async with session_scope() as session:
        await reindex(session, project=PROJECT, incremental=True)
    async with session_scope() as session:
        added = await search_code(session, project=PROJECT, query="farewell")
    added_hits = cast(list[object], added["hits"])
    assert added_hits
    assert cast(dict[str, object], added_hits[0])["stale"] is False
    assert "farewell" in str(cast(dict[str, object], added_hits[0])["snippet"])


async def test_ac15_drop_index_schema_rebuild_preserves_context(tmp_path: Path) -> None:
    """DROP SCHEMA code_index → rebuild; curated context intact (AC15, NFR12)."""
    await _register_and_index(tmp_path)
    async with session_scope() as session:
        await context_service.add_entry(
            session, project=PROJECT, section="blockers", headline="Keep me"
        )
    async with session_scope() as session:
        await session.execute(text("DROP SCHEMA code_index CASCADE"))

    async with session_scope() as session:
        briefing = await context_service.get_project_briefing(session, project=PROJECT)
        entries = await context_service.get_section(session, project=PROJECT, section="blockers")
    assert "Keep me" in briefing
    assert any(e.headline == "Keep me" for e in entries)

    async with session_scope() as session:
        status = await reindex(session, project=PROJECT, incremental=False)
    assert status.file_count >= 3
    assert status.chunk_count >= 3

    async with session_scope() as session:
        payload = await search_code(session, project=PROJECT, query="greet")
        still = await context_service.get_section(session, project=PROJECT, section="blockers")
    assert cast(list[object], payload["hits"])
    assert any(e.headline == "Keep me" for e in still)


async def test_search_scopes_subtree_files_and_focus(tmp_path: Path) -> None:
    await _register_and_index(tmp_path)
    async with session_scope() as session:
        await context_service.set_current_focus(
            session, project=PROJECT, text="Fix greet in src/app.py"
        )

    async with session_scope() as session:
        subtree = await search_code(
            session, project=PROJECT, query="needle", scope="subtree", subtree="docs"
        )
        files = await search_code(
            session,
            project=PROJECT,
            query="helper",
            scope="files",
            files=["src/util.py"],
        )
        focus = await search_code(session, project=PROJECT, query="greet", scope="focus")
        with pytest.raises(ValueError, match=r"escapes|not repo-relative"):
            await search_code(
                session, project=PROJECT, query="greet", scope="subtree", subtree="../"
            )

    docs_hits = cast(list[object], subtree["hits"])
    assert docs_hits
    assert all(str(cast(dict[str, object], h)["path"]).startswith("docs/") for h in docs_hits)

    file_hits = cast(list[object], files["hits"])
    assert file_hits
    assert all(str(cast(dict[str, object], h)["path"]) == "src/util.py" for h in file_hits)

    focus_hits = cast(list[object], focus["hits"])
    assert focus_hits
    assert all(str(cast(dict[str, object], h)["path"]) == "src/app.py" for h in focus_hits)


async def test_search_code_reports_truncation(tmp_path: Path) -> None:
    # hybrid_search always asks keyword_search for at least 20 rows regardless
    # of the caller's own limit, so truncation of the keyword pool itself only
    # shows up once matches exceed that floor.
    (tmp_path / "src").mkdir()
    for i in range(25):
        (tmp_path / "src" / f"mod_{i}.py").write_text(
            f"NEEDLE_{i} = {i}\n\ndef fn_{i}() -> int:\n    return {i}\n",
            encoding="utf-8",
        )
    async with session_scope() as session:
        await context_service.register_project(
            session, name=PROJECT, root_path=str(tmp_path), overview=OVERVIEW
        )
    async with session_scope() as session:
        await reindex(session, project=PROJECT, incremental=False)

    async with session_scope() as session:
        capped = await search_code(session, project=PROJECT, query="NEEDLE", limit=3)
        uncapped = await search_code(session, project=PROJECT, query="NEEDLE", limit=100)
        scoped = await search_code(
            session, project=PROJECT, query="NEEDLE", scope="files", files=["src/mod_0.py"]
        )

    capped_hits = cast(list[object], capped["hits"])
    assert len(capped_hits) == 3
    assert int(str(capped["total_matches"])) == 25
    assert capped["truncated"] is True

    uncapped_hits = cast(list[object], uncapped["hits"])
    assert int(str(uncapped["total_matches"])) == 25
    assert len(uncapped_hits) == 25
    assert uncapped["truncated"] is False

    scoped_hits = cast(list[object], scoped["hits"])
    assert int(str(scoped["total_matches"])) == 1
    assert len(scoped_hits) == 1
    assert scoped["truncated"] is False


async def test_keyword_search_total_matches_exceeds_capped_hits(tmp_path: Path) -> None:
    """Direct unit test of keyword_search's own total_matches, independent of
    hybrid_search's limit-flooring behavior."""
    (tmp_path / "src").mkdir()
    for i in range(25):
        (tmp_path / "src" / f"mod_{i}.py").write_text(f"NEEDLE_{i} = {i}\n", encoding="utf-8")
    async with session_scope() as session:
        await context_service.register_project(
            session, name=PROJECT, root_path=str(tmp_path), overview=OVERVIEW
        )
    async with session_scope() as session:
        await reindex(session, project=PROJECT, incremental=False)

    async with session_scope() as session:
        result = await keyword_search(session, project=PROJECT, query="NEEDLE", limit=5)

    assert len(result.hits) == 5
    assert result.total_matches == 25


async def test_keyword_search_count_matches_false_skips_count_query(tmp_path: Path) -> None:
    """count_matches=False must not run the separate COUNT(*) (perf: T-PREPARE-PERF).

    Same 25-hit fixture as the sibling test above, but with counting disabled:
    total_matches falls back to len(hits) (== limit here) rather than the true
    25, proving the expensive un-LIMITed COUNT query never ran.
    """
    (tmp_path / "src").mkdir()
    for i in range(25):
        (tmp_path / "src" / f"mod_{i}.py").write_text(f"NEEDLE_{i} = {i}\n", encoding="utf-8")
    async with session_scope() as session:
        await context_service.register_project(
            session, name=PROJECT, root_path=str(tmp_path), overview=OVERVIEW
        )
    async with session_scope() as session:
        await reindex(session, project=PROJECT, incremental=False)

    async with session_scope() as session:
        result = await keyword_search(
            session, project=PROJECT, query="NEEDLE", limit=5, count_matches=False
        )

    assert len(result.hits) == 5
    assert result.total_matches == 5


async def test_keyword_search_fuzzy_false_keeps_exact_drops_fuzzy_only(tmp_path: Path) -> None:
    """fuzzy=False keeps exact/FTS matches but drops trigram-similarity-only hits.

    Perf/quality fix (T-PREPARE-PERF follow-up): similarity() isn't
    index-accelerated and dominates keyword_search's cost for long queries,
    while tending to surface only incidental resemblance rather than real
    relevance. fuzzy=False must not affect exact/FTS/symbol/path matching.
    """
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "exact.py").write_text("NEEDLE_MARKER = True\n", encoding="utf-8")
    long_text = (
        "Refactor the payment processing pipeline to handle async retries "
        "gracefully without blocking the main thread"
    )
    (tmp_path / "src" / "fuzzy_only.py").write_text(f"# {long_text}\n", encoding="utf-8")
    async with session_scope() as session:
        await context_service.register_project(
            session, name=PROJECT, root_path=str(tmp_path), overview=OVERVIEW
        )
    async with session_scope() as session:
        await reindex(session, project=PROJECT, incremental=False)

    # NEEDLE_MARKER is an exact/FTS token match on exact.py — unaffected by fuzzy.
    async with session_scope() as session:
        exact_default = await keyword_search(session, project=PROJECT, query="NEEDLE_MARKER")
        exact_no_fuzzy = await keyword_search(
            session, project=PROJECT, query="NEEDLE_MARKER", fuzzy=False
        )
    assert any(h.path.endswith("exact.py") for h in exact_default.hits)
    assert any(h.path.endswith("exact.py") for h in exact_no_fuzzy.hits)

    # A near-duplicate of fuzzy_only.py's text (one word swapped, one word
    # appended) shares no exact substring and no complete FTS token-set match
    # with it, but is trigram-similar enough to match only when fuzzy=True.
    near_dup_query = long_text.replace("Refactor", "Rewrite") + " zzz_unique_suffix_marker"
    async with session_scope() as session:
        fuzzy_on = await keyword_search(session, project=PROJECT, query=near_dup_query)
        fuzzy_off = await keyword_search(
            session, project=PROJECT, query=near_dup_query, fuzzy=False
        )
    assert any(h.path.endswith("fuzzy_only.py") for h in fuzzy_on.hits)
    assert not any(h.path.endswith("fuzzy_only.py") for h in fuzzy_off.hits)


async def test_hybrid_search_count_matches_false_passes_through(tmp_path: Path) -> None:
    """hybrid_search's count_matches threads down to its keyword_search call.

    hybrid_search floors the keyword-side limit at 20 (``max(limit, 20)``)
    regardless of the caller's own ``limit``, so with 25 real matches and
    counting disabled, keyword_total_matches should reflect that internal
    20-cap (len(hits)), not the true 25 — proving the COUNT query was skipped.
    """
    (tmp_path / "src").mkdir()
    for i in range(25):
        (tmp_path / "src" / f"mod_{i}.py").write_text(f"NEEDLE_{i} = {i}\n", encoding="utf-8")
    async with session_scope() as session:
        await context_service.register_project(
            session, name=PROJECT, root_path=str(tmp_path), overview=OVERVIEW
        )
    async with session_scope() as session:
        await reindex(session, project=PROJECT, incremental=False)

    async with session_scope() as session:
        result = await hybrid_search(
            session, project=PROJECT, query="NEEDLE", limit=5, count_matches=False
        )

    assert result.keyword_total_matches == 20


async def test_unknown_project_search_lists_registered(tmp_path: Path) -> None:
    await _register_and_index(tmp_path)
    with pytest.raises(context_service.ProjectNotFoundError) as excinfo:
        async with session_scope() as session:
            await search_code(session, project="ghost", query="greet")
    assert PROJECT in str(excinfo.value)


async def test_mcp_index_tools_and_nfr6_audit(tmp_path: Path) -> None:
    await _register_and_index(tmp_path)
    status = _tool_payload(await mcp.call_tool("get_index_status", {"project": PROJECT}))
    assert int(str(status["file_count"])) >= 3

    found = _tool_payload(await mcp.call_tool("search_code", {"project": PROJECT, "query": "Cart"}))
    hits = cast(list[object], found["hits"])
    assert hits
    assert found["semantic_available"] is False

    with pytest.raises(ToolError):
        await mcp.call_tool("search_code", {"project": "ghost", "query": "greet"})

    from pcs.logging import log_tool_call as real_log

    seen: list[str] = []

    def spy(
        *,
        tool: str,
        project: str | None,
        caller: str,
        outcome: str,
        **fields: object,
    ) -> None:
        seen.append(tool)
        real_log(tool=tool, project=project, caller=caller, outcome=outcome, **fields)

    with patch("pcs.mcp.support.log_tool_call", spy):
        await mcp.call_tool("get_index_status", {"project": PROJECT})
        await mcp.call_tool("search_code", {"project": PROJECT, "query": "helper"})
    assert "get_index_status" in seen
    assert "search_code" in seen


async def test_retrieve_context_docstring_explains_task_is_required_with_files() -> None:
    """An agent that omits `task` while narrowing with `files`/`scope` gets a
    plain "task: Field required" validation error — already clear about what's
    missing, but not about *why* it's still needed once files are given. The
    tool's own registered description (what an agent introspecting the tool
    sees, not docs/mcp-reference.md) must say so, and point at search_code for
    the no-task-description case."""
    tools = {tool.name: tool for tool in await mcp.list_tools()}
    description = tools["retrieve_context"].description or ""
    assert "required in every call" in description.lower()
    assert "scope='files'" in description or 'scope="files"' in description
    assert "search_code" in description


async def test_http_index_routes_are_registered() -> None:
    app = build_http_app()
    paths = {getattr(route, "path", None) for route in app.routes}
    assert "/api/projects/{project}/index" in paths
    assert "/api/projects/{project}/reindex" in paths
    assert "/api/projects/{project}/search" in paths
    assert "/api/projects/{project}/retrieve-context" in paths
    assert "/api/projects/{project}/prepare-task" in paths
