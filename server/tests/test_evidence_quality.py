"""T19 regressions for INV-EVIDENCE-1..7 and AC-EVIDENCE-1..12."""

from __future__ import annotations

import json
import os
import subprocess
from contextlib import suppress
from pathlib import Path
from typing import cast

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from testcontainers.community.postgres import PostgresContainer

from pcs.config import get_settings
from pcs.context import service
from pcs.context.assembly import estimate_tokens
from pcs.context.types import ValidationError
from pcs.db.base import session_scope
from pcs.db.models import RequirementEvidence
from pcs.requirements import briefing, compliance, contracts, evidence

pytestmark = pytest.mark.usefixtures("clean_db")
PROJECT = "t19-evidence"
PGVECTOR_IMAGE = "pgvector/pgvector:pg16"


def _git(root: Path) -> str:
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t19@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "T19"], cwd=root, check=True)
    (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "seed"], cwd=root, check=True, capture_output=True)
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()


async def _contract(
    root: Path,
    *,
    risk: str = "medium",
    review: str = "not-required",
    kind: str = "test",
    key: str = "AC-1",
) -> tuple[str, str, str]:
    _git(root)
    async with session_scope() as session:
        with suppress(service.DuplicateProjectError):
            await service.register_project(
                session, name=PROJECT, root_path=str(root), overview="T19"
            )
        req = await service.add_entry(
            session, project=PROJECT, section="requirements", headline="Evidence quality"
        )
        inv = await contracts.create_invariant(
            session,
            project=PROJECT,
            requirement_id=req.id,
            key="INV-1",
            statement="Security access evidence is scoped.",
            kind="behavior",
            risk=risk,
        )
        ac = await contracts.create_criterion(
            session,
            project=PROJECT,
            invariant_id=inv.id,
            key=key,
            statement="Security access check has specific evidence.",
            evidence_kind=kind,
            independent_review=review,
        )
        return req.id, inv.id, ac.id


async def test_dirty_rejection_and_provisional_lifecycle_hide_paths(tmp_path: Path) -> None:
    _, _, ac_id = await _contract(tmp_path)
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    (tmp_path / "private-secret.py").write_text("DIRTY = True\n", encoding="utf-8")
    async with session_scope() as session:
        with pytest.raises(ValidationError) as caught:
            await evidence.record_evidence(
                session,
                project=PROJECT,
                criterion_id=ac_id,
                kind="test",
                result="passed",
                source_commit=sha,
            )
        message = str(caught.value)
        assert message.startswith("dirty-worktree: worktree_fingerprint required (expected ")
        assert "private-secret.py" not in message
        _, fingerprint = await evidence._repo_state(str(tmp_path))
        assert fingerprint is not None and len(fingerprint) == 64
        assert fingerprint in message
        row = await evidence.record_evidence(
            session,
            project=PROJECT,
            criterion_id=ac_id,
            kind="test",
            result="passed",
            source_commit=sha,
            worktree_fingerprint=fingerprint,
        )
        gate = await evidence.evaluate_close_gate(
            session, project=PROJECT, requirement_id=row.requirement_id
        )
    assert row.lifecycle == "provisional"
    assert not gate.passed


async def test_lifecycle_claim_bounds_and_only_verified_current_passes(tmp_path: Path) -> None:
    req_id, _, ac_id = await _contract(tmp_path)
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    async with session_scope() as session:
        first = await evidence.record_evidence(
            session,
            project=PROJECT,
            criterion_id=ac_id,
            kind="test",
            result="passed",
            source_commit=sha,
            claim_ref="claim:login",
        )
        second = await evidence.record_evidence(
            session,
            project=PROJECT,
            criterion_id=ac_id,
            kind="test",
            result="passed",
            source_commit=sha,
        )
        rows = await evidence.list_evidence(session, project=PROJECT, criterion_id=ac_id)
        gate = await evidence.evaluate_close_gate(session, project=PROJECT, requirement_id=req_id)
        ledger = await evidence.get_requirement_evidence(
            session, project=PROJECT, requirement_id=req_id
        )
        with pytest.raises(ValidationError, match="claim_ref"):
            await evidence.record_evidence(
                session,
                project=PROJECT,
                criterion_id=ac_id,
                kind="test",
                result="passed",
                source_commit=sha,
                claim_ref="x" * 161,
            )
    assert first.id != second.id
    assert [row.lifecycle for row in rows] == ["superseded", "verified-at-commit"]
    assert gate.passed
    assert "claim:login" in json.dumps(ledger)


