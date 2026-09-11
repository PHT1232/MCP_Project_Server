"""Compact requirement-contract retrieval for agents (T11).

Progressive disclosure: ``get_requirement_contract`` is the verbatim drill-down;
``get_task_contract`` / ``prepare_task`` emit only a ≤500-token summary. T12
close-gate data is optional — missing evidence is ``review: not-configured``,
never an error. No MCP/HTTP imports (AGENTS.md).
"""

from __future__ import annotations

import importlib
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final, cast

from sqlalchemy.ext.asyncio import AsyncSession

from pcs.context.assembly import estimate_tokens
from pcs.context.service import get_entry, get_section
from pcs.context.types import (
    CHARS_PER_TOKEN,
    INVARIANT_KIND_FORBIDDEN_PATH,
    REQ_BLOCKED,
    REQ_DONE,
    REQ_IN_PROGRESS,
    REQ_NOT_STARTED,
    RISK_HIGH,
    RISK_LOW,
    RISK_MEDIUM,
    SECTION_FOCUS,
    SECTION_REQUIREMENTS,
    ContractNotFoundError,
    EntryView,
    InvariantView,
    ValidationError,
)
from pcs.requirements import contracts

__all__ = [
    "CONTRACT_TOKEN_CAP",
    "INCLUDE_BOTH",
    "INCLUDE_CRITERIA",
    "INCLUDE_INVARIANTS",
    "CloseGateSummary",
    "TaskContractView",
    "close_gate_from_payload",
    "get_requirement_contract",
    "get_task_contract",
]

# Hard compact budget inside prepare_task's existing total (CONTRACT-COMPLIANCE-PLAN).
CONTRACT_TOKEN_CAP: Final = 500
MAX_COMPACT_REQUIREMENTS: Final = 3
DRILL_DOWN_TOOLS: Final[tuple[str, str]] = (
    "get_requirement_contract",
    "get_requirement_evidence",
)
DRILL_DOWN_LINE: Final = "Details: call get_requirement_contract / get_requirement_evidence"

INCLUDE_INVARIANTS: Final = "invariants"
INCLUDE_CRITERIA: Final = "criteria"
INCLUDE_BOTH: Final = "both"
INCLUDE_CHOICES: Final[frozenset[str]] = frozenset(
    {INCLUDE_INVARIANTS, INCLUDE_CRITERIA, INCLUDE_BOTH}
)

_RISK_RANK: Final[dict[str, int]] = {RISK_HIGH: 0, RISK_MEDIUM: 1, RISK_LOW: 2}
_STATUS_BOOST: Final[dict[str, int]] = {
    REQ_IN_PROGRESS: 10,
    REQ_BLOCKED: 8,
    REQ_NOT_STARTED: 4,
    REQ_DONE: 0,
}
_WORD_RE = re.compile(r"[A-Za-z0-9_]{3,}")
_PATHISH_RE = re.compile(r"[\w./-]+\.[A-Za-z0-9]+|[\w-]+/[\w./-]+")
_DIFF_MARKERS: Final[tuple[str, ...]] = ("diff --git", "\n+++ ", "\n--- ", "\n@@ ")
_LOG_MARKERS: Final[tuple[str, ...]] = ("stdout", "stderr", "traceback (most recent")


@dataclass(frozen=True)
class CloseGateSummary:
    """Compact close-gate facts. T12 may fill these; T11 never invents evidence."""

    configured: bool = False
    ac_verified: int | None = None
    ac_total: int | None = None
    missing_keys: tuple[str, ...] = ()
    validation: str = "not-configured"
    review: str = "not-configured"
    blocking_count: int = 0
    blocking: tuple[tuple[str, str], ...] = ()  # (key, sanitized summary)
    stale_count: int = 0

    @classmethod
    def unconfigured(cls) -> CloseGateSummary:
        return cls()


