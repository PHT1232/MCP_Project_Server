"""MCP tool registration for the curated context store (FR5-FR13, FR15).

Each tool is a thin wrapper: resolve caller → ``session_scope`` → one service
call → ``log_tool_call`` (NFR6). SQL stays in :mod:`pcs.context.service`.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from sqlalchemy.ext.asyncio import AsyncSession

from pcs.context import service
from pcs.context.types import SECTION_REQUIREMENTS
from pcs.mcp.support import caller, run_tool

_CRUD_SECTIONS: tuple[tuple[str, str], ...] = (
    ("focus", "focus"),
    ("blockers", "blocker"),
    ("bugs", "bug"),
    ("conventions", "convention"),
    ("decisions", "decision"),
    ("glossary", "glossary"),
)


def register_tools(mcp: FastMCP) -> None:
    """Attach every T01 context tool to ``mcp``."""
    _register_read_tools(mcp)
    _register_lifecycle_tools(mcp)
    _register_overview_focus(mcp)
    for section, singular in _CRUD_SECTIONS:
        _register_crud(mcp, section, singular)
    _register_requirement_tools(mcp)
    _register_delete(mcp)


def _register_read_tools(mcp: FastMCP) -> None:
    @mcp.tool()
    async def get_project_briefing(
        project: str | None = None,
        sections: list[str] | None = None,
        max_tokens: int | None = None,
        ctx: Context[Any, Any] | None = None,
    ) -> str:
        """Return the compact project briefing (FR5, FR6, FR9, §7.2a).

        Args:
            project: Exact project name or id (D3). Missing/unknown values raise
                an error listing the registered projects (AC16).
            sections: Optional subset of sections to include (FR6).
            max_tokens: Per-call budget override (500-4000); default is the
                project's configured briefing budget (FR9g).
        """

        async def op(session: AsyncSession) -> str:
            return await service.get_project_briefing(
                session, project=project or "", sections=sections, max_tokens=max_tokens
            )

        return await run_tool("get_project_briefing", project, ctx, op)

    @mcp.tool()
    async def get_section(
        section: str,
        project: str | None = None,
        include_resolved: bool = False,
        ctx: Context[Any, Any] | None = None,
    ) -> dict[str, object]:
        """Return verbatim headline+detail for every entry in one section (FR7, FR9f).

        Args:
            section: One of overview, focus, blockers, bugs, conventions,
                decisions, requirements, glossary.
            project: Exact project name or id (D3).
            include_resolved: If true, include resolved (but not deleted) entries.
        """

        async def op(session: AsyncSession) -> dict[str, object]:
            entries = await service.get_section(
                session,
                project=project or "",
                section=section,
                include_resolved=include_resolved,
            )
            return {"section": section, "entries": [e.as_dict() for e in entries]}

        return await run_tool("get_section", project, ctx, op)

    @mcp.tool()
    async def get_entry(
        entry_id: str,
        project: str | None = None,
        ctx: Context[Any, Any] | None = None,
    ) -> dict[str, object]:
        """Return one entry's verbatim detail by id (FR9f, AC4a). Deleted entries 404."""

        async def op(session: AsyncSession) -> dict[str, object]:
            view = await service.get_entry(session, project=project or "", entry_id=entry_id)
            return view.as_dict()

        return await run_tool("get_entry", project, ctx, op)

    @mcp.tool()
    async def get_entry_history(
        entry_id: str,
        project: str | None = None,
        ctx: Context[Any, Any] | None = None,
    ) -> dict[str, object]:
        """Return the immutable revision history of an entry (FR11, AC17)."""

        async def op(session: AsyncSession) -> dict[str, object]:
            revisions = await service.get_entry_history(
                session, project=project or "", entry_id=entry_id
            )
            return {"entry_id": entry_id, "revisions": [r.as_dict() for r in revisions]}

        return await run_tool("get_entry_history", project, ctx, op)

    @mcp.tool()
    async def list_projects(ctx: Context[Any, Any] | None = None) -> list[dict[str, object]]:
        """List registered projects with a one-line status each (FR15)."""

        async def op(session: AsyncSession) -> list[dict[str, object]]:
            return [_project_dict(p) for p in await service.list_projects(session)]

        return await run_tool("list_projects", None, ctx, op)


