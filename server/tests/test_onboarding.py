"""Tests for one-call agent bootstrap tools (T-ONBOARD, add_new_project).

Covers: tool registration, response shape, MCP/HTTP parity, and that
add_new_project actually registers, indexes, watches, and syncs requirements.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import pytest
from mcp.server.fastmcp.exceptions import ToolError
from starlette.testclient import TestClient

from pcs.codemap import service as codemap_service
from pcs.context import service as context_service
from pcs.db.base import session_scope
from pcs.index.service import get_index_status
from pcs.mcp import build_http_app, mcp
from pcs.mcp.onboarding_tools import NEXT_STEPS, TOOL_USAGE
from pcs.planning import TaskSpec, activate_plan, create_plan_with_tasks

pytestmark = pytest.mark.usefixtures("clean_db")

PROJECT = "onboard-proj"


async def _seed_project_with_ready_task(name: str = PROJECT) -> None:
    async with session_scope() as session:
        await context_service.register_project(
            session, name=name, root_path=f"/tmp/{name}", overview=f"Test project {name}"
        )
    async with session_scope() as session:
        plan = await create_plan_with_tasks(
            session,
            name,
            "Onboard Test Plan",
            "Goal",
            [TaskSpec(local_task_id="T01", title="Task 1", objective="Do 1")],
            [],
        )
        await activate_plan(session, name, plan.id)


def _client() -> TestClient:
    return TestClient(build_http_app())


async def _mcp_call(tool: str, args: dict[str, Any], caller_name: str = "test-agent") -> Any:
    with patch("pcs.mcp.onboarding_tools.caller", return_value=caller_name):
        return await mcp.call_tool(tool, args)


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


async def test_onboard_tool_registered() -> None:
    tools = {tool.name for tool in await mcp.list_tools()}
    assert "onboard" in tools


async def test_onboard_response_shape_and_ready_tasks() -> None:
    await _seed_project_with_ready_task()

    res = _extract_dict(await _mcp_call("onboard", {"project": PROJECT}))

    assert res["tool_usage"] == TOOL_USAGE
    assert isinstance(res["briefing"], str)
    assert res["ready_tasks"]
    assert res["ready_tasks"][0]["local_task_id"] == "T01"
    assert isinstance(res["code_map"], dict)
    assert res["code_map"]["project_name"] == PROJECT


async def test_onboard_mcp_http_parity() -> None:
    await _seed_project_with_ready_task()

    mcp_data = _extract_dict(await _mcp_call("onboard", {"project": PROJECT}))

    client = _client()
    resp = client.get(f"/api/projects/{PROJECT}/onboard")
    assert resp.status_code == 200
    http_data = resp.json()

    assert http_data["tool_usage"] == mcp_data["tool_usage"]
    assert http_data["ready_tasks"] == mcp_data["ready_tasks"]
    assert http_data["code_map"] == mcp_data["code_map"]


async def test_onboard_code_map_matches_direct_call() -> None:
    await _seed_project_with_ready_task()

    res = _extract_dict(await _mcp_call("onboard", {"project": PROJECT}))

    async with session_scope() as session:
        direct_code_map = await codemap_service.get_code_map(session, project=PROJECT)

    assert res["code_map"] == direct_code_map


async def test_onboard_unknown_project_errors() -> None:
    with pytest.raises(ToolError):
        await _mcp_call("onboard", {"project": "does-not-exist"})

    client = _client()
    resp = client.get("/api/projects/does-not-exist/onboard")
    assert resp.status_code == 404


REQ_FILE = Path(".project-context") / "requirements.md"
ADD_PROJECT = "add-new-proj"
REG_PROJECT = "reg-compare-proj"
HTTP_PROJECT = "add-new-http-proj"


def _write_sample_repo(root: Path) -> None:
    src = root / "src"
    src.mkdir()
    (src / "app.py").write_text("def greet() -> str:\n    return 'hello'\n", encoding="utf-8")


def _add_payload(name: str, root: Path) -> dict[str, str]:
    return {"name": name, "root_path": str(root), "overview": "Sample app for onboarding tests."}


async def test_add_new_project_tool_registered() -> None:
    tools = {tool.name for tool in await mcp.list_tools()}
    assert "add_new_project" in tools


async def test_add_new_project_creates_indexes_and_syncs(tmp_path: Path) -> None:
    """add_new_project registers, indexes, and writes the requirements file (FR14, FR16a, FR24)."""
    repo = tmp_path / "via-add"
    other = tmp_path / "via-reg"
    repo.mkdir()
    other.mkdir()
    _write_sample_repo(repo)
    _write_sample_repo(other)

    res = _extract_dict(await _mcp_call("add_new_project", _add_payload(ADD_PROJECT, repo)))

    assert set(res) == {"project", "index_status", "code_map", "next_steps"}
    assert res["next_steps"] == NEXT_STEPS
    assert ADD_PROJECT not in res["next_steps"]
    assert res["project"]["name"] == ADD_PROJECT
    assert res["project"]["root_path"] == str(repo)
    assert int(res["index_status"]["file_count"]) >= 1
    assert (repo / REQ_FILE).is_file()
    assert "# Requirements" in (repo / REQ_FILE).read_text(encoding="utf-8")

    registered = _extract_dict(
        await mcp.call_tool("register_project", _add_payload(REG_PROJECT, other))
    )
    assert set(res["project"]) == set(registered)

    async with session_scope() as session:
        add_status = await get_index_status(session, project=ADD_PROJECT)
        reg_status = await get_index_status(session, project=REG_PROJECT)
    assert add_status.file_count == reg_status.file_count
    assert (other / REQ_FILE).is_file()


async def test_add_new_project_mcp_http_parity(tmp_path: Path) -> None:
    mcp_root = tmp_path / "mcp"
    http_root = tmp_path / "http"
    mcp_root.mkdir()
    http_root.mkdir()
    _write_sample_repo(mcp_root)
    _write_sample_repo(http_root)

    mcp_data = _extract_dict(
        await _mcp_call("add_new_project", _add_payload(ADD_PROJECT, mcp_root))
    )

    client = _client()
    resp = client.post("/api/projects/add-new-project", json=_add_payload(HTTP_PROJECT, http_root))
    assert resp.status_code == 201
    http_data = resp.json()

    assert set(http_data) == set(mcp_data) == {"project", "index_status", "code_map", "next_steps"}
    assert http_data["next_steps"] == mcp_data["next_steps"] == NEXT_STEPS
    assert set(http_data["project"]) == set(mcp_data["project"])
    assert set(http_data["index_status"]) == set(mcp_data["index_status"])
    assert http_data["index_status"]["file_count"] == mcp_data["index_status"]["file_count"]
    assert set(http_data["code_map"]) == set(mcp_data["code_map"])


async def test_add_new_project_code_map_and_index_match_direct_calls(tmp_path: Path) -> None:
    _write_sample_repo(tmp_path)
    res = _extract_dict(await _mcp_call("add_new_project", _add_payload(ADD_PROJECT, tmp_path)))

    async with session_scope() as session:
        direct_code_map = await codemap_service.get_code_map(session, project=ADD_PROJECT)
        direct_index = await get_index_status(session, project=ADD_PROJECT)

    assert res["code_map"] == direct_code_map
    assert res["index_status"] == direct_index.as_dict()


async def test_add_new_project_duplicate_errors(tmp_path: Path) -> None:
    _write_sample_repo(tmp_path)
    await _mcp_call("add_new_project", _add_payload(ADD_PROJECT, tmp_path))

    with pytest.raises(ToolError):
        await _mcp_call("add_new_project", _add_payload(ADD_PROJECT, tmp_path))

    client = _client()
    resp = client.post("/api/projects/add-new-project", json=_add_payload(ADD_PROJECT, tmp_path))
    assert resp.status_code == 400
