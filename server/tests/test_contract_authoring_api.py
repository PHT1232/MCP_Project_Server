"""T14 contract authoring adapters — MCP and HTTP wrap pcs.requirements.contracts."""

from __future__ import annotations

import json
import logging
import subprocess
from contextlib import suppress
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import pytest
from mcp.server.fastmcp.exceptions import ToolError
from starlette.testclient import TestClient

from pcs.context import service
from pcs.context.types import CONTRACT_STATEMENT_MAX_CHARS, REQ_DONE
from pcs.db.base import session_scope
from pcs.logging import JsonFormatter
from pcs.mcp import build_http_app, mcp
from pcs.mcp.contract_tools import EMPTY_MUTATION, EXPLICIT_NULL, UNKNOWN_FIELDS
from pcs.requirements import compliance, contracts, evidence

pytestmark = pytest.mark.usefixtures("clean_db")

PROJECT = "t14-project"
OTHER = "t14-other"
SECRET_PROSE = "UNIQUE-CONTRACT-PROSE-MUST-NOT-APPEAR-IN-AUDIT"


def _tool_payload(result: object) -> dict[str, object]:
    if isinstance(result, tuple):
        _, structured = result
        if isinstance(structured, dict):
            return cast(dict[str, object], structured)
    value = result[0].text if isinstance(result, list) else result
    return cast(dict[str, object], json.loads(str(value)))


async def _call(name: str, arguments: dict[str, object]) -> dict[str, object]:
    return _tool_payload(await mcp.call_tool(name, arguments))


def _git(root: Path) -> str:
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t14@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "T14"], cwd=root, check=True)
    (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "seed"], cwd=root, check=True, capture_output=True)
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()


async def _requirement(
    *, project: str = PROJECT, title: str = "Ship login", root: Path | None = None
) -> str:
    path = str(root) if root is not None else f"/repos/{project}"
    async with session_scope() as session:
        with suppress(service.DuplicateProjectError):
            await service.register_project(
                session, name=project, root_path=path, overview=f"{project} overview"
            )
        row = await service.add_entry(
            session, project=project, section="requirements", headline=title
        )
        return row.id


def _client() -> TestClient:
    return TestClient(build_http_app())


def _http(
    client: TestClient,
    method: str,
    path: str,
    *,
    json_body: dict[str, object] | None = None,
    caller: str = "http-reviewer",
) -> Any:
    return client.request(
        method,
        path,
        json=json_body,
        headers={"x-pcs-caller": caller},
    )


async def test_mcp_create_returns_stable_ids_in_contract() -> None:
    req_id = await _requirement()
    with patch("pcs.mcp.contract_tools.caller", return_value="mcp-agent"):
        invariant = await _call(
            "create_requirement_invariant",
            {
                "project": PROJECT,
                "requirement_id": req_id,
                "key": "INV-AUTH",
                "statement": "Login stays passwordless.",
                "kind": "behavior",
                "risk": "high",
            },
        )
        criterion = await _call(
            "create_acceptance_criterion",
            {
                "project": PROJECT,
                "invariant_id": invariant["id"],
                "key": "AC-LOGIN",
                "statement": "Passwordless login is covered by tests.",
                "evidence_kind": "test",
                "independent_review": "required",
            },
        )
        contract = await _call(
            "get_requirement_contract",
            {"project": PROJECT, "requirement_id": req_id},
        )
    assert invariant["id"]
    assert criterion["id"]
    assert criterion["invariant_id"] == invariant["id"]
    invs = cast(list[dict[str, object]], contract["invariants"])
    acs = cast(list[dict[str, object]], contract["criteria"])
    assert invs[0]["id"] == invariant["id"]
    assert invs[0]["key"] == "INV-AUTH"
    assert acs[0]["id"] == criterion["id"]
    assert acs[0]["key"] == "AC-LOGIN"