def _register_lifecycle_tools(mcp: FastMCP) -> None:
    @mcp.tool()
    async def register_project(
        name: str,
        root_path: str,
        overview: str,
        ctx: Context[Any, Any] | None = None,
    ) -> dict[str, object]:
        """Register a new project and seed its overview entry (FR14, D3)."""

        async def op(session: AsyncSession) -> dict[str, object]:
            summary = await service.register_project(
                session,
                name=name,
                root_path=root_path,
                overview=overview,
                author=caller(ctx),
            )
            return _project_dict(summary)

        return await run_tool("register_project", name, ctx, op)

    @mcp.tool()
    async def configure_project(
        project: str | None = None,
        expiry_policy: str | None = None,
        expiry_days: int | None = None,
        briefing_token_budget: int | None = None,
        prepare_task_token_budget: int | None = None,
        headline_max_chars: int | None = None,
        detail_max_chars: int | None = None,
        ctx: Context[Any, Any] | None = None,
    ) -> dict[str, object]:
        """Set per-project budgets and expiry policy (FR3a, FR9g). Defaults stay D13."""

        async def op(session: AsyncSession) -> dict[str, object]:
            summary = await service.configure_project(
                session,
                project=project or "",
                expiry_policy=expiry_policy,
                expiry_days=expiry_days,
                briefing_token_budget=briefing_token_budget,
                prepare_task_token_budget=prepare_task_token_budget,
                headline_max_chars=headline_max_chars,
                detail_max_chars=detail_max_chars,
            )
            return _project_dict(summary)

        return await run_tool("configure_project", project, ctx, op)


def _register_overview_focus(mcp: FastMCP) -> None:
    @mcp.tool()
    async def update_overview(
        project: str | None = None,
        headline: str | None = None,
        detail: str | None = None,
        ctx: Context[Any, Any] | None = None,
    ) -> dict[str, object]:
        """Create or merge-update the project's overview (FR2, FR10)."""

        async def op(session: AsyncSession) -> dict[str, object]:
            view = await service.update_overview(
                session,
                project=project or "",
                headline=headline,
                detail=detail,
                author=caller(ctx),
            )
            return view.as_dict()

        return await run_tool("update_overview", project, ctx, op)

    @mcp.tool()
    async def set_current_focus(
        text: str,
        project: str | None = None,
        ctx: Context[Any, Any] | None = None,
    ) -> dict[str, object]:
        """Replace the project's current focus (resolves prior open focus rows)."""

        async def op(session: AsyncSession) -> dict[str, object]:
            summary = await service.set_current_focus(
                session, project=project or "", text=text, author=caller(ctx)
            )
            return _project_dict(summary)

        return await run_tool("set_current_focus", project, ctx, op)


def _register_crud(mcp: FastMCP, section: str, singular: str) -> None:
    add_name = f"add_{singular}"
    update_name = f"update_{singular}"
    resolve_name = f"resolve_{singular}"

    async def add_tool(
        project: str | None = None,
        headline: str | None = None,
        detail: str | None = None,
        priority: int = 0,
        related_entry_id: str | None = None,
        ctx: Context[Any, Any] | None = None,
    ) -> dict[str, object]:
        async def op(session: AsyncSession) -> dict[str, object]:
            view = await service.add_entry(
                session,
                project=project or "",
                section=section,
                headline=headline,
                detail=detail,
                priority=priority,
                author=caller(ctx),
                related_entry_id=related_entry_id,
            )
            return view.as_dict()

        return await run_tool(add_name, project, ctx, op)

    async def update_tool(
        entry_id: str,
        project: str | None = None,
        headline: str | None = None,
        detail: str | None = None,
        priority: int | None = None,
        related_entry_id: str | None = None,
        ctx: Context[Any, Any] | None = None,
    ) -> dict[str, object]:
        async def op(session: AsyncSession) -> dict[str, object]:
            view = await service.update_entry(
                session,
                project=project or "",
                entry_id=entry_id,
                headline=headline,
                detail=detail,
                priority=priority,
                author=caller(ctx),
                related_entry_id=related_entry_id,
                expected_section=section,
            )
            return view.as_dict()

        return await run_tool(update_name, project, ctx, op)

    async def resolve_tool(
        entry_id: str,
        project: str | None = None,
        ctx: Context[Any, Any] | None = None,
    ) -> dict[str, object]:
        async def op(session: AsyncSession) -> dict[str, object]:
            view = await service.resolve_entry(
                session,
                project=project or "",
                entry_id=entry_id,
                author=caller(ctx),
                expected_section=section,
            )
            return view.as_dict()

        return await run_tool(resolve_name, project, ctx, op)

    add_tool.__name__ = add_name
    add_tool.__doc__ = f"Add a {singular} to the project context store (FR10, FR13)."
    update_tool.__name__ = update_name
    update_tool.__doc__ = f"Merge-update a {singular} entry (FR10, FR17)."
    resolve_tool.__name__ = resolve_name
    resolve_tool.__doc__ = f"Resolve a {singular} so it leaves the active briefing (FR12)."
    mcp.tool(name=add_name)(add_tool)
    mcp.tool(name=update_name)(update_tool)
    mcp.tool(name=resolve_name)(resolve_tool)


