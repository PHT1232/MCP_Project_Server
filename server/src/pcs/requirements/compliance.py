"""Deterministic compact requirement compliance review (T13).

Composes the T10 contract and T12 evidence close gate. It does not execute
validation, inspect logs, or make LLM judgements.
"""

from __future__ import annotations

import shlex
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, cast

from sqlalchemy.ext.asyncio import AsyncSession

from pcs.context import service as context_service
from pcs.context.types import (
    INDEPENDENT_REVIEW_REQUIRED,
    RISK_HIGH,
    SECTION_REQUIREMENTS,
    ContractNotFoundError,
    CriterionView,
    ValidationError,
)
from pcs.requirements import contracts, evidence

MAX_REQUIREMENTS: Final = 25
MAX_EXCEPTIONS_PER_REQUIREMENT: Final = 8
MAX_FILE_REFS_PER_EXCEPTION: Final = 2
MAX_EVIDENCE_ROWS: Final = 20
MAX_VIOLATION_ROWS: Final = 20
MAX_WARNING_CODES: Final = 6
NORMALIZED_TEST_REUSE_THRESHOLD: Final = 3
WARNING_MISSING_COMMIT_REF: Final = "missing-commit-ref"
WARNING_MISSING_FILE_TEST_REF: Final = "missing-file-test-ref"
WARNING_DIRTY_NO_FINGERPRINT: Final = "dirty-no-fingerprint"
WARNING_SECURITY_GENERIC_COMMAND: Final = "security-generic-command"
WARNING_EXCESSIVE_TEST_REUSE: Final = "excessive-test-reuse"
WARNING_REVIEWER_AUTHOR_COLLISION: Final = "reviewer-author-collision"


@dataclass(frozen=True)
class ComplianceReview:
    """Token-bounded compliance verdict for requested requirements (T13)."""

    project_id: str
    requirements: tuple[dict[str, object], ...]
    omitted_requirements: int

    def as_dict(self) -> dict[str, object]:
        return {
            "project_id": self.project_id,
            "requirements": list(self.requirements),
            "reviewed_count": len(self.requirements),
            "omitted_requirements": self.omitted_requirements,
            "limits": {
                "requirements": MAX_REQUIREMENTS,
                "exceptions_per_requirement": MAX_EXCEPTIONS_PER_REQUIREMENT,
            },
        }


def _refs(*values: str | None) -> list[str]:
    return sorted({value for value in values if value})[:MAX_FILE_REFS_PER_EXCEPTION]


