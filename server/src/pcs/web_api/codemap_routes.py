"""HTTP routes for the code map and codebase guide (FR32a, FR43, T06/T07, T16).

``GET /api/projects/{project}/code-map?scope=&depth=&external=`` — code map.
``GET /api/projects/{project}/codebase-guide?scope=&include=`` — codebase guide.
``POST /api/projects/{project}/codebase-guide/sync`` — sync guide artifact.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from pcs.codemap import guide
from pcs.codemap import service as codemap_service
from pcs.config import get_settings
from pcs.context import service as context_service
from pcs.context.types import ValidationError
from pcs.db.base import session_scope
from pcs.logging import log_tool_call
from pcs.repofile import dir_writable, resolve_configured_path

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def _caller(request: Request) -> str:
    return request.headers.get("x-pcs-caller", "frontend")


def _error_response(exc: Exception) -> JSONResponse:
    if isinstance(exc, context_service.ProjectNotFoundError):
        return JSONResponse({"error": str(exc), "available": exc.available}, status_code=404)
    if isinstance(exc, (ValueError, codemap_service.CodeMapError, ValidationError)):
        return JSONResponse({"error": str(exc)}, status_code=400)
    raise exc


def _artifact_metadata(root_path: str) -> dict[str, object]:
    setting = get_settings().codebase_guide_file.strip()
    try:
        target = resolve_configured_path(root_path, setting)
        parent = target.parent
        writable = parent.exists() and dir_writable(parent)
        return {
            "path": str(target),
            "file_writable": writable,
        }
    except ValueError:
        return {
            "path": None,
            "file_writable": False,
        }


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


async def _get_codebase_guide(request: Request) -> Response:
    caller = _caller(request)
    project = str(request.path_params["project"])
    scope = request.query_params.get("scope") or None
    include = request.query_params.get("include") or guide.INCLUDE_ALL
    try:
        async with session_scope() as session:
            proj_row = await context_service.resolve_project(session, project)
            payload = await guide.get_codebase_guide(
                session,
                project=project,
                scope=scope,
                include=include,
            )
            artifact = _artifact_metadata(proj_row.root_path)
            payload["artifact"] = artifact
            payload["file_path"] = artifact["path"]
            payload["file_writable"] = artifact["file_writable"]
    except Exception as exc:
        log_tool_call(
            tool="get_codebase_guide", project=project, caller=caller, outcome=f"error: {exc}"
        )
        return _error_response(exc)
    log_tool_call(tool="get_codebase_guide", project=project, caller=caller, outcome="ok")
    return JSONResponse(payload)


async def _sync_codebase_guide(request: Request) -> Response:
    caller = _caller(request)
    project = str(request.path_params["project"])
    try:
        async with session_scope() as session:
            payload = await guide.write_guide_file(
                session,
                project=project,
            )
    except Exception as exc:
        log_tool_call(
            tool="sync_codebase_guide", project=project, caller=caller, outcome=f"error: {exc}"
        )
        return _error_response(exc)
    log_tool_call(tool="sync_codebase_guide", project=project, caller=caller, outcome="ok")
    return JSONResponse(payload)


def register_codemap_routes(mcp: FastMCP) -> None:
    """Attach the code-map and codebase-guide HTTP endpoints."""
    mcp.custom_route("/api/projects/{project}/code-map", ["GET"])(_code_map)
    mcp.custom_route("/api/projects/{project}/codebase-guide", ["GET"])(_get_codebase_guide)
    mcp.custom_route("/api/projects/{project}/codebase-guide/sync", ["POST"])(_sync_codebase_guide)
