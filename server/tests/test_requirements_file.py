"""Requirements template file two-way sync — acceptance tests (FR16a, D12, D15).

Covers AC18 (add in store -> block in file; file status edit -> store), AC22
(both-changed conflict -> store wins + token rewrite + reconciliation; deleted
block -> archived, not resurrected), the malformed-block path, and round-trip
idempotency. Real Postgres via conftest fixtures.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

from pcs.context import service as ctx
from pcs.db.base import session_scope
from pcs.mcp import mcp
from pcs.requirements import service as reqs
from pcs.requirements.types import SyncReport

pytestmark = pytest.mark.usefixtures("clean_db")

REL_PATH = ".project-context/requirements.md"


async def _register(root: Path, name: str = "proj") -> None:
    async with session_scope() as session:
        await ctx.register_project(session, name=name, root_path=str(root), overview="an overview")


async def _add_req(name: str, headline: str, status: str = "not-started") -> str:
    async with session_scope() as session:
        view = await ctx.add_entry(
            session,
            project=name,
            section="requirements",
            headline=headline,
            requirement_status=status,
        )
    return view.id


async def _sync(name: str = "proj") -> SyncReport:
    async with session_scope() as session:
        return await reqs.sync_requirements(session, project=name, author="tester")


async def _statuses(name: str = "proj") -> dict[str, str]:
    async with session_scope() as session:
        views = await reqs.list_requirements(session, project=name)
    return {v.req_key: v.status for v in views}


async def test_register_creates_the_template_file(tmp_path: Path) -> None:
    async with session_scope() as session:
        await ctx.register_project(session, name="proj", root_path=str(tmp_path), overview="ov")
        report = await reqs.sync_requirements(session, project="proj")
    path = tmp_path / REL_PATH
    assert path.is_file()
    assert report.file_existed is False
    assert "# Requirements" in path.read_text()


async def test_ac18_add_in_store_writes_a_block_into_the_file(tmp_path: Path) -> None:
    await _register(tmp_path)
    await _add_req("proj", "Persist context in PostgreSQL", "in-progress")

    report = await _sync()

    path = tmp_path / REL_PATH
    body = path.read_text()
    assert "### R-001 — Persist context in PostgreSQL" in body
    assert "<!-- req status=in-progress -->" in body
    assert report.written_back == ("R-001",)
    assert [r.req_key for r in report.requirements] == ["R-001"]


async def test_ac18_file_status_edit_flows_to_the_store(tmp_path: Path) -> None:
    await _register(tmp_path)
    await _add_req("proj", "Ship the thing", "not-started")
    await _sync()  # file now has R-001 + a snapshot

    path = tmp_path / REL_PATH
    path.write_text(path.read_text().replace("status=not-started", "status=in-progress"))

    report = await _sync()
    assert report.ok
    assert await _statuses() == {"R-001": "in-progress"}  # file-only change -> file wins


async def test_sync_is_idempotent(tmp_path: Path) -> None:
    await _register(tmp_path)
    await _add_req("proj", "Only requirement", "blocked")
    await _sync()

    second = await _sync()
    assert second.file_written is False
    assert second.created == ()
    assert second.written_back == ()
    assert second.archived == ()


async def test_ac22_status_changed_in_both_store_wins_and_token_rewritten(
    tmp_path: Path,
) -> None:
    await _register(tmp_path)
    entry_id = await _add_req("proj", "Contested requirement", "not-started")
    await _sync()  # snapshot: not-started

    async with session_scope() as session:
        await ctx.set_requirement_status(
            session, project="proj", entry_id=entry_id, status="blocked"
        )
    path = tmp_path / REL_PATH
    path.write_text(path.read_text().replace("status=not-started", "status=done"))

    report = await _sync()

    assert await _statuses() == {"R-001": "blocked"}  # store wins
    assert "<!-- req status=blocked -->" in path.read_text()  # token rewritten
    assert any(
        "both" in note.message and note.req_key == "R-001" for note in report.reconciliations
    )


async def test_ac22_deleted_block_is_archived_and_never_resurrected(
    tmp_path: Path,
) -> None:
    await _register(tmp_path)
    entry_id = await _add_req("proj", "Doomed requirement", "in-progress")
    await _sync()

    path = tmp_path / REL_PATH
    lines = path.read_text().splitlines()
    cut = next(i for i, line in enumerate(lines) if line.startswith("### "))
    path.write_text("\n".join(lines[:cut]).rstrip() + "\n")

    report = await _sync()
    assert report.archived == ("R-001",)
    assert await _statuses() == {}

    async with session_scope() as session:
        history = await ctx.get_entry_history(session, project="proj", entry_id=entry_id)
    assert any(rev.action == "archive" for rev in history)
    assert history[0].action == "create"  # full history retained (D5)

    # A second sync must not bring it back, even though history exists.
    report2 = await _sync()
    assert report2.created == ()
    assert await _statuses() == {}

    # Re-adding the heading by hand does not resurrect the archived R-001.
    with_stale = path.read_text() + "\n### R-001 — Doomed requirement\nback again\n"
    path.write_text(with_stale)
    report3 = await _sync()
    assert "R-001" not in report3.archived
    assert any("not resurrected" in n.message for n in report3.reconciliations)
    assert await _statuses() == {}


async def test_malformed_block_is_skipped_and_last_good_is_retained(
    tmp_path: Path,
) -> None:
    await _register(tmp_path)
    await _add_req("proj", "Good requirement", "not-started")
    await _add_req("proj", "Fragile requirement", "in-progress")
    await _sync()  # R-001 good, R-002 fragile

    path = tmp_path / REL_PATH
    text = path.read_text()
    text = text.replace("<!-- req status=in-progress -->", "<!-- req status=kaboom -->")
    text = text.replace("<!-- req status=not-started -->", "<!-- req status=done -->")
    path.write_text(text)

    report = await _sync()

    assert report.ok is False
    assert any("kaboom" in err for err in report.errors)

    statuses = await _statuses()
    assert statuses["R-001"] == "done"  # good block applied
    assert statuses["R-002"] == "in-progress"  # malformed block: last-good retained


async def test_read_only_location_degrades_gracefully(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A read-only requirements dir (e.g. the repo mounted read-only): the store
    still reconciles and stays authoritative, the report flags the file as
    unwritable rather than failing, and a later sync does not archive the store
    requirement just because the file never received it (FR16a, D15, AC22)."""
    import errno

    def _read_only(*_args: object, **_kwargs: object) -> None:
        raise OSError(errno.EROFS, "Read-only file system")

    monkeypatch.setattr(reqs, "_atomic_write", _read_only)
    monkeypatch.setattr(reqs, "_dir_writable", lambda _dir: False)

    await _register(tmp_path)
    await _add_req("proj", "Keep me", "in-progress")

    first = await _sync()
    assert first.ok is True  # a read-only file is not a sync failure
    assert first.file_writable is False
    assert first.file_written is False
    assert first.errors == ()
    assert not (tmp_path / REL_PATH).exists()  # nothing was written

    # the requirement is keyed and visible in the store view
    assert [r.title for r in first.requirements] == ["Keep me"]
    only_key = first.requirements[0].req_key
    assert only_key.startswith("R-")
    assert await _statuses() == {only_key: "in-progress"}

    # a second sync must NOT archive it (the file baseline was never advanced)
    second = await _sync()
    assert second.file_writable is False
    assert second.archived == ()
    assert await _statuses() == {only_key: "in-progress"}


