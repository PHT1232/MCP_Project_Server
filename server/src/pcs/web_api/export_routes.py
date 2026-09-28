"""HTTP route for full project-context export (Markdown / JSON).

``GET /api/projects/{project}/export?format=markdown|json`` — identical
envelope to the MCP ``export_project_context`` tool.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from pcs.context import service as context_service
from pcs.context.export import EXPORT_FORMAT_MARKDOWN, export_project_context
from pcs.context.types import ValidationError
from pcs.db.base import session_scope
from pcs.logging import log_tool_call

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def _caller(request: Request) -> str:
    return request.headers.get("x-pcs-caller", "frontend")


def _error_response(exc: Exception) -> JSONResponse:
    if isinstance(exc, context_service.ProjectNotFoundError):
        return JSONResponse({"error": str(exc), "available": exc.available}, status_code=404)
    if isinstance(exc, (ValueError, ValidationError)):
        return JSONResponse({"error": str(exc)}, status_code=400)
    raise exc


async def _export(request: Request) -> Response:
    caller = _caller(request)
    project = str(request.path_params["project"])
    fmt = request.query_params.get("format") or EXPORT_FORMAT_MARKDOWN
    try:
        async with session_scope() as session:
            payload = await export_project_context(session, project=project, format=fmt)
    except Exception as exc:
        log_tool_call(
            tool="export_project_context",
            project=project,
            caller=caller,
            outcome=f"error: {exc}",
        )
        return _error_response(exc)
    log_tool_call(tool="export_project_context", project=project, caller=caller, outcome="ok")
    return JSONResponse(payload)


def register_export_routes(mcp: FastMCP) -> None:
    """Attach the project-context export HTTP endpoint."""
    mcp.custom_route("/api/projects/{project}/export", ["GET"])(_export)