def _str_value(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _seq(row: dict[str, object]) -> int:
    value = row.get("seq")
    return value if isinstance(value, int) else 0


def _blocking_ref(row: dict[str, object]) -> list[str]:
    path = row.get("file_ref")
    if not isinstance(path, str) or not path:
        return []
    line_no = row.get("line_no")
    return _refs(f"{path}:{line_no}" if isinstance(line_no, int) else path)


def _latest(rows: Sequence[evidence.EvidenceView]) -> evidence.EvidenceView | None:
    return max(rows, key=lambda row: row.seq, default=None)


def _normalized_test_ref(value: str) -> str:
    """Normalize references before deterministic reuse counting."""
    normalized = value.strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    normalized = "/".join(part for part in normalized.split("/") if part)
    return normalized.casefold()


def _command_tokens(value: str) -> tuple[str, ...] | None:
    """Tokenize command text and unwrap supported shell runners without execution."""
    try:
        tokens = tuple(shlex.split(value, posix=True))
    except ValueError:
        return None
    for _ in range(3):
        if (
            len(tokens) >= 3
            and tokens[0].casefold() in {"sh", "bash", "dash"}
            and tokens[1] == "-c"
        ):
            try:
                tokens = tuple(shlex.split(tokens[2], posix=True))
            except ValueError:
                return None
            continue
        if len(tokens) >= 3 and tokens[:2] == ("uv", "run"):
            tokens = tokens[2:]
            continue
        break
    return tuple(token.casefold() for token in tokens)


def _is_generic_command(value: str) -> bool:
    """Recognize project-wide gates from safely tokenized command text."""
    tokens = _command_tokens(value)
    if not tokens:
        return False
    command = tokens[0]
    args = tokens[1:]
    if command == "just" and args and args[0] == "check":
        return all(arg.startswith("-") for arg in args[1:])
    if command in {"pytest", "py.test"}:
        return not any(not arg.startswith("-") for arg in args)
    if command == "cargo" and args and args[0] in {"test", "build", "clippy"}:
        return not any(not arg.startswith("-") for arg in args[1:])
    if command in {"npm", "pnpm", "yarn"}:
        scripts = args[1:] if args[:1] == ("run",) else args
        return (
            bool(scripts)
            and scripts[0] in {"test", "build", "lint"}
            and all(arg.startswith("-") for arg in scripts[1:])
        )
    return False


def _warning_codes(
    criteria: Sequence[CriterionView],
    invariants_by_id: dict[str, object],
    rows: Sequence[evidence.EvidenceView],
) -> tuple[str, ...]:
    """Return six bounded deterministic weak-evidence codes (INV-EVIDENCE-5).

    ``missing-commit-ref`` and ``dirty-no-fingerprint`` diagnose explicit legacy
    rows; the public recorder rejects those states for newly recorded evidence.
    """
    del invariants_by_id
    current = [row for row in rows if row.lifecycle != evidence.EVIDENCE_LIFECYCLE_SUPERSEDED]
    verified = [row for row in current if row.lifecycle == evidence.EVIDENCE_LIFECYCLE_VERIFIED]
    codes: set[str] = set()
    if any(not row.source_commit or not row.source_commit_verified for row in current):
        codes.add(WARNING_MISSING_COMMIT_REF)
    if any(
        (row.file_ref is not None and row.file_ref_verified is False)
        or (row.test_ref is not None and row.test_ref_verified is False)
        or (row.evidence_kind in {"test", "file"} and not (row.test_ref or row.file_ref))
        for row in current
    ):
        codes.add(WARNING_MISSING_FILE_TEST_REF)
    if any(
        row.recording_state == evidence.EVIDENCE_LIFECYCLE_PROVISIONAL
        and row.worktree_fingerprint is None
        for row in current
    ):
        codes.add(WARNING_DIRTY_NO_FINGERPRINT)
    criterion_by_id = {row.id: row for row in criteria}
    security_terms = ("security", "auth", "secret", "permission", "access", "injection")
    if any(
        row.evidence_kind == "command"
        and row.command_ref is not None
        and _is_generic_command(row.command_ref)
        and any(
            term in criterion_by_id[row.criterion_id].statement.casefold()
            for term in security_terms
        )
        for row in verified
        if row.criterion_id in criterion_by_id
    ):
        codes.add(WARNING_SECURITY_GENERIC_COMMAND)
    test_reuse: dict[str, set[str]] = {}
    for row in verified:
        if row.test_ref:
            test_reuse.setdefault(_normalized_test_ref(row.test_ref), set()).add(row.criterion_id)
    if any(len(ids) > NORMALIZED_TEST_REUSE_THRESHOLD for ids in test_reuse.values()):
        codes.add(WARNING_EXCESSIVE_TEST_REUSE)
    implementation_authors: dict[str, set[str]] = {}
    review_authors: dict[str, set[str]] = {}
    for row in verified:
        target = review_authors if row.evidence_kind == "review" else implementation_authors
        target.setdefault(row.criterion_id, set()).add(row.author.strip().casefold())
    if any(
        implementation_authors.get(criterion_id, set()) & reviewers
        for criterion_id, reviewers in review_authors.items()
    ):
        codes.add(WARNING_REVIEWER_AUTHOR_COLLISION)
    return tuple(sorted(codes)[:MAX_WARNING_CODES])


def _criterion_exception_kind(
    criterion: CriterionView,
    rows: Sequence[evidence.EvidenceView],
    *,
    current_revision_id: str | None,
    invariant_risk: str,
    invariant_id: str,
) -> str | None:
    """Match T12 close-gate semantics using stable criterion identity (T13)."""
    current_rows = [row for row in rows if row.contract_revision_id == current_revision_id]
    implementation = [row for row in current_rows if row.evidence_kind == criterion.evidence_kind]
    reviews = [row for row in current_rows if row.evidence_kind == "review"]
    latest_impl = _latest(implementation)
    if latest_impl is None:
        older_pass = any(
            row.evidence_kind == criterion.evidence_kind
            and row.result == evidence.EVIDENCE_RESULT_PASSED
            for row in rows
        )
        return "stale" if older_pass else "missing"
    if latest_impl.result != evidence.EVIDENCE_RESULT_PASSED:
        return "missing"
    if latest_impl.lifecycle != evidence.EVIDENCE_LIFECYCLE_VERIFIED:
        return "stale"
    if criterion.independent_review != INDEPENDENT_REVIEW_REQUIRED and invariant_risk != RISK_HIGH:
        return None
    latest_review = _latest(reviews)
    if latest_review is None:
        return "review-missing"
    if latest_review.result != evidence.EVIDENCE_RESULT_PASSED:
        return "review-failed"
    if latest_review.lifecycle != evidence.EVIDENCE_LIFECYCLE_VERIFIED:
        return "review-stale"
    if latest_review.author.strip().casefold() == latest_impl.author.strip().casefold():
        return "review-failed"
    if latest_review.review_ref not in {
        f"criterion:{criterion.id}",
        f"invariant:{invariant_id}",
    }:
        return "review-failed"
    return None


def _violation_sort_key(row: dict[str, object]) -> tuple[int, str, str, str]:
    status = str(row.get("status"))
    severity = str(row.get("severity"))
    priority = 2
    if status == evidence.VIOLATION_OPEN:
        priority = 0 if severity == evidence.VIOLATION_BLOCKING else 1
    return priority, status, severity, str(row.get("id"))


async def compact_requirement_evidence(
    session: AsyncSession, *, project: str, requirement_id: str
) -> dict[str, object]:
    """Return bounded latest evidence and violations for HTTP drill-down (T13)."""
    payload = await evidence.get_requirement_evidence(
        session, project=project, requirement_id=requirement_id
    )
    raw_evidence = cast(list[dict[str, object]], payload["evidence"])
    raw_violations = cast(list[dict[str, object]], payload["violations"])
    latest = sorted(raw_evidence, key=_seq, reverse=True)
    evidence_rows = [
        {
            "id": row.get("id"),
            "criterion_id": row.get("criterion_id"),
            "contract_revision_id": row.get("contract_revision_id"),
            "kind": row.get("evidence_kind"),
            "result": row.get("result"),
            "source_commit": row.get("source_commit"),
            "lifecycle": row.get("lifecycle"),
            "claim_ref": row.get("claim_ref"),
            "review_ref": row.get("review_ref"),
            "file_refs": _refs(
                _str_value(row.get("file_ref")),
                _str_value(row.get("test_ref")),
                _str_value(row.get("command_ref")),
                _str_value(row.get("artifact_ref")),
            ),
            "seq": row.get("seq"),
        }
        for row in latest[:MAX_EVIDENCE_ROWS]
    ]
    violations = sorted(raw_violations, key=_violation_sort_key)
    violation_rows = [
        {
            "id": row.get("id"),
            "invariant_id": row.get("invariant_id"),
            "severity": row.get("severity"),
            "status": row.get("status"),
            "summary": row.get("summary"),
            "file_refs": _blocking_ref(row),
        }
        for row in violations[:MAX_VIOLATION_ROWS]
    ]
    return {
        "requirement_id": requirement_id,
        "close_gate": payload["close_gate"],
        "evidence": evidence_rows,
        "evidence_total": len(raw_evidence),
        "evidence_omitted": max(0, len(raw_evidence) - MAX_EVIDENCE_ROWS),
        "violations": violation_rows,
        "violations_total": len(raw_violations),
        "violations_omitted": max(0, len(raw_violations) - MAX_VIOLATION_ROWS),
        "limits": {"evidence": MAX_EVIDENCE_ROWS, "violations": MAX_VIOLATION_ROWS},
    }


async def _exceptions(
    session: AsyncSession, *, project: str, requirement_id: str
) -> tuple[list[dict[str, object]], int]:
    rows = await evidence.get_requirement_evidence(
        session, project=project, requirement_id=requirement_id
    )
    evidence_payload = cast(list[dict[str, object]], rows["evidence"])
    violations = cast(list[dict[str, object]], rows["violations"])
    evidence_rows = await evidence.list_evidence(
        session, project=project, requirement_id=requirement_id
    )

    refs_by_criterion: dict[str, set[str]] = {}
    for row in evidence_payload:
        criterion_id = row.get("criterion_id")
        if not isinstance(criterion_id, str):
            continue
        refs_by_criterion.setdefault(criterion_id, set()).update(
            ref
            for key in ("file_ref", "test_ref", "command_ref", "artifact_ref")
            if isinstance((ref := row.get(key)), str) and ref
        )

    invariants = await contracts.list_invariants(
        session, project=project, requirement_id=requirement_id
    )
    invariant_keys = {row.id: row.key for row in invariants}
    invariant_risks = {row.id: row.risk for row in invariants}
    criteria = await contracts.list_criteria(
        session, project=project, requirement_id=requirement_id
    )
    revisions = await contracts.list_contract_revisions(
        session, project=project, requirement_id=requirement_id
    )
    current_revisions = {
        revision.entity_id: revision.id
        for revision in revisions
        if revision.entity_kind == "criterion"
    }
    evidence_by_criterion: dict[str, list[evidence.EvidenceView]] = {}
    for evidence_row in evidence_rows:
        evidence_by_criterion.setdefault(evidence_row.criterion_id, []).append(evidence_row)
    output: list[dict[str, object]] = []
    for criterion in criteria:
        if not criterion.required or criterion.invariant_id not in invariant_keys:
            continue
        kind = _criterion_exception_kind(
            criterion,
            evidence_by_criterion.get(criterion.id, []),
            current_revision_id=current_revisions.get(criterion.id),
            invariant_risk=invariant_risks[criterion.invariant_id],
            invariant_id=criterion.invariant_id,
        )
        if kind is None:
            continue
        output.append(
            {
                "kind": kind,
                "criterion_id": criterion.id,
                "criterion_key": criterion.key,
                "invariant_id": criterion.invariant_id,
                "invariant_key": invariant_keys[criterion.invariant_id],
                "file_refs": sorted(refs_by_criterion.get(criterion.id, set()))[
                    :MAX_FILE_REFS_PER_EXCEPTION
                ],
            }
        )

    open_blocking = [
        row
        for row in violations
        if row.get("status") == evidence.VIOLATION_OPEN
        and row.get("severity") == evidence.VIOLATION_BLOCKING
    ]
    for row in open_blocking:
        invariant_id = row.get("invariant_id")
        if not isinstance(invariant_id, str):
            continue
        try:
            invariant = await contracts.get_invariant(
                session, project=project, invariant_id=invariant_id, include_deleted=True
            )
            invariant_key = invariant.key
        except ContractNotFoundError:
            invariant_key = invariant_id
        output.append(
            {
                "kind": "blocking",
                "violation_id": row.get("id"),
                "invariant_id": invariant_id,
                "invariant_key": invariant_key,
                "summary": row.get("summary"),
                "file_refs": _blocking_ref(row),
            }
        )

    output.sort(
        key=lambda row: (
            str(row.get("kind")),
            str(row.get("criterion_key", row.get("invariant_key", ""))),
            str(row.get("criterion_id", row.get("violation_id", ""))),
        )
    )
    return output[:MAX_EXCEPTIONS_PER_REQUIREMENT], max(
        0, len(output) - MAX_EXCEPTIONS_PER_REQUIREMENT
    )


async def review_requirement_compliance(
    session: AsyncSession, *, project: str, requirement_ids: Sequence[str]
) -> ComplianceReview:
    """Return deterministic exception-only compliance state (T13)."""
    project_row = await context_service.resolve_project(session, project)
    unique_ids = sorted({item.strip() for item in requirement_ids if item.strip()})
    if not unique_ids:
        raise ValidationError("requirement_ids must contain at least one requirement id")
    selected = unique_ids[:MAX_REQUIREMENTS]
    verdicts: list[dict[str, object]] = []
    for requirement_id in selected:
        entry = await context_service.get_entry(session, project=project, entry_id=requirement_id)
        if entry.section != SECTION_REQUIREMENTS:
            raise ContractNotFoundError("requirement", requirement_id, project_row.name)
        gate = await evidence.evaluate_close_gate(
            session, project=project, requirement_id=requirement_id
        )
        criteria = await contracts.list_criteria(
            session, project=project, requirement_id=requirement_id
        )
        invariants = await contracts.list_invariants(
            session, project=project, requirement_id=requirement_id, include_deleted=True
        )
        evidence_rows = await evidence.list_evidence(
            session, project=project, requirement_id=requirement_id
        )
        warnings = _warning_codes(criteria, {row.id: row for row in invariants}, evidence_rows)
        exceptions, omitted = await _exceptions(
            session, project=project, requirement_id=requirement_id
        )
        verdicts.append(
            {
                "requirement_id": requirement_id,
                "req_key": entry.req_key,
                "status": entry.requirement_status,
                "configured": gate.configured,
                "verdict": "not-configured"
                if not gate.configured
                else ("verified" if gate.passed else "failed"),
                "ac_verified": gate.ac_verified,
                "ac_total": gate.ac_total,
                # T12 canonical values: ok, stale, not-configured. Missing ACs are exceptions.
                "validation": gate.validation,
                "review": gate.review,
                "warning_codes": list(warnings),
                "warning_count": len(warnings),
                "exceptions": exceptions,
                "omitted_exceptions": omitted,
            }
        )
    return ComplianceReview(
        project_id=project_row.id,
        requirements=tuple(verdicts),
        omitted_requirements=max(0, len(unique_ids) - MAX_REQUIREMENTS),
    )
