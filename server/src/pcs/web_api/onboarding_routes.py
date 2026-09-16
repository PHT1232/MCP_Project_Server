"""HTTP routes for one-call agent bootstrap tools (T-ONBOARD, add_new_project).

``GET /api/projects/{project}/onboard`` — identical shape to the MCP ``onboard`` tool.
``POST /api/projects/add-new-project`` — identical shape to the MCP ``add_new_project`` tool.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from pcs.codemap import service as codemap_service
from pcs.context import service as context_service
from pcs.db.base import session_scope
from pcs.logging import log_tool_call
from pcs.mcp.onboarding_tools import TOOL_USAGE, compose_add_new_project
from pcs.planning import service as planning_service

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def _caller(request: Request) -> str:
    return request.headers.get("x-pcs-caller", "frontend")


async def _json_object(request: Request) -> dict[str, object]:
    try:
        raw = await request.json()
    except Exception:
        raise context_service.ValidationError("JSON body must be an object") from None
    if not isinstance(raw, dict):
        raise context_service.ValidationError("JSON body must be an object")
    return {str(k): v for k, v in raw.items()}


def _error_response(exc: Exception) -> JSONResponse:
    if isinstance(exc, context_service.ProjectNotFoundError):
        return JSONResponse({"error": str(exc), "available": exc.available}, status_code=404)
    if isinstance(
        exc,
        (ValueError, context_service.ValidationError, context_service.DuplicateProjectError),
    ):
        return JSONResponse({"error": str(exc)}, status_code=400)
    raise exc


async def _onboard(request: Request) -> Response:
    caller = _caller(request)
    project = str(request.path_params["project"])
    try:
        async with session_scope() as session:
            briefing = await context_service.get_project_briefing(
                session, project=project, caller=caller
            )
            ready_views = await planning_service.list_ready_tasks(
                session, project=project, plan_id=None
            )
            code_map = await codemap_service.get_code_map(session, project=project)
            payload = {
                "tool_usage": TOOL_USAGE,
                "briefing": briefing,
                "ready_tasks": [view.as_dict() for view in ready_views],
                "code_map": code_map,
            }
    except Exception as exc:
        log_tool_call(tool="onboard", project=project, caller=caller, outcome=f"error: {exc}")
        return _error_response(exc)
    log_tool_call(tool="onboard", project=project, caller=caller, outcome="ok")
    return JSONResponse(payload)


async def _add_new_project(request: Request) -> Response:
    caller = _caller(request)
    name = ""
    try:
        body = await _json_object(request)
        name = str(body.get("name", ""))
        async with session_scope() as session:
            payload = await compose_add_new_project(
                session,
                name=name,
                root_path=str(body.get("root_path", "")),
                overview=str(body.get("overview", "")),
                author=caller,
            )
    except Exception as exc:
        log_tool_call(tool="add_new_project", project=name, caller=caller, outcome=f"error: {exc}")
        return _error_response(exc)
    log_tool_call(tool="add_new_project", project=name, caller=caller, outcome="ok")
    return JSONResponse(payload, status_code=201)


def register_onboarding_routes(mcp: FastMCP) -> None:
    """Attach the onboard and add_new_project HTTP endpoints."""
    mcp.custom_route("/api/projects/add-new-project", ["POST"])(_add_new_project)
    mcp.custom_route("/api/projects/{project}/onboard", ["GET"])(_onboard)
