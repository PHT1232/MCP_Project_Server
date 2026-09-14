"""Curated context store - service layer (FR1-FR13, FR17, FR18, D3, D5, D13).

Plain async functions over :class:`AsyncSession`. No MCP or HTTP imports
(AGENTS.md). Transports are thin wrappers around this module.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pcs.ai_settings import load_runtime_ai_settings
from pcs.context.assembly import assemble_briefing
from pcs.context.summarizer import Summarizer
from pcs.context.types import (
    ACTION_ARCHIVE,
    ACTION_CREATE,
    ACTION_DELETE,
    ACTION_RESOLVE,
    ACTION_UPDATE,
    BRIEFING_TOKEN_CAP,
    BRIEFING_TOKEN_MAX,
    BRIEFING_TOKEN_MIN,
    EXPIRY_AGE,
    EXPIRY_OFF,
    EXPIRY_POLICIES,
    HEADLINE_MAX_CHARS,
    HIDDEN_STATUSES,
    PREPARE_TASK_TOKEN_MAX,
    PREPARE_TASK_TOKEN_MIN,
    REQ_DONE,
    SECTION_FOCUS,
    SECTION_OVERVIEW,
    SECTION_REQUIREMENTS,
    STATUS_ARCHIVED,
    STATUS_DELETED,
    STATUS_OPEN,
    STATUS_RESOLVED,
    AssemblyEntry,
    DuplicateProjectError,
    EntryNotFoundError,
    EntryView,
    ProjectNotFoundError,
    ProjectSummary,
    RevisionView,
    ValidationError,
)
from pcs.context.validation import (
    default_requirement_status,
    derive_headline_detail,
    validate_requirement_status,
    validate_section,
)
from pcs.db.models import ContextEntry, ContextEntryRevision, Project

# Re-export names T00 tests and transports already import from this module.
__all__ = [
    "BRIEFING_TOKEN_CAP",
    "HEADLINE_MAX_CHARS",
    "DuplicateProjectError",
    "EntryNotFoundError",
    "ProjectNotFoundError",
    "ProjectSummary",
    "ValidationError",
    "add_entry",
    "archive_entry",
    "configure_project",
    "delete_entry",
    "get_entry",
    "get_entry_history",
    "get_project_briefing",
    "get_section",
    "list_projects",
    "register_project",
    "resolve_entry",
    "resolve_project",
    "set_current_focus",
    "set_requirement_status",
    "update_entry",
    "update_overview",
]


def _now() -> datetime:
    return datetime.now(UTC)


def _as_view(row: ContextEntry) -> EntryView:
    files = row.linked_files if isinstance(row.linked_files, list) else []
    return EntryView(
        id=row.id,
        project_id=row.project_id,
        section=row.section,
        headline=row.headline,
        detail=row.detail,
        status=row.status,
        priority=row.priority,
        author=row.author,
        created_at=row.created_at,
        updated_at=row.updated_at,
        requirement_status=row.requirement_status,
        linked_files=tuple(str(f) for f in files),
        related_entry_id=row.related_entry_id,
        req_key=row.req_key,
    )


def _as_revision(row: ContextEntryRevision) -> RevisionView:
    files = row.linked_files if isinstance(row.linked_files, list) else []
    return RevisionView(
        id=row.id,
        entry_id=row.entry_id,
        action=row.action,
        headline=row.headline,
        detail=row.detail,
        status=row.status,
        priority=row.priority,
        author=row.author,
        created_at=row.created_at,
        requirement_status=row.requirement_status,
        linked_files=tuple(str(f) for f in files),
        related_entry_id=row.related_entry_id,
    )


def _as_summary(row: Project, *, status_line: str = "") -> ProjectSummary:
    return ProjectSummary(
        id=row.id,
        name=row.name,
        root_path=row.root_path,
        status_line=status_line,
        briefing_token_budget=row.briefing_token_budget,
        prepare_task_token_budget=row.prepare_task_token_budget,
        headline_max_chars=row.headline_max_chars,
        detail_max_chars=row.detail_max_chars,
        expiry_policy=row.expiry_policy,
        expiry_days=row.expiry_days,
    )


def _linked_files(value: Sequence[str] | None) -> list[str]:
    if not value:
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _record_revision(session: AsyncSession, entry: ContextEntry, action: str, author: str) -> None:
    """Append an immutable snapshot of ``entry`` after a mutation (FR11, D5)."""
    files = entry.linked_files if isinstance(entry.linked_files, list) else []
    session.add(
        ContextEntryRevision(
            entry_id=entry.id,
            action=action,
            headline=entry.headline,
            detail=entry.detail,
            status=entry.status,
            priority=entry.priority,
            author=author,
            requirement_status=entry.requirement_status,
            linked_files=list(files),
            related_entry_id=entry.related_entry_id,
        )
    )


def _is_expired(entry: ContextEntry, project: Project, now: datetime) -> bool:
    """Age-based hide (FR3a). Overview never auto-expires."""
    if project.expiry_policy != EXPIRY_AGE or not project.expiry_days:
        return False
    if entry.section == SECTION_OVERVIEW:
        return False
    stamp = entry.updated_at
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    return stamp <= now - timedelta(days=project.expiry_days)


def _is_visible(
    entry: ContextEntry,
    project: Project,
    *,
    now: datetime,
    include_resolved: bool,
    include_deleted: bool = False,
) -> bool:
    if entry.status in HIDDEN_STATUSES and not include_deleted:
        return False
    if entry.status == STATUS_RESOLVED and not include_resolved:
        return False
    return include_resolved or not _is_expired(entry, project, now)


async def _project_names(session: AsyncSession) -> list[str]:
    result = await session.execute(select(Project.name).order_by(Project.name))
    return list(result.scalars().all())


async def resolve_project(
    session: AsyncSession, project: str | None, *, for_update: bool = False
) -> Project:
    """Look a project up by name or id, or raise :class:`ProjectNotFoundError` (D3, AC16).

    ``for_update`` takes a row lock so writes on the same project serialize (FR17).
    """
    key = (project or "").strip()
    if key:
        stmt = select(Project).where((Project.name == key) | (Project.id == key))
        if for_update:
            stmt = stmt.with_for_update()
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is not None:
            return row
    raise ProjectNotFoundError(project or "", await _project_names(session))


async def _load_entry(
    session: AsyncSession,
    project: Project,
    entry_id: str,
    *,
    include_deleted: bool = False,
) -> ContextEntry:
    result = await session.execute(
        select(ContextEntry).where(
            ContextEntry.id == entry_id, ContextEntry.project_id == project.id
        )
    )
    row = result.scalar_one_or_none()
    if row is None or (row.status in HIDDEN_STATUSES and not include_deleted):
        raise EntryNotFoundError(entry_id, project.name)
    return row


async def _assert_related(
    session: AsyncSession, project: Project, related_entry_id: str | None
) -> str | None:
    if related_entry_id is None or not related_entry_id.strip():
        return None
    related = await session.execute(
        select(ContextEntry).where(
            ContextEntry.id == related_entry_id.strip(),
            ContextEntry.project_id == project.id,
            ContextEntry.status.notin_((STATUS_DELETED, STATUS_ARCHIVED)),
        )
    )
    if related.scalar_one_or_none() is None:
        raise ValidationError(
            f"related_entry_id {related_entry_id!r} is not an entry in project {project.name!r}"
        )
    return related_entry_id.strip()


async def _status_line(session: AsyncSession, project: Project) -> str:
    now = _now()
    result = await session.execute(
        select(ContextEntry).where(
            ContextEntry.project_id == project.id,
            ContextEntry.status.notin_((STATUS_DELETED, STATUS_ARCHIVED)),
        )
    )
    entries = [
        e
        for e in result.scalars().all()
        if _is_visible(e, project, now=now, include_resolved=False)
    ]
    focus = next((e.headline for e in entries if e.section == SECTION_FOCUS), "no focus")
    blockers = sum(1 for e in entries if e.section == "blockers")
    bugs = sum(1 for e in entries if e.section == "bugs")
    return f"{focus} · {blockers} open blocker(s) · {bugs} open bug(s)"


async def list_projects(session: AsyncSession) -> list[ProjectSummary]:
    """All registered projects, name-ordered, with a one-line status (FR15)."""
    result = await session.execute(select(Project).order_by(Project.name))
    summaries: list[ProjectSummary] = []
    for project in result.scalars().all():
        summaries.append(_as_summary(project, status_line=await _status_line(session, project)))
    return summaries


async def register_project(
    session: AsyncSession,
    *,
    name: str,
    root_path: str,
    overview: str,
    author: str = "agent",
) -> ProjectSummary:
    """Create a project row and seed its overview entry (FR14)."""
    clean_name = name.strip()
    if not clean_name:
        raise ValidationError("project name must not be empty")

    existing = await session.execute(select(Project).where(Project.name == clean_name))
    if existing.scalar_one_or_none() is not None:
        raise DuplicateProjectError(f"project {clean_name!r} is already registered")

    project = Project(name=clean_name, root_path=root_path.strip())
    session.add(project)
    await session.flush()

    headline, detail = derive_headline_detail(
        headline=None,
        detail=(overview.strip() or clean_name),
        headline_max=project.headline_max_chars,
        detail_max=project.detail_max_chars,
    )
    entry = ContextEntry(
        project_id=project.id,
        section=SECTION_OVERVIEW,
        headline=headline,
        detail=detail,
        status=STATUS_OPEN,
        author=author,
        linked_files=[],
    )
    session.add(entry)
    await session.flush()
    _record_revision(session, entry, ACTION_CREATE, author)
    await session.flush()
    return _as_summary(project, status_line=await _status_line(session, project))


async def configure_project(
    session: AsyncSession,
    *,
    project: str,
    expiry_policy: str | None = None,
    expiry_days: int | None = None,
    briefing_token_budget: int | None = None,
    prepare_task_token_budget: int | None = None,
    headline_max_chars: int | None = None,
    detail_max_chars: int | None = None,
) -> ProjectSummary:
    """Update per-project budgets and expiry policy (FR3a, FR9g)."""
    row = await resolve_project(session, project, for_update=True)
    if expiry_policy is not None:
        policy = expiry_policy.strip()
        if policy not in EXPIRY_POLICIES:
            allowed = ", ".join(sorted(EXPIRY_POLICIES))
            raise ValidationError(f"expiry_policy must be one of: {allowed}")
        row.expiry_policy = policy
        if policy == EXPIRY_OFF:
            row.expiry_days = None
    if expiry_days is not None:
        if expiry_days < 1:
            raise ValidationError("expiry_days must be >= 1 when age-based expiry is used")
        row.expiry_days = expiry_days
        if row.expiry_policy == EXPIRY_OFF:
            row.expiry_policy = EXPIRY_AGE
    if row.expiry_policy == EXPIRY_AGE and not row.expiry_days:
        raise ValidationError("expiry_policy='age' requires expiry_days >= 1")
    if briefing_token_budget is not None:
        if not BRIEFING_TOKEN_MIN <= briefing_token_budget <= BRIEFING_TOKEN_MAX:
            raise ValidationError(
                f"briefing_token_budget must be in "
                f"[{BRIEFING_TOKEN_MIN}, {BRIEFING_TOKEN_MAX}] (FR9g)"
            )
        row.briefing_token_budget = briefing_token_budget
    if prepare_task_token_budget is not None:
        if not PREPARE_TASK_TOKEN_MIN <= prepare_task_token_budget <= PREPARE_TASK_TOKEN_MAX:
            raise ValidationError(
                f"prepare_task_token_budget must be in "
                f"[{PREPARE_TASK_TOKEN_MIN}, {PREPARE_TASK_TOKEN_MAX}] (FR9g)"
            )
        row.prepare_task_token_budget = prepare_task_token_budget
    if headline_max_chars is not None:
        if headline_max_chars < 1:
            raise ValidationError("headline_max_chars must be >= 1")
        row.headline_max_chars = headline_max_chars
    if detail_max_chars is not None:
        if detail_max_chars < 1:
            raise ValidationError("detail_max_chars must be >= 1")
        row.detail_max_chars = detail_max_chars
    row.updated_at = _now()
    await session.flush()
    return _as_summary(row, status_line=await _status_line(session, row))


async def add_entry(
    session: AsyncSession,
    *,
    project: str,
    section: str,
    headline: str | None = None,
    detail: str | None = None,
    priority: int = 0,
    author: str = "agent",
    requirement_status: str | None = None,
    linked_files: Sequence[str] | None = None,
    related_entry_id: str | None = None,
    req_key: str | None = None,
) -> EntryView:
    """Append a new entry in ``section`` (FR10, FR13, FR17 append/merge).

    ``req_key`` is the server-assigned ``R-NNN`` identity for a requirement
    (FR16a); it is set by :mod:`pcs.requirements` and is unique per project.
    """
    section_key = validate_section(section)
    if section_key == SECTION_OVERVIEW:
        raise ValidationError("overview is updated via update_overview, not added")
    row = await resolve_project(session, project, for_update=True)
    headline_text, detail_text = derive_headline_detail(
        headline=headline,
        detail=detail,
        headline_max=row.headline_max_chars,
        detail_max=row.detail_max_chars,
    )
    req_status = default_requirement_status(section_key, requirement_status)
    related = await _assert_related(session, row, related_entry_id)
    entry = ContextEntry(
        project_id=row.id,
        section=section_key,
        headline=headline_text,
        detail=detail_text,
        status=STATUS_OPEN,
        priority=priority,
        author=author,
        requirement_status=req_status,
        linked_files=_linked_files(linked_files),
        related_entry_id=related,
        req_key=(req_key.strip() or None) if req_key else None,
    )
    session.add(entry)
    await session.flush()
    _record_revision(session, entry, ACTION_CREATE, author)
    await session.flush()
    return _as_view(entry)


async def update_entry(
    session: AsyncSession,
    *,
    project: str,
    entry_id: str,
    headline: str | None = None,
    detail: str | None = None,
    priority: int | None = None,
    author: str = "agent",
    requirement_status: str | None = None,
    linked_files: Sequence[str] | None = None,
    related_entry_id: str | None = None,
    expected_section: str | None = None,
) -> EntryView:
    """Merge provided fields onto one entry (FR10, FR17, FR18). Unset fields stay."""
    row = await resolve_project(session, project, for_update=True)
    entry = await _load_entry(session, row, entry_id)
    if expected_section is not None and entry.section != expected_section:
        raise ValidationError(
            f"entry {entry_id} is in section {entry.section!r}, not {expected_section!r}"
        )
    if headline is not None:
        h = headline.strip()
        if not h:
            raise ValidationError("headline must not be empty")
        if len(h) > row.headline_max_chars:
            raise ValidationError(
                f"headline exceeds {row.headline_max_chars} characters (FR9g/D13); "
                "shorten it and retry — the server will not truncate a supplied headline"
            )
        entry.headline = h
    if detail is not None:
        d = detail.strip()
        if len(d) > row.detail_max_chars:
            raise ValidationError(
                f"detail exceeds {row.detail_max_chars} characters (FR9g/D13); "
                "shorten it and retry — the server will not truncate a supplied detail"
            )
        entry.detail = d
    if priority is not None:
        entry.priority = priority
    if requirement_status is not None:
        if entry.section != SECTION_REQUIREMENTS:
            raise ValidationError("requirement_status is only valid on the requirements section")
        entry.requirement_status = validate_requirement_status(requirement_status)
    if linked_files is not None:
        entry.linked_files = _linked_files(linked_files)
    if related_entry_id is not None:
        entry.related_entry_id = await _assert_related(session, row, related_entry_id or None)
    entry.author = author
    entry.updated_at = _now()
    await session.flush()
    _record_revision(session, entry, ACTION_UPDATE, author)
    await session.flush()
    return _as_view(entry)


async def resolve_entry(
    session: AsyncSession,
    *,
    project: str,
    entry_id: str,
    author: str = "agent",
    expected_section: str | None = None,
) -> EntryView:
    """Mark an entry resolved so it leaves the active briefing (FR12, AC4)."""
    row = await resolve_project(session, project, for_update=True)
    entry = await _load_entry(session, row, entry_id)
    if expected_section is not None and entry.section != expected_section:
        raise ValidationError(
            f"entry {entry_id} is in section {entry.section!r}, not {expected_section!r}"
        )
    if entry.section == SECTION_OVERVIEW:
        raise ValidationError("overview cannot be resolved; update it instead")
    entry.status = STATUS_RESOLVED
    entry.author = author
    entry.updated_at = _now()
    await session.flush()
    _record_revision(session, entry, ACTION_RESOLVE, author)
    await session.flush()
    return _as_view(entry)


async def delete_entry(
    session: AsyncSession, *, project: str, entry_id: str, author: str = "agent"
) -> EntryView:
    """Soft-delete an entry: gone from reads, history retained (FR11, AC17)."""
    row = await resolve_project(session, project, for_update=True)
    entry = await _load_entry(session, row, entry_id)
    entry.status = STATUS_DELETED
    entry.author = author
    entry.updated_at = _now()
    await session.flush()
    _record_revision(session, entry, ACTION_DELETE, author)
    await session.flush()
    return _as_view(entry)


async def archive_entry(
    session: AsyncSession, *, project: str, entry_id: str, author: str = "agent"
) -> EntryView:
    """Archive a requirement whose block was removed from the file (FR16a, AC22).

    Like a soft-delete, but a distinct state: gone from reads, history retained,
    and never resurrected by a later ``sync_requirements`` (D5, D15).
    """
    row = await resolve_project(session, project, for_update=True)
    entry = await _load_entry(session, row, entry_id)
    entry.status = STATUS_ARCHIVED
    entry.author = author
    entry.updated_at = _now()
    await session.flush()
    _record_revision(session, entry, ACTION_ARCHIVE, author)
    await session.flush()
    return _as_view(entry)


async def set_current_focus(
    session: AsyncSession, *, project: str, text: str, author: str = "agent"
) -> ProjectSummary:
    """Replace the active focus: resolve prior open focus rows, insert a new one (FR2, FR10)."""
    row = await resolve_project(session, project, for_update=True)
    prior = await session.execute(
        select(ContextEntry).where(
            ContextEntry.project_id == row.id,
            ContextEntry.section == SECTION_FOCUS,
            ContextEntry.status == STATUS_OPEN,
        )
    )
    for entry in prior.scalars().all():
        entry.status = STATUS_RESOLVED
        entry.author = author
        entry.updated_at = _now()
        _record_revision(session, entry, ACTION_RESOLVE, author)

    headline, detail = derive_headline_detail(
        headline=None,
        detail=text.strip() or "(focus cleared)",
        headline_max=row.headline_max_chars,
        detail_max=row.detail_max_chars,
    )
    focus = ContextEntry(
        project_id=row.id,
        section=SECTION_FOCUS,
        headline=headline,
        detail=detail,
        status=STATUS_OPEN,
        author=author,
        linked_files=[],
    )
    session.add(focus)
    await session.flush()
    _record_revision(session, focus, ACTION_CREATE, author)
    await session.flush()
    return _as_summary(row, status_line=await _status_line(session, row))


async def update_overview(
    session: AsyncSession,
    *,
    project: str,
    headline: str | None = None,
    detail: str | None = None,
    author: str = "agent",
) -> EntryView:
    """Create or merge-update the (single) open overview entry (FR2, FR10)."""
    row = await resolve_project(session, project, for_update=True)
    result = await session.execute(
        select(ContextEntry).where(
            ContextEntry.project_id == row.id,
            ContextEntry.section == SECTION_OVERVIEW,
            ContextEntry.status == STATUS_OPEN,
        )
    )
    existing = result.scalars().first()
    if existing is None:
        h, d = derive_headline_detail(
            headline=headline,
            detail=detail,
            headline_max=row.headline_max_chars,
            detail_max=row.detail_max_chars,
        )
        entry = ContextEntry(
            project_id=row.id,
            section=SECTION_OVERVIEW,
            headline=h,
            detail=d,
            status=STATUS_OPEN,
            author=author,
            linked_files=[],
        )
        session.add(entry)
        await session.flush()
        _record_revision(session, entry, ACTION_CREATE, author)
        await session.flush()
        return _as_view(entry)
    return await update_entry(
        session,
        project=row.id,
        entry_id=existing.id,
        headline=headline,
        detail=detail,
        author=author,
        expected_section=SECTION_OVERVIEW,
    )


async def set_requirement_status(
    session: AsyncSession,
    *,
    project: str,
    entry_id: str,
    status: str,
    author: str = "agent",
) -> EntryView:
    """Set a requirement's done/in-progress/blocked/not-started status (FR10, FR13, T12).

    Legacy ``done`` is allowed only when there are no criteria and no open
    blocking violations. Otherwise the close gate must pass. Evidence recording
    never calls this function (D4).
    """
    if status == REQ_DONE:
        from pcs.requirements.evidence import assert_close_gate_allows_done

        await assert_close_gate_allows_done(session, project=project, requirement_id=entry_id)
    return await update_entry(
        session,
        project=project,
        entry_id=entry_id,
        requirement_status=status,
        author=author,
        expected_section=SECTION_REQUIREMENTS,
    )


async def get_section(
    session: AsyncSession,
    *,
    project: str,
    section: str,
    include_resolved: bool = False,
) -> list[EntryView]:
    """Return verbatim entries of one section (FR7, FR9f). Deleted rows are omitted."""
    section_key = validate_section(section)
    row = await resolve_project(session, project)
    result = await session.execute(
        select(ContextEntry)
        .where(ContextEntry.project_id == row.id, ContextEntry.section == section_key)
        .order_by(ContextEntry.priority.desc(), ContextEntry.updated_at.desc())
    )
    now = _now()
    return [
        _as_view(e)
        for e in result.scalars().all()
        if _is_visible(e, row, now=now, include_resolved=include_resolved)
    ]


async def get_entry(session: AsyncSession, *, project: str, entry_id: str) -> EntryView:
    """Return one entry's verbatim headline+detail by id (FR9f, AC4a)."""
    row = await resolve_project(session, project)
    entry = await _load_entry(session, row, entry_id)
    return _as_view(entry)


