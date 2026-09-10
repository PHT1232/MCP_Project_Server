"""HTTP route for read-only file source (FR34, AC13, T07).

``GET /api/projects/{project}/source?path=`` — returns
``{path, language, content, truncated}`` for one indexed file. The only server
addition T07 makes; everything else the code-map view needs already exists.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from pcs.codemap import source as source_service
from pcs.context import service as context_service
from pcs.db.base import session_scope
from pcs.index.ignore import PathTraversalError
from pcs.logging import log_tool_call

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def _caller(request: Request) -> str:
    return request.headers.get("x-pcs-caller", "frontend")


def _error_response(exc: Exception) -> JSONResponse:
    if isinstance(exc, context_service.ProjectNotFoundError):
        return JSONResponse({"error": str(exc), "available": exc.available}, status_code=404)
    if isinstance(exc, PathTraversalError):
        return JSONResponse({"error": str(exc)}, status_code=400)
    if isinstance(exc, (source_service.SourceNotIndexedError, FileNotFoundError)):
        return JSONResponse({"error": str(exc)}, status_code=404)
    if isinstance(exc, ValueError):
        return JSONResponse({"error": str(exc)}, status_code=400)
    raise exc


async def _source(request: Request) -> Response:
    caller = _caller(request)
    project = str(request.path_params["project"])
    path = request.query_params.get("path") or ""
    try:
        async with session_scope() as session:
            payload = await source_service.get_source(session, project=project, path=path)
    except Exception as exc:
        log_tool_call(tool="get_source", project=project, caller=caller, outcome=f"error: {exc}")
        return _error_response(exc)
    log_tool_call(tool="get_source", project=project, caller=caller, outcome="ok")
    return JSONResponse(payload)


def register_source_routes(mcp: FastMCP) -> None:
    """Attach the source endpoint without touching T01's route table."""
    mcp.custom_route("/api/projects/{project}/source", ["GET"])(_source)
