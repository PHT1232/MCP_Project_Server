"""HTTP routes for index status, reindex, and keyword search (FR26, FR27, T06)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from pcs.context import service as context_service
from pcs.db.base import session_scope
from pcs.index import retrieval, service
from pcs.index.ignore import PathTraversalError
from pcs.index.search import SearchScopeName
from pcs.index.watch import ensure_watch
from pcs.logging import log_tool_call

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

_SCOPES: frozenset[str] = frozenset({"project", "subtree", "files", "focus"})


def _caller(request: Request) -> str:
    return request.headers.get("x-pcs-caller", "frontend")


def _error_response(exc: Exception) -> JSONResponse:
    if isinstance(exc, context_service.ProjectNotFoundError):
        return JSONResponse({"error": str(exc), "available": exc.available}, status_code=404)
    if isinstance(exc, (ValueError, PathTraversalError, FileNotFoundError)):
        return JSONResponse({"error": str(exc)}, status_code=400)
    raise exc


def _csv(value: str | None) -> list[str] | None:
    if not value:
        return None
    parts = [part.strip() for part in value.split(",") if part.strip()]
    return parts or None


async def _index_status(request: Request) -> Response:
    caller = _caller(request)
    project = str(request.path_params["project"])
    try:
        async with session_scope() as session:
            view = await service.get_index_status(session, project=project)
    except Exception as exc:
        log_tool_call(
            tool="get_index_status", project=project, caller=caller, outcome=f"error: {exc}"
        )
        return _error_response(exc)
    log_tool_call(tool="get_index_status", project=project, caller=caller, outcome="ok")
    return JSONResponse(view.as_dict())


async def _reindex(request: Request) -> Response:
    caller = _caller(request)
    project = str(request.path_params["project"])
    incremental = True
    try:
        try:
            body: Any = await request.json()
        except Exception:
            body = {}
        if isinstance(body, dict) and "incremental" in body:
            incremental = bool(body["incremental"])
        async with session_scope() as session:
            view = await service.reindex(session, project=project, incremental=incremental)
            row = await context_service.resolve_project(session, project)
            await ensure_watch(row.id, row.root_path)
    except Exception as exc:
        log_tool_call(tool="reindex", project=project, caller=caller, outcome=f"error: {exc}")
        return _error_response(exc)
    log_tool_call(tool="reindex", project=project, caller=caller, outcome="ok")
    return JSONResponse(view.as_dict())


async def _search(request: Request) -> Response:
    caller = _caller(request)
    project = str(request.path_params["project"])
    q = request.query_params.get("q") or request.query_params.get("query") or ""
    scope_raw = request.query_params.get("scope") or "project"
    subtree = request.query_params.get("subtree")
    files = _csv(request.query_params.get("files"))
    globs = _csv(request.query_params.get("globs"))
    limit_raw = request.query_params.get("limit")
    try:
        if scope_raw not in _SCOPES:
            raise ValueError(f"scope must be one of {sorted(_SCOPES)}; got {scope_raw!r}")
        limit = int(limit_raw) if limit_raw else 20
        async with session_scope() as session:
            payload = await service.search_code(
                session,
                project=project,
                query=q,
                scope=cast(SearchScopeName, scope_raw),
                subtree=subtree,
                files=files,
                globs=globs,
                limit=limit,
            )
    except Exception as exc:
        log_tool_call(tool="search_code", project=project, caller=caller, outcome=f"error: {exc}")
        return _error_response(exc)
    log_tool_call(tool="search_code", project=project, caller=caller, outcome="ok")
    return JSONResponse(payload)


async def _retrieve_context(request: Request) -> Response:
    caller = _caller(request)
    project = str(request.path_params["project"])
    try:
        try:
            body: Any = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}
        task = str(body.get("task") or request.query_params.get("task") or "")
        max_tokens = int(body.get("max_tokens") or request.query_params.get("max_tokens") or 1500)
        async with session_scope() as session:
            payload = await retrieval.retrieve_context(
                session, project=project, task=task, max_tokens=max_tokens
            )
    except Exception as exc:
        log_tool_call(
            tool="retrieve_context", project=project, caller=caller, outcome=f"error: {exc}"
        )
        return _error_response(exc)
    log_tool_call(tool="retrieve_context", project=project, caller=caller, outcome="ok")
    return JSONResponse(payload)


async def _prepare_task(request: Request) -> Response:
    caller = _caller(request)
    project = str(request.path_params["project"])
    try:
        try:
            body: Any = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}
        task = str(body.get("task") or request.query_params.get("task") or "")
        raw_budget = body.get("max_tokens") or request.query_params.get("max_tokens")
        max_tokens = int(raw_budget) if raw_budget else None
        async with session_scope() as session:
            payload = await retrieval.prepare_task(
                session, project=project, task=task, max_tokens=max_tokens
            )
    except Exception as exc:
        log_tool_call(tool="prepare_task", project=project, caller=caller, outcome=f"error: {exc}")
        return _error_response(exc)
    log_tool_call(tool="prepare_task", project=project, caller=caller, outcome="ok")
    return JSONResponse(payload)


def register_index_routes(mcp: FastMCP) -> None:
    """Attach index HTTP endpoints without modifying T01's route table."""
    mcp.custom_route("/api/projects/{project}/index", ["GET"])(_index_status)
    mcp.custom_route("/api/projects/{project}/reindex", ["POST"])(_reindex)
    mcp.custom_route("/api/projects/{project}/search", ["GET"])(_search)
    mcp.custom_route("/api/projects/{project}/retrieve-context", ["POST"])(_retrieve_context)
    mcp.custom_route("/api/projects/{project}/prepare-task", ["POST"])(_prepare_task)