async def test_read_only_location_surfaces_through_mcp_write_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import errno

    def _read_only(*_args: object, **_kwargs: object) -> None:
        raise OSError(errno.EROFS, "Read-only file system")

    monkeypatch.setattr(reqs, "_atomic_write", _read_only)
    monkeypatch.setattr(reqs, "_dir_writable", lambda _dir: False)

    await mcp.call_tool(
        "register_project",
        {"name": "roproj", "root_path": str(tmp_path), "overview": "o"},
    )
    added = await mcp.call_tool(
        "add_requirement",
        {"project": "roproj", "headline": "Saved anyway", "status": "not-started"},
    )
    file_info = cast(dict[str, object], _tool_payload(added)["requirements_file"])
    assert file_info["writable"] is False
    assert file_info["written"] is False
    assert file_info["errors"] == []
    async with session_scope() as session:
        views = await reqs.list_requirements(session, project="roproj")
    assert [v.title for v in views] == ["Saved anyway"]


async def test_ac18_end_to_end_through_mcp_tools(tmp_path: Path) -> None:
    await mcp.call_tool(
        "register_project",
        {"name": "mcpproj", "root_path": str(tmp_path), "overview": "o"},
    )
    added = await mcp.call_tool(
        "add_requirement",
        {"project": "mcpproj", "headline": "MCP-authored requirement", "status": "not-started"},
    )
    payload = _tool_payload(added)
    file_info = cast(dict[str, object], payload["requirements_file"])
    assert file_info["written"] is True

    path = tmp_path / REL_PATH
    assert "MCP-authored requirement" in path.read_text()

    path.write_text(path.read_text().replace("status=not-started", "status=done"))
    synced = _tool_payload(await mcp.call_tool("sync_requirements", {"project": "mcpproj"}))
    assert synced["done_count"] == 1
    assert synced["total_count"] == 1


def _tool_payload(result: object) -> dict[str, object]:
    if isinstance(result, tuple):
        _, structured = result
        if isinstance(structured, dict):
            return {str(k): v for k, v in cast(dict[object, object], structured).items()}
        result = result[0]
    if isinstance(result, list) and result:
        text = str(getattr(result[0], "text", result[0]))
    else:
        text = str(result)
    data: object = json.loads(text)
    assert isinstance(data, dict)
    return {str(k): v for k, v in cast(dict[object, object], data).items()}
