"""Context operations for the T00 slice (FR5, FR8, FR9, FR14, D3).

Pure async functions over an :class:`AsyncSession` — no MCP or HTTP imports — so
they are unit-tested directly (AGENTS.md). T01 replaces the briefing assembly
with the real deterministic §7.2a strategy and budgets.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pcs.db.models import (
    SECTION_FOCUS,
    SECTION_OVERVIEW,
    STATUS_OPEN,
    STATUS_RESOLVED,
    ContextEntry,
    Project,
)

# FR9g / D13 — hard-coded for T00; per-project configurable in T01.
BRIEFING_TOKEN_CAP = 1500
HEADLINE_MAX_CHARS = 120
_CHARS_PER_TOKEN = 4


class ProjectNotFoundError(Exception):
    """A call named a project that is not registered (D3, FR8, AC16 seed)."""

    def __init__(self, project: str, available: list[str]) -> None:
        self.project = project
        self.available = available
        listed = ", ".join(available) if available else "(none registered yet)"
        super().__init__(
            f"Unknown project {project!r}. Registered projects: {listed}. "
            "Pass an exact project name or id on every call (D3)."
        )


class DuplicateProjectError(Exception):
    """A project with this name is already registered (FR14)."""


@dataclass(frozen=True)
class ProjectSummary:
    """Lightweight view of a project row returned across the API boundary."""

    id: str
    name: str
    root_path: str


def _shorten(text: str, limit: int = HEADLINE_MAX_CHARS) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def cap_to_tokens(text: str, max_tokens: int = BRIEFING_TOKEN_CAP) -> str:
    """Deterministic hard cap (~4 chars/token). Real assembly/budgets are T01 (FR9c)."""
    max_chars = max_tokens * _CHARS_PER_TOKEN
    if len(text) <= max_chars:
        return text
    return (
        text[:max_chars].rstrip() + f"\n\n[briefing truncated to the {max_tokens}-token cap — "
        "call get_section for the full content (T01)]"
    )


async def _project_names(session: AsyncSession) -> list[str]:
    result = await session.execute(select(Project.name).order_by(Project.name))
    return list(result.scalars().all())


async def resolve_project(session: AsyncSession, project: str) -> Project:
    """Look a project up by name or id, or raise :class:`ProjectNotFoundError` (D3)."""
    key = (project or "").strip()
    if key:
        result = await session.execute(
            select(Project).where((Project.name == key) | (Project.id == key))
        )
        row = result.scalar_one_or_none()
        if row is not None:
            return row
    raise ProjectNotFoundError(project, await _project_names(session))


async def list_projects(session: AsyncSession) -> list[ProjectSummary]:
    """All registered projects, name-ordered (FR15, backs GET /api/projects)."""
    result = await session.execute(select(Project).order_by(Project.name))
    return [
        ProjectSummary(id=p.id, name=p.name, root_path=p.root_path) for p in result.scalars().all()
    ]


async def register_project(
    session: AsyncSession, *, name: str, root_path: str, overview: str, author: str = "agent"
) -> ProjectSummary:
    """Create a project row and seed its overview entry (FR14)."""
    clean_name = name.strip()
    if not clean_name:
        raise ValueError("project name must not be empty")

    existing = await session.execute(select(Project).where(Project.name == clean_name))
    if existing.scalar_one_or_none() is not None:
        raise DuplicateProjectError(f"project {clean_name!r} is already registered")

    project = Project(name=clean_name, root_path=root_path.strip())
    session.add(project)
    await session.flush()

    overview_text = overview.strip()
    session.add(
        ContextEntry(
            project_id=project.id,
            section=SECTION_OVERVIEW,
            headline=_shorten(overview_text or clean_name),
            detail=overview_text,
            status=STATUS_OPEN,
            author=author,
        )
    )
    await session.flush()
    return ProjectSummary(id=project.id, name=project.name, root_path=project.root_path)


async def set_current_focus(
    session: AsyncSession, *, project: str, text: str, author: str = "agent"
) -> ProjectSummary:
    """Replace the active focus: resolve any prior open focus, add the new one (FR2)."""
    row = await resolve_project(session, project)
    prior = await session.execute(
        select(ContextEntry).where(
            ContextEntry.project_id == row.id,
            ContextEntry.section == SECTION_FOCUS,
            ContextEntry.status == STATUS_OPEN,
        )
    )
    for entry in prior.scalars().all():
        entry.status = STATUS_RESOLVED

    focus_text = text.strip()
    session.add(
        ContextEntry(
            project_id=row.id,
            section=SECTION_FOCUS,
            headline=_shorten(focus_text or "(focus cleared)"),
            detail=focus_text,
            status=STATUS_OPEN,
            author=author,
        )
    )
    await session.flush()
    return ProjectSummary(id=row.id, name=row.name, root_path=row.root_path)


async def get_project_briefing(session: AsyncSession, *, project: str) -> str:
    """Assemble the plain-text briefing: overview + current focus only (FR5, FR9).

    T00 keeps this trivial. The deterministic multi-section assembly, collapsing,
    and drill-down pointers of §7.2a are T01.
    """
    row = await resolve_project(session, project)
    result = await session.execute(
        select(ContextEntry)
        .where(ContextEntry.project_id == row.id)
        .order_by(ContextEntry.created_at)
    )
    entries = list(result.scalars().all())

    overview = next(
        (e.detail or e.headline for e in entries if e.section == SECTION_OVERVIEW),
        "",
    ).strip()
    focus = next(
        (
            e.detail or e.headline
            for e in entries
            if e.section == SECTION_FOCUS and e.status == STATUS_OPEN
        ),
        "",
    ).strip()

    lines = [
        f"# {row.name} — project briefing",
        "",
        "## Overview",
        overview or "(no overview recorded)",
        "",
        "## Current focus",
        focus or "(no current focus set)",
    ]
    return cap_to_tokens("\n".join(lines))
