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
from pcs.index.ignore import PathTraversalError, resolve_under_root, walk_repo
from pcs.index.service import get_index_status, reindex, search_code
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


async def test_http_index_routes_are_registered() -> None:
    app = build_http_app()
    paths = {getattr(route, "path", None) for route in app.routes}
    assert "/api/projects/{project}/index" in paths
    assert "/api/projects/{project}/reindex" in paths
    assert "/api/projects/{project}/search" in paths
    assert "/api/projects/{project}/retrieve-context" in paths
    assert "/api/projects/{project}/prepare-task" in paths