def _register_requirement_tools(mcp: FastMCP) -> None:
    @mcp.tool()
    async def add_requirement(
        project: str | None = None,
        headline: str | None = None,
        detail: str | None = None,
        status: str = "not-started",
        linked_files: list[str] | None = None,
        related_entry_id: str | None = None,
        priority: int = 0,
        ctx: Context[Any, Any] | None = None,
    ) -> dict[str, object]:
        """Add a requirement to the store (FR10). File sync is T02."""

        async def op(session: AsyncSession) -> dict[str, object]:
            view = await service.add_entry(
                session,
                project=project or "",
                section=SECTION_REQUIREMENTS,
                headline=headline,
                detail=detail,
                priority=priority,
                author=caller(ctx),
                requirement_status=status,
                linked_files=linked_files,
                related_entry_id=related_entry_id,
            )
            return view.as_dict()

        return await run_tool("add_requirement", project, ctx, op)

    @mcp.tool()
    async def update_requirement(
        entry_id: str,
        project: str | None = None,
        headline: str | None = None,
        detail: str | None = None,
        linked_files: list[str] | None = None,
        related_entry_id: str | None = None,
        priority: int | None = None,
        ctx: Context[Any, Any] | None = None,
    ) -> dict[str, object]:
        """Merge-update a requirement's headline/detail/links (FR10, FR17)."""

        async def op(session: AsyncSession) -> dict[str, object]:
            view = await service.update_entry(
                session,
                project=project or "",
                entry_id=entry_id,
                headline=headline,
                detail=detail,
                priority=priority,
                author=caller(ctx),
                linked_files=linked_files,
                related_entry_id=related_entry_id,
                expected_section=SECTION_REQUIREMENTS,
            )
            return view.as_dict()

        return await run_tool("update_requirement", project, ctx, op)

    @mcp.tool()
    async def set_requirement_status(
        entry_id: str,
        status: str,
        project: str | None = None,
        ctx: Context[Any, Any] | None = None,
    ) -> dict[str, object]:
        """Set a requirement's status: not-started | in-progress | blocked | done (FR10)."""

        async def op(session: AsyncSession) -> dict[str, object]:
            view = await service.set_requirement_status(
                session,
                project=project or "",
                entry_id=entry_id,
                status=status,
                author=caller(ctx),
            )
            return view.as_dict()

        return await run_tool("set_requirement_status", project, ctx, op)

    @mcp.tool()
    async def resolve_requirement(
        entry_id: str,
        project: str | None = None,
        ctx: Context[Any, Any] | None = None,
    ) -> dict[str, object]:
        """Resolve a requirement (lifecycle); use set_requirement_status for done/not-started."""

        async def op(session: AsyncSession) -> dict[str, object]:
            view = await service.resolve_entry(
                session,
                project=project or "",
                entry_id=entry_id,
                author=caller(ctx),
                expected_section=SECTION_REQUIREMENTS,
            )
            return view.as_dict()

        return await run_tool("resolve_requirement", project, ctx, op)


def _register_delete(mcp: FastMCP) -> None:
    @mcp.tool()
    async def delete_entry(
        entry_id: str,
        project: str | None = None,
        ctx: Context[Any, Any] | None = None,
    ) -> dict[str, object]:
        """Soft-delete an entry. It disappears from reads; history is kept (FR11, AC17)."""

        async def op(session: AsyncSession) -> dict[str, object]:
            view = await service.delete_entry(
                session, project=project or "", entry_id=entry_id, author=caller(ctx)
            )
            return view.as_dict()

        return await run_tool("delete_entry", project, ctx, op)


def _project_dict(summary: service.ProjectSummary) -> dict[str, object]:
    return {
        "id": summary.id,
        "name": summary.name,
        "root_path": summary.root_path,
        "status_line": summary.status_line,
        "briefing_token_budget": summary.briefing_token_budget,
        "prepare_task_token_budget": summary.prepare_task_token_budget,
        "headline_max_chars": summary.headline_max_chars,
        "detail_max_chars": summary.detail_max_chars,
        "expiry_policy": summary.expiry_policy,
        "expiry_days": summary.expiry_days,
    }