async def get_entry_history(
    session: AsyncSession, *, project: str, entry_id: str
) -> list[RevisionView]:
    """Full immutable revision history, including for deleted entries (FR11, AC17)."""
    row = await resolve_project(session, project)
    entry = await _load_entry(session, row, entry_id, include_deleted=True)
    result = await session.execute(
        select(ContextEntryRevision)
        .where(ContextEntryRevision.entry_id == entry.id)
        .order_by(ContextEntryRevision.created_at.asc())
    )
    return [_as_revision(r) for r in result.scalars().all()]


async def get_project_briefing(
    session: AsyncSession,
    *,
    project: str,
    sections: Sequence[str] | None = None,
    max_tokens: int | None = None,
) -> str:
    """Assemble the §7.2a briefing (FR5, FR6, FR9, FR9a-FR9c, FR9e, FR9f)."""
    row = await resolve_project(session, project)
    budget = row.briefing_token_budget if max_tokens is None else max_tokens
    if not BRIEFING_TOKEN_MIN <= budget <= BRIEFING_TOKEN_MAX:
        raise ValidationError(
            f"max_tokens must be in [{BRIEFING_TOKEN_MIN}, {BRIEFING_TOKEN_MAX}] (FR9g)"
        )
    result = await session.execute(
        select(ContextEntry).where(
            ContextEntry.project_id == row.id,
            ContextEntry.status.notin_((STATUS_DELETED, STATUS_ARCHIVED)),
        )
    )
    now = _now()
    visible = [
        e for e in result.scalars().all() if _is_visible(e, row, now=now, include_resolved=False)
    ]
    assembly = [
        AssemblyEntry(
            id=e.id,
            section=e.section,
            headline=e.headline,
            detail=e.detail,
            priority=e.priority,
            updated_at=e.updated_at,
            related_entry_id=e.related_entry_id,
            requirement_status=e.requirement_status,
        )
        for e in visible
    ]
    runtime_ai = await load_runtime_ai_settings(session)
    return await asyncio.to_thread(
        assemble_briefing,
        project_name=row.name,
        entries=assembly,
        budget_tokens=budget,
        sections=sections,
        summarizer=Summarizer(runtime_ai.summary),
    )