async def test_mcp_mutations_record_caller_as_revision_author() -> None:
    req_id = await _requirement()
    with (
        patch("pcs.mcp.contract_tools.caller", return_value="mcp-agent"),
        patch("pcs.mcp.support.caller", return_value="mcp-agent"),
    ):
        invariant = await _call(
            "create_requirement_invariant",
            {
                "project": PROJECT,
                "requirement_id": req_id,
                "statement": "Agents cannot write SQL from adapters.",
                "kind": "architecture",
                "risk": "high",
            },
        )
        await _call(
            "update_requirement_invariant",
            {"project": PROJECT, "invariant_id": invariant["id"], "risk": "medium"},
        )
        criterion = await _call(
            "create_acceptance_criterion",
            {
                "project": PROJECT,
                "invariant_id": invariant["id"],
                "statement": "Adapter tests cover MCP authorship.",
                "evidence_kind": "test",
            },
        )
        await _call(
            "update_acceptance_criterion",
            {"project": PROJECT, "criterion_id": criterion["id"], "required": False},
        )
        await _call(
            "delete_acceptance_criterion",
            {"project": PROJECT, "criterion_id": criterion["id"]},
        )
    async with session_scope() as session:
        revisions = await contracts.list_contract_revisions(
            session, project=PROJECT, requirement_id=req_id
        )
        invariant_row = await contracts.get_invariant(
            session, project=PROJECT, invariant_id=str(invariant["id"])
        )
    assert {row.author for row in revisions} == {"mcp-agent"}
    assert [row.action for row in revisions] == [
        "create",
        "update",
        "create",
        "update",
        "delete",
    ]
    assert invariant_row.author == "mcp-agent"
    assert invariant_row.risk == "medium"


async def test_http_mutations_match_mcp_stored_state() -> None:
    req_id = await _requirement()
    client = _client()
    created = _http(
        client,
        "POST",
        f"/api/projects/{PROJECT}/requirements/{req_id}/invariants",
        json_body={
            "key": "INV-HTTP",
            "statement": "HTTP and MCP share contracts.create_invariant.",
            "kind": "behavior",
            "risk": "low",
        },
    )
    assert created.status_code == 201
    invariant = created.json()
    assert invariant["author"] == "http-reviewer"
    criterion = _http(
        client,
        "POST",
        f"/api/projects/{PROJECT}/requirements/invariants/{invariant['id']}/criteria",
        json_body={
            "key": "AC-HTTP",
            "statement": "HTTP create stores the same shape as MCP.",
            "evidence_kind": "test",
        },
    )
    assert criterion.status_code == 201
    assert criterion.json()["author"] == "http-reviewer"

    mcp_contract = await _call(
        "get_requirement_contract", {"project": PROJECT, "requirement_id": req_id}
    )
    http_contract = client.get(f"/api/projects/{PROJECT}/requirements/{req_id}/contract").json()
    assert mcp_contract == http_contract
    assert http_contract["invariants"][0]["id"] == invariant["id"]
    assert http_contract["criteria"][0]["id"] == criterion.json()["id"]

    patched = _http(
        client,
        "PATCH",
        f"/api/projects/{PROJECT}/requirements/invariants/{invariant['id']}",
        json_body={"statement": "Updated via HTTP."},
    )
    assert patched.status_code == 200
    assert patched.json()["statement"] == "Updated via HTTP."
    via_mcp = await _call(
        "get_requirement_contract", {"project": PROJECT, "requirement_id": req_id}
    )
    assert cast(list[dict[str, object]], via_mcp["invariants"])[0]["statement"] == (
        "Updated via HTTP."
    )
    async with session_scope() as session:
        revisions = await contracts.list_contract_revisions(
            session, project=PROJECT, requirement_id=req_id
        )
    assert revisions[0].author == "http-reviewer"
    assert revisions[-1].action == "update"
    assert revisions[-1].author == "http-reviewer"


