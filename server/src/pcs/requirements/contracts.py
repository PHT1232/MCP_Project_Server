"""Store-owned requirement contracts: invariants, criteria, immutable history (T10).

PostgreSQL is the source of truth. These records are not written to
``.project-context/requirements.md``. Evidence and the ``done`` close-gate are T12.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, AsyncSessionTransaction

from pcs.context.service import resolve_project
from pcs.context.types import (
    ACTION_CREATE,
    ACTION_DELETE,
    ACTION_UPDATE,
    CONTRACT_AUTHOR_MAX_CHARS,
    CONTRACT_ENTITY_CRITERION,
    CONTRACT_ENTITY_INVARIANT,
    CONTRACT_KEY_MAX_CHARS,
    CONTRACT_STATEMENT_MAX_CHARS,
    EVIDENCE_KINDS,
    HIDDEN_STATUSES,
    INDEPENDENT_REVIEW_NOT_REQUIRED,
    INDEPENDENT_REVIEW_POLICIES,
    INVARIANT_KINDS,
    RISK_LEVELS,
    SECTION_REQUIREMENTS,
    STATUS_DELETED,
    STATUS_OPEN,
    ContractNotFoundError,
    ContractRevisionView,
    CriterionView,
    InvariantView,
    ValidationError,
)
from pcs.db.models import (
    AcceptanceCriterion,
    ContextEntry,
    RequirementContractRevision,
    RequirementInvariant,
)

__all__ = [
    "create_criterion",
    "create_invariant",
    "delete_criterion",
    "delete_invariant",
    "get_criterion",
    "get_invariant",
    "list_contract_revisions",
    "list_criteria",
    "list_invariants",
    "update_criterion",
    "update_invariant",
]

_KEY_RE = re.compile(rf"^[A-Za-z0-9][A-Za-z0-9._:-]{{0,{CONTRACT_KEY_MAX_CHARS - 1}}}$")


def _now() -> datetime:
    return datetime.now(UTC)


def _validate_key(key: str, *, label: str) -> str:
    cleaned = key.strip()
    if not _KEY_RE.fullmatch(cleaned):
        raise ValidationError(
            f"{label} key {key!r} is invalid; use 1-{CONTRACT_KEY_MAX_CHARS} chars "
            "starting with alphanumeric, then letters, digits, '.', '_', ':', or '-'."
        )
    return cleaned


def _validate_statement(statement: str, *, label: str) -> str:
    cleaned = statement.strip()
    if not cleaned:
        raise ValidationError(f"{label} statement must not be empty")
    if len(cleaned) > CONTRACT_STATEMENT_MAX_CHARS:
        raise ValidationError(
            f"{label} statement exceeds {CONTRACT_STATEMENT_MAX_CHARS} characters; "
            "shorten it and retry — the server will not truncate a supplied statement"
        )
    return cleaned


def _validate_choice(value: str, allowed: frozenset[str], *, field: str) -> str:
    cleaned = value.strip()
    if cleaned not in allowed:
        options = ", ".join(sorted(allowed))
        raise ValidationError(f"invalid {field} {value!r}; expected one of: {options}")
    return cleaned


def _validate_author(author: str) -> str:
    cleaned = author.strip()
    if not cleaned:
        raise ValidationError("author must not be empty")
    if len(cleaned) > CONTRACT_AUTHOR_MAX_CHARS:
        raise ValidationError(
            f"author exceeds {CONTRACT_AUTHOR_MAX_CHARS} characters; shorten it and retry"
        )
    return cleaned


def _validate_sort_order(sort_order: int) -> int:
    if sort_order < 0:
        raise ValidationError("sort_order must be >= 0")
    return sort_order


def _as_invariant(row: RequirementInvariant) -> InvariantView:
    return InvariantView(
        id=row.id,
        project_id=row.project_id,
        requirement_id=row.requirement_id,
        key=row.key,
        statement=row.statement,
        kind=row.kind,
        risk=row.risk,
        sort_order=row.sort_order,
        status=row.status,
        author=row.author,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _as_criterion(row: AcceptanceCriterion) -> CriterionView:
    return CriterionView(
        id=row.id,
        project_id=row.project_id,
        invariant_id=row.invariant_id,
        key=row.key,
        statement=row.statement,
        evidence_kind=row.evidence_kind,
        required=row.required,
        independent_review=row.independent_review,
        sort_order=row.sort_order,
        status=row.status,
        author=row.author,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _as_revision(row: RequirementContractRevision) -> ContractRevisionView:
    snapshot = row.snapshot if isinstance(row.snapshot, dict) else {}
    return ContractRevisionView(
        id=row.id,
        project_id=row.project_id,
        requirement_id=row.requirement_id,
        entity_kind=row.entity_kind,
        entity_id=row.entity_id,
        action=row.action,
        snapshot=dict(snapshot),
        author=row.author,
        created_at=row.created_at,
    )


def _invariant_snapshot(row: RequirementInvariant) -> dict[str, object]:
    view = _as_invariant(row)
    return view.as_dict()


def _criterion_snapshot(row: AcceptanceCriterion) -> dict[str, object]:
    view = _as_criterion(row)
    return view.as_dict()


def _record_revision(
    session: AsyncSession,
    *,
    project_id: str,
    requirement_id: str,
    entity_kind: str,
    entity_id: str,
    action: str,
    snapshot: dict[str, object],
    author: str,
) -> None:
    session.add(
        RequirementContractRevision(
            project_id=project_id,
            requirement_id=requirement_id,
            entity_kind=entity_kind,
            entity_id=entity_id,
            action=action,
            snapshot=snapshot,
            author=author,
        )
    )


async def _next_sort_order(
    session: AsyncSession,
    *,
    model: type[RequirementInvariant] | type[AcceptanceCriterion],
    parent_column: Any,
    parent_id: str,
) -> int:
    result = await session.execute(
        select(func.coalesce(func.max(model.sort_order), -1)).where(parent_column == parent_id)
    )
    return int(result.scalar_one()) + 1


async def _allocate_key(
    session: AsyncSession,
    *,
    model: type[RequirementInvariant] | type[AcceptanceCriterion],
    parent_column: Any,
    parent_id: str,
    prefix: str,
) -> str:
    result = await session.execute(select(model.key).where(parent_column == parent_id))
    used = {row[0] for row in result.all()}
    n = 1
    while True:
        candidate = f"{prefix}-{n:03d}"
        if candidate not in used:
            return candidate
        n += 1


async def _flush_contract(
    session: AsyncSession, *, what: str, savepoint: AsyncSessionTransaction
) -> None:
    """Flush and translate unique-constraint failures into actionable ValidationError."""
    try:
        await session.flush()
        await savepoint.commit()
    except IntegrityError as exc:
        await savepoint.rollback()
        raise _integrity_error(what=what) from exc


async def _load_requirement(
    session: AsyncSession, *, project_id: str, project_label: str, requirement_id: str
) -> ContextEntry:
    entry = await session.get(ContextEntry, requirement_id)
    if entry is None:
        raise ValidationError(
            f"requirement {requirement_id!r} does not exist; pass a requirements-section entry id"
        )
    if entry.project_id != project_id:
        raise ValidationError(
            f"cross-project links are rejected: requirement {requirement_id!r} "
            f"does not belong to project {project_label!r}"
        )
    if entry.section != SECTION_REQUIREMENTS:
        raise ValidationError(
            f"entry {requirement_id!r} is not a requirement (section={entry.section!r})"
        )
    return entry


def _is_hidden_requirement(entry: ContextEntry) -> bool:
    return entry.status in HIDDEN_STATUSES


async def _require_writable_requirement(
    session: AsyncSession, *, project_id: str, project_label: str, requirement_id: str
) -> ContextEntry:
    entry = await _load_requirement(
        session, project_id=project_id, project_label=project_label, requirement_id=requirement_id
    )
    if _is_hidden_requirement(entry):
        raise ValidationError(
            f"requirement {requirement_id!r} is {entry.status} and cannot receive contract records"
        )
    return entry


async def _parent_requirement_hidden(session: AsyncSession, requirement_id: str) -> bool:
    entry = await session.get(ContextEntry, requirement_id)
    return entry is None or _is_hidden_requirement(entry)


def _hidden_parent_write_error(requirement_id: str) -> ValidationError:
    return ValidationError(
        f"requirement {requirement_id!r} is hidden and cannot receive contract records"
    )


async def _load_invariant_row(
    session: AsyncSession,
    *,
    project_id: str,
    project_label: str,
    invariant_id: str,
    include_deleted: bool = False,
    for_link: bool = False,
) -> RequirementInvariant:
    row = await session.get(RequirementInvariant, invariant_id)
    if row is None:
        if for_link:
            raise ValidationError(
                f"invariant {invariant_id!r} does not exist; "
                "create the invariant before linking a criterion"
            )
        raise ContractNotFoundError("invariant", invariant_id, project_label)
    if row.project_id != project_id:
        raise ValidationError(
            f"cross-project links are rejected: invariant {invariant_id!r} "
            f"does not belong to project {project_label!r}"
        )
    if row.status == STATUS_DELETED and not include_deleted:
        if for_link:
            raise ValidationError(
                f"invariant {invariant_id!r} is deleted and cannot receive new criteria"
            )
        raise ContractNotFoundError("invariant", invariant_id, project_label)
    return row


async def _load_criterion_row(
    session: AsyncSession,
    *,
    project_id: str,
    project_label: str,
    criterion_id: str,
    include_deleted: bool = False,
) -> AcceptanceCriterion:
    row = await session.get(AcceptanceCriterion, criterion_id)
    if row is None:
        raise ContractNotFoundError("criterion", criterion_id, project_label)
    if row.project_id != project_id:
        raise ValidationError(
            f"cross-project links are rejected: criterion {criterion_id!r} "
            f"does not belong to project {project_label!r}"
        )
    if row.status == STATUS_DELETED and not include_deleted:
        raise ContractNotFoundError("criterion", criterion_id, project_label)
    return row


async def _assert_unique_invariant_key(
    session: AsyncSession, *, requirement_id: str, key: str, exclude_id: str | None = None
) -> None:
    stmt = select(RequirementInvariant.id).where(
        RequirementInvariant.requirement_id == requirement_id,
        RequirementInvariant.key == key,
    )
    if exclude_id is not None:
        stmt = stmt.where(RequirementInvariant.id != exclude_id)
    existing = (await session.execute(stmt)).scalar_one_or_none()
    if existing is not None:
        raise ValidationError(
            f"invariant key {key!r} already exists on requirement {requirement_id!r}; "
            "use update_invariant to change the existing row"
        )


async def _assert_unique_criterion_key(
    session: AsyncSession, *, invariant_id: str, key: str, exclude_id: str | None = None
) -> None:
    stmt = select(AcceptanceCriterion.id).where(
        AcceptanceCriterion.invariant_id == invariant_id,
        AcceptanceCriterion.key == key,
    )
    if exclude_id is not None:
        stmt = stmt.where(AcceptanceCriterion.id != exclude_id)
    existing = (await session.execute(stmt)).scalar_one_or_none()
    if existing is not None:
        raise ValidationError(
            f"criterion key {key!r} already exists on invariant {invariant_id!r}; "
            "use update_criterion to change the existing row"
        )


def _integrity_error(*, what: str) -> ValidationError:
    return ValidationError(
        f"duplicate {what} key rejected; keys must be unique within their parent scope. "
        "Use the matching update function instead of creating a second row."
    )


async def create_invariant(
    session: AsyncSession,
    *,
    project: str,
    requirement_id: str,
    statement: str,
    kind: str,
    risk: str,
    key: str | None = None,
    sort_order: int | None = None,
    author: str = "agent",
) -> InvariantView:
    """Create one invariant with a stable per-requirement key (T10)."""
    project_row = await resolve_project(session, project, for_update=True)
    requirement = await _require_writable_requirement(
        session,
        project_id=project_row.id,
        project_label=project_row.name,
        requirement_id=requirement_id,
    )
    kind_key = _validate_choice(kind, INVARIANT_KINDS, field="kind")
    risk_key = _validate_choice(risk, RISK_LEVELS, field="risk")
    statement_text = _validate_statement(statement, label="invariant")
    author_text = _validate_author(author)
    if key is None or not key.strip():
        key_text = await _allocate_key(
            session,
            model=RequirementInvariant,
            parent_column=RequirementInvariant.requirement_id,
            parent_id=requirement.id,
            prefix="INV",
        )
    else:
        key_text = _validate_key(key, label="invariant")
    await _assert_unique_invariant_key(session, requirement_id=requirement.id, key=key_text)
    order = (
        _validate_sort_order(sort_order)
        if sort_order is not None
        else await _next_sort_order(
            session,
            model=RequirementInvariant,
            parent_column=RequirementInvariant.requirement_id,
            parent_id=requirement.id,
        )
    )
    savepoint = await session.begin_nested()
    row = RequirementInvariant(
        project_id=project_row.id,
        requirement_id=requirement.id,
        requirement_section=SECTION_REQUIREMENTS,
        key=key_text,
        statement=statement_text,
        kind=kind_key,
        risk=risk_key,
        sort_order=order,
        status=STATUS_OPEN,
        author=author_text,
        created_at=_now(),
        updated_at=_now(),
    )
    session.add(row)
    await _flush_contract(session, what="invariant", savepoint=savepoint)
    _record_revision(
        session,
        project_id=project_row.id,
        requirement_id=requirement.id,
        entity_kind=CONTRACT_ENTITY_INVARIANT,
        entity_id=row.id,
        action=ACTION_CREATE,
        snapshot=_invariant_snapshot(row),
        author=author_text,
    )
    await session.flush()
    return _as_invariant(row)


async def update_invariant(
    session: AsyncSession,
    *,
    project: str,
    invariant_id: str,
    statement: str | None = None,
    kind: str | None = None,
    risk: str | None = None,
    key: str | None = None,
    sort_order: int | None = None,
    author: str = "agent",
) -> InvariantView:
    """Merge-update one invariant. Unset fields stay (T10)."""
    project_row = await resolve_project(session, project, for_update=True)
    row = await _load_invariant_row(
        session,
        project_id=project_row.id,
        project_label=project_row.name,
        invariant_id=invariant_id,
    )
    if await _parent_requirement_hidden(session, row.requirement_id):
        raise _hidden_parent_write_error(row.requirement_id)
    author_text = _validate_author(author)
    savepoint = await session.begin_nested()
    changed = False
    if key is not None:
        key_text = _validate_key(key, label="invariant")
        if key_text != row.key:
            await _assert_unique_invariant_key(
                session, requirement_id=row.requirement_id, key=key_text, exclude_id=row.id
            )
            row.key = key_text
            changed = True
    if statement is not None:
        statement_text = _validate_statement(statement, label="invariant")
        if statement_text != row.statement:
            row.statement = statement_text
            changed = True
    if kind is not None:
        kind_key = _validate_choice(kind, INVARIANT_KINDS, field="kind")
        if kind_key != row.kind:
            row.kind = kind_key
            changed = True
    if risk is not None:
        risk_key = _validate_choice(risk, RISK_LEVELS, field="risk")
        if risk_key != row.risk:
            row.risk = risk_key
            changed = True
    if sort_order is not None:
        order = _validate_sort_order(sort_order)
        if order != row.sort_order:
            row.sort_order = order
            changed = True
    if not changed:
        await savepoint.commit()
        return _as_invariant(row)
    row.author = author_text
    row.updated_at = _now()
    await _flush_contract(session, what="invariant", savepoint=savepoint)
    _record_revision(
        session,
        project_id=project_row.id,
        requirement_id=row.requirement_id,
        entity_kind=CONTRACT_ENTITY_INVARIANT,
        entity_id=row.id,
        action=ACTION_UPDATE,
        snapshot=_invariant_snapshot(row),
        author=author_text,
    )
    await session.flush()
    return _as_invariant(row)


async def delete_invariant(
    session: AsyncSession, *, project: str, invariant_id: str, author: str = "agent"
) -> InvariantView:
    """Soft-delete an invariant and its open criteria; history is kept (T10)."""
    project_row = await resolve_project(session, project, for_update=True)
    row = await _load_invariant_row(
        session,
        project_id=project_row.id,
        project_label=project_row.name,
        invariant_id=invariant_id,
    )
    if await _parent_requirement_hidden(session, row.requirement_id):
        raise _hidden_parent_write_error(row.requirement_id)
    author_text = _validate_author(author)
    now = _now()
    children = await session.execute(
        select(AcceptanceCriterion).where(
            AcceptanceCriterion.invariant_id == row.id,
            AcceptanceCriterion.status == STATUS_OPEN,
        )
    )
    for criterion in children.scalars().all():
        criterion.status = STATUS_DELETED
        criterion.author = author_text
        criterion.updated_at = now
        _record_revision(
            session,
            project_id=project_row.id,
            requirement_id=row.requirement_id,
            entity_kind=CONTRACT_ENTITY_CRITERION,
            entity_id=criterion.id,
            action=ACTION_DELETE,
            snapshot=_criterion_snapshot(criterion),
            author=author_text,
        )
    row.status = STATUS_DELETED
    row.author = author_text
    row.updated_at = now
    _record_revision(
        session,
        project_id=project_row.id,
        requirement_id=row.requirement_id,
        entity_kind=CONTRACT_ENTITY_INVARIANT,
        entity_id=row.id,
        action=ACTION_DELETE,
        snapshot=_invariant_snapshot(row),
        author=author_text,
    )
    await session.flush()
    return _as_invariant(row)


async def list_invariants(
    session: AsyncSession,
    *,
    project: str,
    requirement_id: str,
    include_deleted: bool = False,
) -> list[InvariantView]:
    """Active (or all) invariants for one requirement, deterministic order (T10)."""
    project_row = await resolve_project(session, project)
    requirement = await _load_requirement(
        session,
        project_id=project_row.id,
        project_label=project_row.name,
        requirement_id=requirement_id,
    )
    if _is_hidden_requirement(requirement) and not include_deleted:
        return []
    stmt = select(RequirementInvariant).where(
        RequirementInvariant.project_id == project_row.id,
        RequirementInvariant.requirement_id == requirement_id,
    )
    if not include_deleted:
        stmt = stmt.where(RequirementInvariant.status == STATUS_OPEN)
    stmt = stmt.order_by(
        RequirementInvariant.sort_order.asc(),
        RequirementInvariant.key.asc(),
        RequirementInvariant.id.asc(),
    )
    result = await session.execute(stmt)
    return [_as_invariant(row) for row in result.scalars().all()]


async def get_invariant(
    session: AsyncSession,
    *,
    project: str,
    invariant_id: str,
    include_deleted: bool = False,
) -> InvariantView:
    """Return one invariant by id (T10)."""
    project_row = await resolve_project(session, project)
    row = await _load_invariant_row(
        session,
        project_id=project_row.id,
        project_label=project_row.name,
        invariant_id=invariant_id,
        include_deleted=include_deleted,
    )
    if not include_deleted and await _parent_requirement_hidden(session, row.requirement_id):
        raise ContractNotFoundError("invariant", invariant_id, project_row.name)
    return _as_invariant(row)


async def create_criterion(
    session: AsyncSession,
    *,
    project: str,
    invariant_id: str,
    statement: str,
    evidence_kind: str,
    key: str | None = None,
    required: bool = True,
    independent_review: str = INDEPENDENT_REVIEW_NOT_REQUIRED,
    sort_order: int | None = None,
    author: str = "agent",
) -> CriterionView:
    """Create one acceptance criterion with a stable per-invariant key (T10)."""
    project_row = await resolve_project(session, project, for_update=True)
    invariant = await _load_invariant_row(
        session,
        project_id=project_row.id,
        project_label=project_row.name,
        invariant_id=invariant_id,
        for_link=True,
    )
    if await _parent_requirement_hidden(session, invariant.requirement_id):
        raise _hidden_parent_write_error(invariant.requirement_id)
    evidence = _validate_choice(evidence_kind, EVIDENCE_KINDS, field="evidence kind")
    policy = _validate_choice(
        independent_review, INDEPENDENT_REVIEW_POLICIES, field="independent_review"
    )
    statement_text = _validate_statement(statement, label="criterion")
    author_text = _validate_author(author)
    if key is None or not key.strip():
        key_text = await _allocate_key(
            session,
            model=AcceptanceCriterion,
            parent_column=AcceptanceCriterion.invariant_id,
            parent_id=invariant.id,
            prefix="AC",
        )
    else:
        key_text = _validate_key(key, label="criterion")
    await _assert_unique_criterion_key(session, invariant_id=invariant.id, key=key_text)
    order = (
        _validate_sort_order(sort_order)
        if sort_order is not None
        else await _next_sort_order(
            session,
            model=AcceptanceCriterion,
            parent_column=AcceptanceCriterion.invariant_id,
            parent_id=invariant.id,
        )
    )
    savepoint = await session.begin_nested()
    row = AcceptanceCriterion(
        project_id=project_row.id,
        invariant_id=invariant.id,
        key=key_text,
        statement=statement_text,
        evidence_kind=evidence,
        required=required,
        independent_review=policy,
        sort_order=order,
        status=STATUS_OPEN,
        author=author_text,
        created_at=_now(),
        updated_at=_now(),
    )
    session.add(row)
    await _flush_contract(session, what="criterion", savepoint=savepoint)
    _record_revision(
        session,
        project_id=project_row.id,
        requirement_id=invariant.requirement_id,
        entity_kind=CONTRACT_ENTITY_CRITERION,
        entity_id=row.id,
        action=ACTION_CREATE,
        snapshot=_criterion_snapshot(row),
        author=author_text,
    )
    await session.flush()
    return _as_criterion(row)


async def update_criterion(
    session: AsyncSession,
    *,
    project: str,
    criterion_id: str,
    statement: str | None = None,
    evidence_kind: str | None = None,
    required: bool | None = None,
    independent_review: str | None = None,
    key: str | None = None,
    sort_order: int | None = None,
    author: str = "agent",
) -> CriterionView:
    """Merge-update one criterion. Unset fields stay (T10)."""
    project_row = await resolve_project(session, project, for_update=True)
    row = await _load_criterion_row(
        session,
        project_id=project_row.id,
        project_label=project_row.name,
        criterion_id=criterion_id,
    )
    author_text = _validate_author(author)
    savepoint = await session.begin_nested()
    invariant = await _load_invariant_row(
        session,
        project_id=project_row.id,
        project_label=project_row.name,
        invariant_id=row.invariant_id,
        include_deleted=True,
    )
    if await _parent_requirement_hidden(session, invariant.requirement_id):
        raise _hidden_parent_write_error(invariant.requirement_id)
    changed = False
    if key is not None:
        key_text = _validate_key(key, label="criterion")
        if key_text != row.key:
            await _assert_unique_criterion_key(
                session, invariant_id=row.invariant_id, key=key_text, exclude_id=row.id
            )
            row.key = key_text
            changed = True
    if statement is not None:
        statement_text = _validate_statement(statement, label="criterion")
        if statement_text != row.statement:
            row.statement = statement_text
            changed = True
    if evidence_kind is not None:
        evidence = _validate_choice(evidence_kind, EVIDENCE_KINDS, field="evidence kind")
        if evidence != row.evidence_kind:
            row.evidence_kind = evidence
            changed = True
    if required is not None and required != row.required:
        row.required = required
        changed = True
    if independent_review is not None:
        policy = _validate_choice(
            independent_review, INDEPENDENT_REVIEW_POLICIES, field="independent_review"
        )
        if policy != row.independent_review:
            row.independent_review = policy
            changed = True
    if sort_order is not None:
        order = _validate_sort_order(sort_order)
        if order != row.sort_order:
            row.sort_order = order
            changed = True
    if not changed:
        await savepoint.commit()
        return _as_criterion(row)
    row.author = author_text
    row.updated_at = _now()
    await _flush_contract(session, what="criterion", savepoint=savepoint)
    _record_revision(
        session,
        project_id=project_row.id,
        requirement_id=invariant.requirement_id,
        entity_kind=CONTRACT_ENTITY_CRITERION,
        entity_id=row.id,
        action=ACTION_UPDATE,
        snapshot=_criterion_snapshot(row),
        author=author_text,
    )
    await session.flush()
    return _as_criterion(row)


async def delete_criterion(
    session: AsyncSession, *, project: str, criterion_id: str, author: str = "agent"
) -> CriterionView:
    """Soft-delete one criterion; history is kept (T10)."""
    project_row = await resolve_project(session, project, for_update=True)
    row = await _load_criterion_row(
        session,
        project_id=project_row.id,
        project_label=project_row.name,
        criterion_id=criterion_id,
    )
    author_text = _validate_author(author)
    invariant = await _load_invariant_row(
        session,
        project_id=project_row.id,
        project_label=project_row.name,
        invariant_id=row.invariant_id,
        include_deleted=True,
    )
    if await _parent_requirement_hidden(session, invariant.requirement_id):
        raise _hidden_parent_write_error(invariant.requirement_id)
    row.status = STATUS_DELETED
    row.author = author_text
    row.updated_at = _now()
    _record_revision(
        session,
        project_id=project_row.id,
        requirement_id=invariant.requirement_id,
        entity_kind=CONTRACT_ENTITY_CRITERION,
        entity_id=row.id,
        action=ACTION_DELETE,
        snapshot=_criterion_snapshot(row),
        author=author_text,
    )
    await session.flush()
    return _as_criterion(row)


async def list_criteria(
    session: AsyncSession,
    *,
    project: str,
    invariant_id: str | None = None,
    requirement_id: str | None = None,
    include_deleted: bool = False,
) -> list[CriterionView]:
    """Active (or all) criteria for one invariant or requirement (T10)."""
    if (invariant_id is None) == (requirement_id is None):
        raise ValidationError("pass exactly one of invariant_id or requirement_id")
    project_row = await resolve_project(session, project)
    stmt = select(AcceptanceCriterion).where(AcceptanceCriterion.project_id == project_row.id)
    if invariant_id is not None:
        invariant = await _load_invariant_row(
            session,
            project_id=project_row.id,
            project_label=project_row.name,
            invariant_id=invariant_id,
            include_deleted=True,
        )
        if not include_deleted and (
            invariant.status == STATUS_DELETED
            or await _parent_requirement_hidden(session, invariant.requirement_id)
        ):
            return []
        stmt = stmt.where(AcceptanceCriterion.invariant_id == invariant_id)
    else:
        assert requirement_id is not None
        requirement = await _load_requirement(
            session,
            project_id=project_row.id,
            project_label=project_row.name,
            requirement_id=requirement_id,
        )
        if _is_hidden_requirement(requirement) and not include_deleted:
            return []
        stmt = stmt.join(
            RequirementInvariant, RequirementInvariant.id == AcceptanceCriterion.invariant_id
        ).where(RequirementInvariant.requirement_id == requirement_id)
    if not include_deleted:
        stmt = stmt.where(AcceptanceCriterion.status == STATUS_OPEN)
    stmt = stmt.order_by(
        AcceptanceCriterion.sort_order.asc(),
        AcceptanceCriterion.key.asc(),
        AcceptanceCriterion.invariant_id.asc(),
        AcceptanceCriterion.id.asc(),
    )
    result = await session.execute(stmt)
    return [_as_criterion(row) for row in result.scalars().all()]


async def get_criterion(
    session: AsyncSession,
    *,
    project: str,
    criterion_id: str,
    include_deleted: bool = False,
) -> CriterionView:
    """Return one criterion by id (T10)."""
    project_row = await resolve_project(session, project)
    row = await _load_criterion_row(
        session,
        project_id=project_row.id,
        project_label=project_row.name,
        criterion_id=criterion_id,
        include_deleted=include_deleted,
    )
    if not include_deleted:
        invariant = await session.get(RequirementInvariant, row.invariant_id)
        parent_id = invariant.requirement_id if invariant is not None else ""
        if await _parent_requirement_hidden(session, parent_id):
            raise ContractNotFoundError("criterion", criterion_id, project_row.name)
    return _as_criterion(row)


async def list_contract_revisions(
    session: AsyncSession, *, project: str, requirement_id: str
) -> list[ContractRevisionView]:
    """Immutable contract history for one requirement, oldest first (T10)."""
    project_row = await resolve_project(session, project)
    await _load_requirement(
        session,
        project_id=project_row.id,
        project_label=project_row.name,
        requirement_id=requirement_id,
    )
    result = await session.execute(
        select(RequirementContractRevision)
        .where(
            RequirementContractRevision.project_id == project_row.id,
            RequirementContractRevision.requirement_id == requirement_id,
        )
        .order_by(
            RequirementContractRevision.created_at.asc(), RequirementContractRevision.id.asc()
        )
    )
    return [_as_revision(row) for row in result.scalars().all()]
