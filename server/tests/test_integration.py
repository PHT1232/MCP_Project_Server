"""End-to-end context-store proof: MCP tools, resources, HTTP, NFR6, AC14.

Real Postgres via testcontainers. Service-layer ACs live in test_context_store.py.
"""

from __future__ import annotations

import json
import logging
from typing import cast
from unittest.mock import patch

import pytest
from mcp.server.fastmcp.exceptions import ToolError
from starlette.testclient import TestClient

from pcs.context import service
from pcs.db.base import session_scope
from pcs.logging import JsonFormatter
from pcs.mcp import build_http_app, mcp

pytestmark = pytest.mark.usefixtures("clean_db")

PROJECT = "acme-web"
OVERVIEW = "ACME's customer-facing web app. React + FastAPI, deployed on Fly.io."
FOCUS = "Migrate the checkout flow off the legacy payments gateway."

EXPECTED_TOOLS = frozenset(
    {
        "register_project",
        "list_projects",
        "configure_project",
        "get_project_briefing",
        "get_section",
        "get_entry",
        "get_entry_history",
        "set_current_focus",
        "update_overview",
        "delete_entry",
        "add_focus",
        "update_focus",
        "resolve_focus",
        "add_blocker",
        "update_blocker",
        "resolve_blocker",
        "add_bug",
        "update_bug",
        "resolve_bug",
        "add_convention",
        "update_convention",
        "resolve_convention",
        "add_decision",
        "update_decision",
        "resolve_decision",
        "add_glossary",
        "update_glossary",
        "resolve_glossary",
        "add_requirement",
        "update_requirement",
        "set_requirement_status",
        "resolve_requirement",
        "sync_requirements",
        "get_requirement_contract",
        "get_task_contract",
        "get_index_status",
        "reindex",
        "search_code",
        "retrieve_context",
        "prepare_task",
        "get_code_map",
        "record_requirement_evidence",
        "get_requirement_evidence",
        "add_requirement_violation",
        "resolve_requirement_violation",
        "evaluate_close_gate",
        "review_requirement_compliance",
        "create_requirement_invariant",
        "update_requirement_invariant",
        "delete_requirement_invariant",
        "create_acceptance_criterion",
        "update_acceptance_criterion",
        "delete_acceptance_criterion",
    }
)


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


async def test_briefing_round_trip_via_service() -> None:
    async with session_scope() as session:
        await service.register_project(
            session, name=PROJECT, root_path="/repos/acme-web", overview=OVERVIEW
        )
    async with session_scope() as session:
        await service.set_current_focus(session, project=PROJECT, text=FOCUS)
    async with session_scope() as session:
        briefing = await service.get_project_briefing(session, project=PROJECT)
    assert "ACME" in briefing
    assert "Checkout" in briefing or FOCUS[:20] in briefing
    assert briefing.startswith(f"# {PROJECT}")


async def test_unknown_project_lists_registered_projects() -> None:
    async with session_scope() as session:
        await service.register_project(
            session, name=PROJECT, root_path="/repos/acme-web", overview=OVERVIEW
        )
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
    await mcp.call_tool(
        "add_blocker", {"project": PROJECT, "headline": "Waiting on finance for API keys"}
    )

    briefing = await mcp.call_tool("get_project_briefing", {"project": PROJECT})
    text = _tool_text(briefing)
    assert "ACME" in text
    assert "Waiting on finance" in text


async def test_mcp_unknown_project_errors_with_project_list() -> None:
    await mcp.call_tool(
        "register_project",
        {"name": PROJECT, "root_path": "/repos/acme-web", "overview": OVERVIEW},
    )
    with pytest.raises(ToolError) as excinfo:
        await mcp.call_tool("get_project_briefing", {"project": "ghost"})
    assert PROJECT in str(excinfo.value)


async def test_registered_tool_set_covers_the_context_store() -> None:
    tools = {t.name for t in await mcp.list_tools()}
    assert tools == EXPECTED_TOOLS