async def test_partial_update_preserves_omitted_fields_and_rejects_empty() -> None:
    req_id = await _requirement()
    async with session_scope() as session:
        invariant = await contracts.create_invariant(
            session,
            project=PROJECT,
            requirement_id=req_id,
            key="INV-KEEP",
            statement="Original statement.",
            kind="behavior",
            risk="high",
            sort_order=3,
        )
        criterion = await contracts.create_criterion(
            session,
            project=PROJECT,
            invariant_id=invariant.id,
            key="AC-KEEP",
            statement="Original criterion.",
            evidence_kind="test",
            required=True,
            independent_review="required",
        )
    client = _client()
    with pytest.raises(ToolError, match="empty mutation"):
        await mcp.call_tool(
            "update_requirement_invariant",
            {"project": PROJECT, "invariant_id": invariant.id},
        )
    empty_http = _http(
        client,
        "PATCH",
        f"/api/projects/{PROJECT}/requirements/invariants/{invariant.id}",
        json_body={},
    )
    assert empty_http.status_code == 400
    assert EMPTY_MUTATION in empty_http.json()["error"]

    updated = await _call(
        "update_requirement_invariant",
        {"project": PROJECT, "invariant_id": invariant.id, "risk": "low"},
    )
    assert updated["risk"] == "low"
    assert updated["statement"] == "Original statement."
    assert updated["kind"] == "behavior"
    assert updated["key"] == "INV-KEEP"
    assert updated["sort_order"] == 3

    http_updated = _http(
        client,
        "PATCH",
        f"/api/projects/{PROJECT}/requirements/criteria/{criterion.id}",
        json_body={"required": False},
    )
    assert http_updated.status_code == 200
    body = http_updated.json()
    assert body["required"] is False
    assert body["statement"] == "Original criterion."
    assert body["evidence_kind"] == "test"
    assert body["independent_review"] == "required"
    assert body["key"] == "AC-KEEP"

    null_clear = _http(
        client,
        "PATCH",
        f"/api/projects/{PROJECT}/requirements/invariants/{invariant.id}",
        json_body={"statement": None},
    )
    assert null_clear.status_code == 400
    assert EXPLICIT_NULL in null_clear.json()["error"]


async def test_validation_isolation_and_wrong_section_errors() -> None:
    req_id = await _requirement()
    other_req = await _requirement(project=OTHER, title="Other")
    async with session_scope() as session:
        blocker = await service.add_entry(
            session, project=PROJECT, section="blockers", headline="Not a requirement"
        )
        invariant = await contracts.create_invariant(
            session,
            project=PROJECT,
            requirement_id=req_id,
            key="INV-DUP",
            statement="Unique key.",
            kind="behavior",
            risk="low",
        )
        other_inv = await contracts.create_invariant(
            session,
            project=OTHER,
            requirement_id=other_req,
            statement="Other project invariant.",
            kind="behavior",
            risk="low",
        )
    client = _client()

    with pytest.raises(ToolError, match="already exists"):
        await mcp.call_tool(
            "create_requirement_invariant",
            {
                "project": PROJECT,
                "requirement_id": req_id,
                "key": "INV-DUP",
                "statement": "Second.",
                "kind": "behavior",
                "risk": "low",
            },
        )

    bad_kind = _http(
        client,
        "POST",
        f"/api/projects/{PROJECT}/requirements/{req_id}/invariants",
        json_body={"statement": "Bad kind.", "kind": "not-a-kind", "risk": "low"},
    )
    assert bad_kind.status_code == 400
    assert "kind" in bad_kind.json()["error"]

    empty = _http(
        client,
        "POST",
        f"/api/projects/{PROJECT}/requirements/{req_id}/invariants",
        json_body={"statement": "", "kind": "behavior", "risk": "low"},
    )
    assert empty.status_code == 400

    oversized = _http(
        client,
        "POST",
        f"/api/projects/{PROJECT}/requirements/{req_id}/invariants",
        json_body={
            "statement": "x" * (CONTRACT_STATEMENT_MAX_CHARS + 1),
            "kind": "behavior",
            "risk": "low",
        },
    )
    assert oversized.status_code == 400

    negative = _http(
        client,
        "PATCH",
        f"/api/projects/{PROJECT}/requirements/invariants/{invariant.id}",
        json_body={"sort_order": -1},
    )
    assert negative.status_code == 400

    wrong_section = _http(
        client,
        "POST",
        f"/api/projects/{PROJECT}/requirements/{blocker.id}/invariants",
        json_body={"statement": "Nope.", "kind": "behavior", "risk": "low"},
    )
    assert wrong_section.status_code in {400, 404}

    cross = _http(
        client,
        "PATCH",
        f"/api/projects/{PROJECT}/requirements/invariants/{other_inv.id}",
        json_body={"risk": "high"},
    )
    assert cross.status_code in {400, 404}


