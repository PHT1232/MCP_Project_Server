"""T13 compact compliance service, HTTP, and MCP regressions."""

from __future__ import annotations

import json
import subprocess
from contextlib import suppress
from pathlib import Path
from typing import cast
from unittest.mock import patch

import pytest
from mcp.server.fastmcp.exceptions import ToolError
from starlette.testclient import TestClient

from pcs.context import service
from pcs.db.base import session_scope
from pcs.mcp import build_http_app, mcp
from pcs.requirements import compliance, contracts, evidence

pytestmark = pytest.mark.usefixtures("clean_db")
PROJECT = "t13-project"
OTHER = "t13-other"


def _git(root: Path) -> str:
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t13@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "T13"], cwd=root, check=True)
    (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "seed"], cwd=root, check=True, capture_output=True)
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()


async def _requirement(root: Path, *, project: str = PROJECT, title: str = "Ship") -> str:
    async with session_scope() as session:
        with suppress(service.DuplicateProjectError):
            await service.register_project(
                session, name=project, root_path=str(root), overview="T13 test"
            )
        row = await service.add_entry(
            session, project=project, section="requirements", headline=title
        )
        return row.id


async def _criterion(
    requirement_id: str,
    *,
    project: str = PROJECT,
    key: str = "AC-1",
    review: str = "not-required",
) -> tuple[str, str]:
    async with session_scope() as session:
        invariant = await contracts.create_invariant(
            session,
            project=project,
            requirement_id=requirement_id,
            key=f"INV-{key}",
            statement="Invariant.",
            kind="behavior",
            risk="medium",
        )
        criterion = await contracts.create_criterion(
            session,
            project=project,
            invariant_id=invariant.id,
            key=key,
            statement="Criterion prose must not leak into compliance.",
            evidence_kind="test",
            independent_review=review,
        )
        return invariant.id, criterion.id


async def _record(criterion_id: str, sha: str, *, kind: str = "test", author: str = "dev") -> None:
    async with session_scope() as session:
        await evidence.record_evidence(
            session,
            project=PROJECT,
            criterion_id=criterion_id,
            kind=kind,
            result="passed",
            source_commit=sha,
            test_ref="tests/test_ship.py",
            author=author,
            review_ref=f"criterion:{criterion_id}" if kind == "review" else None,
        )


def _tool_payload(result: object) -> dict[str, object]:
    if isinstance(result, tuple):
        _, structured = result
        if isinstance(structured, dict):
            return cast(dict[str, object], structured)
    value = result[0].text if isinstance(result, list) else result
    return cast(dict[str, object], json.loads(str(value)))


async def test_verified_is_short_and_no_criteria_is_not_configured(tmp_path: Path) -> None:
    sha = _git(tmp_path)
    verified = await _requirement(tmp_path, title="Verified")
    _, criterion_id = await _criterion(verified)
    await _record(criterion_id, sha)
    legacy = await _requirement(tmp_path, title="Legacy")
    async with session_scope() as session:
        result = await compliance.review_requirement_compliance(
            session, project=PROJECT, requirement_ids=[verified, legacy]
        )
    rows = {str(row["requirement_id"]): row for row in result.requirements}
    assert rows[verified]["verdict"] == "verified"
    assert rows[verified]["exceptions"] == []
    assert rows[legacy]["verdict"] == "not-configured"
    assert rows[legacy]["validation"] == "not-configured"
    assert "Criterion prose" not in json.dumps(result.as_dict())