async def test_context_resources_are_registered_and_readable() -> None:
    await mcp.call_tool(
        "register_project",
        {"name": PROJECT, "root_path": "/repos/acme-web", "overview": OVERVIEW},
    )
    await mcp.call_tool("add_blocker", {"project": PROJECT, "headline": "Need a sandbox account"})
    templates = await mcp.list_resource_templates()
    uris = {getattr(t, "uriTemplate", None) or getattr(t, "uri_template", None) for t in templates}
    assert "context://{project}/blockers" in uris
    assert "context://{project}/history/{entry_id}" in uris
    contents = list(await mcp.read_resource(f"context://{PROJECT}/blockers"))
    assert contents
    body = str(contents[0].content)
    assert "Need a sandbox account" in body


async def test_http_app_and_ac14_http_mcp_share_the_store() -> None:
    """HTTP routes mount, and a frontend-shaped write is visible to MCP (AC14 server-side)."""
    app = build_http_app()
    paths = {getattr(route, "path", None) for route in app.routes}
    assert "/mcp" in paths
    assert "/api/health" in paths
    assert "/api/projects" in paths
    assert "/api/projects/{project}/entries" in paths
    assert "/api/projects/{project}/index" in paths
    assert "/api/projects/{project}/reindex" in paths
    assert "/api/projects/{project}/search" in paths

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

        briefing = client.get(f"/api/projects/{PROJECT}/briefing").json()
        assert "ACME" in briefing["briefing"]

        index_status = client.get(f"/api/projects/{PROJECT}/index")
        assert index_status.status_code == 200
        assert index_status.json()["file_count"] == 0

        empty_search = client.get(f"/api/projects/{PROJECT}/search", params={"q": "greet"})
        assert empty_search.status_code == 200
        assert empty_search.json()["hits"] == []
        assert empty_search.json()["semantic_available"] is False

        missing = client.get("/api/projects/nope/briefing")
        assert missing.status_code == 404
        assert PROJECT in missing.json()["available"]

        added = client.post(
            f"/api/projects/{PROJECT}/entries",
            json={"section": "blockers", "headline": "HTTP-ORIGINATED-BLOCKER"},
        )
        assert added.status_code == 201
        entry_id = str(added.json()["id"])

        await mcp.call_tool("add_bug", {"project": PROJECT, "headline": "MCP-ORIGINATED-BUG"})
        via_http = client.get(f"/api/projects/{PROJECT}/briefing").json()["briefing"]
        assert "HTTP-ORIGINATED-BLOCKER" in via_http
        assert "MCP-ORIGINATED-BUG" in via_http

        patched = client.patch(
            f"/api/projects/{PROJECT}/entries/{entry_id}",
            json={"headline": "HTTP-UPDATED-BLOCKER"},
        )
        assert patched.status_code == 200

    follow = _tool_text(await mcp.call_tool("get_project_briefing", {"project": PROJECT}))
    assert "HTTP-UPDATED-BLOCKER" in follow
    assert "MCP-ORIGINATED-BUG" in follow


async def test_nfr6_tool_call_emits_structured_audit_line() -> None:
    """S2 / NFR6: a tool call records tool, project, caller, and outcome."""
    from pcs.logging import log_tool_call as real_log

    await mcp.call_tool(
        "register_project",
        {"name": PROJECT, "root_path": "/repos/acme-web", "overview": OVERVIEW},
    )

    seen: list[dict[str, str]] = []

    def spy(
        *,
        tool: str,
        project: str | None,
        caller: str,
        outcome: str,
        **fields: object,
    ) -> None:
        seen.append(
            {
                "tool": tool,
                "project": project or "",
                "caller": caller,
                "outcome": outcome,
            }
        )
        real_log(tool=tool, project=project, caller=caller, outcome=outcome, **fields)

    with patch("pcs.mcp.support.log_tool_call", spy):
        await mcp.call_tool("get_project_briefing", {"project": PROJECT})

    assert seen, "expected log_tool_call to run for get_project_briefing"
    audit = seen[-1]
    assert audit["tool"] == "get_project_briefing"
    assert audit["project"] == PROJECT
    assert audit["caller"]
    assert audit["outcome"] == "ok"

    record = logging.LogRecord("pcs", logging.INFO, __file__, 0, "tool_call", (), None)
    record.__dict__["context"] = audit
    payload = json.loads(JsonFormatter().format(record))
    assert payload["event"] == "tool_call"
    assert payload["tool"] == "get_project_briefing"
    assert payload["project"] == PROJECT
    assert payload["caller"]
    assert payload["outcome"] == "ok"