async def test_soft_delete_hides_from_reads_and_keeps_history() -> None:
    req_id = await _requirement()
    async with session_scope() as session:
        invariant = await contracts.create_invariant(
            session,
            project=PROJECT,
            requirement_id=req_id,
            key="INV-DEL",
            statement="Will be deleted.",
            kind="behavior",
            risk="medium",
        )
        criterion = await contracts.create_criterion(
            session,
            project=PROJECT,
            invariant_id=invariant.id,
            key="AC-DEL",
            statement="Cascaded delete.",
            evidence_kind="test",
        )
    with patch("pcs.mcp.contract_tools.caller", return_value="mcp-agent"):
        deleted = await _call(
            "delete_requirement_invariant",
            {"project": PROJECT, "invariant_id": invariant.id},
        )
    assert deleted["status"] == "deleted"
    contract = await _call(
        "get_requirement_contract", {"project": PROJECT, "requirement_id": req_id}
    )
    assert contract["invariants"] == []
    assert contract["criteria"] == []
    client = _client()
    http_contract = client.get(f"/api/projects/{PROJECT}/requirements/{req_id}/contract").json()
    assert http_contract["invariants"] == []
    async with session_scope() as session:
        revisions = await contracts.list_contract_revisions(
            session, project=PROJECT, requirement_id=req_id
        )
        hidden_inv = await contracts.get_invariant(
            session, project=PROJECT, invariant_id=invariant.id, include_deleted=True
        )
        hidden_ac = await contracts.get_criterion(
            session, project=PROJECT, criterion_id=criterion.id, include_deleted=True
        )
    actions = [(row.entity_kind, row.action, row.entity_id) for row in revisions]
    assert ("criterion", "delete", criterion.id) in actions
    assert ("invariant", "delete", invariant.id) in actions
    assert hidden_inv.status == "deleted"
    assert hidden_ac.status == "deleted"


async def test_audit_logs_omit_contract_prose() -> None:
    req_id = await _requirement()
    seen: list[dict[str, object]] = []

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
                **fields,
            }
        )

    with (
        patch("pcs.mcp.contract_tools.caller", return_value="mcp-agent"),
        patch("pcs.mcp.support.caller", return_value="mcp-agent"),
        patch("pcs.mcp.contract_tools.log_tool_call", spy),
        patch("pcs.web_api.requirements_routes.log_tool_call", spy),
    ):
        invariant = await _call(
            "create_requirement_invariant",
            {
                "project": PROJECT,
                "requirement_id": req_id,
                "statement": SECRET_PROSE,
                "kind": "behavior",
                "risk": "high",
            },
        )
        client = _client()
        _http(
            client,
            "PATCH",
            f"/api/projects/{PROJECT}/requirements/invariants/{invariant['id']}",
            json_body={"statement": SECRET_PROSE},
        )
    dumped = json.dumps(seen)
    assert SECRET_PROSE not in dumped
    assert any(item["tool"] == "create_requirement_invariant" for item in seen)
    assert any(item["tool"] == "update_requirement_invariant" for item in seen)
    assert all(item["caller"] for item in seen)
    assert all(item["project"] == PROJECT for item in seen)
    record = logging.LogRecord("pcs", logging.INFO, __file__, 0, "tool_call", (), None)
    record.__dict__["context"] = {
        "tool": "create_requirement_invariant",
        "project": PROJECT,
        "caller": "mcp-agent",
        "outcome": "ok",
    }
    payload = json.loads(JsonFormatter().format(record))
    assert payload["tool"] == "create_requirement_invariant"
    assert SECRET_PROSE not in json.dumps(payload)


