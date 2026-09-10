"""FastMCP app + tool definitions for the walking skeleton.

Tool bodies delegate to :mod:`pcs.context.service` (unit-tested without this
layer) and emit the mandatory audit line for every call (NFR6). Unknown/missing
``project`` raises :class:`~pcs.context.service.ProjectNotFoundError`, whose
message lists the registered projects (D3, FR8, AC16 seed).
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from starlette.applications import Starlette

from pcs.config import get_settings
from pcs.context import service
from pcs.db.base import session_scope
from pcs.logging import log_tool_call
from pcs.web_api import register_routes

_settings = get_settings()

mcp: FastMCP = FastMCP(
    "pcs",
    instructions=(
        "Project Context MCP Server (walking skeleton). Register a project, set "
        "its current focus, then fetch a compact briefing. Every call must name "
        "its project explicitly."
    ),
    host=_settings.bind_host,
    port=_settings.port,
)


def _caller(ctx: Context[Any, Any] | None) -> str:
    """Best-effort MCP client identity for the audit log (NFR6).

    ``ctx`` is ``None`` when a tool is invoked outside a live request (e.g. tests
    calling ``mcp.call_tool`` directly); the audit line still records "unknown".
    """
    if ctx is None:
        return "unknown"
    try:
        params = ctx.session.client_params
        if params is not None and params.clientInfo is not None:
            return str(params.clientInfo.name)
    except (AttributeError, ValueError):
        return "unknown"
    return getattr(ctx, "client_id", None) or "unknown"


@mcp.tool()
async def register_project(
    name: str, root_path: str, overview: str, ctx: Context[Any, Any] | None = None
) -> dict[str, str]:
    """Register a new project and seed its overview entry (FR14, D3).

    Args:
        name: Human-readable, unique project name.
        root_path: Absolute path to the project repository on the host.
        overview: What the project is and its purpose (stored verbatim, FR4).
    """
    caller = _caller(ctx)
    try:
        async with session_scope() as session:
            summary = await service.register_project(
                session, name=name, root_path=root_path, overview=overview, author=caller
            )
    except Exception as exc:
        log_tool_call(tool="register_project", project=name, caller=caller, outcome=f"error: {exc}")
        raise
    log_tool_call(tool="register_project", project=summary.id, caller=caller, outcome="ok")
    return {"id": summary.id, "name": summary.name, "root_path": summary.root_path}


@mcp.tool()
async def set_current_focus(
    project: str, text: str, ctx: Context[Any, Any] | None = None
) -> dict[str, str]:
    """Replace the project's current focus so the briefing has something to show.

    Args:
        project: Exact project name or id (D3).
        text: The task(s) actively being worked on.
    """
    caller = _caller(ctx)
    try:
        async with session_scope() as session:
            summary = await service.set_current_focus(
                session, project=project, text=text, author=caller
            )
    except Exception as exc:
        log_tool_call(
            tool="set_current_focus", project=project, caller=caller, outcome=f"error: {exc}"
        )
        raise
    log_tool_call(tool="set_current_focus", project=summary.id, caller=caller, outcome="ok")
    return {"id": summary.id, "name": summary.name}


@mcp.tool()
async def get_project_briefing(project: str, ctx: Context[Any, Any] | None = None) -> str:
    """Return the compact plain-text briefing (overview + current focus) (FR5, FR9).

    Args:
        project: Exact project name or id (D3). Unknown/missing values raise an
            error listing the registered projects.
    """
    caller = _caller(ctx)
    try:
        async with session_scope() as session:
            text = await service.get_project_briefing(session, project=project)
    except Exception as exc:
        log_tool_call(
            tool="get_project_briefing", project=project, caller=caller, outcome=f"error: {exc}"
        )
        raise
    log_tool_call(tool="get_project_briefing", project=project, caller=caller, outcome="ok")
    return text


register_routes(mcp)


def build_http_app() -> Starlette:
    """The streamable-HTTP MCP app with the ``/api`` routes mounted."""
    return mcp.streamable_http_app()
