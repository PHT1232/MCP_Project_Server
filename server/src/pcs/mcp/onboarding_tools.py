"""MCP surface for one-call agent bootstrap tools (T-ONBOARD, add_new_project).

Thin composers over existing services — no new business logic and no content
generation. Every call emits the NFR6 audit line via :func:`pcs.mcp.support.run_tool`.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from sqlalchemy.ext.asyncio import AsyncSession

from pcs.codemap import service as codemap_service
from pcs.context import service as context_service
from pcs.context.types import ProjectSummary
from pcs.index.service import get_index_status, index_if_root_exists
from pcs.index.watch import ensure_watch
from pcs.mcp.support import caller, run_tool
from pcs.planning import service as planning_service
from pcs.requirements import service as requirements_service

TOOL_USAGE = (
    "pcs is the exclusive tool for this project: code search (search_code / "
    "retrieve_context / get_code_map instead of grep or ad-hoc file exploration), "
    'context and "remember this" notes (add_focus / add_blocker / add_bug / '
    "add_convention / add_decision / add_requirement / add_feature instead of local "
    "scratch notes), and planning (create_plan_with_tasks / list_ready_tasks / "
    "claim_task / set_task_status / complete_task). If pcs is unreachable or this "
    "project isn't registered, stop and ask before silently falling back to anything else."
)

NEXT_STEPS = (
    "1. Confirm indexing settled: call get_index_status; if file_count is 0, call reindex.\n"
    "2. Requirements: call get_section with section 'requirements' to see whether a file "
    "already synced. If nothing is defined yet, ASK THE USER before writing any — never "
    "invent them. Then add_requirement per item, or sync_requirements if a file is the "
    "source of truth.\n"
    "3. Conventions: call search_code and get_code_map (never grep) to find real observed "
    "patterns, then add_convention for those — not assumed ones.\n"
    "4. Features: add_feature per major feature with detail=overview, linked_files, "
    "related_entry_id if applicable, and diagram as a Mermaid sequenceDiagram.\n"
    "5. File explanations: describe_files for important files (entry points, core modules).\n"
    "6. update_overview if the one-liner given at registration needs expanding once the "
    "codebase is understood.\n"
    "7. set_current_focus once oriented.\n"
    "8. Going forward: add_decision / add_blocker / add_bug as they arise, and "
    "create_plan_with_tasks once work splits into ordered pieces.\n"
    "Everything above is agent- or human-authored. pcs never invents requirements, "
    "conventions, features, diagrams, or summaries itself."
)


def _project_payload(summary: ProjectSummary) -> dict[str, object]:
    """Same field set as ``register_project`` / ``_project_dict`` (FR14)."""
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


async def compose_add_new_project(
    session: AsyncSession,
    *,
    name: str,
    root_path: str,
    overview: str,
    author: str,
) -> dict[str, object]:
    """Register, index, watch, and sync requirements, then return a fixed checklist.

    Reuses the ``register_project`` MCP sequence (FR14, FR16a, FR24) plus
    ``get_index_status`` / ``get_code_map``. Never synthesizes requirements,
    conventions, features, diagrams, or file summaries.
    """
    summary = await context_service.register_project(
        session, name=name, root_path=root_path, overview=overview, author=author
    )
    await index_if_root_exists(session, project=summary.id, root_path=summary.root_path)
    await ensure_watch(summary.id, summary.root_path)
    await requirements_service.write_through_requirement_change(
        session, project=summary.id, author=author
    )
    index_status = await get_index_status(session, project=summary.id)
    code_map = await codemap_service.get_code_map(session, project=summary.id)
    return {
        "project": _project_payload(summary),
        "index_status": index_status.as_dict(),
        "code_map": code_map,
        "next_steps": NEXT_STEPS,
    }


def register_onboarding_tools(mcp: FastMCP) -> None:
    """Attach the onboard and add_new_project MCP tools."""

    @mcp.tool()
    async def onboard(
        project: str | None = None,
        ctx: Context[Any, Any] | None = None,
    ) -> dict[str, object]:
        """One-call bootstrap for a fresh agent session on a pcs-registered project.

        Args:
            project: Exact project name or id (D3).

        Composes the pcs-first tool-usage rule with the project's live briefing
        (get_project_briefing), ready tasks (list_ready_tasks), and the top tier
        of the code map (get_code_map) — everything a new agent needs before it
        starts working, in a single call.
        """
        who = caller(ctx)

        async def op(session: AsyncSession) -> dict[str, object]:
            briefing = await context_service.get_project_briefing(
                session, project=project or "", caller=who
            )
            ready_views = await planning_service.list_ready_tasks(
                session, project=project or "", plan_id=None
            )
            code_map = await codemap_service.get_code_map(session, project=project or "")
            return {
                "tool_usage": TOOL_USAGE,
                "briefing": briefing,
                "ready_tasks": [view.as_dict() for view in ready_views],
                "code_map": code_map,
            }

        return await run_tool("onboard", project, ctx, op)

    @mcp.tool()
    async def add_new_project(
        name: str,
        root_path: str,
        overview: str,
        ctx: Context[Any, Any] | None = None,
    ) -> dict[str, object]:
        """Register a project, index it, and return a fixed onboarding checklist.

        Thin composer over the existing ``register_project`` sequence plus
        ``get_index_status`` and ``get_code_map``. Does not invent requirements,
        conventions, features, diagrams, or summaries.
        """
        who = caller(ctx)

        async def op(session: AsyncSession) -> dict[str, object]:
            return await compose_add_new_project(
                session,
                name=name,
                root_path=root_path,
                overview=overview,
                author=who,
            )

        return await run_tool("add_new_project", name, ctx, op)
