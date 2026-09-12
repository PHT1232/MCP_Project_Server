"""T15 Codebase Guide storage, freshness, Markdown, and schema healing (R-064)."""

from __future__ import annotations

import inspect
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import cast

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from testcontainers.community.postgres import PostgresContainer

from pcs.codemap.guide import (
    DO_NOT_EDIT,
    automatic_summary_generation_exists,
    describe_files,
    get_codebase_guide,
    render_guide_markdown,
    write_guide_file,
)
from pcs.codemap.service import CodeMapError
from pcs.config import get_settings
from pcs.context import service as context_service
from pcs.context.types import ValidationError
from pcs.db.base import session_scope
from pcs.index import service as index_service
from pcs.index.schema import ensure_index_schema
from pcs.repofile import atomic_write, resolve_configured_path

pytestmark = pytest.mark.usefixtures("clean_db")

PROJECT = "acme-guide"
OVERVIEW = "Sample repo for Codebase Guide tests."
PRIOR_HEAD = "0007_requirement_evidence"
CALLER_PROSE = "Invoice assembly for the billing bounded context."
PGVECTOR_IMAGE = "pgvector/pgvector:pg16"


def _sample_repo(root: Path) -> None:
    (root / "services" / "billing").mkdir(parents=True)
    (root / "lib").mkdir()
    (root / "services" / "billing" / "invoice.py").write_text(
        "from lib.money import Money\n\ndef make_invoice(order):\n    return Money(1)\n",
        encoding="utf-8",
    )
    (root / "lib" / "money.py").write_text(
        "class Money:\n    def __init__(self, amount):\n        self.amount = amount\n",
        encoding="utf-8",
    )
    (root / "main.py").write_text("from lib.money import Money\n", encoding="utf-8")
    (root / "README.md").write_text("# Acme\n", encoding="utf-8")
    (root / ".gitignore").write_text("secret.bin\n", encoding="utf-8")
    (root / "secret.bin").write_text("ignored", encoding="utf-8")


async def _register_and_index(root: Path) -> None:
    _sample_repo(root)
    async with session_scope() as session:
        await context_service.register_project(
            session, name=PROJECT, root_path=str(root), overview=OVERVIEW
        )
    async with session_scope() as session:
        await index_service.reindex(session, project=PROJECT, incremental=False)


@contextmanager
def _temporary_database_url(url: str) -> Iterator[None]:
    previous = os.environ.get("PCS_DATABASE_URL")
    os.environ["PCS_DATABASE_URL"] = url
    get_settings.cache_clear()
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("PCS_DATABASE_URL", None)
        else:
            os.environ["PCS_DATABASE_URL"] = previous
        get_settings.cache_clear()


def _index_tables(url: str) -> set[str]:
    engine = create_engine(url)
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'code_index'")
        ).fetchall()
    engine.dispose()
    return {str(row[0]) for row in rows}


async def test_summaries_are_caller_supplied_only(tmp_path: Path) -> None:
    """AC-GUIDE-1 / INV-GUIDE-1: no automatic stub or LLM summary path."""
    await _register_and_index(tmp_path)
    assert automatic_summary_generation_exists() is False
    source = inspect.getsource(describe_files) + inspect.getsource(get_codebase_guide)
    assert "openai" not in source.lower()
    assert "generate_summary" not in source
    async with session_scope() as session:
        guide = await get_codebase_guide(session, project=PROJECT)
    files = cast(list[dict[str, object]], guide["files"])
    assert files
    assert all(item["summary"] is None for item in files)
    async with session_scope() as session:
        written = await describe_files(
            session,
            project=PROJECT,
            notes=[{"path": "lib/money.py", "summary": CALLER_PROSE}],
            author="guide-agent",
            write_artifact=False,
        )
    assert written["applied"] == ["lib/money.py"]
    async with session_scope() as session:
        after = await get_codebase_guide(session, project=PROJECT, include="documented")
    documented = cast(list[dict[str, object]], after["files"])
    assert documented[0]["summary"] == CALLER_PROSE
    with pytest.raises(ValidationError, match="secret"):
        async with session_scope() as session:
            await describe_files(
                session,
                project=PROJECT,
                notes=[{"path": "main.py", "summary": "api_key = hunter2"}],
                author="guide-agent",
                write_artifact=False,
            )