async def test_actionable_missing_stale_review_and_blocking(tmp_path: Path) -> None:
    sha = _git(tmp_path)
    missing = await _requirement(tmp_path, title="Missing")
    _, missing_ac = await _criterion(missing, key="AC-MISSING")
    stale = await _requirement(tmp_path, title="Stale")
    _, stale_ac = await _criterion(stale, key="AC-STALE")
    await _record(stale_ac, sha)
    review = await _requirement(tmp_path, title="Review")
    _, review_ac = await _criterion(review, key="AC-REVIEW", review="required")
    await _record(review_ac, sha)
    blocked = await _requirement(tmp_path, title="Blocked")
    invariant_id, blocked_ac = await _criterion(blocked, key="AC-BLOCK")
    await _record(blocked_ac, sha)
    async with session_scope() as session:
        await contracts.update_criterion(
            session, project=PROJECT, criterion_id=stale_ac, statement="Revised criterion."
        )
        await evidence.add_violation(
            session,
            project=PROJECT,
            invariant_id=invariant_id,
            summary="Forbidden dependency remains.",
            file_ref="src/app.py",
            line_no=42,
            author="reviewer",
        )
        result = await compliance.review_requirement_compliance(
            session,
            project=PROJECT,
            requirement_ids=[blocked, stale, review, missing],
        )
    rows = {str(row["requirement_id"]): row for row in result.requirements}
    missing_ex = cast(list[dict[str, object]], rows[missing]["exceptions"])
    stale_ex = cast(list[dict[str, object]], rows[stale]["exceptions"])
    review_ex = cast(list[dict[str, object]], rows[review]["exceptions"])
    blocked_ex = cast(list[dict[str, object]], rows[blocked]["exceptions"])
    assert missing_ex[0]["criterion_id"] == missing_ac
    assert missing_ex[0]["criterion_key"] == "AC-MISSING"
    assert stale_ex[0]["kind"] == "stale"
    assert stale_ex[0]["file_refs"] == ["tests/test_ship.py"]
    assert review_ex[0]["criterion_id"] == review_ac
    assert rows[review]["review"] == "failed"
    assert any(
        item["kind"] == "blocking" and item["file_refs"] == ["src/app.py:42"] for item in blocked_ex
    )


async def test_isolation_determinism_and_bounds(tmp_path: Path) -> None:
    _git(tmp_path)
    ids = [await _requirement(tmp_path, title=f"Req {index:02}") for index in range(30)]
    for index, requirement_id in enumerate(ids):
        await _criterion(requirement_id, key=f"AC-{index:02}")
    other = await _requirement(tmp_path / "other", project=OTHER)
    async with session_scope() as session:
        first = (
            await compliance.review_requirement_compliance(
                session, project=PROJECT, requirement_ids=[*reversed(ids), ids[0]]
            )
        ).as_dict()
        second = (
            await compliance.review_requirement_compliance(
                session, project=PROJECT, requirement_ids=ids
            )
        ).as_dict()
        with pytest.raises(service.EntryNotFoundError):
            await compliance.review_requirement_compliance(
                session, project=PROJECT, requirement_ids=[other]
            )
    assert first == second
    assert first["reviewed_count"] == compliance.MAX_REQUIREMENTS
    assert first["omitted_requirements"] == 5
    assert len(json.dumps(first)) < 20_000


async def test_duplicate_criterion_keys_are_classified_by_identity(tmp_path: Path) -> None:
    sha = _git(tmp_path)
    requirement_id = await _requirement(tmp_path)
    async with session_scope() as session:
        verified_invariant = await contracts.create_invariant(
            session,
            project=PROJECT,
            requirement_id=requirement_id,
            key="INV-VERIFIED",
            statement="Verified invariant.",
            kind="behavior",
            risk="medium",
        )
        missing_invariant = await contracts.create_invariant(
            session,
            project=PROJECT,
            requirement_id=requirement_id,
            key="INV-MISSING",
            statement="Missing invariant.",
            kind="behavior",
            risk="medium",
        )
        verified = await contracts.create_criterion(
            session,
            project=PROJECT,
            invariant_id=verified_invariant.id,
            key="AC-1",
            statement="Verified criterion.",
            evidence_kind="test",
        )
        missing = await contracts.create_criterion(
            session,
            project=PROJECT,
            invariant_id=missing_invariant.id,
            key="AC-1",
            statement="Missing criterion.",
            evidence_kind="test",
        )
        await evidence.record_evidence(
            session,
            project=PROJECT,
            criterion_id=verified.id,
            kind="test",
            result="passed",
            source_commit=sha,
            test_ref="tests/test_verified.py",
        )
        result = await compliance.review_requirement_compliance(
            session, project=PROJECT, requirement_ids=[requirement_id]
        )
    row = result.requirements[0]
    exceptions = cast(list[dict[str, object]], row["exceptions"])
    assert row["ac_verified"] == 1
    assert row["ac_total"] == 2
    assert row["omitted_exceptions"] == 0
    assert len(exceptions) == 1
    assert exceptions[0]["criterion_id"] == missing.id
    assert exceptions[0]["invariant_id"] == missing_invariant.id
    assert exceptions[0]["kind"] == "missing"


