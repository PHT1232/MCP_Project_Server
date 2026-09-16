"""T12 evidence ledger and close gate — one regression per acceptance item."""

from __future__ import annotations

import asyncio
import os
import subprocess
import uuid
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import cast

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from testcontainers.community.postgres import PostgresContainer

from pcs.config import get_settings
from pcs.context import service
from pcs.context.types import REQ_DONE, REQ_NOT_STARTED, ValidationError
from pcs.db.base import session_scope
from pcs.mcp import mcp
from pcs.requirements import briefing, contracts, evidence

PGVECTOR_IMAGE = "pgvector/pgvector:pg16"
PRIOR_HEAD = "0006_requirement_contracts"
PROJECT = "acme-evidence"
OTHER = "other-evidence"
FAKE_SHA = "a" * 40


def _links(payload: object, key: str) -> list[dict[str, str]]:
    assert isinstance(payload, dict)
    raw = payload[key]
    assert isinstance(raw, list)
    return [cast(dict[str, str], row) for row in raw]


pytestmark = pytest.mark.usefixtures("clean_db")


async def _seed_requirement(
    *, name: str = PROJECT, title: str = "Ship login", root: Path | None = None
) -> str:
    path = str(root) if root is not None else f"/repos/{name}"
    async with session_scope() as session:
        with suppress(service.DuplicateProjectError):
            await service.register_project(
                session, name=name, root_path=path, overview=f"{name} overview"
            )
        req = await service.add_entry(session, project=name, section="requirements", headline=title)
        return req.id


async def _seed_git_requirement(
    root: Path, *, name: str = PROJECT, title: str = "Ship login"
) -> tuple[str, str]:
    sha = _git_init(root)
    req_id = await _seed_requirement(name=name, title=title, root=root)
    return req_id, sha


async def _add_required_criterion(
    req_id: str,
    *,
    inv_key: str = "INV-1",
    ac_key: str = "AC-1",
    independent_review: str = "not-required",
    kind: str = "test",
    project: str = PROJECT,
    sort_order: int = 0,
) -> tuple[str, str]:
    async with session_scope() as session:
        inv = await contracts.create_invariant(
            session,
            project=project,
            requirement_id=req_id,
            key=inv_key,
            statement=f"{inv_key} under test.",
            kind="behavior",
            risk="medium",
            sort_order=sort_order,
        )
        ac = await contracts.create_criterion(
            session,
            project=project,
            invariant_id=inv.id,
            key=ac_key,
            statement=f"{ac_key} under test.",
            evidence_kind=kind,
            required=True,
            independent_review=independent_review,
        )
        return inv.id, ac.id


async def _pass(
    ac_id: str,
    sha: str,
    *,
    author: str = "alice",
    kind: str = "test",
    project: str = PROJECT,
    worktree_fingerprint: str | None = None,
    claim_ref: str | None = None,
) -> evidence.EvidenceView:
    async with session_scope() as session:
        return await evidence.record_evidence(
            session,
            project=project,
            criterion_id=ac_id,
            kind=kind,
            result="passed",
            source_commit=sha,
            author=author,
            worktree_fingerprint=worktree_fingerprint,
            claim_ref=claim_ref,
        )


