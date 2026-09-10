"""End-to-end walking-skeleton proof (task T00 acceptance).

Real Postgres via testcontainers -> baseline migration -> register_project ->
set_current_focus -> get_project_briefing, exercised both through the plain
service layer and through the MCP tool layer, plus an assertion that the HTTP
app mounts the MCP transport and the /api routes.
"""

from __future__ import annotations

import json

import pytest
from mcp.server.fastmcp.exceptions import ToolError
from starlette.testclient import TestClient

from pcs.context import service
from pcs.db.base import session_scope
from pcs.mcp import build_http_app, mcp

pytestmark = pytest.mark.usefixtures("clean_db")

PROJECT = "acme-web"
OVERVIEW = "ACME's customer-facing web app. React + FastAPI, deployed on Fly.io."
FOCUS = "Migrate the checkout flow off the legacy payments gateway."


async def _register_and_focus() -> str:
    async with session_scope() as session:
        summary = await service.register_project(
            session, name=PROJECT, root_path="/repos/acme-web", overview=OVERVIEW
        )
    async with session_scope() as session:
        await service.set_current_focus(session, project=PROJECT, text=FOCUS)
    return summary.id


async def test_briefing_round_trip_via_service() -> None:
    await _register_and_focus()
    async with session_scope() as session:
        briefing = await service.get_project_briefing(session, project=PROJECT)
    assert OVERVIEW in briefing
    assert FOCUS in briefing
    assert briefing.startswith(f"# {PROJECT}")


async def test_unknown_project_lists_registered_projects() -> None:
    await _register_and_focus()
    with pytest.raises(service.ProjectNotFoundError) as excinfo:
        async with session_scope() as session:
            await service.get_project_briefing(session, project="does-not-exist")
    assert PROJECT in str(excinfo.value)


async def test_briefing_round_trip_through_mcp_tools() -> None:
    reg = await mcp.call_tool(
        "register_project",
        {"name": PROJECT, "root_path": "/repos/acme-web", "overview": OVERVIEW},
    )
    assert _tool_payload(reg)["name"] == PROJECT

    await mcp.call_tool("set_current_focus", {"project": PROJECT, "text": FOCUS})

    briefing = await mcp.call_tool("get_project_briefing", {"project": PROJECT})
    text = _tool_text(briefing)
    assert OVERVIEW in text
    assert FOCUS in text


async def test_mcp_unknown_project_errors_with_project_list() -> None:
    await mcp.call_tool(
        "register_project",
        {"name": PROJECT, "root_path": "/repos/acme-web", "overview": OVERVIEW},
    )
    with pytest.raises(ToolError) as excinfo:
        await mcp.call_tool("get_project_briefing", {"project": "ghost"})
    assert PROJECT in str(excinfo.value)


async def test_registered_tool_set_is_exactly_the_skeleton() -> None:
    tools = {t.name for t in await mcp.list_tools()}
    assert tools == {"register_project", "set_current_focus", "get_project_briefing"}


def test_http_app_mounts_mcp_and_api_routes() -> None:
    app = build_http_app()
    paths = {getattr(route, "path", None) for route in app.routes}
    assert "/mcp" in paths
    assert "/api/health" in paths
    assert "/api/projects" in paths

    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["bind_host"] == "127.0.0.1"

        created = client.post(
            "/api/projects",
            json={"name": PROJECT, "root_path": "/repos/acme-web", "overview": OVERVIEW},
        )
        assert created.status_code == 201

        listed = client.get("/api/projects").json()
        assert [p["name"] for p in listed] == [PROJECT]

        client.get(f"/api/projects/{PROJECT}/briefing")
        briefing = client.get(f"/api/projects/{PROJECT}/briefing").json()
        assert OVERVIEW in briefing["briefing"]

        missing = client.get("/api/projects/nope/briefing")
        assert missing.status_code == 404
        assert PROJECT in missing.json()["available"]


def _tool_text(result: object) -> str:
    if isinstance(result, tuple):
        result = result[0]
    if isinstance(result, list) and result:
        return str(getattr(result[0], "text", result[0]))
    return str(result)


def _tool_payload(result: object) -> dict[str, str]:
    if isinstance(result, tuple):
        _, structured = result
        if isinstance(structured, dict):
            return {str(k): str(v) for k, v in structured.items()}
    data: dict[str, object] = json.loads(_tool_text(result))
    return {str(k): str(v) for k, v in data.items()}