async def test_exception_omission_count_uses_complete_gate_state(tmp_path: Path) -> None:
    _git(tmp_path)
    requirement_id = await _requirement(tmp_path)
    criterion_ids = [
        (await _criterion(requirement_id, key=f"AC-{index:02}"))[1]
        for index in range(compliance.MAX_EXCEPTIONS_PER_REQUIREMENT + 4)
    ]
    async with session_scope() as session:
        result = await compliance.review_requirement_compliance(
            session, project=PROJECT, requirement_ids=[requirement_id]
        )
    row = result.requirements[0]
    exceptions = cast(list[dict[str, object]], row["exceptions"])
    assert len(exceptions) == compliance.MAX_EXCEPTIONS_PER_REQUIREMENT
    assert row["omitted_exceptions"] == 4
    assert [item["criterion_key"] for item in exceptions] == [
        f"AC-{index:02}" for index in range(compliance.MAX_EXCEPTIONS_PER_REQUIREMENT)
    ]
    assert {str(item["criterion_id"]) for item in exceptions}.issubset(set(criterion_ids))


async def test_compact_violations_keep_open_blocking_ahead_of_warning_cap(
    tmp_path: Path,
) -> None:
    _git(tmp_path)
    requirement_id = await _requirement(tmp_path)
    invariant_id, _ = await _criterion(requirement_id)
    async with session_scope() as session:
        for index in range(compliance.MAX_VIOLATION_ROWS + 3):
            await evidence.add_violation(
                session,
                project=PROJECT,
                invariant_id=invariant_id,
                summary=f"Warning {index:02}",
                severity="warning",
            )
        blocking = await evidence.add_violation(
            session,
            project=PROJECT,
            invariant_id=invariant_id,
            summary="Blocking finding",
            severity="blocking",
        )
        compact = await compliance.compact_requirement_evidence(
            session, project=PROJECT, requirement_id=requirement_id
        )
    violations = cast(list[dict[str, object]], compact["violations"])
    assert len(violations) == compliance.MAX_VIOLATION_ROWS
    assert violations[0]["id"] == blocking.id
    assert violations[0]["severity"] == "blocking"
    assert all(item["status"] == "open" for item in violations)
    assert compact["violations_omitted"] == 4


async def test_http_reads_equal_mcp_and_audit_errors(tmp_path: Path) -> None:
    sha = _git(tmp_path)
    requirement_id = await _requirement(tmp_path)
    _, criterion_id = await _criterion(requirement_id)
    await _record(criterion_id, sha)
    app = build_http_app()
    paths = {getattr(route, "path", None) for route in app.routes}
    assert "/api/projects/{project}/requirements/{requirement_id}/contract" in paths
    assert "/api/projects/{project}/requirements/{requirement_id}/evidence" in paths
    assert "/api/projects/{project}/requirements/compliance" in paths

    seen: list[dict[str, object]] = []
    client = TestClient(app)
    with patch(
        "pcs.web_api.requirements_routes.log_tool_call",
        side_effect=lambda **kw: seen.append(kw),
    ):
        contract = client.get(f"/api/projects/{PROJECT}/requirements/{requirement_id}/contract")
        ledger = client.get(f"/api/projects/{PROJECT}/requirements/{requirement_id}/evidence")
        http = client.get(
            f"/api/projects/{PROJECT}/requirements/compliance",
            params={"requirement_id": requirement_id},
            headers={"x-pcs-caller": "dashboard-test"},
        )
        bad = client.get(f"/api/projects/{PROJECT}/requirements/compliance")
    assert contract.status_code == ledger.status_code == http.status_code == 200
    assert ledger.json()["limits"] == {"evidence": 20, "violations": 20}
    assert "evidence_omitted" in ledger.json()
    mcp_payload = _tool_payload(
        await mcp.call_tool(
            "review_requirement_compliance",
            {"project": PROJECT, "requirement_ids": [requirement_id]},
        )
    )
    assert http.json() == mcp_payload
    assert bad.status_code == 400
    assert seen[-2]["tool"] == "review_requirement_compliance"
    assert seen[-2]["caller"] == "dashboard-test"
    assert seen[-2]["outcome"] == "ok"
    assert str(seen[-1]["outcome"]).startswith("error:")
    with pytest.raises(ToolError):
        await mcp.call_tool(
            "review_requirement_compliance",
            {"project": "ghost", "requirement_ids": [requirement_id]},
        )


