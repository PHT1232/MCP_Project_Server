"""T30 project-context export — service, MCP tool, and HTTP route."""

from __future__ import annotations

import json
from typing import Any, cast

import pytest
from mcp.server.fastmcp.exceptions import ToolError
from starlette.testclient import TestClient

from pcs.context import service
from pcs.context.export import (
    EXPORT_FORMAT_JSON,
    EXPORT_FORMAT_MARKDOWN,
    assemble_project_export,
    export_project_context,
    render_export_json,
    render_export_markdown,
    validate_export_format,
)
from pcs.context.types import ALL_SECTIONS, SECTION_HEADINGS, ValidationError
from pcs.db.base import session_scope
from pcs.mcp import build_http_app, mcp
from pcs.requirements import contracts

pytestmark = pytest.mark.usefixtures("clean_db")

PROJECT = "export-demo"
OVERVIEW = "Export demo project for full context dump."
LONG_DETAIL = "VERBATIM-LONG-DETAIL-" + ("x" * 4000)


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


async def _seed_rich_project() -> str:
    """Register a project with every section populated, plus a requirement contract."""
    async with session_scope() as session:
        await service.register_project(
            session, name=PROJECT, root_path="/repos/export-demo", overview=OVERVIEW
        )
    async with session_scope() as session:
        await service.set_current_focus(session, project=PROJECT, text="Ship the export API")
        await service.add_entry(
            session,
            project=PROJECT,
            section="blockers",
            headline="Waiting on review",
            detail=LONG_DETAIL,
        )
        await service.add_entry(
            session, project=PROJECT, section="bugs", headline="Null deref in cart"
        )
        await service.add_entry(
            session, project=PROJECT, section="conventions", headline="Always pass --env-file .env"
        )
        await service.add_entry(
            session, project=PROJECT, section="decisions", headline="Export is entry-level only"
        )
        await service.add_entry(
            session,
            project=PROJECT,
            section="glossary",
            headline="PCS",
            detail="Project Context Server",
        )
        await service.add_entry(
            session,
            project=PROJECT,
            section="features",
            headline="Context export",
            detail="Dumps all nine sections.",
            linked_files=["server/src/pcs/context/export.py"],
        )
        req = await service.add_entry(
            session,
            project=PROJECT,
            section="requirements",
            headline="Agents can download full context",
            detail="Export must include every section.",
            requirement_status="in-progress",
        )
        req_id = req.id
    async with session_scope() as session:
        inv = await contracts.create_invariant(
            session,
            project=PROJECT,
            requirement_id=req_id,
            statement="Export never nests contract rows under requirements entries.",
            kind="behavior",
            risk="high",
            key="INV-EXPORT-1",
        )
        await contracts.create_criterion(
            session,
            project=PROJECT,
            invariant_id=inv.id,
            statement="JSON requirements entries lack invariants/criteria keys.",
            evidence_kind="test",
            key="AC-EXPORT-1",
        )
    return req_id


def test_validate_export_format_accepts_known_and_rejects_unknown() -> None:
    assert validate_export_format("markdown") == EXPORT_FORMAT_MARKDOWN
    assert validate_export_format("JSON") == EXPORT_FORMAT_JSON
    with pytest.raises(ValidationError, match="invalid export format"):
        validate_export_format("yaml")
    with pytest.raises(ValidationError, match="invalid export format"):
        validate_export_format("")


async def test_all_nine_sections_present_untruncated_in_markdown_and_json() -> None:
    await _seed_rich_project()

    async with session_scope() as session:
        export = await assemble_project_export(session, project=PROJECT)
        md = render_export_markdown(export)
        js = render_export_json(export)

    assert len(ALL_SECTIONS) == 9
    for section in ALL_SECTIONS:
        assert section in export.sections
        assert f"## {SECTION_HEADINGS[section]}" in md

    assert LONG_DETAIL in md
    assert "VERBATIM-LONG-DETAIL" in js
    assert "truncated" not in md.lower()

    payload = json.loads(js)
    assert set(payload["sections"]) == set(ALL_SECTIONS)
    for section in ALL_SECTIONS:
        assert isinstance(payload["sections"][section], list)


async def test_requirements_entries_are_entry_level_only() -> None:
    await _seed_rich_project()

    async with session_scope() as session:
        envelope = await export_project_context(session, project=PROJECT, format=EXPORT_FORMAT_JSON)

    content = str(envelope["content"])
    assert "INV-EXPORT-1" not in content
    assert "AC-EXPORT-1" not in content
    assert "invariants" not in content
    assert "acceptance" not in content.lower()
    assert "evidence" not in content.lower()

    tree = json.loads(content)
    reqs = tree["sections"]["requirements"]
    assert reqs
    for entry in reqs:
        assert "invariants" not in entry
        assert "criteria" not in entry
        assert "evidence" not in entry
        assert "headline" in entry
        assert "detail" in entry


async def test_mcp_and_http_return_equivalent_content() -> None:
    await _seed_rich_project()

    mcp_md = _extract_dict(
        await mcp.call_tool(
            "export_project_context",
            {"project": PROJECT, "format": "markdown"},
        )
    )
    mcp_json = _extract_dict(
        await mcp.call_tool(
            "export_project_context",
            {"project": PROJECT, "format": "json"},
        )
    )

    client = TestClient(build_http_app())
    http_md = client.get(f"/api/projects/{PROJECT}/export", params={"format": "markdown"})
    http_json = client.get(f"/api/projects/{PROJECT}/export", params={"format": "json"})
    assert http_md.status_code == 200
    assert http_json.status_code == 200
    http_md_body = http_md.json()
    http_json_body = http_json.json()

    assert set(mcp_md) == set(http_md_body)
    assert set(mcp_json) == set(http_json_body)
    for key in ("format", "filename", "media_type", "project"):
        assert mcp_md[key] == http_md_body[key]
        assert mcp_json[key] == http_json_body[key]

    assert _stable_markdown(str(mcp_md["content"])) == _stable_markdown(
        str(http_md_body["content"])
    )
    assert _stable_json_tree(str(mcp_json["content"])) == _stable_json_tree(
        str(http_json_body["content"])
    )
    assert mcp_md["filename"] == "export-demo-context.md"
    assert mcp_json["format"] == "json"


def _stable_markdown(content: str) -> str:
    """Drop the wall-clock export timestamp so MCP/HTTP dumps can match."""
    return "\n".join(line for line in content.splitlines() if not line.startswith("Exported at:"))


def _stable_json_tree(content: str) -> dict[str, Any]:
    tree = json.loads(content)
    tree.pop("exported_at", None)
    return cast(dict[str, Any], tree)


async def test_invalid_format_400_unknown_project_404() -> None:
    await _seed_rich_project()
    client = TestClient(build_http_app())

    bad = client.get(f"/api/projects/{PROJECT}/export", params={"format": "yaml"})
    assert bad.status_code == 400
    assert "format" in bad.json()["error"].lower()

    missing = client.get("/api/projects/no-such-project/export")
    assert missing.status_code == 404
    assert PROJECT in missing.json()["available"]

    with pytest.raises(ToolError):
        await mcp.call_tool(
            "export_project_context",
            {"project": PROJECT, "format": "yaml"},
        )
    with pytest.raises(ToolError):
        await mcp.call_tool(
            "export_project_context",
            {"project": "no-such-project", "format": "markdown"},
        )


async def test_export_tool_registered_and_route_mounted() -> None:
    tools = {tool.name for tool in await mcp.list_tools()}
    assert "export_project_context" in tools
    paths = {getattr(route, "path", None) for route in build_http_app().routes}
    assert "/api/projects/{project}/export" in paths