async def test_legacy_requirement_to_verified_close_gate(tmp_path: Path) -> None:
    sha = _git(tmp_path)
    req_id = await _requirement(root=tmp_path, title="Author then verify")
    async with session_scope() as session:
        before = await evidence.evaluate_close_gate(session, project=PROJECT, requirement_id=req_id)
        review_before = await compliance.review_requirement_compliance(
            session, project=PROJECT, requirement_ids=[req_id]
        )
    assert before.configured is False
    assert before.passed is True
    assert review_before.requirements[0]["verdict"] == "not-configured"

    with patch("pcs.mcp.contract_tools.caller", return_value="mcp-agent"):
        invariant = await _call(
            "create_requirement_invariant",
            {
                "project": PROJECT,
                "requirement_id": req_id,
                "key": "INV-GATE",
                "statement": "Close gate requires evidence and independent review.",
                "kind": "behavior",
                "risk": "high",
            },
        )
        criterion = await _call(
            "create_acceptance_criterion",
            {
                "project": PROJECT,
                "invariant_id": invariant["id"],
                "key": "AC-GATE",
                "statement": "Record passing tests and an independent review.",
                "evidence_kind": "test",
                "independent_review": "required",
            },
        )
        missing_gate = await _call(
            "evaluate_close_gate", {"project": PROJECT, "requirement_id": req_id}
        )
        missing_review = await _call(
            "review_requirement_compliance",
            {"project": PROJECT, "requirement_ids": [req_id]},
        )
    assert missing_gate["configured"] is True
    assert missing_gate["passed"] is False
    assert missing_gate["ac_total"] == 1
    assert missing_gate["ac_verified"] == 0
    assert any("AC-GATE" in item for item in cast(list[str], missing_gate["unmet"]))
    missing_row = cast(list[dict[str, object]], missing_review["requirements"])[0]
    assert missing_row["verdict"] == "failed"
    assert missing_row["ac_total"] == 1

    with pytest.raises(evidence.CloseGateError):
        async with session_scope() as session:
            await service.set_requirement_status(
                session, project=PROJECT, entry_id=req_id, status=REQ_DONE
            )

    async with session_scope() as session:
        await evidence.record_evidence(
            session,
            project=PROJECT,
            criterion_id=str(criterion["id"]),
            kind="test",
            result="passed",
            source_commit=sha,
            test_ref="tests/test_contract_authoring_api.py",
            author="implementer",
        )
        await evidence.record_evidence(
            session,
            project=PROJECT,
            criterion_id=str(criterion["id"]),
            kind="review",
            result="passed",
            source_commit=sha,
            author="reviewer",
        )
        gate = await evidence.evaluate_close_gate(session, project=PROJECT, requirement_id=req_id)
        review = await compliance.review_requirement_compliance(
            session, project=PROJECT, requirement_ids=[req_id]
        )
        done = await service.set_requirement_status(
            session, project=PROJECT, entry_id=req_id, status=REQ_DONE
        )
    assert gate.passed is True
    assert gate.ac_verified == 1
    assert gate.ac_total == 1
    assert review.requirements[0]["verdict"] == "verified"
    assert review.requirements[0]["exceptions"] == []
    assert done.requirement_status == REQ_DONE


async def test_existing_read_routes_remain_registered() -> None:
    app = build_http_app()
    paths = {getattr(route, "path", None) for route in app.routes}
    assert "/api/projects/{project}/requirements/{requirement_id}/contract" in paths
    assert "/api/projects/{project}/requirements/{requirement_id}/evidence" in paths
    assert "/api/projects/{project}/requirements/compliance" in paths
    assert "/api/projects/{project}/requirements/{requirement_id}/invariants" in paths
    tools = {t.name for t in await mcp.list_tools()}
    assert "create_requirement_invariant" in tools
    assert "update_requirement_invariant" in tools
    assert "delete_requirement_invariant" in tools
    assert "create_acceptance_criterion" in tools
    assert "update_acceptance_criterion" in tools
    assert "delete_acceptance_criterion" in tools
    assert "get_requirement_contract" in tools
    assert "evaluate_close_gate" in tools
    assert "review_requirement_compliance" in tools


async def test_http_criterion_delete_matches_mcp() -> None:
    req_id = await _requirement()
    client = _client()
    invariant = _http(
        client,
        "POST",
        f"/api/projects/{PROJECT}/requirements/{req_id}/invariants",
        json_body={"statement": "Keep parent.", "kind": "behavior", "risk": "low"},
    ).json()
    criterion = _http(
        client,
        "POST",
        f"/api/projects/{PROJECT}/requirements/invariants/{invariant['id']}/criteria",
        json_body={"statement": "Soft-delete me.", "evidence_kind": "manual"},
    ).json()
    deleted = _http(
        client,
        "DELETE",
        f"/api/projects/{PROJECT}/requirements/criteria/{criterion['id']}",
    )
    assert deleted.status_code == 200
    assert deleted.json()["status"] == "deleted"
    contract = client.get(f"/api/projects/{PROJECT}/requirements/{req_id}/contract").json()
    assert contract["invariants"][0]["id"] == invariant["id"]
    assert contract["criteria"] == []


