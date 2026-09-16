"""Compact evidence ledger and deterministic close gate (T12).

Records revision-bound evidence and violations. ``set_requirement_status(...,
done)`` is rejected when required evidence is missing, failed, stale, or blocked.
Recording evidence never changes requirement status (D4). No MCP/HTTP imports.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pcs.context.service import resolve_project
from pcs.context.types import (
    CONTRACT_AUTHOR_MAX_CHARS,
    EVIDENCE_KINDS,
    INDEPENDENT_REVIEW_REQUIRED,
    STATUS_DELETED,
    ContractNotFoundError,
    CriterionView,
    InvariantView,
    ValidationError,
)
from pcs.db.models import (
    ContextEntry,
    RequirementContractRevision,
    RequirementEvidence,
    RequirementViolation,
)
from pcs.requirements import contracts

__all__ = [
    "EVIDENCE_LIFECYCLE_PROVISIONAL",
    "EVIDENCE_LIFECYCLE_STALE",
    "EVIDENCE_LIFECYCLE_SUPERSEDED",
    "EVIDENCE_LIFECYCLE_VERIFIED",
    "EVIDENCE_RESULT_FAILED",
    "EVIDENCE_RESULT_PASSED",
    "EVIDENCE_RESULT_PENDING",
    "VIOLATION_BLOCKING",
    "VIOLATION_OPEN",
    "VIOLATION_RESOLVED",
    "VIOLATION_WARNING",
    "CloseGateError",
    "CloseGateView",
    "EvidenceView",
    "ViolationView",
    "add_violation",
    "assert_close_gate_allows_done",
    "evaluate_close_gate",
    "get_requirement_evidence",
    "list_evidence",
    "record_evidence",
    "resolve_violation",
    "summarize_close_gate",
]

EVIDENCE_RESULT_PASSED: Final = "passed"
EVIDENCE_RESULT_FAILED: Final = "failed"
EVIDENCE_RESULT_PENDING: Final = "manual-pending"
EVIDENCE_RESULTS: Final[frozenset[str]] = frozenset(
    {EVIDENCE_RESULT_PASSED, EVIDENCE_RESULT_FAILED, EVIDENCE_RESULT_PENDING}
)

VIOLATION_BLOCKING: Final = "blocking"
VIOLATION_WARNING: Final = "warning"
VIOLATION_SEVERITIES: Final[frozenset[str]] = frozenset({VIOLATION_BLOCKING, VIOLATION_WARNING})
VIOLATION_OPEN: Final = "open"
VIOLATION_RESOLVED: Final = "resolved"

REF_MAX: Final = 200
FILE_REF_MAX: Final = 240
ARTIFACT_MAX: Final = 500
SUMMARY_MAX: Final = 200
COMMIT_SHORT_MIN: Final = 7
COMMIT_FULL_LEN: Final = 40
FINGERPRINT_MAX: Final = 64
CLAIM_REF_MAX: Final = 160
REVIEW_REF_MAX: Final = 80
_REVIEW_REF_RE = re.compile(
    r"^(criterion|invariant):[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
EVIDENCE_LIFECYCLE_PROVISIONAL: Final = "provisional"
EVIDENCE_LIFECYCLE_VERIFIED: Final = "verified-at-commit"
EVIDENCE_LIFECYCLE_STALE: Final = "stale"
EVIDENCE_LIFECYCLE_SUPERSEDED: Final = "superseded"
_CLEAN_FINGERPRINT: Final = hashlib.sha256(b"").hexdigest()

_COMMIT_RE = re.compile(r"^[0-9a-f]{7,40}$", re.IGNORECASE)
_FULL_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_SECRET_RE = re.compile(
    r"(password|secret|api[_-]?key|token|bearer|private[_-]?key)\s*[:=]",
    re.IGNORECASE,
)
_DIFF_MARKERS: Final[tuple[str, ...]] = ("diff --git", "\n+++ ", "\n--- ", "\n@@ ")
_LOG_MARKERS: Final[tuple[str, ...]] = ("traceback (most recent", "stdout", "stderr")


class CloseGateError(ValidationError):
    """``done`` rejected because the close gate is not satisfied (T12)."""

    def __init__(self, unmet: Sequence[str]) -> None:
        self.unmet = tuple(unmet)
        super().__init__("Cannot mark requirement done: " + "; ".join(self.unmet))


@dataclass(frozen=True)
class EvidenceView:
    """Public compact evidence row. Never includes stdout or diffs."""

    id: str
    project_id: str
    requirement_id: str
    criterion_id: str
    contract_revision_id: str
    evidence_kind: str
    result: str
    command_ref: str | None
    test_ref: str | None
    file_ref: str | None
    source_commit: str
    worktree_fingerprint: str | None
    artifact_ref: str | None
    claim_ref: str | None
    review_ref: str | None
    recording_state: str
    effective_lifecycle: str
    source_commit_verified: bool
    file_ref_verified: bool | None
    test_ref_verified: bool | None
    author: str
    created_at: datetime
    seq: int

    @property
    def lifecycle(self) -> str:
        """Return the derived four-state lifecycle (INV-EVIDENCE-2)."""
        return self.effective_lifecycle

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "requirement_id": self.requirement_id,
            "criterion_id": self.criterion_id,
            "contract_revision_id": self.contract_revision_id,
            "evidence_kind": self.evidence_kind,
            "result": self.result,
            "command_ref": self.command_ref,
            "test_ref": self.test_ref,
            "file_ref": self.file_ref,
            "source_commit": self.source_commit,
            "worktree_fingerprint": self.worktree_fingerprint,
            "artifact_ref": self.artifact_ref,
            "claim_ref": self.claim_ref,
            "review_ref": self.review_ref,
            "recording_state": self.recording_state,
            "lifecycle": self.lifecycle,
            "effective_lifecycle": self.effective_lifecycle,
            "source_commit_verified": self.source_commit_verified,
            "file_ref_verified": self.file_ref_verified,
            "test_ref_verified": self.test_ref_verified,
            "author": self.author,
            "seq": self.seq,
            "created_at": self.created_at.isoformat(),
        }


@dataclass(frozen=True)
class ViolationView:
    """Public violation row (T12)."""

    id: str
    project_id: str
    requirement_id: str
    invariant_id: str
    severity: str
    summary: str
    file_ref: str | None
    line_no: int | None
    status: str
    author: str
    created_at: datetime
    resolved_at: datetime | None
    resolved_by: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "requirement_id": self.requirement_id,
            "invariant_id": self.invariant_id,
            "severity": self.severity,
            "summary": self.summary,
            "file_ref": self.file_ref,
            "line_no": self.line_no,
            "status": self.status,
            "author": self.author,
            "created_at": self.created_at.isoformat(),
            "resolved_at": None if self.resolved_at is None else self.resolved_at.isoformat(),
            "resolved_by": self.resolved_by,
        }


@dataclass(frozen=True)
class CloseGateView:
    """Deterministic close-gate evaluation for one requirement (T12)."""

    requirement_id: str
    configured: bool
    passed: bool
    unmet: tuple[str, ...]
    ac_verified: int
    ac_total: int
    missing: tuple[dict[str, str], ...]
    stale: tuple[dict[str, str], ...]
    blocking: tuple[dict[str, str], ...]
    validation: str
    review: str

    def as_dict(self) -> dict[str, object]:
        return {
            "requirement_id": self.requirement_id,
            "configured": self.configured,
            "passed": self.passed,
            "unmet": list(self.unmet),
            "ac_verified": self.ac_verified,
            "ac_total": self.ac_total,
            "missing": list(self.missing),
            "stale": list(self.stale),
            "blocking": list(self.blocking),
            "validation": self.validation,
            "review": self.review,
        }

    def t11_payload(self) -> dict[str, object]:
        """Compact mapping consumed by T11 ``close_gate_from_payload``."""
        if not self.configured:
            return {
                "validation": "not-configured",
                "review": "not-configured",
            }
        missing_keys = [row["key"] for row in self.missing if row.get("key")]
        return {
            "ac_verified": self.ac_verified,
            "ac_total": self.ac_total,
            "missing_keys": missing_keys,
            "missing": list(self.missing),
            "stale": list(self.stale),
            "stale_count": len(self.stale),
            "validation": self.validation,
            "review": self.review,
            "blocking": list(self.blocking),
            "blocking_count": len(self.blocking),
        }


def _as_evidence(row: RequirementEvidence) -> EvidenceView:
    return EvidenceView(
        id=row.id,
        project_id=row.project_id,
        requirement_id=row.requirement_id,
        criterion_id=row.criterion_id,
        contract_revision_id=row.contract_revision_id,
        evidence_kind=row.evidence_kind,
        result=row.result,
        command_ref=row.command_ref,
        test_ref=row.test_ref,
        file_ref=row.file_ref,
        source_commit=row.source_commit,
        worktree_fingerprint=row.worktree_fingerprint,
        artifact_ref=row.artifact_ref,
        claim_ref=row.claim_ref,
        review_ref=row.review_ref,
        recording_state=row.recording_state,
        effective_lifecycle=row.recording_state,
        source_commit_verified=row.source_commit_verified,
        file_ref_verified=row.file_ref_verified,
        test_ref_verified=row.test_ref_verified,
        author=row.author,
        created_at=row.created_at,
        seq=row.seq,
    )


def _as_violation(row: RequirementViolation) -> ViolationView:
    return ViolationView(
        id=row.id,
        project_id=row.project_id,
        requirement_id=row.requirement_id,
        invariant_id=row.invariant_id,
        severity=row.severity,
        summary=row.summary,
        file_ref=row.file_ref,
        line_no=row.line_no,
        status=row.status,
        author=row.author,
        created_at=row.created_at,
        resolved_at=row.resolved_at,
        resolved_by=row.resolved_by,
    )


def _looks_like_log_or_secret(text: str) -> bool:
    lower = text.lower()
    if _SECRET_RE.search(text):
        return True
    if any(marker in text for marker in _DIFF_MARKERS):
        return True
    return any(marker in lower for marker in _LOG_MARKERS)


def _bound_optional(value: str | None, *, field: str, max_chars: int) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if len(cleaned) > max_chars or _looks_like_log_or_secret(cleaned):
        raise ValidationError(
            f"{field} looks like a log, diff, secret, or exceeds {max_chars} characters"
        )
    return cleaned


def _bound_author(author: str) -> str:
    cleaned = author.strip()
    if not cleaned:
        raise ValidationError("author must not be empty")
    if len(cleaned) > CONTRACT_AUTHOR_MAX_CHARS:
        raise ValidationError(f"author must be at most {CONTRACT_AUTHOR_MAX_CHARS} characters")
    return cleaned


def _reviewer_identity(author: str) -> str:
    """Normalize reviewer/implementer identity for independent-review comparison."""
    return author.strip().casefold()


def _bound_fingerprint(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip().lower()
    if not cleaned:
        return None
    if len(cleaned) > FINGERPRINT_MAX or not re.fullmatch(r"[0-9a-f]+", cleaned):
        raise ValidationError("worktree_fingerprint must be a hex digest")
    return cleaned


async def _git_bytes(root: str, *args: str) -> bytes | None:
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            root,
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError:
        return None
    out, _ = await proc.communicate()
    if proc.returncode != 0:
        return None
    return out


async def _git(root: str, *args: str) -> str | None:
    raw = await _git_bytes(root, *args)
    if raw is None:
        return None
    return raw.decode().rstrip("\n")


def _nul_paths(blob: bytes) -> list[bytes]:
    return [part for part in blob.split(b"\0") if part]


def _worktree_bytes(root: str, relpath: bytes) -> bytes:
    file_path = Path(root) / os.fsdecode(relpath)
    if file_path.is_file():
        return file_path.read_bytes()
    return b"<deleted>"


def _fingerprint_dirty_layers(
    *, index_listing: bytes, unstaged: bytes, untracked: bytes, root: str
) -> str:
    """Hash staged index blobs, unstaged worktree bytes, and untracked file bytes."""
    hasher = hashlib.sha256()
    hasher.update(b"index\0")
    hasher.update(index_listing)
    hasher.update(b"\0unstaged\0")
    for path in _nul_paths(unstaged):
        hasher.update(path)
        hasher.update(b"\0")
        hasher.update(_worktree_bytes(root, path))
        hasher.update(b"\0")
    hasher.update(b"untracked\0")
    for path in _nul_paths(untracked):
        hasher.update(path)
        hasher.update(b"\0")
        hasher.update(_worktree_bytes(root, path))
        hasher.update(b"\0")
    return hasher.hexdigest()


async def _repo_state(root: str) -> tuple[str | None, str | None]:
    """Return the current commit and a bounded clean/dirty fingerprint (INV-EVIDENCE-1)."""
    commit = await _git(root, "rev-parse", "HEAD")
    if commit is None or not _FULL_COMMIT_RE.fullmatch(commit.lower()):
        return None, None
    index_listing = await _git_bytes(root, "ls-files", "-s", "-z")
    staged = await _git_bytes(root, "diff", "--cached", "--name-only", "-z")
    unstaged = await _git_bytes(root, "diff", "--name-only", "-z")
    untracked = await _git_bytes(root, "ls-files", "-o", "--exclude-standard", "-z")
    if index_listing is None or staged is None or unstaged is None or untracked is None:
        return None, None
    if not staged and not unstaged and not untracked:
        return commit.lower(), _CLEAN_FINGERPRINT
    return commit.lower(), _fingerprint_dirty_layers(
        index_listing=index_listing, unstaged=unstaged, untracked=untracked, root=root
    )


async def _normalize_commit(root: str, value: str) -> str:
    """Accept 7-40 hex; store the full 40-character SHA. Short SHAs must expand."""
    cleaned = value.strip().lower()
    if not _COMMIT_RE.fullmatch(cleaned) or not (
        COMMIT_SHORT_MIN <= len(cleaned) <= COMMIT_FULL_LEN
    ):
        raise ValidationError("source_commit must be a git SHA (7-40 hex characters)")
    resolved = await _git(root, "rev-parse", "--verify", f"{cleaned}^{{commit}}")
    if resolved is not None:
        full = resolved.lower()
        if _FULL_COMMIT_RE.fullmatch(full):
            return full
    raise ValidationError("source_commit must resolve to an existing commit object")


def _normalize_repo_ref(value: str | None, *, field: str, max_chars: int) -> str | None:
    bounded = _bound_optional(value, field=field, max_chars=max_chars)
    if bounded is None:
        return None
    normalized = bounded.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    if normalized.startswith("/") or any(part in {"", ".."} for part in normalized.split("/")):
        raise ValidationError(f"{field} must be a repository-relative path")
    return normalized


def _bound_review_ref(value: str | None) -> str | None:
    bounded = _bound_optional(value, field="review_ref", max_chars=REVIEW_REF_MAX)
    if bounded is None:
        return None
    normalized = bounded.casefold()
    if not _REVIEW_REF_RE.fullmatch(normalized):
        raise ValidationError("review_ref must be criterion:<uuid> or invariant:<uuid>")
    return normalized


async def _commit_has_path(root: str, commit: str, path: str | None) -> bool | None:
    """Return whether a claimed commit path resolves specifically to a blob."""
    if path is None:
        return None
    object_type = await _git(root, "cat-file", "-t", f"{commit}:{path}")
    return object_type == "blob"


def _is_stale(
    evidence: EvidenceView,
    *,
    current_commit: str | None,
    current_fingerprint: str | None,
) -> bool:
    if current_commit is None or current_fingerprint is None:
        return True
    if evidence.source_commit.lower() != current_commit:
        return True
    stored = evidence.worktree_fingerprint
    if stored is None:
        return current_fingerprint != _CLEAN_FINGERPRINT
    return stored != current_fingerprint


async def _lock_requirement(
    session: AsyncSession, *, project_id: str, requirement_id: str, project_label: str
) -> None:
    """Row-lock the requirement after the project lock (T12)."""
    result = await session.execute(
        select(ContextEntry)
        .where(
            ContextEntry.id == requirement_id,
            ContextEntry.project_id == project_id,
            ContextEntry.section == "requirements",
        )
        .with_for_update()
    )
    if result.scalar_one_or_none() is None:
        raise ContractNotFoundError("requirement", requirement_id, project_label)


async def _latest_criterion_revision(
    session: AsyncSession, *, project_id: str, requirement_id: str, criterion_id: str
) -> RequirementContractRevision:
    result = await session.execute(
        select(RequirementContractRevision)
        .where(
            RequirementContractRevision.project_id == project_id,
            RequirementContractRevision.requirement_id == requirement_id,
            RequirementContractRevision.entity_kind == "criterion",
            RequirementContractRevision.entity_id == criterion_id,
        )
        .order_by(
            RequirementContractRevision.created_at.desc(),
            RequirementContractRevision.id.desc(),
        )
        .limit(1)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise ValidationError("criterion has no contract revision to bind")
    return row


async def _current_revision_ids(
    session: AsyncSession, *, project_id: str, requirement_id: str
) -> dict[str, str]:
    result = await session.execute(
        select(RequirementContractRevision)
        .where(
            RequirementContractRevision.project_id == project_id,
            RequirementContractRevision.requirement_id == requirement_id,
            RequirementContractRevision.entity_kind == "criterion",
        )
        .order_by(
            RequirementContractRevision.created_at.desc(),
            RequirementContractRevision.id.desc(),
        )
    )
    latest: dict[str, str] = {}
    for row in result.scalars().all():
        latest.setdefault(row.entity_id, row.id)
    return latest


async def record_evidence(
    session: AsyncSession,
    *,
    project: str,
    criterion_id: str,
    kind: str,
    result: str,
    source_commit: str,
    author: str = "agent",
    command_ref: str | None = None,
    test_ref: str | None = None,
    file_ref: str | None = None,
    worktree_fingerprint: str | None = None,
    artifact_ref: str | None = None,
    claim_ref: str | None = None,
    review_ref: str | None = None,
) -> EvidenceView:
    """Append bounded evidence with explicit recording state (INV-EVIDENCE-1..3)."""
    kind_key = kind.strip().lower()
    if kind_key not in EVIDENCE_KINDS:
        raise ValidationError(f"evidence kind must be one of {sorted(EVIDENCE_KINDS)}")
    result_key = result.strip().lower()
    if result_key not in EVIDENCE_RESULTS:
        raise ValidationError(f"result must be one of {sorted(EVIDENCE_RESULTS)}")
    criterion = await contracts.get_criterion(session, project=project, criterion_id=criterion_id)
    if kind_key != "review" and kind_key != criterion.evidence_kind:
        raise ValidationError(
            f"evidence kind {kind_key!r} does not match criterion kind {criterion.evidence_kind!r}"
        )
    invariant = await contracts.get_invariant(
        session, project=project, invariant_id=criterion.invariant_id
    )
    project_row = await resolve_project(session, project, for_update=True)
    await _lock_requirement(
        session,
        project_id=project_row.id,
        requirement_id=invariant.requirement_id,
        project_label=project_row.name,
    )
    revision = await _latest_criterion_revision(
        session,
        project_id=project_row.id,
        requirement_id=invariant.requirement_id,
        criterion_id=criterion.id,
    )
    current_commit, current_fp = await _repo_state(project_row.root_path)
    supplied_fp = _bound_fingerprint(worktree_fingerprint)
    dirty = current_fp is not None and current_fp != _CLEAN_FINGERPRINT
    if dirty and supplied_fp is None:
        raise ValidationError(
            f"dirty-worktree: worktree_fingerprint required (expected {current_fp})"
        )
    if dirty and supplied_fp != current_fp:
        raise ValidationError(
            f"dirty-worktree: worktree_fingerprint does not match (expected {current_fp})"
        )
    normalized_command_ref = _bound_optional(command_ref, field="command_ref", max_chars=REF_MAX)
    normalized_artifact_ref = _bound_optional(
        artifact_ref, field="artifact_ref", max_chars=ARTIFACT_MAX
    )
    normalized_claim_ref = _bound_optional(claim_ref, field="claim_ref", max_chars=CLAIM_REF_MAX)
    normalized_review_ref = _bound_review_ref(review_ref)
    normalized_file_ref = _normalize_repo_ref(file_ref, field="file_ref", max_chars=FILE_REF_MAX)
    normalized_test_ref = _normalize_repo_ref(test_ref, field="test_ref", max_chars=REF_MAX)
    normalized_commit = await _normalize_commit(project_row.root_path, source_commit)
    file_verified = await _commit_has_path(
        project_row.root_path, normalized_commit, normalized_file_ref
    )
    test_verified = await _commit_has_path(
        project_row.root_path, normalized_commit, normalized_test_ref
    )
    recording_lifecycle = (
        EVIDENCE_LIFECYCLE_PROVISIONAL
        if dirty or current_commit is None or normalized_commit != current_commit
        else EVIDENCE_LIFECYCLE_VERIFIED
    )
    row = RequirementEvidence(
        project_id=project_row.id,
        requirement_id=invariant.requirement_id,
        criterion_id=criterion.id,
        contract_revision_id=revision.id,
        evidence_kind=kind_key,
        result=result_key,
        command_ref=normalized_command_ref,
        test_ref=normalized_test_ref,
        file_ref=normalized_file_ref,
        source_commit=normalized_commit,
        worktree_fingerprint=supplied_fp,
        artifact_ref=normalized_artifact_ref,
        claim_ref=normalized_claim_ref,
        review_ref=normalized_review_ref,
        recording_state=recording_lifecycle,
        source_commit_verified=True,
        file_ref_verified=file_verified,
        test_ref_verified=test_verified,
        author=_bound_author(author),
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return _as_evidence(row)


async def list_evidence(
    session: AsyncSession,
    *,
    project: str,
    requirement_id: str | None = None,
    criterion_id: str | None = None,
) -> list[EvidenceView]:
    """List compact evidence for one requirement or criterion, oldest first."""
    if (requirement_id is None) == (criterion_id is None):
        raise ValidationError("pass exactly one of requirement_id or criterion_id")
    project_row = await resolve_project(session, project)
    stmt = select(RequirementEvidence).where(RequirementEvidence.project_id == project_row.id)
    if criterion_id is not None:
        await contracts.get_criterion(session, project=project, criterion_id=criterion_id)
        stmt = stmt.where(RequirementEvidence.criterion_id == criterion_id)
    else:
        assert requirement_id is not None
        await contracts.list_invariants(session, project=project, requirement_id=requirement_id)
        stmt = stmt.where(RequirementEvidence.requirement_id == requirement_id)
    stmt = stmt.order_by(RequirementEvidence.seq.asc())
    result = await session.execute(stmt)
    stored = [_as_evidence(row) for row in result.scalars().all()]
    current_commit, current_fp = await _repo_state(project_row.root_path)
    current_revisions: dict[str, str] = {}
    if requirement_id is not None:
        current_revisions = await _current_revision_ids(
            session, project_id=project_row.id, requirement_id=requirement_id
        )
    elif stored:
        current_revisions = await _current_revision_ids(
            session, project_id=project_row.id, requirement_id=stored[0].requirement_id
        )
    latest_by_slot: dict[tuple[str, str], int] = {}
    for row in stored:
        if row.contract_revision_id == current_revisions.get(row.criterion_id):
            latest_by_slot[(row.criterion_id, row.evidence_kind)] = row.seq
    derived: list[EvidenceView] = []
    for row in stored:
        lifecycle = row.recording_state
        revision_stale = row.contract_revision_id != current_revisions.get(row.criterion_id)
        provenance_stale = _is_stale(
            row, current_commit=current_commit, current_fingerprint=current_fp
        )
        if revision_stale or provenance_stale:
            lifecycle = EVIDENCE_LIFECYCLE_STALE
        elif latest_by_slot.get((row.criterion_id, row.evidence_kind)) != row.seq:
            lifecycle = EVIDENCE_LIFECYCLE_SUPERSEDED
        derived.append(replace(row, effective_lifecycle=lifecycle))
    return derived


async def get_requirement_evidence(
    session: AsyncSession, *, project: str, requirement_id: str
) -> dict[str, object]:
    """Drill-down evidence + violations for one requirement (T11 seam name)."""
    project_row = await resolve_project(session, project)
    gate = await evaluate_close_gate(session, project=project, requirement_id=requirement_id)
    evidence = await list_evidence(session, project=project, requirement_id=requirement_id)
    violations = await _list_violations(
        session, project_id=project_row.id, requirement_id=requirement_id
    )
    return {
        "requirement_id": requirement_id,
        "evidence": [row.as_dict() for row in evidence],
        "violations": [row.as_dict() for row in violations],
        "close_gate": gate.as_dict(),
    }


async def add_violation(
    session: AsyncSession,
    *,
    project: str,
    invariant_id: str,
    summary: str,
    severity: str = VIOLATION_BLOCKING,
    author: str = "agent",
    file_ref: str | None = None,
    line_no: int | None = None,
) -> ViolationView:
    """Record a review violation against one invariant (T12)."""
    sev = severity.strip().lower()
    if sev not in VIOLATION_SEVERITIES:
        raise ValidationError(f"severity must be one of {sorted(VIOLATION_SEVERITIES)}")
    cleaned = summary.strip()
    if not cleaned or len(cleaned) > SUMMARY_MAX or _looks_like_log_or_secret(cleaned):
        raise ValidationError(
            f"summary looks like a log, diff, secret, or exceeds {SUMMARY_MAX} characters"
        )
    if line_no is not None and line_no < 1:
        raise ValidationError("line_no must be >= 1")
    invariant = await contracts.get_invariant(session, project=project, invariant_id=invariant_id)
    project_row = await resolve_project(session, project, for_update=True)
    await _lock_requirement(
        session,
        project_id=project_row.id,
        requirement_id=invariant.requirement_id,
        project_label=project_row.name,
    )
    row = RequirementViolation(
        project_id=project_row.id,
        requirement_id=invariant.requirement_id,
        invariant_id=invariant.id,
        severity=sev,
        summary=cleaned,
        file_ref=_bound_optional(file_ref, field="file_ref", max_chars=FILE_REF_MAX),
        line_no=line_no,
        status=VIOLATION_OPEN,
        author=_bound_author(author),
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return _as_violation(row)


async def resolve_violation(
    session: AsyncSession,
    *,
    project: str,
    violation_id: str,
    author: str = "agent",
) -> ViolationView:
    """Mark a violation resolved without deleting history (T12)."""
    resolver = _bound_author(author)
    project_row = await resolve_project(session, project, for_update=True)
    result = await session.execute(
        select(RequirementViolation).where(
            RequirementViolation.id == violation_id,
            RequirementViolation.project_id == project_row.id,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise ContractNotFoundError("violation", violation_id, project_row.name)
    await _lock_requirement(
        session,
        project_id=project_row.id,
        requirement_id=row.requirement_id,
        project_label=project_row.name,
    )
    if row.status == VIOLATION_RESOLVED:
        return _as_violation(row)
    row.status = VIOLATION_RESOLVED
    row.resolved_at = datetime.now(tz=UTC)
    row.resolved_by = resolver
    row.updated_at = row.resolved_at
    await session.flush()
    return _as_violation(row)


async def _list_violations(
    session: AsyncSession, *, project_id: str, requirement_id: str
) -> list[ViolationView]:
    result = await session.execute(
        select(RequirementViolation)
        .where(
            RequirementViolation.project_id == project_id,
            RequirementViolation.requirement_id == requirement_id,
        )
        .order_by(RequirementViolation.created_at.asc(), RequirementViolation.id.asc())
    )
    return [_as_violation(row) for row in result.scalars().all()]


def _latest(rows: Sequence[EvidenceView]) -> EvidenceView | None:
    if not rows:
        return None
    return max(rows, key=lambda row: row.seq)


def _review_is_scoped(
    review: EvidenceView, criterion: CriterionView, invariant: InvariantView
) -> bool:
    """Require an explicit invariant/criterion claim scope (INV-EVIDENCE-4)."""
    return review.review_ref in {
        f"criterion:{criterion.id}",
        f"invariant:{invariant.id}",
    }


def _link(criterion: CriterionView, invariant: InvariantView) -> dict[str, str]:
    return {
        "id": criterion.id,
        "key": criterion.key,
        "invariant_id": invariant.id,
        "invariant_key": invariant.key,
    }


def _not_configured(requirement_id: str) -> CloseGateView:
    return CloseGateView(
        requirement_id=requirement_id,
        configured=False,
        passed=True,
        unmet=(),
        ac_verified=0,
        ac_total=0,
        missing=(),
        stale=(),
        blocking=(),
        validation="not-configured",
        review="not-configured",
    )


async def evaluate_close_gate(
    session: AsyncSession, *, project: str, requirement_id: str
) -> CloseGateView:
    """Compute close-gate state from required criteria, evidence, and violations."""
    project_row = await resolve_project(session, project, for_update=True)
    invariants = await contracts.list_invariants(
        session, project=project, requirement_id=requirement_id, include_deleted=True
    )
    await _lock_requirement(
        session,
        project_id=project_row.id,
        requirement_id=requirement_id,
        project_label=project_row.name,
    )
    criteria = await contracts.list_criteria(
        session, project=project, requirement_id=requirement_id
    )
    violations = await _list_violations(
        session, project_id=project_row.id, requirement_id=requirement_id
    )
    inv_by_id = {row.id: row for row in invariants}
    blocking = [
        {
            "key": (
                inv_by_id[row.invariant_id].key
                if row.invariant_id in inv_by_id
                else row.invariant_id
            ),
            "summary": row.summary,
        }
        for row in violations
        if row.status == VIOLATION_OPEN and row.severity == VIOLATION_BLOCKING
    ]
    active_ids = {row.id for row in invariants if row.status != STATUS_DELETED}
    required = [row for row in criteria if row.required and row.invariant_id in active_ids]
    if not criteria and not blocking:
        return _not_configured(requirement_id)

    evidence_rows = (
        await list_evidence(session, project=project, requirement_id=requirement_id)
        if required
        else []
    )
    by_criterion: dict[str, list[EvidenceView]] = {}
    for row in evidence_rows:
        by_criterion.setdefault(row.criterion_id, []).append(row)
    current_revs = await _current_revision_ids(
        session, project_id=project_row.id, requirement_id=requirement_id
    )
    missing: list[dict[str, str]] = []
    stale: list[dict[str, str]] = []
    unmet: list[str] = []
    verified = 0
    for criterion in required:
        invariant = inv_by_id[criterion.invariant_id]
        link = _link(criterion, invariant)
        rows = by_criterion.get(criterion.id, [])
        current_rev = current_revs.get(criterion.id)
        current_rows = [row for row in rows if row.contract_revision_id == current_rev]
        implementation = [
            row for row in current_rows if row.evidence_kind == criterion.evidence_kind
        ]
        reviews = [row for row in current_rows if row.evidence_kind == "review"]
        latest_impl = _latest(implementation)
        if latest_impl is None:
            older_pass = any(
                row.evidence_kind == criterion.evidence_kind
                and row.result == EVIDENCE_RESULT_PASSED
                for row in rows
            )
            if older_pass:
                stale.append(link)
                unmet.append(f"stale {criterion.key}")
            else:
                missing.append(link)
                unmet.append(f"missing {criterion.key}")
            continue
        if latest_impl.result != EVIDENCE_RESULT_PASSED:
            missing.append(link)
            unmet.append(f"failed {criterion.key}")
            continue
        if latest_impl.lifecycle != EVIDENCE_LIFECYCLE_VERIFIED:
            stale.append(link)
            unmet.append(f"{latest_impl.lifecycle} {criterion.key}")
            continue
        review_required = (
            criterion.independent_review == INDEPENDENT_REVIEW_REQUIRED or invariant.risk == "high"
        )
        if review_required:
            latest_review = _latest(reviews)
            if latest_review is None:
                missing.append(link)
                unmet.append(f"independent review missing for {criterion.key}")
                continue
            if latest_review.result != EVIDENCE_RESULT_PASSED:
                missing.append(link)
                unmet.append(f"independent review of {criterion.key} is {latest_review.result}")
                continue
            if latest_review.lifecycle != EVIDENCE_LIFECYCLE_VERIFIED:
                stale.append(link)
                unmet.append(f"{latest_review.lifecycle} independent review for {criterion.key}")
                continue
            if _reviewer_identity(latest_review.author) == _reviewer_identity(latest_impl.author):
                missing.append(link)
                unmet.append(f"independent review of {criterion.key} cannot be self-authored")
                continue
            if not _review_is_scoped(latest_review, criterion, invariant):
                missing.append(link)
                unmet.append(f"independent review scope missing for {criterion.key}")
                continue
        verified += 1

    for item in blocking:
        unmet.append(f"blocking {item['key']}: {item['summary']}")

    passed = not unmet
    validation = "stale" if stale else "ok"
    review_failed = bool(blocking) or any("independent review" in item for item in unmet)
    review = "failed" if review_failed else "passed"
    return CloseGateView(
        requirement_id=requirement_id,
        configured=True,
        passed=passed,
        unmet=tuple(unmet),
        ac_verified=verified,
        ac_total=len(required),
        missing=tuple(missing[:8]),
        stale=tuple(stale[:8]),
        blocking=tuple(blocking[:8]),
        validation=validation,
        review=review,
    )


async def summarize_close_gate(
    session: AsyncSession, *, project: str, requirement_ids: Sequence[str]
) -> Mapping[str, object]:
    """T11 seam: compact close-gate payload for selected requirements."""
    if not requirement_ids:
        return {"validation": "not-configured", "review": "not-configured"}
    gates = [
        await evaluate_close_gate(session, project=project, requirement_id=rid)
        for rid in requirement_ids
        if rid.strip()
    ]
    configured = [gate for gate in gates if gate.configured]
    if not configured:
        return {"validation": "not-configured", "review": "not-configured"}
    missing: list[dict[str, str]] = []
    stale: list[dict[str, str]] = []
    blocking: list[dict[str, str]] = []
    lifecycle_counts = {
        EVIDENCE_LIFECYCLE_VERIFIED: 0,
        EVIDENCE_LIFECYCLE_PROVISIONAL: 0,
        EVIDENCE_LIFECYCLE_STALE: 0,
        EVIDENCE_LIFECYCLE_SUPERSEDED: 0,
    }
    warning_codes: set[str] = set()
    violation_count = 0
    from pcs.requirements import compliance

    for requirement_id in requirement_ids:
        rows = await list_evidence(session, project=project, requirement_id=requirement_id)
        for row in rows:
            lifecycle_counts[row.lifecycle] += 1
        criteria = await contracts.list_criteria(
            session, project=project, requirement_id=requirement_id
        )
        invariants = await contracts.list_invariants(
            session, project=project, requirement_id=requirement_id, include_deleted=True
        )
        warning_codes.update(
            compliance._warning_codes(criteria, {row.id: row for row in invariants}, rows)
        )
        project_row = await resolve_project(session, project)
        violation_count += len(
            await _list_violations(
                session, project_id=project_row.id, requirement_id=requirement_id
            )
        )
    for gate in configured:
        missing.extend(gate.missing)
        stale.extend(gate.stale)
        blocking.extend(gate.blocking)
    ac_verified = sum(gate.ac_verified for gate in configured)
    ac_total = sum(gate.ac_total for gate in configured)
    validation = "stale" if stale else "ok"
    review = "failed" if any(gate.review == "failed" for gate in configured) else "passed"
    missing_keys = [row["key"] for row in missing if row.get("key")]
    return {
        "ac_verified": ac_verified,
        "ac_total": ac_total,
        "missing_keys": missing_keys[:8],
        "missing": missing[:8],
        "stale": stale[:8],
        "stale_count": len(stale),
        "validation": validation,
        "review": review,
        "blocking": blocking[:8],
        "blocking_count": len(blocking),
        "evidence_lifecycle": lifecycle_counts,
        "warning_count": min(len(warning_codes), compliance.MAX_WARNING_CODES),
        "violation_count": violation_count,
    }


async def assert_close_gate_allows_done(
    session: AsyncSession, *, project: str, requirement_id: str
) -> None:
    """Reject ``done`` when the close gate is not satisfied (T12)."""
    gate = await evaluate_close_gate(session, project=project, requirement_id=requirement_id)
    if not gate.passed:
        raise CloseGateError(gate.unmet)