async def test_high_risk_and_independent_review_require_distinct_scope(tmp_path: Path) -> None:
    req_id, inv_id, ac_id = await _contract(tmp_path, risk="high")
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    async with session_scope() as session:
        await evidence.record_evidence(
            session,
            project=PROJECT,
            criterion_id=ac_id,
            kind="test",
            result="passed",
            source_commit=sha,
            author="dev",
        )
        await evidence.record_evidence(
            session,
            project=PROJECT,
            criterion_id=ac_id,
            kind="review",
            result="passed",
            source_commit=sha,
            author="reviewer",
            review_ref="criterion:00000000-0000-4000-8000-000000000000",
        )
        assert not (
            await evidence.evaluate_close_gate(session, project=PROJECT, requirement_id=req_id)
        ).passed
        await evidence.record_evidence(
            session,
            project=PROJECT,
            criterion_id=ac_id,
            kind="review",
            result="passed",
            source_commit=sha,
            author="reviewer",
            review_ref=f"invariant:{inv_id}",
        )
        assert (
            await evidence.evaluate_close_gate(session, project=PROJECT, requirement_id=req_id)
        ).passed


async def test_warning_codes_are_stable_bounded_and_compact(tmp_path: Path) -> None:
    req_id, _, ac_id = await _contract(tmp_path)
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    async with session_scope() as session:
        await evidence.record_evidence(
            session,
            project=PROJECT,
            criterion_id=ac_id,
            kind="test",
            result="passed",
            source_commit=sha,
            author="same",
        )
        await evidence.record_evidence(
            session,
            project=PROJECT,
            criterion_id=ac_id,
            kind="review",
            result="passed",
            source_commit=sha,
            author="same",
            review_ref=f"criterion:{ac_id}",
        )
        first = await compliance.review_requirement_compliance(
            session, project=PROJECT, requirement_ids=[req_id]
        )
        second = await compliance.review_requirement_compliance(
            session, project=PROJECT, requirement_ids=[req_id]
        )
        pack = await briefing.get_task_contract(
            session,
            project=PROJECT,
            task="evidence quality",
            requirement_ids=[req_id],
            max_tokens=500,
            ranked_paths=(),
        )
    row = first.requirements[0]
    assert first.as_dict() == second.as_dict()
    assert cast(int, row["warning_count"]) <= compliance.MAX_WARNING_CODES
    assert "missing-file-test-ref" in cast(list[str], row["warning_codes"])
    assert "reviewer-author-collision" in cast(list[str], row["warning_codes"])
    assert "claim_ref" not in pack.text
    assert estimate_tokens(pack.text) <= 500
    assert not any(term in json.dumps(row) for term in ("diff --git", "stdout", "stderr"))


def test_migration_round_trip() -> None:
    with PostgresContainer(PGVECTOR_IMAGE, driver="psycopg") as container:
        url = container.get_connection_url()
        previous = os.environ.get("PCS_DATABASE_URL")
        os.environ["PCS_DATABASE_URL"] = url
        get_settings.cache_clear()
        config = Config("alembic.ini")
        command.upgrade(config, "0019_evidence_quality")
        engine = create_engine(url)
        with engine.connect() as connection:
            columns = {
                row[0]
                for row in connection.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name='requirement_evidence'"
                    )
                )
            }
        assert {
            "recording_state",
            "claim_ref",
            "review_ref",
            "source_commit_verified",
            "file_ref_verified",
            "test_ref_verified",
        }.issubset(columns)
        command.downgrade(config, "0007_requirement_evidence")
        with engine.connect() as connection:
            columns = {
                row[0]
                for row in connection.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name='requirement_evidence'"
                    )
                )
            }
        assert (
            "recording_state" not in columns
            and "claim_ref" not in columns
            and "review_ref" not in columns
        )
        engine.dispose()
        if previous is None:
            os.environ.pop("PCS_DATABASE_URL", None)
        else:
            os.environ["PCS_DATABASE_URL"] = previous
        get_settings.cache_clear()