def _git_init(root: Path, message: str = "init") -> str:
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t12@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "T12"], cwd=root, check=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=root, check=True)
    (root / "README").write_text(message, encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", message], cwd=root, check=True, capture_output=True)
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()


def _git_commit(root: Path, message: str) -> str:
    (root / "README").write_text(message, encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", message], cwd=root, check=True, capture_output=True)
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()


async def test_missing_required_criterion_rejects_done_and_names_key() -> None:
    req_id = await _seed_requirement()
    await _add_required_criterion(req_id, ac_key="AC-1")
    async with session_scope() as session:
        with pytest.raises(evidence.CloseGateError, match="missing AC-1"):
            await service.set_requirement_status(
                session, project=PROJECT, entry_id=req_id, status=REQ_DONE
            )
        payload = await evidence.summarize_close_gate(
            session, project=PROJECT, requirement_ids=[req_id]
        )
        entry = await service.get_entry(session, project=PROJECT, entry_id=req_id)
    missing = _links(payload, "missing")
    assert missing[0]["key"] == "AC-1"
    assert missing[0]["id"]
    assert entry.requirement_status != REQ_DONE


async def test_failed_evidence_rejects_done_until_later_pass_supersedes(tmp_path: Path) -> None:
    req_id, sha = await _seed_git_requirement(tmp_path)
    _, ac_id = await _add_required_criterion(req_id, ac_key="AC-FAIL")
    async with session_scope() as session:
        failed = await evidence.record_evidence(
            session,
            project=PROJECT,
            criterion_id=ac_id,
            kind="test",
            result="failed",
            source_commit=sha,
            test_ref="tests/test_login.py",
            author="alice",
        )
        with pytest.raises(evidence.CloseGateError, match="failed AC-FAIL"):
            await service.set_requirement_status(
                session, project=PROJECT, entry_id=req_id, status=REQ_DONE
            )
        passed = await evidence.record_evidence(
            session,
            project=PROJECT,
            criterion_id=ac_id,
            kind="test",
            result="passed",
            source_commit=sha,
            test_ref="tests/test_login.py",
            author="alice",
        )
        done = await service.set_requirement_status(
            session, project=PROJECT, entry_id=req_id, status=REQ_DONE
        )
        history = await evidence.list_evidence(session, project=PROJECT, criterion_id=ac_id)
    assert failed.id != passed.id
    assert [row.id for row in history] == [failed.id, passed.id]
    assert done.requirement_status == REQ_DONE


async def test_older_commit_is_stale_and_rejects_done(tmp_path: Path) -> None:
    sha1 = _git_init(tmp_path, "first")
    req_id = await _seed_requirement(root=tmp_path)
    _, ac_id = await _add_required_criterion(req_id, ac_key="AC-STALE")
    async with session_scope() as session:
        await evidence.record_evidence(
            session,
            project=PROJECT,
            criterion_id=ac_id,
            kind="test",
            result="passed",
            source_commit=sha1,
            author="alice",
        )
    _git_commit(tmp_path, "second")
    async with session_scope() as session:
        gate = await evidence.evaluate_close_gate(session, project=PROJECT, requirement_id=req_id)
        payload = await evidence.summarize_close_gate(
            session, project=PROJECT, requirement_ids=[req_id]
        )
        with pytest.raises(evidence.CloseGateError, match="stale AC-STALE"):
            await service.set_requirement_status(
                session, project=PROJECT, entry_id=req_id, status=REQ_DONE
            )
    assert gate.validation == "stale"
    stale = _links(payload, "stale")
    assert stale[0]["id"]
    assert stale[0]["key"] == "AC-STALE"
    assert payload["stale_count"] == 1


async def test_open_blocking_violation_rejects_done_until_resolved(tmp_path: Path) -> None:
    req_id, sha = await _seed_git_requirement(tmp_path)
    inv_id, ac_id = await _add_required_criterion(req_id, ac_key="AC-1")
    await _pass(ac_id, sha)
    async with session_scope() as session:
        finding = await evidence.add_violation(
            session,
            project=PROJECT,
            invariant_id=inv_id,
            summary="Forbidden path still imported.",
            severity="blocking",
            author="reviewer",
        )
        with pytest.raises(evidence.CloseGateError, match="blocking INV-1"):
            await service.set_requirement_status(
                session, project=PROJECT, entry_id=req_id, status=REQ_DONE
            )
        resolved = await evidence.resolve_violation(
            session, project=PROJECT, violation_id=finding.id, author="resolver-bot"
        )
        done = await service.set_requirement_status(
            session, project=PROJECT, entry_id=req_id, status=REQ_DONE
        )
        listed = await evidence.get_requirement_evidence(
            session, project=PROJECT, requirement_id=req_id
        )
    assert resolved.status == "resolved"
    assert resolved.resolved_at is not None
    assert resolved.resolved_by == "resolver-bot"
    assert finding.id == resolved.id
    assert done.requirement_status == REQ_DONE
    assert _links(listed, "violations")[0]["status"] == "resolved"
    assert _links(listed, "violations")[0]["resolved_by"] == "resolver-bot"


async def test_independent_review_rejects_self_authored_review(tmp_path: Path) -> None:
    req_id, sha = await _seed_git_requirement(tmp_path)
    _, ac_id = await _add_required_criterion(req_id, ac_key="AC-REV", independent_review="required")
    async with session_scope() as session:
        await evidence.record_evidence(
            session,
            project=PROJECT,
            criterion_id=ac_id,
            kind="test",
            result="passed",
            source_commit=sha,
            author="alice",
        )
        await evidence.record_evidence(
            session,
            project=PROJECT,
            criterion_id=ac_id,
            kind="review",
            result="passed",
            source_commit=sha,
            author="alice",
        )
        with pytest.raises(evidence.CloseGateError, match="cannot be self-authored"):
            await service.set_requirement_status(
                session, project=PROJECT, entry_id=req_id, status=REQ_DONE
            )
        await evidence.record_evidence(
            session,
            project=PROJECT,
            criterion_id=ac_id,
            kind="review",
            result="passed",
            source_commit=sha,
            author="bob",
            review_ref=f"criterion:{ac_id}",
        )
        done = await service.set_requirement_status(
            session, project=PROJECT, entry_id=req_id, status=REQ_DONE
        )
    assert done.requirement_status == REQ_DONE


async def test_requirements_without_criteria_keep_legacy_status_updates() -> None:
    req_id = await _seed_requirement(title="No contract")
    async with session_scope() as session:
        done = await service.set_requirement_status(
            session, project=PROJECT, entry_id=req_id, status=REQ_DONE
        )
        payload = await evidence.summarize_close_gate(
            session, project=PROJECT, requirement_ids=[req_id]
        )
    assert done.requirement_status == REQ_DONE
    assert payload["validation"] == "not-configured"
    assert payload["review"] == "not-configured"


async def test_no_criteria_open_blocking_violation_rejects_done() -> None:
    req_id = await _seed_requirement(title="Legacy blockers")
    async with session_scope() as session:
        inv = await contracts.create_invariant(
            session,
            project=PROJECT,
            requirement_id=req_id,
            key="INV-BLOCK",
            statement="Must not ship with an open blocker.",
            kind="behavior",
            risk="high",
        )
        await evidence.add_violation(
            session,
            project=PROJECT,
            invariant_id=inv.id,
            summary="Open finding with no criteria.",
            severity="blocking",
            author="reviewer",
        )
        with pytest.raises(evidence.CloseGateError, match="blocking INV-BLOCK"):
            await service.set_requirement_status(
                session, project=PROJECT, entry_id=req_id, status=REQ_DONE
            )
        payload = await evidence.summarize_close_gate(
            session, project=PROJECT, requirement_ids=[req_id]
        )
    assert payload["review"] == "failed"
    assert payload["blocking_count"] == 1


async def test_open_blocking_violation_survives_soft_deleted_invariant() -> None:
    req_id = await _seed_requirement(title="Deleted parent blocker")
    async with session_scope() as session:
        inv = await contracts.create_invariant(
            session,
            project=PROJECT,
            requirement_id=req_id,
            key="INV-GONE",
            statement="Parent may be soft-deleted; the finding stays.",
            kind="behavior",
            risk="high",
        )
        await contracts.create_criterion(
            session,
            project=PROJECT,
            invariant_id=inv.id,
            key="AC-GONE",
            statement="Must not count after the parent is deleted.",
            evidence_kind="test",
            required=True,
        )
        finding = await evidence.add_violation(
            session,
            project=PROJECT,
            invariant_id=inv.id,
            summary="Still blocking after parent delete.",
            severity="blocking",
            author="reviewer",
        )
        await contracts.delete_invariant(session, project=PROJECT, invariant_id=inv.id)
        with pytest.raises(evidence.CloseGateError, match="blocking INV-GONE"):
            await service.set_requirement_status(
                session, project=PROJECT, entry_id=req_id, status=REQ_DONE
            )
        blocked = await evidence.evaluate_close_gate(
            session, project=PROJECT, requirement_id=req_id
        )
        payload = await evidence.summarize_close_gate(
            session, project=PROJECT, requirement_ids=[req_id]
        )
        listed = await evidence.get_requirement_evidence(
            session, project=PROJECT, requirement_id=req_id
        )
        entry = await service.get_entry(session, project=PROJECT, entry_id=req_id)
        await evidence.resolve_violation(
            session, project=PROJECT, violation_id=finding.id, author="resolver-bot"
        )
        cleared = await evidence.evaluate_close_gate(
            session, project=PROJECT, requirement_id=req_id
        )
        cleared_payload = await evidence.summarize_close_gate(
            session, project=PROJECT, requirement_ids=[req_id]
        )
        done = await service.set_requirement_status(
            session, project=PROJECT, entry_id=req_id, status=REQ_DONE
        )
    assert not blocked.passed
    assert blocked.ac_verified == blocked.ac_total
    assert blocked.ac_total == 0
    assert blocked.missing == ()
    assert blocked.stale == ()
    assert payload["review"] == "failed"
    assert payload["blocking_count"] == 1
    assert payload["ac_total"] == 0
    assert payload["ac_verified"] == 0
    assert payload["missing"] == []
    assert payload["stale"] == []
    blocked_keys = payload["missing_keys"]
    assert isinstance(blocked_keys, list)
    assert "AC-GONE" not in blocked_keys
    blocking = _links(payload, "blocking")
    assert blocking[0]["key"] == "INV-GONE"
    assert blocking[0]["summary"] == "Still blocking after parent delete."
    violations = _links(listed, "violations")
    assert violations[0]["id"] == finding.id
    assert violations[0]["status"] == "open"
    assert violations[0]["invariant_id"] == inv.id
    assert entry.requirement_status != REQ_DONE
    assert cleared.passed
    assert cleared.ac_verified == cleared.ac_total
    assert cleared.ac_total == 0
    assert cleared.missing == ()
    assert cleared.stale == ()
    assert cleared.blocking == ()
    if cleared.configured:
        assert cleared_payload["ac_verified"] == 0
        assert cleared_payload["ac_total"] == 0
        assert cleared_payload["missing"] == []
        assert cleared_payload["stale"] == []
        cleared_keys = cleared_payload["missing_keys"]
        assert isinstance(cleared_keys, list)
        assert "AC-GONE" not in cleared_keys
        assert cleared_payload["blocking_count"] == 0
        assert cleared_payload["review"] == "passed"
    else:
        assert cleared_payload["validation"] == "not-configured"
        assert cleared_payload["review"] == "not-configured"
    assert done.requirement_status == REQ_DONE


async def test_payload_limits_reject_logs_and_do_not_echo_secrets(tmp_path: Path) -> None:
    req_id, sha = await _seed_git_requirement(tmp_path)
    _, ac_id = await _add_required_criterion(req_id)
    async with session_scope() as session:
        with pytest.raises(ValidationError, match="command_ref") as log_exc:
            await evidence.record_evidence(
                session,
                project=PROJECT,
                criterion_id=ac_id,
                kind="test",
                result="passed",
                source_commit=sha,
                command_ref="pytest\nTraceback (most recent call last):\n  File",
            )
        with pytest.raises(ValidationError, match="artifact_ref") as secret_exc:
            await evidence.record_evidence(
                session,
                project=PROJECT,
                criterion_id=ac_id,
                kind="test",
                result="passed",
                source_commit=sha,
                artifact_ref="password=super-secret-value",
            )
        with pytest.raises(ValidationError, match="summary"):
            await evidence.add_violation(
                session,
                project=PROJECT,
                invariant_id=(
                    await contracts.list_invariants(session, project=PROJECT, requirement_id=req_id)
                )[0].id,
                summary="diff --git a/x b/x\n+++ leaked",
            )
    assert "super-secret-value" not in str(secret_exc.value)
    assert "Traceback" not in str(log_exc.value)


async def test_concurrent_evidence_writes_preserve_all_and_latest_is_deterministic(
    tmp_path: Path,
) -> None:
    req_id, sha = await _seed_git_requirement(tmp_path)
    _, ac_id = await _add_required_criterion(req_id, ac_key="AC-CON")

    async def _write(author: str, suffix: str) -> str:
        async with session_scope() as session:
            row = await evidence.record_evidence(
                session,
                project=PROJECT,
                criterion_id=ac_id,
                kind="test",
                result="passed",
                source_commit=sha,
                test_ref=f"tests/test_{suffix}.py",
                author=author,
            )
            return row.id

    first, second = await asyncio.gather(_write("alice", "a"), _write("bob", "b"))
    async with session_scope() as session:
        rows = await evidence.list_evidence(session, project=PROJECT, criterion_id=ac_id)
        gate = await evidence.evaluate_close_gate(session, project=PROJECT, requirement_id=req_id)
    assert {first, second} == {row.id for row in rows}
    assert len(rows) == 2
    latest = max(rows, key=lambda row: row.seq)
    assert rows[-1].id == latest.id
    assert gate.ac_verified == 1


async def test_project_isolation_rejects_foreign_criterion_and_requirement(tmp_path: Path) -> None:
    local, sha = await _seed_git_requirement(tmp_path / "local", title="Local")
    foreign, foreign_sha = await _seed_git_requirement(
        tmp_path / "foreign", name=OTHER, title="Foreign"
    )
    _, local_ac = await _add_required_criterion(local)
    async with session_scope() as session:
        inv = await contracts.create_invariant(
            session,
            project=OTHER,
            requirement_id=foreign,
            key="INV-X",
            statement="Other project secret.",
            kind="behavior",
            risk="high",
        )
        foreign_ac = await contracts.create_criterion(
            session,
            project=OTHER,
            invariant_id=inv.id,
            key="AC-1",
            statement="Foreign AC.",
            evidence_kind="test",
        )
        with pytest.raises(ValidationError, match="cross-project"):
            await evidence.record_evidence(
                session,
                project=PROJECT,
                criterion_id=foreign_ac.id,
                kind="test",
                result="passed",
                source_commit=foreign_sha,
            )
        with pytest.raises(ValidationError, match="cross-project"):
            await evidence.evaluate_close_gate(session, project=PROJECT, requirement_id=foreign)
        ok = await evidence.record_evidence(
            session,
            project=PROJECT,
            criterion_id=local_ac,
            kind="test",
            result="passed",
            source_commit=sha,
        )
    assert ok.criterion_id == local_ac


async def test_evidence_binds_immutable_contract_revision(tmp_path: Path) -> None:
    req_id, sha = await _seed_git_requirement(tmp_path)
    _, ac_id = await _add_required_criterion(req_id)
    async with session_scope() as session:
        row = await evidence.record_evidence(
            session,
            project=PROJECT,
            criterion_id=ac_id,
            kind="test",
            result="passed",
            source_commit=sha,
        )
        revisions = await contracts.list_contract_revisions(
            session, project=PROJECT, requirement_id=req_id
        )
        crit_revs = [item for item in revisions if item.entity_id == ac_id]
        assert row.contract_revision_id == crit_revs[-1].id
        with pytest.raises(DBAPIError, match="append-only"):
            await session.execute(
                text("UPDATE requirement_evidence SET author = 'mutated' WHERE id = :id"),
                {"id": row.id},
            )
            await session.flush()


async def test_recording_evidence_does_not_change_requirement_status(tmp_path: Path) -> None:
    req_id, sha = await _seed_git_requirement(tmp_path)
    _, ac_id = await _add_required_criterion(req_id)
    async with session_scope() as session:
        before = await service.get_entry(session, project=PROJECT, entry_id=req_id)
        await evidence.record_evidence(
            session,
            project=PROJECT,
            criterion_id=ac_id,
            kind="test",
            result="passed",
            source_commit=sha,
        )
        after = await service.get_entry(session, project=PROJECT, entry_id=req_id)
        gate = await evidence.evaluate_close_gate(session, project=PROJECT, requirement_id=req_id)
    assert before.requirement_status == REQ_NOT_STARTED
    assert after.requirement_status == REQ_NOT_STARTED
    assert gate.passed is True


async def test_mcp_evidence_tools_are_registered() -> None:
    tools = {tool.name: tool for tool in await mcp.list_tools()}
    assert "record_requirement_evidence" in tools
    assert "get_requirement_evidence" in tools
    assert "evaluate_close_gate" in tools
    record_schema = tools["record_requirement_evidence"].inputSchema
    kind_schema = record_schema["properties"]["kind"]
    result_schema = record_schema["properties"]["result"]
    commit_schema = record_schema["properties"]["source_commit"]
    assert "enum" in kind_schema
    assert set(kind_schema["enum"]) == {"test", "command", "review", "manual", "file"}
    assert set(result_schema["enum"]) == {"passed", "failed", "manual-pending"}
    assert commit_schema["minLength"] == 7
    assert commit_schema["maxLength"] == 40
    assert commit_schema["pattern"] == r"^[0-9a-fA-F]{7,40}$"
    violation_schema = tools["add_requirement_violation"].inputSchema
    assert set(violation_schema["properties"]["severity"]["enum"]) == {"blocking", "warning"}
    assert violation_schema["properties"]["summary"]["maxLength"] == 200
    line_schema = violation_schema["properties"]["line_no"]
    line_options = line_schema.get("anyOf", [line_schema])
    assert any(isinstance(opt, dict) and opt.get("minimum") == 1 for opt in line_options)


async def test_criterion_update_makes_prior_evidence_stale(tmp_path: Path) -> None:
    req_id, sha = await _seed_git_requirement(tmp_path)
    _, ac_id = await _add_required_criterion(req_id, ac_key="AC-REVBIND")
    first = await _pass(ac_id, sha)
    async with session_scope() as session:
        updated = await contracts.update_criterion(
            session,
            project=PROJECT,
            criterion_id=ac_id,
            statement="Updated acceptance criterion.",
        )
        gate = await evidence.evaluate_close_gate(session, project=PROJECT, requirement_id=req_id)
        with pytest.raises(evidence.CloseGateError, match="stale AC-REVBIND"):
            await service.set_requirement_status(
                session, project=PROJECT, entry_id=req_id, status=REQ_DONE
            )
        second = await evidence.record_evidence(
            session,
            project=PROJECT,
            criterion_id=ac_id,
            kind="test",
            result="passed",
            source_commit=sha,
            author="alice",
        )
        done = await service.set_requirement_status(
            session, project=PROJECT, entry_id=req_id, status=REQ_DONE
        )
    assert first.contract_revision_id != second.contract_revision_id
    assert updated.statement == "Updated acceptance criterion."
    assert gate.validation == "stale"
    assert done.requirement_status == REQ_DONE


async def test_latest_failed_review_supersedes_older_pass(tmp_path: Path) -> None:
    req_id, sha = await _seed_git_requirement(tmp_path)
    _, ac_id = await _add_required_criterion(req_id, ac_key="AC-REV", independent_review="required")
    async with session_scope() as session:
        await evidence.record_evidence(
            session,
            project=PROJECT,
            criterion_id=ac_id,
            kind="test",
            result="passed",
            source_commit=sha,
            author="alice",
        )
        await evidence.record_evidence(
            session,
            project=PROJECT,
            criterion_id=ac_id,
            kind="review",
            result="passed",
            source_commit=sha,
            author="bob",
        )
        await evidence.record_evidence(
            session,
            project=PROJECT,
            criterion_id=ac_id,
            kind="review",
            result="failed",
            source_commit=sha,
            author="carol",
        )
        with pytest.raises(evidence.CloseGateError, match="independent review of AC-REV is failed"):
            await service.set_requirement_status(
                session, project=PROJECT, entry_id=req_id, status=REQ_DONE
            )
        await evidence.record_evidence(
            session,
            project=PROJECT,
            criterion_id=ac_id,
            kind="review",
            result="manual-pending",
            source_commit=sha,
            author="dave",
        )
        with pytest.raises(evidence.CloseGateError, match="manual-pending"):
            await service.set_requirement_status(
                session, project=PROJECT, entry_id=req_id, status=REQ_DONE
            )


async def test_reviewer_identity_is_normalized(tmp_path: Path) -> None:
    req_id, sha = await _seed_git_requirement(tmp_path)
    _, ac_id = await _add_required_criterion(
        req_id, ac_key="AC-CASE", independent_review="required"
    )
    async with session_scope() as session:
        await evidence.record_evidence(
            session,
            project=PROJECT,
            criterion_id=ac_id,
            kind="test",
            result="passed",
            source_commit=sha,
            author="Alice",
        )
        await evidence.record_evidence(
            session,
            project=PROJECT,
            criterion_id=ac_id,
            kind="review",
            result="passed",
            source_commit=sha,
            author=" alice ",
        )
        with pytest.raises(evidence.CloseGateError, match="cannot be self-authored"):
            await service.set_requirement_status(
                session, project=PROJECT, entry_id=req_id, status=REQ_DONE
            )


async def test_short_sha_expands_or_rejects(tmp_path: Path) -> None:
    req_id, sha = await _seed_git_requirement(tmp_path)
    _, ac_id = await _add_required_criterion(req_id)
    short = sha[:7]
    async with session_scope() as session:
        expanded = await evidence.record_evidence(
            session,
            project=PROJECT,
            criterion_id=ac_id,
            kind="test",
            result="passed",
            source_commit=short,
            author="alice",
        )
        full = await evidence.record_evidence(
            session,
            project=PROJECT,
            criterion_id=ac_id,
            kind="test",
            result="passed",
            source_commit=sha,
            author="alice",
        )
        with pytest.raises(ValidationError, match="existing commit object"):
            await evidence.record_evidence(
                session,
                project=PROJECT,
                criterion_id=ac_id,
                kind="test",
                result="passed",
                source_commit="abc1234",
                author="alice",
            )
        with pytest.raises(ValidationError, match="7-40 hex"):
            await evidence.record_evidence(
                session,
                project=PROJECT,
                criterion_id=ac_id,
                kind="test",
                result="passed",
                source_commit="abc123",
                author="alice",
            )
    assert expanded.source_commit == sha
    assert len(expanded.source_commit) == 40
    assert full.source_commit == sha


async def test_dirty_content_changes_fingerprint_with_same_porcelain(tmp_path: Path) -> None:
    req_id, sha = await _seed_git_requirement(tmp_path)
    _, ac_id = await _add_required_criterion(req_id, ac_key="AC-DIRTY")
    (tmp_path / "README").write_text("dirty-one", encoding="utf-8")
    _, first_fp = await evidence._repo_state(str(tmp_path))
    first = await _pass(ac_id, sha, worktree_fingerprint=first_fp)
    (tmp_path / "README").write_text("dirty-two", encoding="utf-8")
    _, second_fp = await evidence._repo_state(str(tmp_path))
    second = await _pass(ac_id, sha, worktree_fingerprint=second_fp)
    async with session_scope() as session:
        gate = await evidence.evaluate_close_gate(session, project=PROJECT, requirement_id=req_id)
        listed = await evidence.list_evidence(session, project=PROJECT, criterion_id=ac_id)
    assert first.worktree_fingerprint != second.worktree_fingerprint
    assert listed[0].worktree_fingerprint != listed[1].worktree_fingerprint
    assert gate.passed is False
    (tmp_path / "README").write_text("dirty-three", encoding="utf-8")
    async with session_scope() as session:
        stale_gate = await evidence.evaluate_close_gate(
            session, project=PROJECT, requirement_id=req_id
        )
        with pytest.raises(evidence.CloseGateError, match=r"(?:stale|provisional) AC-DIRTY"):
            await service.set_requirement_status(
                session, project=PROJECT, entry_id=req_id, status=REQ_DONE
            )
    assert stale_gate.validation == "stale"


async def test_staged_index_change_after_clean_evidence_is_stale(tmp_path: Path) -> None:
    req_id, sha = await _seed_git_requirement(tmp_path)
    _, ac_id = await _add_required_criterion(req_id, ac_key="AC-STAGED")
    await _pass(ac_id, sha)
    (tmp_path / "README").write_text("staged-only change", encoding="utf-8")
    subprocess.run(["git", "add", "README"], cwd=tmp_path, check=True, capture_output=True)
    async with session_scope() as session:
        gate = await evidence.evaluate_close_gate(session, project=PROJECT, requirement_id=req_id)
        with pytest.raises(evidence.CloseGateError, match="stale AC-STAGED"):
            await service.set_requirement_status(
                session, project=PROJECT, entry_id=req_id, status=REQ_DONE
            )
    assert gate.validation == "stale"
    assert gate.passed is False


async def test_untracked_files_never_cause_staleness_or_block_done(tmp_path: Path) -> None:
    """Regression: untracked files (incidental clutter unrelated to the
    evidenced commit) must never make evidence stale or block `done` — only
    a TRACKED file differing from HEAD counts as dirty/stale."""
    req_id, sha = await _seed_git_requirement(tmp_path)
    _, ac_id = await _add_required_criterion(req_id, ac_key="AC-UNTRACKED")
    first = await _pass(ac_id, sha)
    assert first.worktree_fingerprint is None
    scratch = tmp_path / "scratch.txt"
    scratch.write_text("untracked-one", encoding="utf-8")
    async with session_scope() as session:
        created = await evidence.evaluate_close_gate(
            session, project=PROJECT, requirement_id=req_id
        )
    assert created.validation == "ok"
    assert created.passed is True

    scratch.write_text("untracked-two", encoding="utf-8")
    async with session_scope() as session:
        changed = await evidence.evaluate_close_gate(
            session, project=PROJECT, requirement_id=req_id
        )
        await service.set_requirement_status(
            session, project=PROJECT, entry_id=req_id, status=REQ_DONE
        )
    assert changed.validation == "ok"
    assert changed.passed is True


async def test_unreadable_git_state_fails_closed(tmp_path: Path) -> None:
    req_id, sha = await _seed_git_requirement(tmp_path)
    _, ac_id = await _add_required_criterion(req_id, ac_key="AC-GIT")
    await _pass(ac_id, sha)
    (tmp_path / ".git").rename(tmp_path / ".git.bak")
    async with session_scope() as session:
        gate = await evidence.evaluate_close_gate(session, project=PROJECT, requirement_id=req_id)
        with pytest.raises(evidence.CloseGateError, match="stale AC-GIT"):
            await service.set_requirement_status(
                session, project=PROJECT, entry_id=req_id, status=REQ_DONE
            )
    assert gate.passed is False
    assert gate.validation == "stale"


async def test_ownership_constraints_reject_cross_requirement_and_revision_sql(
    tmp_path: Path,
) -> None:
    left, sha = await _seed_git_requirement(tmp_path, title="Left")
    right = await _seed_requirement(title="Right", root=tmp_path)
    _, left_ac = await _add_required_criterion(left, inv_key="INV-L", ac_key="AC-L")
    _, right_ac = await _add_required_criterion(right, inv_key="INV-R", ac_key="AC-R")
    async with session_scope() as session:
        project_row = await service.resolve_project(session, PROJECT)
        left_revs = await contracts.list_contract_revisions(
            session, project=PROJECT, requirement_id=left
        )
        right_revs = await contracts.list_contract_revisions(
            session, project=PROJECT, requirement_id=right
        )
        left_rev = [row for row in left_revs if row.entity_id == left_ac][-1]
        right_rev = [row for row in right_revs if row.entity_id == right_ac][-1]
        left_invs = await contracts.list_invariants(session, project=PROJECT, requirement_id=left)
        right_invs = await contracts.list_invariants(session, project=PROJECT, requirement_id=right)

        async def _reject(sql: str, params: dict[str, object]) -> None:
            nested = await session.begin_nested()
            try:
                await session.execute(text(sql), params)
                await session.flush()
            except IntegrityError:
                await nested.rollback()
                return
            await nested.rollback()
            raise AssertionError("expected IntegrityError")

        evidence_sql = (
            "INSERT INTO requirement_evidence "
            "(id, project_id, requirement_id, criterion_id, "
            "contract_revision_id, evidence_kind, result, source_commit, author) "
            "VALUES (:id, :project_id, :requirement_id, :criterion_id, "
            ":revision_id, 'test', 'passed', :sha, 'alice')"
        )
        await _reject(
            evidence_sql,
            {
                "id": str(uuid.uuid4()),
                "project_id": project_row.id,
                "requirement_id": left,
                "criterion_id": right_ac,
                "revision_id": right_rev.id,
                "sha": FAKE_SHA,
            },
        )
        await _reject(
            evidence_sql,
            {
                "id": str(uuid.uuid4()),
                "project_id": project_row.id,
                "requirement_id": left,
                "criterion_id": left_ac,
                "revision_id": right_rev.id,
                "sha": FAKE_SHA,
            },
        )
        await _reject(
            "INSERT INTO requirement_violations "
            "(id, project_id, requirement_id, invariant_id, "
            "severity, summary, author) "
            "VALUES (:id, :project_id, :requirement_id, :invariant_id, "
            "'blocking', 'cross requirement', 'alice')",
            {
                "id": str(uuid.uuid4()),
                "project_id": project_row.id,
                "requirement_id": left,
                "invariant_id": right_invs[0].id,
            },
        )

        ok = await evidence.record_evidence(
            session,
            project=PROJECT,
            criterion_id=left_ac,
            kind="test",
            result="passed",
            source_commit=sha,
        )
    assert ok.contract_revision_id == left_rev.id
    assert left_invs[0].requirement_id == left


async def test_done_waits_for_in_flight_add_violation(tmp_path: Path) -> None:
    req_id, sha = await _seed_git_requirement(tmp_path)
    inv_id, ac_id = await _add_required_criterion(req_id)
    await _pass(ac_id, sha)
    lock_held = asyncio.Event()
    release = asyncio.Event()
    outcome: dict[str, str] = {}

    async def add_and_hold() -> None:
        async with session_scope() as session:
            await evidence.add_violation(
                session,
                project=PROJECT,
                invariant_id=inv_id,
                summary="Race blocker.",
                author="reviewer",
            )
            lock_held.set()
            await release.wait()

    async def try_done() -> None:
        await lock_held.wait()
        async with session_scope() as session:
            try:
                await service.set_requirement_status(
                    session, project=PROJECT, entry_id=req_id, status=REQ_DONE
                )
                outcome["status"] = "done"
            except evidence.CloseGateError as exc:
                outcome["status"] = str(exc)

    adder = asyncio.create_task(add_and_hold())
    doner = asyncio.create_task(try_done())
    await lock_held.wait()
    await asyncio.sleep(0.1)
    release.set()
    await asyncio.gather(adder, doner)
    assert "blocking" in outcome["status"]


async def test_done_waits_for_in_flight_resolve_violation(tmp_path: Path) -> None:
    req_id, sha = await _seed_git_requirement(tmp_path)
    inv_id, ac_id = await _add_required_criterion(req_id)
    await _pass(ac_id, sha)
    async with session_scope() as session:
        finding = await evidence.add_violation(
            session,
            project=PROJECT,
            invariant_id=inv_id,
            summary="Will be resolved in flight.",
            author="reviewer",
        )
    lock_held = asyncio.Event()
    release = asyncio.Event()
    outcome: dict[str, str] = {}

    async def resolve_and_hold() -> None:
        async with session_scope() as session:
            await evidence.resolve_violation(
                session, project=PROJECT, violation_id=finding.id, author="resolver"
            )
            lock_held.set()
            await release.wait()

    async def try_done() -> None:
        await lock_held.wait()
        async with session_scope() as session:
            done = await service.set_requirement_status(
                session, project=PROJECT, entry_id=req_id, status=REQ_DONE
            )
            outcome["status"] = done.requirement_status or ""

    resolver = asyncio.create_task(resolve_and_hold())
    doner = asyncio.create_task(try_done())
    await lock_held.wait()
    await asyncio.sleep(0.1)
    release.set()
    await asyncio.gather(resolver, doner)
    assert outcome["status"] == REQ_DONE


async def test_criterion_mutation_serializes_with_done_transition(tmp_path: Path) -> None:
    req_id, sha = await _seed_git_requirement(tmp_path)
    _, ac_id = await _add_required_criterion(req_id, ac_key="AC-LOCK")
    await _pass(ac_id, sha)
    original_statement = "AC-LOCK under test."

    lock_held = asyncio.Event()
    release = asyncio.Event()
    done_status: dict[str, str] = {}

    async def evaluate_and_hold_then_done() -> None:
        async with session_scope() as session:
            gate = await evidence.evaluate_close_gate(
                session, project=PROJECT, requirement_id=req_id
            )
            assert gate.passed is True
            lock_held.set()
            await release.wait()
            done = await service.set_requirement_status(
                session, project=PROJECT, entry_id=req_id, status=REQ_DONE
            )
            done_status["status"] = done.requirement_status or ""

    async def mutate_criterion() -> None:
        await lock_held.wait()
        async with session_scope() as session:
            await contracts.update_criterion(
                session,
                project=PROJECT,
                criterion_id=ac_id,
                statement="Mutated between gate evaluation and done.",
            )

    holder = asyncio.create_task(evaluate_and_hold_then_done())
    mutator = asyncio.create_task(mutate_criterion())
    await lock_held.wait()
    await asyncio.sleep(0.15)
    assert not mutator.done()
    async with session_scope() as session:
        current = await contracts.get_criterion(session, project=PROJECT, criterion_id=ac_id)
    assert current.statement == original_statement
    release.set()
    await asyncio.gather(holder, mutator)
    assert done_status["status"] == REQ_DONE
    async with session_scope() as session:
        after = await contracts.get_criterion(session, project=PROJECT, criterion_id=ac_id)
    assert after.statement == "Mutated between gate evaluation and done."

    other_root = tmp_path / "rev"
    other_id, other_sha = await _seed_git_requirement(
        other_root, name="lock-rev", title="Revision race"
    )
    _, other_ac = await _add_required_criterion(other_id, ac_key="AC-REVLOCK", project="lock-rev")
    await _pass(other_ac, other_sha, project="lock-rev")
    mutate_held = asyncio.Event()
    mutate_release = asyncio.Event()
    stale_outcome: dict[str, str] = {}

    async def mutate_and_hold() -> None:
        async with session_scope() as session:
            await contracts.update_criterion(
                session,
                project="lock-rev",
                criterion_id=other_ac,
                statement="New revision while done waits.",
            )
            mutate_held.set()
            await mutate_release.wait()

    async def done_after_mutate() -> None:
        await mutate_held.wait()
        async with session_scope() as session:
            try:
                await service.set_requirement_status(
                    session, project="lock-rev", entry_id=other_id, status=REQ_DONE
                )
                stale_outcome["status"] = "done"
            except evidence.CloseGateError as exc:
                stale_outcome["status"] = str(exc)

    mut_hold = asyncio.create_task(mutate_and_hold())
    done_wait = asyncio.create_task(done_after_mutate())
    await mutate_held.wait()
    await asyncio.sleep(0.15)
    assert not done_wait.done()
    mutate_release.set()
    await asyncio.gather(mut_hold, done_wait)
    assert "stale" in stale_outcome["status"]


async def test_t12_close_gate_ranks_missing_stale_and_blocking_in_task_contract(
    tmp_path: Path,
) -> None:
    req_id, sha = await _seed_git_requirement(tmp_path, title="Cart totals")
    miss_inv, miss_ac = await _add_required_criterion(
        req_id, inv_key="INV-MISS", ac_key="AC-MISS", sort_order=1
    )
    _peer_inv, peer_ac = await _add_required_criterion(
        req_id, inv_key="INV-PEER", ac_key="AC-PEER", sort_order=0
    )
    await _pass(peer_ac, sha)
    async with session_scope() as session:
        missing_pack = await briefing.get_task_contract(
            session,
            project=PROJECT,
            task="cart totals",
            requirement_ids=[req_id],
            max_tokens=160,
            ranked_paths=(),
        )
    assert "INV-MISS" in missing_pack.text
    if "INV-PEER" in missing_pack.text:
        assert missing_pack.text.index("INV-MISS") < missing_pack.text.index("INV-PEER")

    stale_req, stale_sha = await _seed_git_requirement(
        tmp_path / "stale", name="stale-evidence", title="Stale ranking"
    )
    stale_inv, stale_ac = await _add_required_criterion(
        stale_req,
        inv_key="INV-STALE",
        ac_key="AC-STALE",
        project="stale-evidence",
        sort_order=1,
    )
    _fresh_inv, fresh_ac = await _add_required_criterion(
        stale_req,
        inv_key="INV-FRESH",
        ac_key="AC-FRESH",
        project="stale-evidence",
        sort_order=0,
    )
    await _pass(stale_ac, stale_sha, project="stale-evidence")
    await _pass(fresh_ac, stale_sha, project="stale-evidence")
    new_sha = _git_commit(tmp_path / "stale", "move HEAD")
    await _pass(fresh_ac, new_sha, project="stale-evidence")
    async with session_scope() as session:
        stale_pack = await briefing.get_task_contract(
            session,
            project="stale-evidence",
            task="stale ranking",
            requirement_ids=[stale_req],
            max_tokens=160,
            ranked_paths=(),
        )
    assert "INV-STALE" in stale_pack.text
    assert "Validation: stale" in stale_pack.text
    if "INV-FRESH" in stale_pack.text:
        assert stale_pack.text.index("INV-STALE") < stale_pack.text.index("INV-FRESH")

    block_req, block_sha = await _seed_git_requirement(
        tmp_path / "block", name="block-evidence", title="Blocking ranking"
    )
    block_inv, block_ac = await _add_required_criterion(
        block_req,
        inv_key="INV-BLOCK",
        ac_key="AC-BLOCK",
        project="block-evidence",
        sort_order=1,
    )
    _ok_inv, ok_ac = await _add_required_criterion(
        block_req,
        inv_key="INV-OK",
        ac_key="AC-OK",
        project="block-evidence",
        sort_order=0,
    )
    await _pass(block_ac, block_sha, project="block-evidence")
    await _pass(ok_ac, block_sha, project="block-evidence")
    async with session_scope() as session:
        await evidence.add_violation(
            session,
            project="block-evidence",
            invariant_id=block_inv,
            summary="Open blocking finding.",
            author="reviewer",
        )
        block_pack = await briefing.get_task_contract(
            session,
            project="block-evidence",
            task="blocking ranking",
            requirement_ids=[block_req],
            max_tokens=160,
            ranked_paths=(),
        )
    assert "INV-BLOCK" in block_pack.text
    if "INV-OK" in block_pack.text:
        assert block_pack.text.index("INV-BLOCK") < block_pack.text.index("INV-OK")
    assert miss_inv
    assert miss_ac
    assert stale_inv


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


def _requirement_snapshot(url: str) -> list[tuple[object, ...]]:
    engine = create_engine(url)
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT id, project_id, section, headline, detail, status, "
                "requirement_status, req_key FROM context_entries "
                "WHERE section = 'requirements' ORDER BY id"
            )
        ).fetchall()
    engine.dispose()
    return [tuple(row) for row in rows]