async def test_review_exceptions_distinguish_missing_and_latest_failed(tmp_path: Path) -> None:
    sha = _git(tmp_path)
    missing_req = await _requirement(tmp_path, title="Review missing")
    _, missing_ac = await _criterion(missing_req, key="AC-REV-MISS", review="required")
    await _record(missing_ac, sha)
    failed_req = await _requirement(tmp_path, title="Review failed")
    _, failed_ac = await _criterion(failed_req, key="AC-REV-FAIL", review="required")
    await _record(failed_ac, sha)
    async with session_scope() as session:
        await evidence.record_evidence(
            session,
            project=PROJECT,
            criterion_id=failed_ac,
            kind="review",
            result="passed",
            source_commit=sha,
            author="reviewer-a",
        )
        await evidence.record_evidence(
            session,
            project=PROJECT,
            criterion_id=failed_ac,
            kind="review",
            result="failed",
            source_commit=sha,
            author="reviewer-b",
        )
        result = await compliance.review_requirement_compliance(
            session, project=PROJECT, requirement_ids=[missing_req, failed_req]
        )
    rows = {str(row["requirement_id"]): row for row in result.requirements}
    missing = cast(list[dict[str, object]], rows[missing_req]["exceptions"])[0]
    failed = cast(list[dict[str, object]], rows[failed_req]["exceptions"])[0]
    assert missing["kind"] == "review-missing"
    assert missing["criterion_id"] == missing_ac
    assert missing["invariant_id"]
    assert failed["kind"] == "review-failed"
    assert failed["criterion_id"] == failed_ac
    assert "independent review" not in json.dumps(result.as_dict()).lower()
    # T12 canonical validation remains ok when evidence is missing/failed; exceptions carry it.
    assert rows[missing_req]["validation"] == "ok"
    assert rows[failed_req]["validation"] == "ok"


async def test_compact_evidence_is_latest_bounded_and_reports_omissions(tmp_path: Path) -> None:
    sha = _git(tmp_path)
    requirement_id = await _requirement(tmp_path)
    invariant_id, criterion_id = await _criterion(requirement_id)
    async with session_scope() as session:
        for index in range(compliance.MAX_EVIDENCE_ROWS + 5):
            await evidence.record_evidence(
                session,
                project=PROJECT,
                criterion_id=criterion_id,
                kind="test",
                result="passed",
                source_commit=sha,
                test_ref=f"tests/test_{index:02}.py",
            )
        for index in range(compliance.MAX_VIOLATION_ROWS + 3):
            await evidence.add_violation(
                session,
                project=PROJECT,
                invariant_id=invariant_id,
                summary=f"Finding {index:02}",
                severity="warning",
                file_ref="src/app.py",
                line_no=index + 1,
            )
        compact = await compliance.compact_requirement_evidence(
            session, project=PROJECT, requirement_id=requirement_id
        )
        full = await evidence.get_requirement_evidence(
            session, project=PROJECT, requirement_id=requirement_id
        )
    compact_rows = cast(list[dict[str, object]], compact["evidence"])
    assert len(compact_rows) == compliance.MAX_EVIDENCE_ROWS
    assert compact["evidence_total"] == compliance.MAX_EVIDENCE_ROWS + 5
    assert compact["evidence_omitted"] == 5
    assert int(cast(int, compact_rows[0]["seq"])) > int(
        cast(int, compact_rows[-1]["seq"])
    )  # latest first
    assert len(cast(list[object], compact["violations"])) == compliance.MAX_VIOLATION_ROWS
    assert compact["violations_omitted"] == 3
    assert len(cast(list[object], full["evidence"])) == compliance.MAX_EVIDENCE_ROWS + 5
    assert "author" not in compact_rows[0]
    assert "created_at" not in compact_rows[0]