@dataclass(frozen=True)
class TaskContractView:
    """Budgeted compact contract + close-gate pack (T11)."""

    text: str
    token_estimate: int
    token_budget: int
    requirement_ids: tuple[str, ...]
    req_keys: tuple[str, ...]
    truncated: bool
    omitted_invariants: int
    omitted_requirements: int
    review: str
    drill_down: tuple[str, ...] = DRILL_DOWN_TOOLS

    def as_dict(self) -> dict[str, object]:
        """JSON-ready payload for MCP (NFR6 wrappers add audit, not this dict)."""
        return {
            "text": self.text,
            "token_estimate": self.token_estimate,
            "token_budget": self.token_budget,
            "requirement_ids": list(self.requirement_ids),
            "req_keys": list(self.req_keys),
            "truncated": self.truncated,
            "omitted": {
                "invariants": self.omitted_invariants,
                "requirements": self.omitted_requirements,
            },
            "review": self.review,
            "drill_down": list(self.drill_down),
        }


@dataclass(frozen=True)
class _RankedStatement:
    """One compact line candidate in deterministic selection order."""

    rank: tuple[int | str, ...]
    kind: str  # "violation" | "must_not" | "must"
    line: str


@dataclass(frozen=True)
class _ReqRef:
    """Requirement fields needed for compact selection (T11)."""

    entry_id: str
    req_key: str
    title: str
    status: str
    linked_files: tuple[str, ...]


def _ref_from_entry(entry: EntryView) -> _ReqRef:
    return _ReqRef(
        entry_id=entry.id,
        req_key=entry.req_key or "",
        title=entry.headline,
        status=entry.requirement_status or REQ_NOT_STARTED,
        linked_files=entry.linked_files,
    )


def _clamp_contract_budget(max_tokens: int | None) -> int:
    if max_tokens is None:
        return CONTRACT_TOKEN_CAP
    return max(1, min(int(max_tokens), CONTRACT_TOKEN_CAP))


def _fit(text: str, max_tokens: int) -> str:
    if max_tokens <= 0:
        return ""
    if estimate_tokens(text) <= max_tokens:
        return text
    max_chars = max_tokens * CHARS_PER_TOKEN
    if max_chars <= 1:
        return ""
    return text[: max_chars - 1].rstrip() + "…"


def _looks_like_log_or_diff(text: str) -> bool:
    lower = text.lower()
    if any(marker in text for marker in _DIFF_MARKERS):
        return True
    return any(marker in lower for marker in _LOG_MARKERS)


def _sanitize_summary(text: str, *, max_chars: int = 120) -> str:
    cleaned = " ".join(text.split())
    if _looks_like_log_or_diff(cleaned):
        return "(omitted)"
    if len(cleaned) > max_chars:
        return cleaned[: max_chars - 1].rstrip() + "…"
    return cleaned


def _as_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _as_str(value: object) -> str | None:
    if isinstance(value, str):
        return value
    return None


def close_gate_from_payload(payload: object) -> CloseGateSummary:
    """Map a T12 payload onto compact fields; unknown/raw keys are dropped.

    Accepted keys: ``ac_verified``, ``ac_total``, ``missing_keys``,
    ``validation`` (ok|stale|not-configured), ``review`` (passed|failed|
    not-configured), ``blocking`` (list of ``{key, summary}``), ``stale_count``.
    Stdout, diffs, and other evidence bodies are never copied.
    """
    if not isinstance(payload, Mapping):
        return CloseGateSummary.unconfigured()
    data = cast(Mapping[str, object], payload)
    ac_verified = _as_int(data.get("ac_verified"))
    ac_total = _as_int(data.get("ac_total"))
    missing_raw = data.get("missing_keys")
    missing: list[str] = []
    if isinstance(missing_raw, (list, tuple)):
        for item in missing_raw:
            if isinstance(item, str) and item.strip():
                missing.append(item.strip()[:40])
            if len(missing) >= 8:
                break
    validation = _as_str(data.get("validation")) or "not-configured"
    if validation not in {"ok", "stale", "not-configured"}:
        validation = "not-configured"
    review = _as_str(data.get("review")) or "not-configured"
    if review not in {"passed", "failed", "not-configured"}:
        review = "not-configured"
    blocking_raw = data.get("blocking")
    blocking: list[tuple[str, str]] = []
    if isinstance(blocking_raw, (list, tuple)):
        for item in blocking_raw:
            if not isinstance(item, Mapping):
                continue
            row = cast(Mapping[str, object], item)
            key = _as_str(row.get("key")) or "INV"
            summary = _sanitize_summary(_as_str(row.get("summary")) or "")
            if summary:
                blocking.append((key, summary))
            if len(blocking) >= 8:
                break
    stale_count = _as_int(data.get("stale_count")) or 0
    blocking_count = _as_int(data.get("blocking_count"))
    if blocking_count is None:
        blocking_count = len(blocking)
    return CloseGateSummary(
        configured=True,
        ac_verified=ac_verified,
        ac_total=ac_total,
        missing_keys=tuple(missing),
        validation=validation,
        review=review,
        blocking_count=blocking_count,
        blocking=tuple(blocking),
        stale_count=stale_count,
    )