async def test_source_commit_requires_commit_object_and_expands_abbreviation(
    tmp_path: Path,
) -> None:
    _, _, ac_id = await _contract(tmp_path)
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    blob = subprocess.check_output(
        ["git", "rev-parse", "HEAD:app.py"], cwd=tmp_path, text=True
    ).strip()
    tree = subprocess.check_output(
        ["git", "rev-parse", "HEAD^{tree}"], cwd=tmp_path, text=True
    ).strip()
    async with session_scope() as session:
        row = await evidence.record_evidence(
            session,
            project=PROJECT,
            criterion_id=ac_id,
            kind="test",
            result="passed",
            source_commit=sha[:7],
            test_ref="app.py",
        )
        assert row.source_commit == sha
        for invalid in ("a" * 40, blob, tree):
            with pytest.raises(ValidationError, match="existing commit object"):
                await evidence.record_evidence(
                    session,
                    project=PROJECT,
                    criterion_id=ac_id,
                    kind="test",
                    result="passed",
                    source_commit=invalid,
                )


async def test_missing_refs_at_claimed_commit_warn_and_fabrication_does_not_suppress_security(
    tmp_path: Path,
) -> None:
    req_id, _, ac_id = await _contract(tmp_path, kind="command")
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    async with session_scope() as session:
        row = await evidence.record_evidence(
            session,
            project=PROJECT,
            criterion_id=ac_id,
            kind="command",
            result="passed",
            source_commit=sha,
            command_ref="just check",
            test_ref="tests/fabricated.py",
            file_ref="missing/security.py",
        )
        review = await compliance.review_requirement_compliance(
            session, project=PROJECT, requirement_ids=[req_id]
        )
    assert row.file_ref_verified is False and row.test_ref_verified is False
    codes = cast(list[str], review.requirements[0]["warning_codes"])
    assert "missing-file-test-ref" in codes
    assert "security-generic-command" in codes


@pytest.mark.parametrize(
    ("command_ref", "generic"),
    [
        ("just check", True),
        ("pytest", True),
        ("uv run pytest", True),
        ("npm run build", True),
        ("ruff check", False),
        ("uv run pytest tests/test_security.py::test_denied", False),
    ],
)
def test_security_generic_command_gates_are_explicit(command_ref: str, generic: bool) -> None:
    assert compliance._is_generic_command(command_ref) is generic


def test_normalized_reuse_threshold_boundary() -> None:
    assert compliance.NORMALIZED_TEST_REUSE_THRESHOLD == 3
    assert compliance._normalized_test_ref(r"./Tests\\Auth.py") == "tests/auth.py"


@pytest.mark.parametrize(
    "command_ref",
    [
        "pytest -q",
        "uv run pytest -q",
        "just check --verbose",
        "cargo test --all",
        "npm run test",
        "sh -c 'just check'",
    ],
)
def test_generic_security_commands_accept_wrappers_and_options(command_ref: str) -> None:
    assert compliance._is_generic_command(command_ref)


@pytest.mark.parametrize(
    "command_ref",
    [
        "pytest -q tests/test_security.py",
        "uv run pytest tests/test_security.py::test_denied -q",
        "cargo test auth_denied --all",
        "sh -c 'pytest tests/test_security.py -q'",
    ],
)
def test_scoped_security_commands_are_not_generic(command_ref: str) -> None:
    assert not compliance._is_generic_command(command_ref)


async def test_file_and_test_refs_must_resolve_to_blobs(tmp_path: Path) -> None:
    req_id, _, ac_id = await _contract(tmp_path)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_app.py").write_text("def test_app(): pass\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "tests"], cwd=tmp_path, check=True, capture_output=True)
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    async with session_scope() as session:
        row = await evidence.record_evidence(
            session,
            project=PROJECT,
            criterion_id=ac_id,
            kind="test",
            result="passed",
            source_commit=sha,
            file_ref="tests",
            test_ref="tests/test_app.py",
        )
        review = await compliance.review_requirement_compliance(
            session, project=PROJECT, requirement_ids=[req_id]
        )
    assert row.file_ref_verified is False
    assert row.test_ref_verified is True
    assert "missing-file-test-ref" in cast(list[str], review.requirements[0]["warning_codes"])


async def test_stale_precedes_superseded_exact_ordering(tmp_path: Path) -> None:
    _, _, ac_id = await _contract(tmp_path)
    first_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True
    ).strip()
    async with session_scope() as session:
        await evidence.record_evidence(
            session,
            project=PROJECT,
            criterion_id=ac_id,
            kind="test",
            result="passed",
            source_commit=first_sha,
        )
        await evidence.record_evidence(
            session,
            project=PROJECT,
            criterion_id=ac_id,
            kind="test",
            result="passed",
            source_commit=first_sha,
        )
    (tmp_path / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-m", "advance"], cwd=tmp_path, check=True, capture_output=True
    )
    async with session_scope() as session:
        stale_rows = await evidence.list_evidence(session, project=PROJECT, criterion_id=ac_id)
        await contracts.update_criterion(
            session, project=PROJECT, criterion_id=ac_id, statement="Changed security criterion."
        )
        revision_rows = await evidence.list_evidence(session, project=PROJECT, criterion_id=ac_id)
    assert [row.lifecycle for row in stale_rows] == ["stale", "stale"]
    assert [row.lifecycle for row in revision_rows] == ["stale", "stale"]


