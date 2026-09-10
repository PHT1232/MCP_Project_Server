"""HTTP route for the code map (FR32a, T06/T07).

``GET /api/projects/{project}/code-map?scope=&depth=&external=`` — the same
level-of-detail contract as the ``get_code_map`` MCP tool.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from pcs.codemap import service as codemap_service
from pcs.context import service as context_service
from pcs.db.base import session_scope
from pcs.logging import log_tool_call

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


async def _code_map(request: Request) -> Response:
    caller = _caller(request)
    project = str(request.path_params["project"])
    scope = request.query_params.get("scope") or None
    depth_raw = request.query_params.get("depth")
    external = request.query_params.get("external", "").lower() in ("1", "true", "yes")
    try:
        depth = int(depth_raw) if depth_raw else codemap_service.DEFAULT_DEPTH
        async with session_scope() as session:
            payload = await codemap_service.get_code_map(
                session,
                project=project,
                scope=scope,
                depth=depth,
                include_external=external,
            )
    except Exception as exc:  # int(depth) / scope errors → 400 via _error_response
        log_tool_call(tool="get_code_map", project=project, caller=caller, outcome=f"error: {exc}")
        return _error_response(exc)
    log_tool_call(tool="get_code_map", project=project, caller=caller, outcome="ok")
    return JSONResponse(payload)


def register_codemap_routes(mcp: FastMCP) -> None:
    """Attach the code-map HTTP endpoint without touching T01's route table."""
    mcp.custom_route("/api/projects/{project}/code-map", ["GET"])(_code_map)