async def _load_close_gate(
    session: AsyncSession, *, project: str, requirement_ids: Sequence[str]
) -> CloseGateSummary:
    try:
        evidence_mod = importlib.import_module("pcs.requirements.evidence")
    except ImportError:
        return CloseGateSummary.unconfigured()
    loader = getattr(evidence_mod, "summarize_close_gate", None)
    if not callable(loader):
        return CloseGateSummary.unconfigured()
    typed = cast(Callable[..., Awaitable[object]], loader)
    raw = await typed(session, project=project, requirement_ids=list(requirement_ids))
    return close_gate_from_payload(raw)


def _format_close_gate(gate: CloseGateSummary) -> str:
    if not gate.configured:
        return "\n".join(
            (
                "CLOSE GATE",
                "AC: not-configured",
                "Validation: not-configured",
                "Review: not-configured",
                DRILL_DOWN_LINE,
            )
        )
    if gate.ac_verified is not None and gate.ac_total is not None:
        ac_line = f"AC: {gate.ac_verified}/{gate.ac_total} verified"
        if gate.missing_keys:
            shown = ", ".join(gate.missing_keys[:5])
            extra = len(gate.missing_keys) - 5
            ac_line += f"; missing {shown}"
            if extra > 0:
                ac_line += f" (+{extra} more)"
    else:
        ac_line = "AC: not-configured"
    validation = gate.validation
    if gate.stale_count and validation == "ok":
        validation = "stale"
    if gate.review == "failed" and gate.blocking_count:
        review_line = f"Review: failed ({gate.blocking_count} blocking violation"
        review_line += "s)" if gate.blocking_count != 1 else ")"
    else:
        review_line = f"Review: {gate.review}"
    return "\n".join(
        (
            "CLOSE GATE",
            ac_line,
            f"Validation: {validation}",
            review_line,
            DRILL_DOWN_LINE,
        )
    )


def _tokens(*parts: str) -> list[str]:
    blob = " ".join(parts)
    return [m.group(0).lower() for m in _WORD_RE.finditer(blob)]


def _paths_from_text(*blobs: str) -> set[str]:
    found: set[str] = set()
    for blob in blobs:
        for match in _PATHISH_RE.finditer(blob):
            found.add(match.group(0).lower())
    return found


def _path_overlap(linked: Sequence[str], candidates: Sequence[str]) -> bool:
    if not linked or not candidates:
        return False
    left = [p.lower().lstrip("./") for p in linked]
    right = [p.lower().lstrip("./") for p in candidates]
    for a in left:
        for b in right:
            if a == b or a.endswith("/" + b) or b.endswith("/" + a) or a in b or b in a:
                return True
    return False


