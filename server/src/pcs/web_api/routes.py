"""Plain-HTTP routes for the frontend (non-MCP).

Registered on the same Starlette app as the streamable-HTTP MCP transport. Every
handler is a thin shell over :mod:`pcs.context.service` -- the exact same logic
the MCP tools call -- so the frontend and agents never drift apart.

T00 scope (task file) names ``GET /api/health`` and ``GET /api/projects``.
``POST /api/projects`` and ``GET /api/projects/{project}/briefing`` are added
because the reference page must register a project and render its briefing
without embedding an MCP JSON-RPC client in the browser (see handoff).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from pcs.config import get_settings
from pcs.context import service
from pcs.db.base import session_scope
from pcs.logging import log_tool_call

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

_Handler = Callable[[Request], Awaitable[Response]]


def _summary_json(summary: service.ProjectSummary) -> dict[str, str]:
    return {"id": summary.id, "name": summary.name, "root_path": summary.root_path}


async def _health(_request: Request) -> Response:
    settings = get_settings()
    return JSONResponse(
        {
            "status": "ok",
            "bind_mode": settings.bind_mode,
            "bind_host": settings.bind_host,
        }
    )


async def _list_projects(_request: Request) -> Response:
    async with session_scope() as session:
        projects = await service.list_projects(session)
    return JSONResponse([_summary_json(p) for p in projects])


async def _register_project(request: Request) -> Response:
    caller = request.headers.get("x-pcs-caller", "frontend")
    body = await request.json()
    name = str(body.get("name", ""))
    root_path = str(body.get("root_path", ""))
    overview = str(body.get("overview", ""))
    try:
        async with session_scope() as session:
            summary = await service.register_project(
                session, name=name, root_path=root_path, overview=overview, author=caller
            )
    except (ValueError, service.DuplicateProjectError) as exc:
        log_tool_call(tool="register_project", project=name, caller=caller, outcome=f"error: {exc}")
        return JSONResponse({"error": str(exc)}, status_code=400)
    log_tool_call(tool="register_project", project=summary.id, caller=caller, outcome="ok")
    return JSONResponse(_summary_json(summary), status_code=201)


async def _briefing(request: Request) -> Response:
    caller = request.headers.get("x-pcs-caller", "frontend")
    project = str(request.path_params["project"])
    try:
        async with session_scope() as session:
            text = await service.get_project_briefing(session, project=project)
    except service.ProjectNotFoundError as exc:
        log_tool_call(
            tool="get_project_briefing", project=project, caller=caller, outcome="not_found"
        )
        return JSONResponse({"error": str(exc), "available": exc.available}, status_code=404)
    log_tool_call(tool="get_project_briefing", project=project, caller=caller, outcome="ok")
    return JSONResponse({"project": project, "briefing": text})


_ROUTES: list[tuple[str, list[str], _Handler]] = [
    ("/api/health", ["GET"], _health),
    ("/api/projects", ["GET"], _list_projects),
    ("/api/projects", ["POST"], _register_project),
    ("/api/projects/{project}/briefing", ["GET"], _briefing),
]


def register_routes(mcp: FastMCP) -> None:
    """Attach the ``/api`` routes to ``mcp``'s HTTP app."""
    for path, methods, handler in _ROUTES:
        mcp.custom_route(path, methods)(handler)
