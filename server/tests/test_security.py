"""T09 security regression checks for FR19, NFR5, SQL safety, and subprocess use."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path
from typing import cast
from unittest.mock import patch

import pytest

from pcs.codemap import source as source_service
from pcs.context import service as context_service
from pcs.db.base import session_scope
from pcs.index import gitutil
from pcs.index import service as index_service
from pcs.index.embedding import set_embedding_backend_override
from pcs.index.ignore import PathTraversalError, resolve_under_root, walk_repo

pytestmark = pytest.mark.usefixtures("clean_db")


@pytest.fixture(autouse=True)
def no_embedding_backend() -> Iterator[None]:
    """Keep security checks deterministic and prevent external data transfer."""
    set_embedding_backend_override(None, active=True)
    try:
        yield
    finally:
        set_embedding_backend_override(None, active=False)


@pytest.mark.parametrize(
    "hostile_path",
    [
        "../outside.py",
        "src/../../outside.py",
        "/etc/passwd",
        "~/private.key",
    ],
)
def test_resolve_under_root_rejects_traversal(tmp_path: Path, hostile_path: str) -> None:
    """Lexical and absolute traversal cannot escape a configured repo (NFR5)."""
    with pytest.raises(PathTraversalError):
        resolve_under_root(tmp_path.resolve(), hostile_path)


def test_resolve_under_root_rejects_symlink_escape(tmp_path: Path) -> None:
    """A repo-local symlink cannot be used to read outside the repo (NFR5)."""
    root = tmp_path / "repo"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "secret.txt").write_text("outside secret", encoding="utf-8")
    (root / "escape").symlink_to(outside, target_is_directory=True)

    with pytest.raises(PathTraversalError):
        resolve_under_root(root.resolve(), "escape/secret.txt")
    assert not walk_repo(root.resolve()).files


def test_default_secret_names_and_key_material_are_not_indexed(tmp_path: Path) -> None:
    """Default indexing excludes common environment and credential files (FR19)."""
    safe = tmp_path / "src" / "app.py"
    safe.parent.mkdir()
    safe.write_text("VALUE = 1\n", encoding="utf-8")
    secret_paths = (
        ".env",
        ".env.local",
        ".env.production",
        "server.pem",
        "server.key",
        "identity.p12",
        "identity.pfx",
        "id_rsa",
        "id_rsa.backup",
        "secrets/token.txt",
        ".ssh/config",
    )
    for relative in secret_paths:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("SECRET=must-not-index\n", encoding="utf-8")

    walked = walk_repo(tmp_path.resolve())
    indexed = {path.relative_to(tmp_path).as_posix() for path in walked.files}
    skipped = {path for path, reason in walked.skipped if reason == "ignored"}

    assert indexed == {"src/app.py"}
    for relative in secret_paths:
        top_level = relative.split("/", 1)[0]
        assert relative in skipped or top_level in skipped


async def _register_and_index(name: str, root: Path, marker: str) -> None:
    root.mkdir()
    (root / "app.py").write_text(f"def marker() -> str:\n    return {marker!r}\n", encoding="utf-8")
    async with session_scope() as session:
        await context_service.register_project(
            session,
            name=name,
            root_path=str(root),
            overview=f"Project containing {marker}",
        )
    async with session_scope() as session:
        await index_service.reindex(session, project=name, incremental=False)


async def test_sql_injection_shaped_search_does_not_leak_or_alter_state(tmp_path: Path) -> None:
    """Hostile search values stay bound and scoped to one project."""
    first = "security-first"
    second = "security-second"
    await _register_and_index(first, tmp_path / "first", "FIRST_ONLY_MARKER")
    await _register_and_index(second, tmp_path / "second", "SECOND_ONLY_MARKER")

    hostile = "' OR 1=1; DROP TABLE projects; --"
    async with session_scope() as session:
        result = await index_service.search_code(
            session,
            project=first,
            query=hostile,
            globs=["*.py' OR 1=1 --"],
        )
        first_result = await index_service.search_code(
            session, project=first, query="FIRST_ONLY_MARKER"
        )
        second_result = await index_service.search_code(
            session, project=second, query="SECOND_ONLY_MARKER"
        )
        projects = await context_service.list_projects(session)

    assert result["hits"] == []
    first_hits = cast(list[dict[str, object]], first_result["hits"])
    second_hits = cast(list[dict[str, object]], second_result["hits"])
    assert first_hits and all("SECOND_ONLY_MARKER" not in str(hit) for hit in first_hits)
    assert second_hits and all("FIRST_ONLY_MARKER" not in str(hit) for hit in second_hits)
    assert {project.name for project in projects} == {first, second}


async def test_sql_injection_shaped_project_name_is_data(tmp_path: Path) -> None:
    """A project identifier containing SQL syntax cannot alter statements."""
    hostile_name = "project'; DROP TABLE projects; --"
    await _register_and_index(hostile_name, tmp_path / "hostile", "SAFE_MARKER")

    async with session_scope() as session:
        briefing = await context_service.get_project_briefing(session, project=hostile_name)
        projects = await context_service.list_projects(session)

    assert "SAFE_MARKER" in briefing
    assert [project.name for project in projects] == [hostile_name]


async def test_source_service_rejects_symlink_escape_even_if_path_is_requested(
    tmp_path: Path,
) -> None:
    """Source retrieval applies real-path containment before its index lookup (NFR5)."""
    root = tmp_path / "repo"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "secret.py").write_text("TOKEN = 'outside'\n", encoding="utf-8")
    (root / "escape.py").symlink_to(outside / "secret.py")
    async with session_scope() as session:
        await context_service.register_project(
            session, name="symlink-source", root_path=str(root), overview="Safety test"
        )

    async with session_scope() as session:
        with pytest.raises(PathTraversalError):
            await source_service.get_source(session, project="symlink-source", path="escape.py")


async def test_git_helpers_use_argument_vector_without_a_shell(tmp_path: Path) -> None:
    """Repository paths and revisions are subprocess arguments, never shell text (NFR5)."""
    process = asyncio.subprocess.Process
    del process  # Type anchor only; the fake below supplies the used protocol surface.

    class FakeProcess:
        returncode = 0

        async def communicate(self) -> tuple[bytes, bytes]:
            return b"true\n", b""

    with patch(
        "pcs.index.gitutil.asyncio.create_subprocess_exec",
        return_value=FakeProcess(),
    ) as create:
        result = await gitutil._git(tmp_path, "rev-parse", "HEAD; touch /tmp/pwned")

    assert result == "true"
    create.assert_called_once_with(
        "git",
        "rev-parse",
        "HEAD; touch /tmp/pwned",
        cwd=tmp_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