def _score_requirement(
    req: _ReqRef,
    *,
    task: str,
    focus_text: str,
    focus_paths: Sequence[str],
    ranked_paths: Sequence[str],
) -> tuple[int, int]:
    """Return ``(match_score, status_boost)``. Match is path/focus/task overlap."""
    match = 0
    task_l = task.lower()
    if req.linked_files:
        if _path_overlap(req.linked_files, ranked_paths):
            match += 100
        if _path_overlap(req.linked_files, focus_paths):
            match += 70
        if any(f.lower() in task_l for f in req.linked_files):
            match += 80
    if req.req_key and req.req_key.lower() in task_l:
        match += 50
    title_l = req.title.lower()
    task_tokens = set(_tokens(task))
    if title_l and title_l in task_l:
        match += 40
    elif task_tokens and set(_tokens(req.title)) & task_tokens:
        match += 25
    if focus_text and set(_tokens(req.title)) & set(_tokens(focus_text)):
        match += 15
    status = _STATUS_BOOST.get(req.status, 0)
    if req.status == REQ_DONE:
        status -= 20
    return match, status


async def _select_requirements(
    session: AsyncSession,
    *,
    project: str,
    task: str,
    requirement_ids: Sequence[str] | None,
    ranked_paths: Sequence[str],
) -> tuple[list[_ReqRef], int]:
    if requirement_ids:
        selected: list[_ReqRef] = []
        for raw in requirement_ids:
            rid = raw.strip()
            if not rid:
                continue
            entry = await get_entry(session, project=project, entry_id=rid)
            if entry.section != SECTION_REQUIREMENTS:
                raise ContractNotFoundError("requirement", rid, project)
            selected.append(_ref_from_entry(entry))
        omitted = max(0, len(selected) - MAX_COMPACT_REQUIREMENTS)
        return selected[:MAX_COMPACT_REQUIREMENTS], omitted

    catalog = [
        _ref_from_entry(entry)
        for entry in await get_section(session, project=project, section=SECTION_REQUIREMENTS)
    ]
    focus_entries = await get_section(session, project=project, section=SECTION_FOCUS)
    focus_text = " ".join(f"{e.headline} {e.detail}" for e in focus_entries)
    focus_paths = [
        *_paths_from_text(task, focus_text),
        *[p for e in focus_entries for p in e.linked_files],
    ]
    scored: list[tuple[int, int, str, _ReqRef]] = []
    for req in catalog:
        if req.status == REQ_DONE:
            continue
        match, status = _score_requirement(
            req,
            task=task,
            focus_text=focus_text,
            focus_paths=focus_paths,
            ranked_paths=ranked_paths,
        )
        scored.append((match, status, req.req_key, req))

    with_contracts: list[tuple[int, int, str, _ReqRef]] = []
    for match, status, key, req in scored:
        invs = await contracts.list_invariants(
            session, project=project, requirement_id=req.entry_id
        )
        if not invs:
            continue
        with_contracts.append((match, status, key, req))

    if not with_contracts:
        return [], 0

    with_contracts.sort(key=lambda row: (-row[0], -row[1], row[2], row[3].entry_id))
    relevant = [row for row in with_contracts if row[0] > 0]
    pool = relevant or with_contracts
    omitted = max(0, len(pool) - MAX_COMPACT_REQUIREMENTS)
    return [row[3] for row in pool[:MAX_COMPACT_REQUIREMENTS]], omitted


def _statement_rank(
    inv: InvariantView,
    *,
    blocking_keys: set[str],
    missing_for_invariant: bool,
    stale: bool,
) -> tuple[int | str, ...]:
    """Deterministic order: blocking → forbidden → high-risk → missing AC → stale."""
    blocking = 0 if (inv.key in blocking_keys or inv.id in blocking_keys) else 1
    forbidden = 0 if inv.kind == INVARIANT_KIND_FORBIDDEN_PATH else 1
    risk = _RISK_RANK.get(inv.risk, 9)
    missing = 0 if missing_for_invariant else 1
    stale_r = 0 if stale else 1
    return (blocking, forbidden, risk, missing, stale_r, inv.sort_order, inv.key)


def _compact_line(inv: InvariantView) -> str:
    statement = " ".join(inv.statement.split())
    return f"{inv.key}: {statement}"


