"""Deterministic compact requirement compliance review (T13).

Composes the T10 contract and T12 evidence close gate. It does not execute
validation, inspect logs, or make LLM judgements.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Final, cast

from sqlalchemy.ext.asyncio import AsyncSession

from pcs.context import service as context_service
from pcs.context.types import (
    INDEPENDENT_REVIEW_REQUIRED,
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

EvidenceFreshness = Callable[..., bool]
RepoState = Callable[[str], Awaitable[tuple[str | None, str | None]]]
evidence_is_stale = cast(EvidenceFreshness, vars(evidence)["_is_stale"])
evidence_repo_state = cast(RepoState, vars(evidence)["_repo_state"])


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


def _criterion_exception_kind(
    criterion: CriterionView,
    rows: Sequence[evidence.EvidenceView],
    *,
    current_revision_id: str | None,
    current_commit: str | None,
    current_fingerprint: str | None,
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
    if evidence_is_stale(
        latest_impl,
        current_commit=current_commit,
        current_fingerprint=current_fingerprint,
    ):
        return "stale"
    if criterion.independent_review != INDEPENDENT_REVIEW_REQUIRED:
        return None
    latest_review = _latest(reviews)
    if latest_review is None:
        return "review-missing"
    if latest_review.result != evidence.EVIDENCE_RESULT_PASSED:
        return "review-failed"
    if evidence_is_stale(
        latest_review,
        current_commit=current_commit,
        current_fingerprint=current_fingerprint,
    ):
        return "review-stale"
    if latest_review.author.strip().casefold() == latest_impl.author.strip().casefold():
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
    project_row = await context_service.resolve_project(session, project)
    current_commit, current_fingerprint = await evidence_repo_state(project_row.root_path)

    output: list[dict[str, object]] = []
    for criterion in criteria:
        if not criterion.required or criterion.invariant_id not in invariant_keys:
            continue
        kind = _criterion_exception_kind(
            criterion,
            evidence_by_criterion.get(criterion.id, []),
            current_revision_id=current_revisions.get(criterion.id),
            current_commit=current_commit,
            current_fingerprint=current_fingerprint,
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
                "exceptions": exceptions,
                "omitted_exceptions": omitted,
            }
        )
    return ComplianceReview(
        project_id=project_row.id,
        requirements=tuple(verdicts),
        omitted_requirements=max(0, len(unique_ids) - MAX_REQUIREMENTS),
    )