async def test_mcp_explicit_null_rejects_whole_payload_false_and_zero_ok() -> None:
    req_id = await _requirement()
    async with session_scope() as session:
        invariant = await contracts.create_invariant(
            session,
            project=PROJECT,
            requirement_id=req_id,
            key="INV-NULL",
            statement="Keep original statement.",
            kind="behavior",
            risk="high",
            sort_order=4,
        )
        criterion = await contracts.create_criterion(
            session,
            project=PROJECT,
            invariant_id=invariant.id,
            key="AC-NULL",
            statement="Keep original criterion.",
            evidence_kind="test",
            required=True,
            independent_review="required",
            sort_order=2,
        )
    with pytest.raises(ToolError, match="explicit null"):
        await mcp.call_tool(
            "update_requirement_invariant",
            {"project": PROJECT, "invariant_id": invariant.id, "statement": None},
        )
    with pytest.raises(ToolError, match="explicit null"):
        await mcp.call_tool(
            "update_requirement_invariant",
            {
                "project": PROJECT,
                "invariant_id": invariant.id,
                "statement": None,
                "risk": "low",
            },
        )
    async with session_scope() as session:
        unchanged = await contracts.get_invariant(
            session, project=PROJECT, invariant_id=invariant.id
        )
    assert unchanged.statement == "Keep original statement."
    assert unchanged.risk == "high"

    zeroed = await _call(
        "update_requirement_invariant",
        {"project": PROJECT, "invariant_id": invariant.id, "sort_order": 0},
    )
    assert zeroed["sort_order"] == 0
    assert zeroed["statement"] == "Keep original statement."
    assert zeroed["risk"] == "high"

    cleared_required = await _call(
        "update_acceptance_criterion",
        {"project": PROJECT, "criterion_id": criterion.id, "required": False},
    )
    assert cleared_required["required"] is False
    assert cleared_required["independent_review"] == "required"
    assert cleared_required["sort_order"] == 2

    with pytest.raises(ToolError, match="explicit null"):
        await mcp.call_tool(
            "update_acceptance_criterion",
            {
                "project": PROJECT,
                "criterion_id": criterion.id,
                "required": False,
                "statement": None,
            },
        )
    async with session_scope() as session:
        still = await contracts.get_criterion(session, project=PROJECT, criterion_id=criterion.id)
    assert still.required is False
    assert still.statement == "Keep original criterion."


async def test_http_unknown_fields_and_strict_json_types() -> None:
    req_id = await _requirement()
    client = _client()
    created = _http(
        client,
        "POST",
        f"/api/projects/{PROJECT}/requirements/{req_id}/invariants",
        json_body={
            "statement": "Typed create.",
            "kind": "behavior",
            "risk": "low",
            "sort_order": 0,
        },
    )
    assert created.status_code == 201
    assert created.json()["sort_order"] == 0
    invariant_id = str(created.json()["id"])

    unknown = _http(
        client,
        "POST",
        f"/api/projects/{PROJECT}/requirements/{req_id}/invariants",
        json_body={
            "statement": "Typo field.",
            "kind": "behavior",
            "risk": "low",
            "statment": SECRET_PROSE,
        },
    )
    assert unknown.status_code == 400
    assert unknown.json()["error"] == UNKNOWN_FIELDS

    coerced = _http(
        client,
        "POST",
        f"/api/projects/{PROJECT}/requirements/{req_id}/invariants",
        json_body={"statement": 123, "kind": "behavior", "risk": "low"},
    )
    assert coerced.status_code == 400
    assert "must be a string" in coerced.json()["error"]

    bool_as_kind = _http(
        client,
        "PATCH",
        f"/api/projects/{PROJECT}/requirements/invariants/{invariant_id}",
        json_body={"risk": True},
    )
    assert bool_as_kind.status_code == 400

    string_sort = _http(
        client,
        "PATCH",
        f"/api/projects/{PROJECT}/requirements/invariants/{invariant_id}",
        json_body={"sort_order": "0"},
    )
    assert string_sort.status_code == 400

    criterion = _http(
        client,
        "POST",
        f"/api/projects/{PROJECT}/requirements/invariants/{invariant_id}/criteria",
        json_body={
            "statement": "Typed criterion.",
            "evidence_kind": "test",
            "required": False,
            "sort_order": 0,
        },
    )
    assert criterion.status_code == 201
    assert criterion.json()["required"] is False
    assert criterion.json()["sort_order"] == 0
    criterion_id = str(criterion.json()["id"])

    int_required = _http(
        client,
        "PATCH",
        f"/api/projects/{PROJECT}/requirements/criteria/{criterion_id}",
        json_body={"required": 0},
    )
    assert int_required.status_code == 400

    unknown_patch = _http(
        client,
        "PATCH",
        f"/api/projects/{PROJECT}/requirements/criteria/{criterion_id}",
        json_body={"required": False, "extra": SECRET_PROSE},
    )
    assert unknown_patch.status_code == 400
    assert unknown_patch.json()["error"] == UNKNOWN_FIELDS
    mixed_null = _http(
        client,
        "PATCH",
        f"/api/projects/{PROJECT}/requirements/invariants/{invariant_id}",
        json_body={"statement": None, "risk": "high"},
    )
    assert mixed_null.status_code == 400
    assert EXPLICIT_NULL in mixed_null.json()["error"]
    listed = client.get(f"/api/projects/{PROJECT}/requirements/{req_id}/contract").json()
    assert listed["criteria"][0]["required"] is False
    assert listed["invariants"][0]["statement"] == "Typed create."
    assert listed["invariants"][0]["risk"] == "low"