def _rank_statements(
    invariants: Sequence[InvariantView],
    gate: CloseGateSummary,
) -> list[_RankedStatement]:
    blocking_keys = {key for key, _ in gate.blocking}
    missing_keys = set(gate.missing_keys)
    stale = bool(gate.stale_count) or gate.validation == "stale"
    ranked: list[_RankedStatement] = []
    for key, summary in gate.blocking:
        ranked.append(
            _RankedStatement(
                rank=(0, 0, 0, 0, 0, 0, key),
                kind="violation",
                line=f"{key}: {summary}",
            )
        )
    for inv in invariants:
        line = _compact_line(inv)
        kind = "must_not" if inv.kind == INVARIANT_KIND_FORBIDDEN_PATH else "must"
        ranked.append(
            _RankedStatement(
                rank=_statement_rank(
                    inv,
                    blocking_keys=blocking_keys,
                    missing_for_invariant=any(
                        mk.startswith(inv.key) or mk == inv.key for mk in missing_keys
                    ),
                    stale=stale,
                ),
                kind=kind,
                line=line,
            )
        )
    ranked.sort(key=lambda item: (item.rank, item.kind, item.line))
    return ranked


def _join_clause(label: str, parts: Sequence[str]) -> str | None:
    if not parts:
        return None
    return f"{label}: " + "; ".join(parts)


def _render_compact(
    ranked: Sequence[_RankedStatement],
    gate: CloseGateSummary,
    *,
    max_tokens: int,
) -> tuple[str, int, bool]:
    close_block = _format_close_gate(gate)
    # Always keep the close-gate; shrink contract body first.
    close_tokens = estimate_tokens(close_block)
    body_budget = max(0, max_tokens - close_tokens - estimate_tokens("CONTRACT\n\n"))

    must: list[str] = []
    must_not: list[str] = []
    violations: list[str] = []
    omitted = 0
    used = 0

    def _try_add(target: list[str], line: str) -> bool:
        nonlocal used, omitted
        first_item = not (must or must_not or violations)
        clause_kind = (
            "Violations" if target is violations else "Must not" if target is must_not else "Must"
        )
        probe_full = [*target, line]
        extra_full = estimate_tokens(_join_clause(clause_kind, probe_full) or "") - estimate_tokens(
            _join_clause(clause_kind, target) or ""
        )
        if used + extra_full <= body_budget:
            target.append(line)
            used += extra_full
            return True
        if not first_item:
            omitted += 1
            return False
        fitted = _fit(line, max(1, body_budget))
        extra = estimate_tokens(_join_clause(clause_kind, [fitted]) or "")
        if not fitted or extra > body_budget:
            omitted += 1
            return False
        target.append(fitted)
        used += extra
        return True

    for item in ranked:
        if item.kind == "must_not":
            bucket = must_not
        elif item.kind == "violation":
            bucket = violations
        else:
            bucket = must
        _try_add(bucket, item.line)

    overflow = ""
    if omitted:
        overflow = f"+{omitted} more; call get_requirement_contract / get_requirement_evidence"
        if used + estimate_tokens(overflow) > body_budget and (must or must_not or violations):
            # Drop the last added line to make room for the overflow pointer.
            for bucket in (must, must_not, violations):
                if bucket:
                    bucket.pop()
                    omitted += 1
                    overflow = (
                        f"+{omitted} more; call get_requirement_contract / get_requirement_evidence"
                    )
                    break

    contract_lines = ["CONTRACT"]
    for clause in (
        _join_clause("Violations", violations),
        _join_clause("Must", must),
        _join_clause("Must not", must_not),
    ):
        if clause:
            contract_lines.append(clause)
    if overflow:
        contract_lines.append(overflow)
    text = "\n".join(contract_lines) + "\n\n" + close_block
    if estimate_tokens(text) > max_tokens:
        text = _fit(text, max_tokens)
    return text, omitted, omitted > 0 or estimate_tokens(text) >= max_tokens


