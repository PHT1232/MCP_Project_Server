"""Tests for Codebase Guide MCP tools, resource, and HTTP routes (T16, R-078).

Invariants:
- INV-GUIDE-8: MCP and HTTP reads return equivalent guide state.
- INV-GUIDE-9: Only MCP describe_files writes summaries in v1; HTTP offers reads and sync only.
- INV-GUIDE-10: Every tool/route logs project, caller, and outcome without logging summary prose.
- INV-GUIDE-11: Markdown resource is generated from the same service payload.
- INV-GUIDE-12: Project isolation and scope/path validation apply identically at every adapter.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import pytest
from mcp.server.fastmcp.exceptions import ToolError
from starlette.testclient import TestClient

from pcs.codemap import guide
from pcs.context import service as context_service
from pcs.db.base import session_scope
from pcs.index import service as index_service
from pcs.mcp import build_http_app, mcp

pytestmark = pytest.mark.usefixtures("clean_db")

PROJECT_A = "guide-api-a"
PROJECT_B = "guide-api-b"


def _sample_repo(root: Path) -> None:
    (root / "services" / "billing").mkdir(parents=True, exist_ok=True)
    (root / "lib").mkdir(parents=True, exist_ok=True)
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


async def _register_and_index(root: Path, project: str = PROJECT_A) -> None:
    _sample_repo(root)
    async with session_scope() as session:
        await context_service.register_project(
            session,
            name=project,
            root_path=str(root),
            overview=f"Test repo {project}",
        )
        await index_service.reindex(session, project=project, incremental=False)


def _client() -> TestClient:
    return TestClient(build_http_app())


async def _mcp_call(tool: str, args: dict[str, Any], caller_name: str = "test-agent") -> Any:
    with patch("pcs.mcp.codemap_tools.caller", return_value=caller_name):
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


# ---------------------------------------------------------------------------
# AC-GUIDE-API-1: MCP read exposes all/documented/undocumented/stale and scoped views
# ---------------------------------------------------------------------------
async def test_mcp_guide_read_and_scoped_views(tmp_path: Path) -> None:
    await _register_and_index(tmp_path)

    # Initially undocumented
    res = _extract_dict(await _mcp_call("get_codebase_guide", {"project": PROJECT_A}))
    assert res["project"] == PROJECT_A
    assert res["coverage"]["total"] == 5
    assert res["coverage"]["documented"] == 0
    assert len(res["files"]) == 5

    # Add a note
    await _mcp_call(
        "describe_files",
        {
            "project": PROJECT_A,
            "notes": [{"path": "main.py", "summary": "Application entry point."}],
        },
    )

    # Filter: documented
    doc_res = _extract_dict(
        await _mcp_call("get_codebase_guide", {"project": PROJECT_A, "include": "documented"})
    )
    assert len(doc_res["files"]) == 1
    assert doc_res["files"][0]["path"] == "main.py"

    # Filter: undocumented
    undoc_res = _extract_dict(
        await _mcp_call("get_codebase_guide", {"project": PROJECT_A, "include": "undocumented"})
    )
    assert len(undoc_res["files"]) == 4
    paths = {f["path"] for f in undoc_res["files"]}
    assert "main.py" not in paths
    assert {"lib/money.py", "services/billing/invoice.py"}.issubset(paths)

    # Scoped view: services/billing
    scoped_res = _extract_dict(
        await _mcp_call(
            "get_codebase_guide",
            {"project": PROJECT_A, "scope": "services/billing"},
        )
    )
    assert len(scoped_res["files"]) == 1
    assert scoped_res["files"][0]["path"] == "services/billing/invoice.py"


# ---------------------------------------------------------------------------
# AC-GUIDE-API-2: MCP describe writes multiple summaries, deletes empty summaries, reports unknown
# ---------------------------------------------------------------------------
async def test_mcp_describe_writes_deletes_and_reports_unknown(tmp_path: Path) -> None:
    await _register_and_index(tmp_path)

    desc_res = _extract_dict(
        await _mcp_call(
            "describe_files",
            {
                "project": PROJECT_A,
                "notes": [
                    {"path": "main.py", "summary": "Entry point."},
                    {"path": "lib/money.py", "summary": "Money value object."},
                    {"path": "nonexistent.py", "summary": "Unknown file."},
                ],
            },
        )
    )
    assert "main.py" in desc_res["applied"]
    assert "lib/money.py" in desc_res["applied"]
    assert len(desc_res["unknown"]) == 1
    assert desc_res["unknown"][0]["path"] == "nonexistent.py"
    assert desc_res["coverage"]["documented"] == 2

    # Delete empty summary
    del_res = _extract_dict(
        await _mcp_call(
            "describe_files",
            {
                "project": PROJECT_A,
                "notes": [{"path": "main.py", "summary": ""}],
            },
        )
    )
    assert "main.py" in del_res["deleted"]
    assert del_res["coverage"]["documented"] == 1


# ---------------------------------------------------------------------------
# AC-GUIDE-API-3: MCP sync regenerates the configured artifact
# ---------------------------------------------------------------------------
async def test_mcp_sync_regenerates_configured_artifact(tmp_path: Path) -> None:
    await _register_and_index(tmp_path)
    await _mcp_call(
        "describe_files",
        {
            "project": PROJECT_A,
            "notes": [{"path": "main.py", "summary": "Entry point."}],
        },
    )

    sync_res = _extract_dict(await _mcp_call("sync_codebase_guide", {"project": PROJECT_A}))
    assert sync_res["file_writable"] is True
    artifact_path = Path(str(sync_res["path"]))
    assert artifact_path.exists()
    content = artifact_path.read_text(encoding="utf-8")
    assert "Entry point." in content
    assert guide.DO_NOT_EDIT in content


# ---------------------------------------------------------------------------
# AC-GUIDE-API-4 / INV-GUIDE-11: Resource Markdown equals service renderer output
# ---------------------------------------------------------------------------
async def test_resource_markdown_equals_renderer_output(tmp_path: Path) -> None:
    await _register_and_index(tmp_path)
    await _mcp_call(
        "describe_files",
        {
            "project": PROJECT_A,
            "notes": [{"path": "lib/money.py", "summary": "Money representation."}],
        },
    )

    contents = list(await mcp.read_resource(f"context://{PROJECT_A}/codebase-guide"))
    assert len(contents) == 1
    resource_md = str(contents[0].content)

    async with session_scope() as session:
        service_data = await guide.get_codebase_guide(
            session, project=PROJECT_A, include=guide.INCLUDE_ALL
        )
        expected_md = guide.render_guide_markdown(service_data)

    assert resource_md == expected_md
    assert "Money representation." in resource_md


# ---------------------------------------------------------------------------
# AC-GUIDE-API-5 / INV-GUIDE-8: HTTP guide read equals MCP state + artifact writability
# ---------------------------------------------------------------------------
async def test_http_guide_read_equals_mcp_state_and_metadata(tmp_path: Path) -> None:
    await _register_and_index(tmp_path)
    await _mcp_call(
        "describe_files",
        {
            "project": PROJECT_A,
            "notes": [{"path": "main.py", "summary": "App main."}],
        },
    )

    mcp_data = _extract_dict(await _mcp_call("get_codebase_guide", {"project": PROJECT_A}))

    client = _client()
    resp = client.get(f"/api/projects/{PROJECT_A}/codebase-guide")
    assert resp.status_code == 200
    http_data = resp.json()

    assert http_data["project"] == mcp_data["project"]
    assert http_data["scope"] == mcp_data["scope"]
    assert http_data["include"] == mcp_data["include"]
    assert http_data["coverage"] == mcp_data["coverage"]
    assert http_data["files"] == mcp_data["files"]
    assert "artifact" in http_data
    assert http_data["file_writable"] is True
    assert http_data["file_path"] is not None


# ---------------------------------------------------------------------------
# AC-GUIDE-API-6 / INV-GUIDE-9: HTTP sync regenerates artifact; no summary editing route
# ---------------------------------------------------------------------------
async def test_http_sync_and_no_summary_edit_route(tmp_path: Path) -> None:
    await _register_and_index(tmp_path)
    await _mcp_call(
        "describe_files",
        {
            "project": PROJECT_A,
            "notes": [{"path": "main.py", "summary": "Entry point via MCP."}],
        },
    )

    client = _client()
    sync_resp = client.post(f"/api/projects/{PROJECT_A}/codebase-guide/sync")
    assert sync_resp.status_code == 200
    res = sync_resp.json()
    assert res["file_writable"] is True
    artifact_path = Path(res["path"])
    assert "Entry point via MCP." in artifact_path.read_text(encoding="utf-8")

    # INV-GUIDE-9: Ensure POST/PUT to /codebase-guide (summary edit) does not exist (405 or 404)
    bad_post = client.post(
        f"/api/projects/{PROJECT_A}/codebase-guide",
        json={"notes": [{"path": "main.py", "summary": "Hacked via HTTP"}]},
    )
    assert bad_post.status_code == 405


# ---------------------------------------------------------------------------
# AC-GUIDE-API-7: Bounded error responses for unknown project, invalid params, etc.
# ---------------------------------------------------------------------------
async def test_bounded_error_responses(tmp_path: Path) -> None:
    await _register_and_index(tmp_path)
    client = _client()

    # Unknown project -> 404
    resp = client.get("/api/projects/unknown-proj/codebase-guide")
    assert resp.status_code == 404

    # Invalid include -> 400
    resp = client.get(f"/api/projects/{PROJECT_A}/codebase-guide?include=invalid_mode")
    assert resp.status_code == 400

    # Invalid / unknown scope -> 400
    resp = client.get(f"/api/projects/{PROJECT_A}/codebase-guide?scope=nonexistent/dir")
    assert resp.status_code == 400

    # MCP malformed notes (not a list) -> ToolError
    with pytest.raises(ToolError):
        await _mcp_call("describe_files", {"project": PROJECT_A, "notes": "not-a-list"})


# ---------------------------------------------------------------------------
# AC-GUIDE-API-8 / INV-GUIDE-12: Cross-project isolation
# ---------------------------------------------------------------------------
async def test_cross_project_isolation(tmp_path: Path) -> None:
    root_a = tmp_path / "repo_a"
    root_b = tmp_path / "repo_b"
    root_a.mkdir()
    root_b.mkdir()
    await _register_and_index(root_a, project=PROJECT_A)
    await _register_and_index(root_b, project=PROJECT_B)

    # Write summary to project A
    await _mcp_call(
        "describe_files",
        {
            "project": PROJECT_A,
            "notes": [{"path": "main.py", "summary": "Project A main"}],
        },
    )

    # Project B must remain completely undocumented
    b_res = _extract_dict(await _mcp_call("get_codebase_guide", {"project": PROJECT_B}))
    assert b_res["coverage"]["documented"] == 0
    for f in b_res["files"]:
        assert f["summary"] is None

    # Project B cannot sync Project A's files
    sync_b = _extract_dict(await _mcp_call("sync_codebase_guide", {"project": PROJECT_B}))
    assert "Project A main" not in Path(str(sync_b["path"])).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# AC-GUIDE-API-9 / INV-GUIDE-10: Audit logging without summary prose
# ---------------------------------------------------------------------------
async def test_audit_logging_omits_summary_prose(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    await _register_and_index(tmp_path)
    sensitive_summary = "SECRET_TOKEN_42 in billing service implementation."

    caplog.clear()
    with caplog.at_level(logging.INFO, logger="pcs"):
        await _mcp_call(
            "describe_files",
            {
                "project": PROJECT_A,
                "notes": [{"path": "main.py", "summary": sensitive_summary}],
            },
            caller_name="agent-xyz",
        )

    # Sensitive prose must NEVER appear in any log record
    for record in caplog.records:
        assert sensitive_summary not in record.getMessage()

    # HTTP read logging
    client = _client()
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="pcs"):
        resp = client.get(
            f"/api/projects/{PROJECT_A}/codebase-guide",
            headers={"x-pcs-caller": "frontend-user"},
        )
        assert resp.status_code == 200

    for record in caplog.records:
        assert sensitive_summary not in record.getMessage()


# ---------------------------------------------------------------------------
# AC-GUIDE-API-10: Existing code-map routes/tools remain compatible
# ---------------------------------------------------------------------------
async def test_existing_codemap_compatibility(tmp_path: Path) -> None:
    await _register_and_index(tmp_path)

    # Tool
    map_res = await mcp.call_tool("get_code_map", {"project": PROJECT_A})
    assert map_res

    # Resource
    map_res_content = list(await mcp.read_resource(f"context://{PROJECT_A}/code-map"))
    assert map_res_content

    # HTTP route
    client = _client()
    resp = client.get(f"/api/projects/{PROJECT_A}/code-map")
    assert resp.status_code == 200
