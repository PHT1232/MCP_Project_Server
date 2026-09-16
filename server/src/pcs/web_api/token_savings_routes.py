"""HTTP routes for reading the token-savings log.

Read-only — writes happen as a side effect of retrieve_context, search_code,
prepare_task, and get_project_briefing themselves (pcs.token_savings.service).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from pcs.context import service as context_service
from pcs.db.base import session_scope
from pcs.logging import log_tool_call
from pcs.token_savings.service import get_token_savings_summary, list_token_savings

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def _caller(request: Request) -> str:
    return request.headers.get("x-pcs-caller", "frontend")


def _error_response(exc: Exception) -> JSONResponse:
    if isinstance(exc, context_service.ProjectNotFoundError):
        return JSONResponse({"error": str(exc), "available": exc.available}, status_code=404)
    if isinstance(exc, ValueError):
        return JSONResponse({"error": str(exc)}, status_code=400)
    raise exc


async def _list_log(request: Request) -> Response:
    caller = _caller(request)
    project = str(request.path_params["project"])
    operation = request.query_params.get("operation")
    limit_raw = request.query_params.get("limit")
    try:
        limit = int(limit_raw) if limit_raw else 100
        async with session_scope() as session:
            payload = await list_token_savings(session, project, operation=operation, limit=limit)
    except Exception as exc:
        log_tool_call(
            tool="get_token_savings_log", project=project, caller=caller, outcome=f"error: {exc}"
        )
        return _error_response(exc)
    log_tool_call(tool="get_token_savings_log", project=project, caller=caller, outcome="ok")
    return JSONResponse(payload)


async def _summary(request: Request) -> Response:
    caller = _caller(request)
    project = str(request.path_params["project"])
    try:
        async with session_scope() as session:
            payload = await get_token_savings_summary(session, project)
    except Exception as exc:
        log_tool_call(
            tool="get_token_savings_summary",
            project=project,
            caller=caller,
            outcome=f"error: {exc}",
        )
        return _error_response(exc)
    log_tool_call(tool="get_token_savings_summary", project=project, caller=caller, outcome="ok")
    return JSONResponse(payload)


def register_token_savings_routes(mcp: FastMCP) -> None:
    """Attach the token-savings log read routes."""
    mcp.custom_route("/api/projects/{project}/token-savings", ["GET"])(_list_log)
    mcp.custom_route("/api/projects/{project}/token-savings/summary", ["GET"])(_summary)
