"""Plain-HTTP routes for the frontend (non-MCP).

Registered on the same Starlette app as the streamable-HTTP MCP transport. Every
handler is a thin shell over :mod:`pcs.context.service` -- the exact same logic
the MCP tools call -- so the frontend and agents never drift apart (AC14).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from pcs.config import get_settings
from pcs.context import service
from pcs.context.types import SECTION_REQUIREMENTS
from pcs.db.base import session_scope
from pcs.index.service import index_if_root_exists
from pcs.index.watch import ensure_watch
from pcs.logging import log_tool_call
from pcs.requirements import service as requirements_service

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

_Handler = Callable[[Request], Awaitable[Response]]


def _project_json(summary: service.ProjectSummary) -> dict[str, object]:
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


def _caller(request: Request) -> str:
    return request.headers.get("x-pcs-caller", "frontend")


async def _sync_if_requirement(
    session: AsyncSession, project: str, caller: str, section: str
) -> dict[str, object] | None:
    """Write a requirements-section change through to the file (FR16a, D12)."""
    if section != SECTION_REQUIREMENTS:
        return None
    report = await requirements_service.write_through_requirement_change(
        session, project=project, author=caller
    )
    if report is None:
        return None
    return {
        "path": report.file_path,
        "written": report.file_written,
        "writable": report.file_writable,
        "errors": list(report.errors),
        "reconciliations": [n.as_dict() for n in report.reconciliations],
    }


def _with_file_sync(
    payload: dict[str, object], file_sync: dict[str, object] | None
) -> dict[str, object]:
    if file_sync is not None:
        payload["requirements_file"] = file_sync
    return payload


def _error_response(exc: Exception) -> JSONResponse:
    if isinstance(exc, service.ProjectNotFoundError):
        return JSONResponse({"error": str(exc), "available": exc.available}, status_code=404)
    if isinstance(exc, service.EntryNotFoundError):
        return JSONResponse({"error": str(exc)}, status_code=404)
    if isinstance(exc, (ValueError, service.DuplicateProjectError, service.ValidationError)):
        return JSONResponse({"error": str(exc)}, status_code=400)
    raise exc


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
    return JSONResponse([_project_json(p) for p in projects])


async def _register_project(request: Request) -> Response:
    caller = _caller(request)
    name = ""
    try:
        body = await _json_object(request)
        name = str(body.get("name", ""))
        async with session_scope() as session:
            summary = await service.register_project(
                session,
                name=name,
                root_path=str(body.get("root_path", "")),
                overview=str(body.get("overview", "")),
                author=caller,
            )
            await index_if_root_exists(session, project=summary.id, root_path=summary.root_path)
            await ensure_watch(summary.id, summary.root_path)
            await requirements_service.write_through_requirement_change(
                session, project=summary.id, author=caller
            )
    except Exception as exc:
        log_tool_call(tool="register_project", project=name, caller=caller, outcome=f"error: {exc}")
        return _error_response(exc)
    log_tool_call(tool="register_project", project=summary.id, caller=caller, outcome="ok")
    return JSONResponse(_project_json(summary), status_code=201)


async def _configure_project(request: Request) -> Response:
    caller = _caller(request)
    project = str(request.path_params["project"])
    body = await _json_object(request)
    try:
        async with session_scope() as session:
            summary = await service.configure_project(
                session,
                project=project,
                expiry_policy=_opt_str(body, "expiry_policy"),
                expiry_days=_opt_int(body, "expiry_days"),
                briefing_token_budget=_opt_int(body, "briefing_token_budget"),
                prepare_task_token_budget=_opt_int(body, "prepare_task_token_budget"),
                headline_max_chars=_opt_int(body, "headline_max_chars"),
                detail_max_chars=_opt_int(body, "detail_max_chars"),
            )
    except Exception as exc:
        log_tool_call(
            tool="configure_project", project=project, caller=caller, outcome=f"error: {exc}"
        )
        return _error_response(exc)
    log_tool_call(tool="configure_project", project=project, caller=caller, outcome="ok")
    return JSONResponse(_project_json(summary))


async def _briefing(request: Request) -> Response:
    caller = _caller(request)
    project = str(request.path_params["project"])
    sections = _csv(request.query_params.get("sections"))
    max_tokens_raw = request.query_params.get("max_tokens")
    max_tokens = int(max_tokens_raw) if max_tokens_raw else None
    try:
        async with session_scope() as session:
            text = await service.get_project_briefing(
                session, project=project, sections=sections, max_tokens=max_tokens, caller=caller
            )
    except Exception as exc:
        log_tool_call(
            tool="get_project_briefing", project=project, caller=caller, outcome=f"error: {exc}"
        )
        return _error_response(exc)
    log_tool_call(tool="get_project_briefing", project=project, caller=caller, outcome="ok")
    return JSONResponse({"project": project, "briefing": text})


async def _get_section(request: Request) -> Response:
    caller = _caller(request)
    project = str(request.path_params["project"])
    section = str(request.path_params["section"])
    include_resolved = request.query_params.get("include_resolved", "").lower() in {
        "1",
        "true",
        "yes",
    }
    try:
        async with session_scope() as session:
            entries = await service.get_section(
                session, project=project, section=section, include_resolved=include_resolved
            )
    except Exception as exc:
        log_tool_call(tool="get_section", project=project, caller=caller, outcome=f"error: {exc}")
        return _error_response(exc)
    log_tool_call(tool="get_section", project=project, caller=caller, outcome="ok")
    return JSONResponse({"section": section, "entries": [e.as_dict() for e in entries]})


async def _add_entry(request: Request) -> Response:
    caller = _caller(request)
    project = str(request.path_params["project"])
    body = await _json_object(request)
    priority = _opt_int(body, "priority")
    try:
        async with session_scope() as session:
            view = await service.add_entry(
                session,
                project=project,
                section=str(body.get("section", "")),
                headline=_opt_str(body, "headline"),
                detail=_opt_str(body, "detail"),
                priority=0 if priority is None else priority,
                author=caller,
                requirement_status=_opt_str(body, "requirement_status") or _opt_str(body, "status"),
                linked_files=_opt_str_list(body, "linked_files"),
                related_entry_id=_opt_str(body, "related_entry_id"),
                diagram=_opt_str(body, "diagram"),
            )
            file_sync = await _sync_if_requirement(session, project, caller, view.section)
    except Exception as exc:
        log_tool_call(tool="add_entry", project=project, caller=caller, outcome=f"error: {exc}")
        return _error_response(exc)
    log_tool_call(tool="add_entry", project=project, caller=caller, outcome="ok")
    return JSONResponse(_with_file_sync(view.as_dict(), file_sync), status_code=201)


async def _get_entry(request: Request) -> Response:
    caller = _caller(request)
    project = str(request.path_params["project"])
    entry_id = str(request.path_params["entry_id"])
    try:
        async with session_scope() as session:
            view = await service.get_entry(session, project=project, entry_id=entry_id)
    except Exception as exc:
        log_tool_call(tool="get_entry", project=project, caller=caller, outcome=f"error: {exc}")
        return _error_response(exc)
    log_tool_call(tool="get_entry", project=project, caller=caller, outcome="ok")
    return JSONResponse(view.as_dict())


async def _patch_entry(request: Request) -> Response:
    caller = _caller(request)
    project = str(request.path_params["project"])
    entry_id = str(request.path_params["entry_id"])
    body = await _json_object(request)
    try:
        async with session_scope() as session:
            view = await service.update_entry(
                session,
                project=project,
                entry_id=entry_id,
                headline=_opt_str(body, "headline"),
                detail=_opt_str(body, "detail"),
                priority=_opt_int(body, "priority"),
                author=caller,
                requirement_status=_opt_str(body, "requirement_status") or _opt_str(body, "status"),
                linked_files=_opt_str_list(body, "linked_files"),
                related_entry_id=_opt_str(body, "related_entry_id"),
                diagram=_opt_str(body, "diagram"),
            )
            file_sync = await _sync_if_requirement(session, project, caller, view.section)
    except Exception as exc:
        log_tool_call(tool="update_entry", project=project, caller=caller, outcome=f"error: {exc}")
        return _error_response(exc)
    log_tool_call(tool="update_entry", project=project, caller=caller, outcome="ok")
    return JSONResponse(_with_file_sync(view.as_dict(), file_sync))


async def _resolve_entry(request: Request) -> Response:
    caller = _caller(request)
    project = str(request.path_params["project"])
    entry_id = str(request.path_params["entry_id"])
    try:
        async with session_scope() as session:
            view = await service.resolve_entry(
                session, project=project, entry_id=entry_id, author=caller
            )
            file_sync = await _sync_if_requirement(session, project, caller, view.section)
    except Exception as exc:
        log_tool_call(tool="resolve_entry", project=project, caller=caller, outcome=f"error: {exc}")
        return _error_response(exc)
    log_tool_call(tool="resolve_entry", project=project, caller=caller, outcome="ok")
    return JSONResponse(_with_file_sync(view.as_dict(), file_sync))


async def _delete_entry(request: Request) -> Response:
    caller = _caller(request)
    project = str(request.path_params["project"])
    entry_id = str(request.path_params["entry_id"])
    try:
        async with session_scope() as session:
            view = await service.delete_entry(
                session, project=project, entry_id=entry_id, author=caller
            )
            file_sync = await _sync_if_requirement(session, project, caller, view.section)
    except Exception as exc:
        log_tool_call(tool="delete_entry", project=project, caller=caller, outcome=f"error: {exc}")
        return _error_response(exc)
    log_tool_call(tool="delete_entry", project=project, caller=caller, outcome="ok")
    return JSONResponse(_with_file_sync(view.as_dict(), file_sync))


async def _entry_history(request: Request) -> Response:
    caller = _caller(request)
    project = str(request.path_params["project"])
    entry_id = str(request.path_params["entry_id"])
    try:
        async with session_scope() as session:
            revisions = await service.get_entry_history(session, project=project, entry_id=entry_id)
    except Exception as exc:
        log_tool_call(
            tool="get_entry_history", project=project, caller=caller, outcome=f"error: {exc}"
        )
        return _error_response(exc)
    log_tool_call(tool="get_entry_history", project=project, caller=caller, outcome="ok")
    return JSONResponse({"entry_id": entry_id, "revisions": [r.as_dict() for r in revisions]})


async def _set_focus(request: Request) -> Response:
    caller = _caller(request)
    project = str(request.path_params["project"])
    body = await _json_object(request)
    try:
        async with session_scope() as session:
            summary = await service.set_current_focus(
                session, project=project, text=str(body.get("text", "")), author=caller
            )
    except Exception as exc:
        log_tool_call(
            tool="set_current_focus", project=project, caller=caller, outcome=f"error: {exc}"
        )
        return _error_response(exc)
    log_tool_call(tool="set_current_focus", project=project, caller=caller, outcome="ok")
    return JSONResponse(_project_json(summary))


async def _list_requirements(request: Request) -> Response:
    """Read-only requirements list for the frontend view (AC14a). No file write."""
    caller = _caller(request)
    project = str(request.path_params["project"])
    try:
        async with session_scope() as session:
            reqs = await requirements_service.list_requirements(session, project=project)
    except Exception as exc:
        log_tool_call(
            tool="list_requirements", project=project, caller=caller, outcome=f"error: {exc}"
        )
        return _error_response(exc)
    log_tool_call(tool="list_requirements", project=project, caller=caller, outcome="ok")
    done = sum(1 for r in reqs if r.status == "done")
    return JSONResponse(
        {
            "requirements": [r.as_dict() for r in reqs],
            "done_count": done,
            "total_count": len(reqs),
        }
    )


async def _sync_requirements(request: Request) -> Response:
    """Re-parse the requirements file and reconcile with the store (FR16a, D12)."""
    caller = _caller(request)
    project = str(request.path_params["project"])
    try:
        async with session_scope() as session:
            report = await requirements_service.sync_requirements(
                session, project=project, author=caller
            )
    except Exception as exc:
        log_tool_call(
            tool="sync_requirements", project=project, caller=caller, outcome=f"error: {exc}"
        )
        return _error_response(exc)
    log_tool_call(tool="sync_requirements", project=project, caller=caller, outcome="ok")
    return JSONResponse(report.as_dict())


def _opt_str(body: Mapping[str, object], key: str) -> str | None:
    if key not in body or body[key] is None:
        return None
    return str(body[key])


def _opt_int(body: Mapping[str, object], key: str) -> int | None:
    if key not in body or body[key] is None:
        return None
    return int(str(body[key]))


def _opt_str_list(body: Mapping[str, object], key: str) -> list[str] | None:
    if key not in body or body[key] is None:
        return None
    raw = body[key]
    if not isinstance(raw, list):
        raise service.ValidationError(f"{key} must be a list of strings")
    return [str(item) for item in raw]


async def _json_object(request: Request) -> dict[str, object]:
    raw = await request.json()
    if not isinstance(raw, dict):
        raise service.ValidationError("JSON body must be an object")
    return {str(k): v for k, v in raw.items()}


def _csv(value: str | None) -> Sequence[str] | None:
    if not value:
        return None
    return [part.strip() for part in value.split(",") if part.strip()]


_ROUTES: list[tuple[str, list[str], _Handler]] = [
    ("/api/health", ["GET"], _health),
    ("/api/projects", ["GET"], _list_projects),
    ("/api/projects", ["POST"], _register_project),
    ("/api/projects/{project}", ["PATCH"], _configure_project),
    ("/api/projects/{project}/briefing", ["GET"], _briefing),
    ("/api/projects/{project}/focus", ["PUT"], _set_focus),
    ("/api/projects/{project}/sections/{section}", ["GET"], _get_section),
    ("/api/projects/{project}/entries", ["POST"], _add_entry),
    ("/api/projects/{project}/entries/{entry_id}", ["GET"], _get_entry),
    ("/api/projects/{project}/entries/{entry_id}", ["PATCH"], _patch_entry),
    ("/api/projects/{project}/entries/{entry_id}", ["DELETE"], _delete_entry),
    ("/api/projects/{project}/entries/{entry_id}/resolve", ["POST"], _resolve_entry),
    ("/api/projects/{project}/entries/{entry_id}/history", ["GET"], _entry_history),
    ("/api/projects/{project}/requirements", ["GET"], _list_requirements),
    ("/api/projects/{project}/requirements/sync", ["POST"], _sync_requirements),
]


def register_routes(mcp: FastMCP) -> None:
    """Attach the ``/api`` routes to ``mcp``'s HTTP app."""
    for path, methods, handler in _ROUTES:
        mcp.custom_route(path, methods)(handler)