async def test_audit_failure_omits_caller_payload() -> None:
    req_id = await _requirement()
    seen: list[dict[str, object]] = []

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
                **fields,
            }
        )

    leak_key = "INV-LEAK-KEY"
    with (
        patch("pcs.mcp.contract_tools.caller", return_value="mcp-agent"),
        patch("pcs.mcp.contract_tools.log_tool_call", spy),
        patch("pcs.web_api.requirements_routes.log_tool_call", spy),
    ):
        first = await _call(
            "create_requirement_invariant",
            {
                "project": PROJECT,
                "requirement_id": req_id,
                "key": leak_key,
                "statement": SECRET_PROSE,
                "kind": "behavior",
                "risk": "high",
            },
        )
        with pytest.raises(ToolError):
            await mcp.call_tool(
                "create_requirement_invariant",
                {
                    "project": PROJECT,
                    "requirement_id": req_id,
                    "key": leak_key,
                    "statement": SECRET_PROSE,
                    "kind": "manual",
                    "risk": "low",
                },
            )
        client = _client()
        _http(
            client,
            "POST",
            f"/api/projects/{PROJECT}/requirements/{req_id}/invariants",
            json_body={
                "statement": SECRET_PROSE,
                "kind": "not-a-kind",
                "risk": "low",
                "key": leak_key,
            },
        )
        _http(
            client,
            "PATCH",
            f"/api/projects/{PROJECT}/requirements/invariants/{first['id']}",
            json_body={"statement": None, "statment": SECRET_PROSE},
        )
        include_get = client.get(
            f"/api/projects/{PROJECT}/requirements/{req_id}/contract",
            params={"include": SECRET_PROSE},
        )
        assert include_get.status_code == 400
        before_null = len(seen)
        with pytest.raises(ToolError, match="explicit null"):
            await mcp.call_tool(
                "update_requirement_invariant",
                {
                    "project": PROJECT,
                    "invariant_id": first["id"],
                    "statement": None,
                    "risk": "low",
                },
            )
        null_events = seen[before_null:]
        assert len(null_events) == 1
        assert null_events[0]["tool"] == "update_requirement_invariant"
        assert null_events[0]["outcome"] == "error: validation"
        with pytest.raises(ToolError):
            await mcp.call_tool(
                "get_requirement_contract",
                {"project": PROJECT, "requirement_id": req_id, "include": SECRET_PROSE},
            )
        client.get(f"/api/projects/{PROJECT}/requirements/compliance")
    dumped = json.dumps(seen)
    assert SECRET_PROSE not in dumped
    assert leak_key not in dumped
    assert "not-a-kind" not in dumped
    assert "manual" not in dumped
    failures = [item for item in seen if str(item["outcome"]).startswith("error:")]
    assert failures
    assert any(item["tool"] == "get_requirement_contract" for item in failures)
    assert any(item["tool"] == "review_requirement_compliance" for item in failures)
    assert all(
        item["outcome"] in {"error: validation", "error: not-found", "error: failed"}
        for item in failures
    )
    assert all(item["tool"] for item in failures)
    assert all(item["project"] == PROJECT for item in failures)
    assert all(item["caller"] for item in failures)