async def get_requirement_contract(
    session: AsyncSession,
    *,
    project: str,
    requirement_id: str,
    include: str = INCLUDE_BOTH,
) -> dict[str, object]:
    """Verbatim invariant/criterion drill-down for one requirement (T11).

    ``include`` selects ``invariants``, ``criteria``, or ``both``. Hidden parents
    yield empty collections, matching T10 active-read rules. Never returns
    evidence logs or diffs.
    """
    choice = include.strip().lower() if include.strip() else INCLUDE_BOTH
    if choice not in INCLUDE_CHOICES:
        raise ValidationError(f"include must be one of {sorted(INCLUDE_CHOICES)}; got {include!r}")
    entry = await get_entry(session, project=project, entry_id=requirement_id)
    payload: dict[str, object] = {
        "requirement_id": entry.id,
        "req_key": entry.req_key,
        "headline": entry.headline,
        "include": choice,
    }
    if choice in {INCLUDE_INVARIANTS, INCLUDE_BOTH}:
        invs = await contracts.list_invariants(
            session, project=project, requirement_id=requirement_id
        )
        payload["invariants"] = [row.as_dict() for row in invs]
    if choice in {INCLUDE_CRITERIA, INCLUDE_BOTH}:
        criteria = await contracts.list_criteria(
            session, project=project, requirement_id=requirement_id
        )
        payload["criteria"] = [row.as_dict() for row in criteria]
    return payload


async def get_task_contract(
    session: AsyncSession,
    *,
    project: str,
    task: str,
    requirement_ids: Sequence[str] | None = None,
    max_tokens: int | None = None,
    ranked_paths: Sequence[str] | None = None,
) -> TaskContractView:
    """Relevant active contract statements + compact close-gate (T11).

    Selection: explicit IDs first, then linked files / current focus / retrieval
    paths. Normal output is 1-3 requirements. Unused budget is not padded.
    Empty/unconfigured contracts return an empty string (0 tokens) so
    ``prepare_task`` keeps its current split.
    """
    if not task.strip():
        raise ValueError("task description must not be empty")
    budget = _clamp_contract_budget(max_tokens)
    paths = list(ranked_paths) if ranked_paths is not None else []
    if ranked_paths is None:
        from pcs.index.hybrid import gather_relevant

        hybrid = await gather_relevant(
            session, project=project, task=task, scope="project", limit=40
        )
        paths = [hit.hit.path for hit in hybrid.ranked]

    selected, omitted_reqs = await _select_requirements(
        session,
        project=project,
        task=task,
        requirement_ids=requirement_ids,
        ranked_paths=paths,
    )
    if not selected:
        return TaskContractView(
            text="",
            token_estimate=0,
            token_budget=budget,
            requirement_ids=(),
            req_keys=(),
            truncated=False,
            omitted_invariants=0,
            omitted_requirements=0,
            review="not-configured",
        )

    invariants: list[InvariantView] = []
    for req in selected:
        invariants.extend(
            await contracts.list_invariants(session, project=project, requirement_id=req.entry_id)
        )
    if not invariants:
        return TaskContractView(
            text="",
            token_estimate=0,
            token_budget=budget,
            requirement_ids=tuple(r.entry_id for r in selected),
            req_keys=tuple(r.req_key for r in selected),
            truncated=False,
            omitted_invariants=0,
            omitted_requirements=omitted_reqs,
            review="not-configured",
        )

    gate = await _load_close_gate(
        session, project=project, requirement_ids=[r.entry_id for r in selected]
    )
    ranked = _rank_statements(invariants, gate)
    text, omitted_invs, truncated = _render_compact(ranked, gate, max_tokens=budget)
    return TaskContractView(
        text=text,
        token_estimate=estimate_tokens(text),
        token_budget=budget,
        requirement_ids=tuple(r.entry_id for r in selected),
        req_keys=tuple(r.req_key for r in selected),
        truncated=truncated,
        omitted_invariants=omitted_invs,
        omitted_requirements=omitted_reqs,
        review=gate.review,
    )