async def test_postgresql_rejects_malformed_review_ref_directly(tmp_path: Path) -> None:
    _, _, ac_id = await _contract(tmp_path)
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    async with session_scope() as session:
        valid = await evidence.record_evidence(
            session,
            project=PROJECT,
            criterion_id=ac_id,
            kind="test",
            result="passed",
            source_commit=sha,
        )
        nested = await session.begin_nested()
        with pytest.raises(IntegrityError, match="ck_requirement_evidence_review_ref"):
            session.add(
                RequirementEvidence(
                    project_id=valid.project_id,
                    requirement_id=valid.requirement_id,
                    criterion_id=valid.criterion_id,
                    contract_revision_id=valid.contract_revision_id,
                    evidence_kind="review",
                    result="passed",
                    source_commit=sha,
                    author="reviewer",
                    review_ref="criterion:------------------------------------",
                )
            )
            await session.flush()
        await nested.rollback()


async def test_compliance_emits_all_six_codes_and_filters_noncurrent_lifecycle(
    tmp_path: Path,
) -> None:
    req_id, inv_id, first_ac = await _contract(tmp_path)
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    (tmp_path / "shared.py").write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "shared"], cwd=tmp_path, check=True, capture_output=True)
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    async with session_scope() as session:
        criterion_ids = [first_ac]
        for index in range(2, 6):
            criterion = await contracts.create_criterion(
                session,
                project=PROJECT,
                invariant_id=inv_id,
                key=f"AC-{index}",
                statement="Security access evidence is scoped.",
                evidence_kind="test",
            )
            criterion_ids.append(criterion.id)
        command_ac = await contracts.create_criterion(
            session,
            project=PROJECT,
            invariant_id=inv_id,
            key="AC-CMD",
            statement="Security access command is scoped.",
            evidence_kind="command",
        )
        recorded = []
        for criterion_id in criterion_ids[:3]:
            recorded.append(
                await evidence.record_evidence(
                    session,
                    project=PROJECT,
                    criterion_id=criterion_id,
                    kind="test",
                    result="passed",
                    source_commit=sha,
                    test_ref="shared.py",
                )
            )
        boundary = await compliance.review_requirement_compliance(
            session, project=PROJECT, requirement_ids=[req_id]
        )
        boundary_codes = cast(list[str], boundary.requirements[0]["warning_codes"])
        assert "excessive-test-reuse" not in boundary_codes
        await evidence.record_evidence(
            session,
            project=PROJECT,
            criterion_id=criterion_ids[3],
            kind="test",
            result="passed",
            source_commit=sha,
            test_ref="./shared.py",
        )
        missing = await evidence.record_evidence(
            session,
            project=PROJECT,
            criterion_id=criterion_ids[4],
            kind="test",
            result="passed",
            source_commit=sha,
            test_ref="missing.py",
            author="same",
        )
        await evidence.record_evidence(
            session,
            project=PROJECT,
            criterion_id=criterion_ids[4],
            kind="review",
            result="passed",
            source_commit=sha,
            author="same",
            review_ref=f"criterion:{criterion_ids[4]}",
        )
        await evidence.record_evidence(
            session,
            project=PROJECT,
            criterion_id=command_ac.id,
            kind="command",
            result="passed",
            source_commit=sha,
            command_ref="sh -c 'just check --verbose'",
        )
        session.add(
            RequirementEvidence(
                project_id=missing.project_id,
                requirement_id=req_id,
                criterion_id=first_ac,
                contract_revision_id=recorded[0].contract_revision_id,
                evidence_kind="file",
                result="passed",
                source_commit=sha,
                recording_state="provisional",
                source_commit_verified=False,
                author="legacy",
            )
        )
        await session.flush()
        final = await compliance.review_requirement_compliance(
            session, project=PROJECT, requirement_ids=[req_id]
        )
    assert cast(list[str], final.requirements[0]["warning_codes"]) == sorted(
        [
            "dirty-no-fingerprint",
            "excessive-test-reuse",
            "missing-commit-ref",
            "missing-file-test-ref",
            "reviewer-author-collision",
            "security-generic-command",
        ]
    )