# Keep T00's estimate helper importable from the service for existing unit tests.
def cap_to_tokens(text: str, max_tokens: int = BRIEFING_TOKEN_CAP) -> str:
    """Delegates to :func:`pcs.context.assembly.cap_to_tokens`."""
    from pcs.context.assembly import cap_to_tokens as _cap

    return _cap(text, max_tokens)


def format_section_text(section: str, entries: Sequence[EntryView]) -> str:
    """Verbatim resource body for one section (FR7, FR9f)."""
    lines = [f"# {section}", ""]
    if not entries:
        lines.append("(no entries)")
        return "\n".join(lines) + "\n"
    for entry in entries:
        lines.extend(
            [
                f"## [{entry.id}] {entry.headline}",
                f"status: {entry.status}",
                f"priority: {entry.priority}",
                f"author: {entry.author}",
                f"updated: {entry.updated_at.isoformat()}",
            ]
        )
        if entry.requirement_status:
            lines.append(f"requirement_status: {entry.requirement_status}")
        if entry.linked_files:
            lines.append("files: " + ", ".join(entry.linked_files))
        if entry.related_entry_id:
            lines.append(f"related: {entry.related_entry_id}")
        lines.append("")
        lines.append(entry.detail)
        lines.append("")
    return "\n".join(lines)