async def test_guide_reads_index_facts_only(tmp_path: Path) -> None:
    """AC-GUIDE-2 / INV-GUIDE-2: symbols, imports, importers, provenance from index."""
    await _register_and_index(tmp_path)
    async with session_scope() as session:
        guide = await get_codebase_guide(session, project=PROJECT)
    files = {str(item["path"]): item for item in cast(list[dict[str, object]], guide["files"])}
    assert "secret.bin" not in files
    invoice = files["services/billing/invoice.py"]
    invoice_symbols = cast(list[str], invoice["symbols"])
    invoice_imports = cast(list[str], invoice["imports"])
    assert "Money" in invoice_symbols or "make_invoice" in invoice_symbols
    assert "lib/money.py" in invoice_imports
    money = files["lib/money.py"]
    assert "services/billing/invoice.py" in cast(list[str], money["imported_by"])
    provenance = cast(dict[str, object], guide["generated_from"])
    assert provenance["source"] == "code_index"
    assert provenance["indexed"] is True


async def test_full_reindex_preserves_notes(tmp_path: Path) -> None:
    """AC-GUIDE-3 / INV-GUIDE-3: notes key by path, not files.id."""
    await _register_and_index(tmp_path)
    async with session_scope() as session:
        await describe_files(
            session,
            project=PROJECT,
            notes=[{"path": "lib/money.py", "summary": CALLER_PROSE}],
            author="guide-agent",
            write_artifact=False,
        )
    async with session_scope() as session:
        await index_service.reindex(session, project=PROJECT, incremental=False)
    async with session_scope() as session:
        guide = await get_codebase_guide(session, project=PROJECT, include="documented")
    files = cast(list[dict[str, object]], guide["files"])
    assert files[0]["path"] == "lib/money.py"
    assert files[0]["summary"] == CALLER_PROSE


async def test_hash_change_marks_stale_without_changing_prose(tmp_path: Path) -> None:
    """AC-GUIDE-4 / INV-GUIDE-4."""
    await _register_and_index(tmp_path)
    async with session_scope() as session:
        await describe_files(
            session,
            project=PROJECT,
            notes=[{"path": "lib/money.py", "summary": CALLER_PROSE}],
            author="guide-agent",
            write_artifact=False,
        )
    (tmp_path / "lib" / "money.py").write_text(
        "class Money:\n    def __init__(self, amount):\n        self.amount = amount + 1\n",
        encoding="utf-8",
    )
    async with session_scope() as session:
        await index_service.reindex(session, project=PROJECT, incremental=True)
    async with session_scope() as session:
        guide = await get_codebase_guide(session, project=PROJECT, include="stale")
    files = cast(list[dict[str, object]], guide["files"])
    assert len(files) == 1
    assert files[0]["path"] == "lib/money.py"
    assert files[0]["summary"] == CALLER_PROSE
    assert files[0]["stale"] is True