def test_migration_upgrades_from_contract_head_and_downgrades_without_changing_requirements() -> (
    None
):
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
                        "VALUES ('proj-legacy', 'legacy', '/repos/legacy')"
                    )
                )
                conn.execute(
                    text(
                        "INSERT INTO context_entries "
                        "(id, project_id, section, headline, detail, status, author, "
                        "requirement_status, req_key) "
                        "VALUES ('req-legacy', 'proj-legacy', 'requirements', "
                        "'Ship login', 'Must ship login', 'open', 'tester', "
                        "'in-progress', 'R-001')"
                    )
                )
            engine.dispose()
            before = _requirement_snapshot(url)
            command.upgrade(config, "head")
            assert _requirement_snapshot(url) == before
            engine = create_engine(url)
            with engine.connect() as conn:
                tables = {
                    str(row[0])
                    for row in conn.execute(
                        text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
                    )
                }
            engine.dispose()
            assert "requirement_evidence" in tables
            assert "requirement_violations" in tables
            command.downgrade(config, PRIOR_HEAD)
            assert _requirement_snapshot(url) == before
            engine = create_engine(url)
            with engine.connect() as conn:
                tables_after = {
                    str(row[0])
                    for row in conn.execute(
                        text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
                    )
                }
            engine.dispose()
            assert "requirement_evidence" not in tables_after
            assert "requirement_violations" not in tables_after
