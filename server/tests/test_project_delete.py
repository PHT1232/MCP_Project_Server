"""Unregister a pcs project without touching the repo (AC-DEL-1..4)."""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from starlette.testclient import TestClient

from pcs.context import service as context_service
from pcs.db.base import session_scope
from pcs.db.models import ContextEntry, RequirementContractRevision, RequirementEvidence
from pcs.index import watch as index_watch
from pcs.index.models import IndexChunk, IndexFile
from pcs.index.service import reindex
from pcs.mcp import build_http_app, mcp
from pcs.planning.models import Plan, PlanTaskEvent
from pcs.planning.service import create_plan_with_tasks
from pcs.planning.types import TaskSpec
from pcs.requirements import contracts, evidence
from pcs.token_savings.models import TokenSavingsLogEntry

pytestmark = pytest.mark.usefixtures("clean_db")

VICTIM = "delete-victim"
SIBLING = "delete-sibling"
MARKER = "pcs-delete-marker.txt"
REQUIREMENTS_REL = Path(".project-context") / "requirements.md"


def _git_init(root: Path) -> str:
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "del@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Delete"], cwd=root, check=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=root, check=True)
    (root / "README").write_text("victim repo\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=root, check=True, capture_output=True)
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()


def _plant_files(root: Path) -> tuple[bytes, bytes]:
    root.mkdir(parents=True, exist_ok=True)
    marker = root / MARKER
    reqs = root / REQUIREMENTS_REL
    reqs.parent.mkdir(parents=True, exist_ok=True)
    marker_bytes = b"do-not-delete-me\n"
    reqs_bytes = b"### R-001 -- planted\nkeep this file\n"
    marker.write_bytes(marker_bytes)
    reqs.write_bytes(reqs_bytes)
    return marker_bytes, reqs_bytes


async def _register(name: str, root: Path, overview: str = "overview") -> str:
    async with session_scope() as session:
        summary = await context_service.register_project(
            session, name=name, root_path=str(root), overview=overview
        )
        return summary.id


async def _seed_restrict_children(name: str, sha: str) -> None:
    async with session_scope() as session:
        req = await context_service.add_entry(
            session, project=name, section="requirements", headline="Must survive on disk only"
        )
        inv = await contracts.create_invariant(
            session,
            project=name,
            requirement_id=req.id,
            key="INV-DEL",
            statement="Victim project has a contract.",
            kind="behavior",
            risk="high",
        )
        ac = await contracts.create_criterion(
            session,
            project=name,
            invariant_id=inv.id,
            key="AC-DEL",
            statement="Evidence exists so teardown must clear RESTRICT rows.",
            evidence_kind="test",
            required=True,
        )
        await evidence.record_evidence(
            session,
            project=name,
            criterion_id=ac.id,
            kind="test",
            result="passed",
            source_commit=sha,
            author="tester",
        )
        await create_plan_with_tasks(
            session,
            name,
            "Victim plan",
            "Exercise plan_task_events teardown",
            [TaskSpec(local_task_id="T01", title="Task", objective="Do it")],
        )
        await reindex(session, project=name, incremental=False)


def _client() -> TestClient:
    return TestClient(build_http_app())


def _extract_dict(result: object) -> dict[str, Any]:
    if isinstance(result, tuple):
        result = result[0]
    if isinstance(result, list) and result:
        text_val = getattr(result[0], "text", None)
        if text_val:
            parsed: object = json.loads(str(text_val))
            if isinstance(parsed, dict):
                return cast(dict[str, Any], parsed)
    if isinstance(result, dict):
        return cast(dict[str, Any], result)
    raise AssertionError(f"Unexpected result: {result!r}")


async def _count(model: type[Any], project_id: str) -> int:
    async with session_scope() as session:
        result = await session.execute(
            select(func.count()).select_from(model).where(model.project_id == project_id)
        )
        return int(result.scalar_one())


async def test_delete_project_removes_pcs_rows_and_leaves_disk(tmp_path: Path) -> None:
    victim_root = tmp_path / "victim"
    sibling_root = tmp_path / "sibling"
    marker_bytes, reqs_bytes = _plant_files(victim_root)
    sha = _git_init(victim_root)

    victim_id = await _register(VICTIM, victim_root)
    sibling_id = await _register(SIBLING, sibling_root, overview="keep me")
    await _seed_restrict_children(VICTIM, sha)
    async with session_scope() as session:
        await context_service.add_entry(
            session, project=SIBLING, section="bugs", headline="Sibling bug stays"
        )

    assert await _count(RequirementEvidence, victim_id) >= 1
    assert await _count(RequirementContractRevision, victim_id) >= 1
    assert await _count(PlanTaskEvent, victim_id) >= 1
    assert await _count(IndexFile, victim_id) >= 1

    async with session_scope() as session:
        deleted = await context_service.delete_project(session, project=VICTIM, author="tester")
    assert deleted.id == victim_id
    assert deleted.name == VICTIM

    async with session_scope() as session:
        names = [p.name for p in await context_service.list_projects(session)]
    assert VICTIM not in names
    assert SIBLING in names

    assert await _count(ContextEntry, victim_id) == 0
    assert await _count(RequirementEvidence, victim_id) == 0
    assert await _count(RequirementContractRevision, victim_id) == 0
    assert await _count(PlanTaskEvent, victim_id) == 0
    assert await _count(Plan, victim_id) == 0
    assert await _count(IndexFile, victim_id) == 0
    assert await _count(IndexChunk, victim_id) == 0
    assert await _count(TokenSavingsLogEntry, victim_id) == 0

    assert await _count(ContextEntry, sibling_id) >= 1
    async with session_scope() as session:
        bugs = await context_service.get_section(session, project=SIBLING, section="bugs")
    assert any(entry.headline == "Sibling bug stays" for entry in bugs)

    assert (victim_root / MARKER).read_bytes() == marker_bytes
    assert (victim_root / REQUIREMENTS_REL).read_bytes() == reqs_bytes

    reused = await _register(VICTIM, victim_root, overview="re-registered")
    assert reused != victim_id
    async with session_scope() as session:
        await context_service.delete_project(session, project=VICTIM)


async def test_delete_project_unknown_name_lists_available() -> None:
    async with session_scope() as session:
        with pytest.raises(context_service.ProjectNotFoundError, match="ghost") as excinfo:
            await context_service.delete_project(session, project="ghost")
    assert "(none registered yet)" in str(excinfo.value) or "Registered projects" in str(
        excinfo.value
    )


async def test_append_only_delete_still_rejected_without_teardown_guc(tmp_path: Path) -> None:
    root = tmp_path / "locked"
    await _register(VICTIM, root)
    async with session_scope() as session:
        await create_plan_with_tasks(
            session,
            VICTIM,
            "Lock plan",
            "Keep events immutable",
            [TaskSpec(local_task_id="T01", title="Task", objective="Do it")],
        )
    with pytest.raises(DBAPIError, match="append-only"):
        async with session_scope() as session:
            await session.execute(text("DELETE FROM plan_task_events"))
            await session.flush()


async def test_stop_watch_cancels_in_process_task() -> None:
    async def linger() -> None:
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            raise

    task = asyncio.create_task(linger())
    index_watch._tasks["watch-pid"] = task
    await index_watch.stop_watch("watch-pid")
    assert "watch-pid" not in index_watch._tasks
    assert task.done()
    await index_watch.stop_watch("watch-pid")


async def test_delete_project_mcp_http_parity_and_unknown_404(tmp_path: Path) -> None:
    root = tmp_path / "api-victim"
    await _register(VICTIM, root)
    mcp_data = _extract_dict(await mcp.call_tool("delete_project", {"project": VICTIM}))
    assert mcp_data["deleted"] is True
    assert mcp_data["name"] == VICTIM
    assert isinstance(mcp_data["id"], str)

    async with session_scope() as session:
        names = [p.name for p in await context_service.list_projects(session)]
    assert VICTIM not in names

    sibling_root = tmp_path / "api-sibling"
    await _register(SIBLING, sibling_root)
    client = _client()
    resp = client.delete(f"/api/projects/{SIBLING}")
    assert resp.status_code == 200
    http_data = resp.json()
    assert http_data["deleted"] is True
    assert http_data["name"] == SIBLING
    assert set(http_data) == {"deleted", "id", "name"}

    missing = client.delete("/api/projects/does-not-exist")
    assert missing.status_code == 404
    assert "available" in missing.json()

    from mcp.server.fastmcp.exceptions import ToolError

    with pytest.raises(ToolError):
        await mcp.call_tool("delete_project", {"project": "does-not-exist"})


async def test_delete_project_tool_is_registered() -> None:
    tools = {tool.name for tool in await mcp.list_tools()}
    assert "delete_project" in tools