async def test_relative_traversal_rejected_and_writes_atomic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-GUIDE-5 / INV-GUIDE-5: traversal, symlink race, interrupted replace."""
    monkeypatch.setenv("PCS_CODEBASE_GUIDE_FILE", "../escaped.md")
    get_settings.cache_clear()
    try:
        with pytest.raises(ValueError, match=r"\.\."):
            resolve_configured_path(str(tmp_path), get_settings().codebase_guide_file)
    finally:
        monkeypatch.delenv("PCS_CODEBASE_GUIDE_FILE", raising=False)
        get_settings.cache_clear()

    root = tmp_path / "proj"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    link_dir = root / "linkdir"
    link_dir.symlink_to(outside)
    with pytest.raises(ValueError, match="escapes project root"):
        resolve_configured_path(str(root), "linkdir/CODEBASE_GUIDE.md")
    assert list(outside.iterdir()) == []

    guide_dir = root / ".project-context"
    guide_dir.mkdir()
    target = resolve_configured_path(str(root), ".project-context/CODEBASE_GUIDE.md")
    atomic_write(target, "safe\n", contain_under=root)
    assert target.read_text(encoding="utf-8") == "safe\n"
    # Plant a symlink after resolve; write-time containment must reject escape.
    target.unlink()
    guide_dir.rmdir()
    guide_dir.symlink_to(outside)
    with pytest.raises(ValueError, match="escapes project root"):
        atomic_write(target, "escaped\n", contain_under=root)
    assert not (outside / "CODEBASE_GUIDE.md").exists()
    guide_dir.unlink()
    guide_dir.mkdir()

    target = root / "guide.md"
    atomic_write(target, "one\n", contain_under=root)
    atomic_write(target, "two\n", contain_under=root)
    assert target.read_text(encoding="utf-8") == "two\n"
    leftovers = list(root.glob(".guide.md.*.tmp"))
    assert leftovers == []

    # Interrupted temp write must leave the previous artifact intact.
    def _boom_write(self: Path, *_args: object, **_kwargs: object) -> int:
        if ".tmp" in self.name:
            raise OSError("simulated interrupt before replace")
        raise AssertionError(f"unexpected write_text target {self}")

    monkeypatch.setattr(Path, "write_text", _boom_write)
    with pytest.raises(OSError, match="simulated interrupt"):
        atomic_write(target, "three\n", contain_under=root)
    monkeypatch.undo()
    assert target.read_text(encoding="utf-8") == "two\n"
    assert list(root.glob(".guide.md.*.tmp")) == []

    # Interrupted replace must also leave the previous artifact intact.
    def _boom_replace(
        _src: str | bytes | os.PathLike[str],
        _dst: str | bytes | os.PathLike[str],
    ) -> None:
        raise OSError("simulated interrupt during replace")

    monkeypatch.setattr(os, "replace", _boom_replace)
    with pytest.raises(OSError, match="simulated interrupt during replace"):
        atomic_write(target, "four\n", contain_under=root)
    monkeypatch.undo()
    assert target.read_text(encoding="utf-8") == "two\n"

    await _register_and_index(tmp_path)
    async with session_scope() as session:
        with pytest.raises(ValidationError, match="invalid path"):
            await describe_files(
                session,
                project=PROJECT,
                notes=[{"path": "../secret.py", "summary": CALLER_PROSE}],
                author="guide-agent",
                write_artifact=False,
            )


async def test_connection_facts_exclude_skipped_and_missing_endpoints(tmp_path: Path) -> None:
    """AC-GUIDE-2 / INV-GUIDE-2: imports/imported_by need active non-skipped ends."""
    await _register_and_index(tmp_path)
    async with session_scope() as session:
        project = await context_service.resolve_project(session, PROJECT)
        await session.execute(
            text(
                """
                INSERT INTO code_index.symbol_edges
                    (id, project_id, src_path, dst_path, dst_module, kind, language, mode)
                VALUES
                    (
                        'edge-skip', :pid, 'main.py', 'secret.bin', 'secret',
                        'import', 'python', 'test'
                    ),
                    (
                        'edge-miss', :pid, 'main.py', 'ghost.py', 'ghost',
                        'import', 'python', 'test'
                    )
                """
            ),
            {"pid": project.id},
        )
        guide = await get_codebase_guide(session, project=PROJECT)
    files = {str(item["path"]): item for item in cast(list[dict[str, object]], guide["files"])}
    main_imports = cast(list[str], files["main.py"]["imports"])
    assert "lib/money.py" in main_imports
    assert "secret.bin" not in main_imports
    assert "ghost.py" not in main_imports
    money_importers = cast(list[str], files["lib/money.py"]["imported_by"])
    assert "main.py" in money_importers
    assert "secret.bin" not in files


async def test_readonly_artifact_preserves_db_note(tmp_path: Path) -> None:
    """AC-GUIDE-6 / INV-GUIDE-6."""
    await _register_and_index(tmp_path)
    guide_dir = tmp_path / ".project-context"
    guide_dir.mkdir(parents=True, exist_ok=True)
    original_mode = guide_dir.stat().st_mode
    os.chmod(guide_dir, stat.S_IREAD | stat.S_IEXEC | stat.S_IRGRP | stat.S_IXGRP)
    try:
        async with session_scope() as session:
            result = await describe_files(
                session,
                project=PROJECT,
                notes=[{"path": "lib/money.py", "summary": CALLER_PROSE}],
                author="guide-agent",
                write_artifact=True,
            )
        assert result["file_writable"] is False
        assert result["applied"] == ["lib/money.py"]
        artifact = tmp_path / ".project-context" / "CODEBASE_GUIDE.md"
        assert not artifact.exists()
    finally:
        os.chmod(guide_dir, original_mode)
    async with session_scope() as session:
        guide = await get_codebase_guide(session, project=PROJECT, include="documented")
    files = cast(list[dict[str, object]], guide["files"])
    assert files[0]["summary"] == CALLER_PROSE


def test_migration_upgrade_downgrade_preserves_index_tables() -> None:
    """AC-GUIDE-7 / INV-GUIDE-7: 0008 round-trip does not drop index tables."""
    with PostgresContainer(PGVECTOR_IMAGE, driver="psycopg") as container:
        url = container.get_connection_url()
        with _temporary_database_url(url):
            config = Config("alembic.ini")
            command.upgrade(config, PRIOR_HEAD)
            engine = create_engine(url)
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO projects (id, name, root_path) "
                        "VALUES ('proj-guide', 'guide', '/repos/guide')"
                    )
                )
                conn.execute(
                    text(
                        "INSERT INTO code_index.files "
                        "(id, project_id, path, skipped, size_bytes) "
                        "VALUES ('file-1', 'proj-guide', 'lib/money.py', false, 12)"
                    )
                )
            engine.dispose()
            before = _index_tables(url)
            assert "files" in before
            assert "file_notes" not in before
            command.upgrade(config, "head")
            after_up = _index_tables(url)
            assert "files" in after_up
            assert "file_notes" in after_up
            engine = create_engine(url)
            with engine.connect() as conn:
                paths = [
                    str(row[0]) for row in conn.execute(text("SELECT path FROM code_index.files"))
                ]
            engine.dispose()
            assert paths == ["lib/money.py"]
            command.downgrade(config, PRIOR_HEAD)
            after_down = _index_tables(url)
            assert "files" in after_down
            assert "file_notes" not in after_down
            command.upgrade(config, "head")
            assert "file_notes" in _index_tables(url)


async def test_ac15_heals_file_notes_when_only_that_table_is_missing(tmp_path: Path) -> None:
    """AC-GUIDE-7: schema probe cannot return early while file_notes is missing."""
    await _register_and_index(tmp_path)
    async with session_scope() as session:
        await describe_files(
            session,
            project=PROJECT,
            notes=[{"path": "main.py", "summary": "Entrypoint."}],
            author="guide-agent",
            write_artifact=False,
        )
        await session.execute(text("DROP TABLE code_index.file_notes"))
        files_before = (
            await session.execute(text("SELECT count(*) FROM code_index.files"))
        ).scalar_one()
        await ensure_index_schema(session)
        present = (
            await session.execute(text("SELECT to_regclass('code_index.file_notes')"))
        ).scalar()
        files_after = (
            await session.execute(text("SELECT count(*) FROM code_index.files"))
        ).scalar_one()
    assert present is not None
    assert files_after == files_before
    assert int(files_after) >= 3


async def test_mixed_unknown_empty_delete(tmp_path: Path) -> None:
    """AC-GUIDE-8."""
    await _register_and_index(tmp_path)
    async with session_scope() as session:
        mixed = await describe_files(
            session,
            project=PROJECT,
            notes=[
                {"path": "lib/money.py", "summary": CALLER_PROSE},
                {"path": "no/such.py", "summary": "Missing."},
                {"path": "secret.bin", "summary": "Should skip."},
            ],
            author="guide-agent",
            write_artifact=False,
        )
    assert mixed["applied"] == ["lib/money.py"]
    unknown = {str(item["path"]): item for item in cast(list[dict[str, object]], mixed["unknown"])}
    assert "no/such.py" in unknown
    assert unknown["no/such.py"]["reason"] == "unknown"
    near = cast(list[str], unknown["no/such.py"]["near"])
    assert 0 < len(near) <= 5
    assert unknown["secret.bin"]["reason"] == "skipped"
    with pytest.raises(ValidationError, match="no valid indexed paths"):
        async with session_scope() as session:
            await describe_files(
                session,
                project=PROJECT,
                notes=[{"path": "ghost.py", "summary": "Nope."}],
                author="guide-agent",
                write_artifact=False,
            )
    with pytest.raises(ValidationError, match="duplicate path"):
        async with session_scope() as session:
            await describe_files(
                session,
                project=PROJECT,
                notes=[
                    {"path": "main.py", "summary": "a"},
                    {"path": "main.py", "summary": "b"},
                ],
                author="guide-agent",
                write_artifact=False,
            )
    async with session_scope() as session:
        deleted = await describe_files(
            session,
            project=PROJECT,
            notes=[{"path": "lib/money.py", "summary": "  "}],
            author="guide-agent",
            write_artifact=False,
        )
    assert deleted["deleted"] == ["lib/money.py"]
    async with session_scope() as session:
        guide = await get_codebase_guide(session, project=PROJECT, include="documented")
    assert cast(list[object], guide["files"]) == []


async def test_scope_and_include_modes(tmp_path: Path) -> None:
    """AC-GUIDE-9."""
    await _register_and_index(tmp_path)
    async with session_scope() as session:
        await describe_files(
            session,
            project=PROJECT,
            notes=[{"path": "lib/money.py", "summary": CALLER_PROSE}],
            author="guide-agent",
            write_artifact=False,
        )
    (tmp_path / "lib" / "money.py").write_text("class Money:\n    pass\n", encoding="utf-8")
    async with session_scope() as session:
        await index_service.reindex(session, project=PROJECT, incremental=True)
    async with session_scope() as session:
        with pytest.raises(ValidationError, match="include must be"):
            await get_codebase_guide(session, project=PROJECT, include="maybe")
        with pytest.raises(CodeMapError, match="invalid scope"):
            await get_codebase_guide(session, project=PROJECT, scope="../etc")
        with pytest.raises(CodeMapError, match="no indexed files"):
            await get_codebase_guide(session, project=PROJECT, scope="does-not-exist")
        scoped = await get_codebase_guide(session, project=PROJECT, scope="lib")
        documented = await get_codebase_guide(session, project=PROJECT, include="documented")
        undocumented = await get_codebase_guide(session, project=PROJECT, include="undocumented")
        stale = await get_codebase_guide(session, project=PROJECT, include="stale")
        all_rows = await get_codebase_guide(session, project=PROJECT, include="all")
    scoped_paths = [str(item["path"]) for item in cast(list[dict[str, object]], scoped["files"])]
    assert scoped_paths == ["lib/money.py"]
    assert [str(item["path"]) for item in cast(list[dict[str, object]], documented["files"])] == [
        "lib/money.py"
    ]
    undocumented_paths = {
        str(item["path"]) for item in cast(list[dict[str, object]], undocumented["files"])
    }
    assert "lib/money.py" not in undocumented_paths
    assert "main.py" in undocumented_paths
    assert [str(item["path"]) for item in cast(list[dict[str, object]], stale["files"])] == [
        "lib/money.py"
    ]
    all_paths = [str(item["path"]) for item in cast(list[dict[str, object]], all_rows["files"])]
    assert all_paths == sorted(all_paths)
    assert "secret.bin" not in all_paths


async def test_upsert_captures_hash_caller_coverage(tmp_path: Path) -> None:
    """AC-GUIDE-10."""
    await _register_and_index(tmp_path)
    async with session_scope() as session:
        result = await describe_files(
            session,
            project=PROJECT,
            notes=[{"path": "lib/money.py", "summary": CALLER_PROSE}],
            author="guide-agent",
            write_artifact=False,
        )
        guide = await get_codebase_guide(session, project=PROJECT, include="documented")
    coverage = cast(dict[str, int], result["coverage"])
    assert coverage["documented"] == 1
    assert coverage["total"] >= 4
    assert coverage["stale"] == 0
    file_row = cast(list[dict[str, object]], guide["files"])[0]
    note = cast(dict[str, object], file_row["note"])
    assert note["updated_by"] == "guide-agent"
    assert note["updated_at"]
    assert note["content_hash"]
    assert file_row["stale"] is False


async def test_markdown_is_deterministic(tmp_path: Path) -> None:
    """AC-GUIDE-11."""
    await _register_and_index(tmp_path)
    async with session_scope() as session:
        await describe_files(
            session,
            project=PROJECT,
            notes=[{"path": "lib/money.py", "summary": CALLER_PROSE}],
            author="guide-agent",
            write_artifact=True,
        )
        guide = await get_codebase_guide(session, project=PROJECT)
        first = render_guide_markdown(guide)
        second = render_guide_markdown(guide)
        written = await write_guide_file(session, project=PROJECT)
    assert first == second
    assert DO_NOT_EDIT in first
    assert "Coverage: documented 1 / total" in first
    assert CALLER_PROSE in first
    assert "_Undocumented._" in first
    assert "## lib" in first
    assert "### lib/money.py" in first
    assert "Imported by:" in first or "Imports:" in first
    (tmp_path / "lib" / "money.py").write_text("class Money:\n    pass\n", encoding="utf-8")
    async with session_scope() as session:
        await index_service.reindex(session, project=PROJECT, incremental=True)
        stale_guide = await get_codebase_guide(session, project=PROJECT)
        rendered = render_guide_markdown(stale_guide)
    assert "_Stale: indexed content hash differs" in rendered
    assert written["file_writable"] is True
    artifact = Path(str(written["path"]))
    assert artifact.is_relative_to(tmp_path)
    assert artifact.read_text(encoding="utf-8") == first
    assert artifact.resolve().is_relative_to(tmp_path.resolve())
