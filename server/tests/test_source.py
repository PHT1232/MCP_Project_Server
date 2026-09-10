"""T07 server addition: the read-only source route (FR34, AC13).

Covers: content is returned for an indexed file, path traversal is rejected
(NFR5), an unknown / non-indexed path is a 404, and the HTTP route is wired.
Runs on the real Postgres testcontainer via the shared fixtures.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pcs.codemap import source as source_service
from pcs.context import service as context_service
from pcs.db.base import session_scope
from pcs.index import service as index_service
from pcs.index.ignore import PathTraversalError
from pcs.mcp import build_http_app

pytestmark = pytest.mark.usefixtures("clean_db")

PROJECT = "acme-source"
OVERVIEW = "Sample repo for the source route tests."


def _sample_repo(root: Path) -> None:
    (root / "src").mkdir()
    (root / "src" / "app.py").write_text(
        "def greet(name: str) -> str:\n    return f'hello {name}'\n", encoding="utf-8"
    )
    (root / "README.md").write_text("# Acme\n", encoding="utf-8")


async def _register_and_index(root: Path) -> None:
    _sample_repo(root)
    async with session_scope() as session:
        await context_service.register_project(
            session, name=PROJECT, root_path=str(root), overview=OVERVIEW
        )
    async with session_scope() as session:
        await index_service.reindex(session, project=PROJECT, incremental=False)


async def test_source_returns_file_content(tmp_path: Path) -> None:
    await _register_and_index(tmp_path)
    async with session_scope() as session:
        payload = await source_service.get_source(session, project=PROJECT, path="src/app.py")
    assert payload["path"] == "src/app.py"
    assert payload["language"] == "python"
    assert "def greet(name: str)" in str(payload["content"])
    assert payload["truncated"] is False


async def test_source_rejects_path_traversal(tmp_path: Path) -> None:
    await _register_and_index(tmp_path)
    async with session_scope() as session:
        with pytest.raises(PathTraversalError):
            await source_service.get_source(session, project=PROJECT, path="../outside.py")
        with pytest.raises(PathTraversalError):
            await source_service.get_source(session, project=PROJECT, path="/etc/passwd")


async def test_source_unknown_file_is_not_found(tmp_path: Path) -> None:
    await _register_and_index(tmp_path)
    async with session_scope() as session:
        with pytest.raises(source_service.SourceNotIndexedError):
            await source_service.get_source(session, project=PROJECT, path="src/missing.py")


async def test_source_unknown_project_lists_registered(tmp_path: Path) -> None:
    await _register_and_index(tmp_path)
    async with session_scope() as session:
        with pytest.raises(context_service.ProjectNotFoundError):
            await source_service.get_source(session, project="ghost", path="src/app.py")


def test_http_source_route_is_registered() -> None:
    app = build_http_app()
    paths = {getattr(route, "path", None) for route in app.routes}
    assert "/api/projects/{project}/source" in paths
