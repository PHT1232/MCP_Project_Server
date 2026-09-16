"""Starlette HTTP routes for Plan & Task Orchestration (T24, AC-PLAN-7, FR43-FR48).

Every handler delegates to :mod:`pcs.planning.service` — the same functions the
MCP tools call. Caller identity comes from ``x-pcs-caller`` (default
``"frontend"``). Audit lines omit tokens and request payloads (NFR6, INV-PLAN-3).
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from pcs.context import service as context_service
from pcs.db.base import session_scope
from pcs.logging import log_tool_call
from pcs.mcp.planning_tools import (
    EMPTY_MUTATION,
    EXPLICIT_NULL,
    UNKNOWN_FIELDS,
    audit_outcome,
    dependency_specs_from_payload,
    task_specs_from_payload,
)
from pcs.planning import generator
from pcs.planning import service as planning
from pcs.planning.errors import (
    ClaimConflictError,
    InvalidStateTransitionError,
    PlanningValidationError,
    PlanNotActiveError,
    PlanNotFoundError,
    StaleClaimTokenError,
    TaskNotFoundError,
)
from pcs.planning.types import DEFAULT_LEASE_SECONDS

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

_Handler = Callable[[Request], Awaitable[Response]]


def _caller(request: Request) -> str:
    return request.headers.get("x-pcs-caller", "frontend")


def _error_response(exc: Exception) -> JSONResponse:
    """Map planning exceptions to HTTP status codes (T24 error table)."""
    if isinstance(exc, context_service.ProjectNotFoundError):
        return JSONResponse({"error": str(exc), "available": exc.available}, status_code=404)
    if isinstance(exc, (PlanNotFoundError, TaskNotFoundError)):
        return JSONResponse({"error": str(exc)}, status_code=404)
    if isinstance(exc, (ClaimConflictError, StaleClaimTokenError, PlanNotActiveError)):
        return JSONResponse({"error": str(exc)}, status_code=409)
    if isinstance(exc, InvalidStateTransitionError):
        return JSONResponse({"error": str(exc)}, status_code=400)
    if isinstance(exc, (PlanningValidationError, ValueError)):
        return JSONResponse({"error": str(exc)}, status_code=400)
    raise exc


async def _json_object(request: Request) -> dict[str, object]:
    try:
        raw = await request.json()
    except Exception:
        raise PlanningValidationError("JSON body must be an object") from None
    if not isinstance(raw, dict):
        raise PlanningValidationError("JSON body must be an object")
    return {str(k): v for k, v in raw.items()}


async def _json_object_or_empty(request: Request) -> dict[str, object]:
    body = await request.body()
    if not body:
        return {}
    try:
        raw = json.loads(body)
    except Exception:
        raise PlanningValidationError("JSON body must be an object") from None
    if not isinstance(raw, dict):
        raise PlanningValidationError("JSON body must be an object")
    return {str(k): v for k, v in raw.items()}


def _reject_unknown(body: Mapping[str, object], allowed: frozenset[str]) -> None:
    if any(name not in allowed for name in body):
        raise PlanningValidationError(UNKNOWN_FIELDS)


def _as_str(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise PlanningValidationError(f"{field} must be a string")
    return value


def _as_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PlanningValidationError(f"{field} must be an integer")
    return value


def _as_str_list(value: object, *, field: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise PlanningValidationError(f"{field} must be a list of strings")
    return [str(item) for item in value]


def _required_str(body: Mapping[str, object], key: str) -> str:
    if key not in body or body[key] is None:
        raise PlanningValidationError(f"{key} is required")
    return _as_str(body[key], field=key)


def _optional_typed[T](
    body: Mapping[str, object],
    key: str,
    convert: Callable[[object], T],
) -> T | None:
    if key not in body:
        return None
    value = body[key]
    if value is None:
        raise PlanningValidationError(EXPLICIT_NULL)
    return convert(value)


def _optional_or_default[T](
    body: Mapping[str, object],
    key: str,
    convert: Callable[[object], T],
    default: T,
) -> T:
    if key not in body:
        return default
    value = body[key]
    if value is None:
        raise PlanningValidationError(EXPLICIT_NULL)
    return convert(value)


def _merge_kwargs(
    body: Mapping[str, object],
    converters: Mapping[str, Callable[[object], object]],
) -> dict[str, Any]:
    """Pass only JSON-present fields so omitted keys stay."""
    _reject_unknown(body, frozenset(converters))
    kwargs: dict[str, Any] = {}
    for name, convert in converters.items():
        if name not in body:
            continue
        value = body[name]
        if value is None:
            raise PlanningValidationError(EXPLICIT_NULL)
        kwargs[name] = convert(value)
    if not kwargs:
        raise PlanningValidationError(EMPTY_MUTATION)
    return kwargs


async def _handle(
    request: Request,
    tool: str,
    fn: Callable[[AsyncSession], Awaitable[Any]],
    *,
    status_code: int = 200,
) -> Response:
    """Run ``fn`` in a session, map errors, and emit the NFR6 audit line."""
    caller_name = _caller(request)
    project = str(request.path_params["project"])
    try:
        async with session_scope() as session:
            payload = await fn(session)
    except Exception as exc:
        log_tool_call(tool=tool, project=project, caller=caller_name, outcome=audit_outcome(exc))
        return _error_response(exc)
    log_tool_call(tool=tool, project=project, caller=caller_name, outcome="ok")
    return JSONResponse(payload, status_code=status_code)


async def _create_plan(request: Request) -> Response:
    async def fn(session: AsyncSession) -> dict[str, object]:
        body = await _json_object(request)
        _reject_unknown(body, frozenset({"title", "goal"}))
        view = await planning.create_plan(
            session,
            project=str(request.path_params["project"]),
            title=_required_str(body, "title"),
            goal=_required_str(body, "goal"),
            author=_caller(request),
        )
        return view.as_dict()

    return await _handle(request, "create_plan", fn, status_code=201)


async def _create_plan_with_tasks(request: Request) -> Response:
    async def fn(session: AsyncSession) -> dict[str, object]:
        body = await _json_object(request)
        _reject_unknown(body, frozenset({"title", "goal", "tasks", "dependencies"}))
        view = await planning.create_plan_with_tasks(
            session,
            project=str(request.path_params["project"]),
            title=_required_str(body, "title"),
            goal=_required_str(body, "goal"),
            tasks=task_specs_from_payload(body.get("tasks")),
            dependencies=dependency_specs_from_payload(body.get("dependencies")),
            author=_caller(request),
        )
        return view.as_dict()

    return await _handle(request, "create_plan_with_tasks", fn, status_code=201)


async def _list_plans(request: Request) -> Response:
    async def fn(session: AsyncSession) -> list[dict[str, object]]:
        status = request.query_params.get("status")
        views = await planning.list_plans(
            session, project=str(request.path_params["project"]), status=status
        )
        return [view.as_dict() for view in views]

    return await _handle(request, "list_plans", fn)


async def _get_plan(request: Request) -> Response:
    async def fn(session: AsyncSession) -> dict[str, object]:
        view = await planning.get_plan(
            session,
            project=str(request.path_params["project"]),
            plan_id=str(request.path_params["plan_id"]),
        )
        return view.as_dict()

    return await _handle(request, "get_plan", fn)


async def _update_plan(request: Request) -> Response:
    async def fn(session: AsyncSession) -> dict[str, object]:
        body = await _json_object(request)
        kwargs = _merge_kwargs(
            body,
            {
                "title": lambda value: _as_str(value, field="title"),
                "goal": lambda value: _as_str(value, field="goal"),
            },
        )
        view = await planning.update_plan(
            session,
            project=str(request.path_params["project"]),
            plan_id=str(request.path_params["plan_id"]),
            **kwargs,
        )
        return view.as_dict()

    return await _handle(request, "update_plan", fn)


async def _archive_plan(request: Request) -> Response:
    async def fn(session: AsyncSession) -> dict[str, object]:
        view = await planning.archive_plan(
            session,
            project=str(request.path_params["project"]),
            plan_id=str(request.path_params["plan_id"]),
            actor=_caller(request),
        )
        return view.as_dict()

    return await _handle(request, "archive_plan", fn)


async def _activate_plan(request: Request) -> Response:
    async def fn(session: AsyncSession) -> dict[str, object]:
        view = await planning.activate_plan(
            session,
            project=str(request.path_params["project"]),
            plan_id=str(request.path_params["plan_id"]),
            actor=_caller(request),
        )
        return view.as_dict()

    return await _handle(request, "activate_plan", fn)


async def _complete_plan(request: Request) -> Response:
    async def fn(session: AsyncSession) -> dict[str, object]:
        view = await planning.complete_plan(
            session,
            project=str(request.path_params["project"]),
            plan_id=str(request.path_params["plan_id"]),
            actor=_caller(request),
        )
        return view.as_dict()

    return await _handle(request, "complete_plan", fn)


async def _add_plan_task(request: Request) -> Response:
    async def fn(session: AsyncSession) -> dict[str, object]:
        body = await _json_object(request)
        _reject_unknown(
            body,
            frozenset(
                {
                    "local_task_id",
                    "title",
                    "objective",
                    "acceptance_criteria",
                    "linked_files",
                    "requirement_ids",
                    "priority",
                }
            ),
        )
        view = await planning.add_plan_task(
            session,
            project=str(request.path_params["project"]),
            plan_id=str(request.path_params["plan_id"]),
            local_task_id=_required_str(body, "local_task_id"),
            title=_required_str(body, "title"),
            objective=_required_str(body, "objective"),
            acceptance_criteria=_optional_typed(
                body,
                "acceptance_criteria",
                lambda value: _as_str_list(value, field="acceptance_criteria"),
            ),
            linked_files=_optional_typed(
                body, "linked_files", lambda value: _as_str_list(value, field="linked_files")
            ),
            requirement_ids=_optional_typed(
                body, "requirement_ids", lambda value: _as_str_list(value, field="requirement_ids")
            ),
            priority=_optional_or_default(
                body, "priority", lambda value: _as_int(value, field="priority"), 0
            ),
            actor=_caller(request),
        )
        return view.as_dict()

    return await _handle(request, "add_plan_task", fn, status_code=201)


async def _update_plan_task(request: Request) -> Response:
    async def fn(session: AsyncSession) -> dict[str, object]:
        body = await _json_object(request)
        kwargs = _merge_kwargs(
            body,
            {
                "title": lambda value: _as_str(value, field="title"),
                "objective": lambda value: _as_str(value, field="objective"),
                "acceptance_criteria": lambda value: _as_str_list(
                    value, field="acceptance_criteria"
                ),
                "linked_files": lambda value: _as_str_list(value, field="linked_files"),
                "requirement_ids": lambda value: _as_str_list(value, field="requirement_ids"),
                "priority": lambda value: _as_int(value, field="priority"),
                "claim_token": lambda value: _as_str(value, field="claim_token"),
            },
        )
        view = await planning.update_plan_task(
            session,
            project=str(request.path_params["project"]),
            plan_id=str(request.path_params["plan_id"]),
            task_id=str(request.path_params["task_id"]),
            actor=_caller(request),
            **kwargs,
        )
        return view.as_dict()

    return await _handle(request, "update_plan_task", fn)


async def _add_task_dependency(request: Request) -> Response:
    async def fn(session: AsyncSession) -> dict[str, object]:
        body = await _json_object(request)
        _reject_unknown(body, frozenset({"task_id", "depends_on_task_id"}))
        task_id = _required_str(body, "task_id")
        depends_on_task_id = _required_str(body, "depends_on_task_id")
        await planning.add_task_dependency(
            session,
            project=str(request.path_params["project"]),
            plan_id=str(request.path_params["plan_id"]),
            task_id=task_id,
            depends_on_task_id=depends_on_task_id,
            actor=_caller(request),
        )
        return {"task_id": task_id, "depends_on_task_id": depends_on_task_id}

    return await _handle(request, "add_task_dependency", fn)


async def _list_ready_tasks(request: Request) -> Response:
    async def fn(session: AsyncSession) -> list[dict[str, object]]:
        plan_id = request.path_params.get("plan_id")
        views = await planning.list_ready_tasks(
            session,
            project=str(request.path_params["project"]),
            plan_id=str(plan_id) if plan_id is not None else None,
        )
        return [view.as_dict() for view in views]

    return await _handle(request, "list_ready_tasks", fn)


async def _claim_task(request: Request) -> Response:
    async def fn(session: AsyncSession) -> dict[str, object]:
        body = await _json_object(request)
        _reject_unknown(body, frozenset({"claimed_by", "lease_seconds"}))
        result = await planning.claim_task(
            session,
            project=str(request.path_params["project"]),
            plan_id=str(request.path_params["plan_id"]),
            task_id=str(request.path_params["task_id"]),
            claimed_by=_required_str(body, "claimed_by"),
            lease_seconds=_optional_or_default(
                body,
                "lease_seconds",
                lambda value: _as_int(value, field="lease_seconds"),
                DEFAULT_LEASE_SECONDS,
            ),
        )
        return result.as_dict()

    return await _handle(request, "claim_task", fn)


async def _heartbeat_task(request: Request) -> Response:
    async def fn(session: AsyncSession) -> dict[str, object]:
        body = await _json_object(request)
        _reject_unknown(body, frozenset({"claim_token", "lease_seconds"}))
        view = await planning.heartbeat_task(
            session,
            project=str(request.path_params["project"]),
            plan_id=str(request.path_params["plan_id"]),
            task_id=str(request.path_params["task_id"]),
            claim_token=_required_str(body, "claim_token"),
            lease_seconds=_optional_or_default(
                body,
                "lease_seconds",
                lambda value: _as_int(value, field="lease_seconds"),
                DEFAULT_LEASE_SECONDS,
            ),
        )
        return view.as_dict()

    return await _handle(request, "heartbeat_task", fn)


async def _release_task(request: Request) -> Response:
    async def fn(session: AsyncSession) -> dict[str, object]:
        body = await _json_object(request)
        _reject_unknown(body, frozenset({"claim_token"}))
        view = await planning.release_task(
            session,
            project=str(request.path_params["project"]),
            plan_id=str(request.path_params["plan_id"]),
            task_id=str(request.path_params["task_id"]),
            claim_token=_required_str(body, "claim_token"),
        )
        return view.as_dict()

    return await _handle(request, "release_task", fn)


async def _set_task_status(request: Request) -> Response:
    async def fn(session: AsyncSession) -> dict[str, object]:
        body = await _json_object(request)
        _reject_unknown(body, frozenset({"status", "claim_token", "reason"}))
        view = await planning.set_task_status(
            session,
            project=str(request.path_params["project"]),
            plan_id=str(request.path_params["plan_id"]),
            task_id=str(request.path_params["task_id"]),
            status=_required_str(body, "status"),
            claim_token=_optional_typed(
                body, "claim_token", lambda value: _as_str(value, field="claim_token")
            ),
            reason=_optional_typed(body, "reason", lambda value: _as_str(value, field="reason")),
            actor=_caller(request),
        )
        return view.as_dict()

    return await _handle(request, "set_task_status", fn)


async def _complete_task(request: Request) -> Response:
    async def fn(session: AsyncSession) -> dict[str, object]:
        body = await _json_object_or_empty(request)
        _reject_unknown(body, frozenset({"claim_token"}))
        view = await planning.complete_task(
            session,
            project=str(request.path_params["project"]),
            plan_id=str(request.path_params["plan_id"]),
            task_id=str(request.path_params["task_id"]),
            claim_token=_optional_typed(
                body, "claim_token", lambda value: _as_str(value, field="claim_token")
            ),
            actor=_caller(request),
        )
        return view.as_dict()

    return await _handle(request, "complete_task", fn)


async def _generate_plan_draft(request: Request) -> Response:
    async def fn(session: AsyncSession) -> dict[str, object]:
        body = await _json_object(request)
        _reject_unknown(body, frozenset({"goal", "constraints", "max_tasks"}))
        result = await generator.generate_plan_draft(
            session,
            project=str(request.path_params["project"]),
            goal=_required_str(body, "goal"),
            constraints=_optional_typed(
                body, "constraints", lambda value: _as_str(value, field="constraints")
            ),
            max_tasks=_optional_or_default(
                body,
                "max_tasks",
                lambda value: _as_int(value, field="max_tasks"),
                generator.MAX_TASKS_DEFAULT,
            ),
        )
        return result.as_dict()

    return await _handle(request, "generate_plan_draft", fn)


async def _get_task_history(request: Request) -> Response:
    async def fn(session: AsyncSession) -> list[dict[str, object]]:
        events = await planning.get_task_history(
            session,
            project=str(request.path_params["project"]),
            plan_id=str(request.path_params["plan_id"]),
            task_id=str(request.path_params["task_id"]),
        )
        return [event.as_dict() for event in events]

    return await _handle(request, "get_task_history", fn)


def register_planning_routes(mcp: FastMCP) -> None:
    """Attach the nested T24 planning HTTP routes (AC-PLAN-7)."""
    routes: list[tuple[str, list[str], _Handler]] = [
        ("/api/projects/{project}/plans", ["POST"], _create_plan),
        ("/api/projects/{project}/plans/with-tasks", ["POST"], _create_plan_with_tasks),
        ("/api/projects/{project}/plans/generate-draft", ["POST"], _generate_plan_draft),
        ("/api/projects/{project}/plans", ["GET"], _list_plans),
        ("/api/projects/{project}/plans/{plan_id}", ["GET"], _get_plan),
        ("/api/projects/{project}/plans/{plan_id}", ["PATCH"], _update_plan),
        ("/api/projects/{project}/plans/{plan_id}/archive", ["POST"], _archive_plan),
        ("/api/projects/{project}/plans/{plan_id}/activate", ["POST"], _activate_plan),
        ("/api/projects/{project}/plans/{plan_id}/tasks", ["POST"], _add_plan_task),
        (
            "/api/projects/{project}/plans/{plan_id}/tasks/{task_id}",
            ["PATCH"],
            _update_plan_task,
        ),
        (
            "/api/projects/{project}/plans/{plan_id}/dependencies",
            ["POST"],
            _add_task_dependency,
        ),
        ("/api/projects/{project}/ready-tasks", ["GET"], _list_ready_tasks),
        (
            "/api/projects/{project}/plans/{plan_id}/ready-tasks",
            ["GET"],
            _list_ready_tasks,
        ),
        (
            "/api/projects/{project}/plans/{plan_id}/tasks/{task_id}/claim",
            ["POST"],
            _claim_task,
        ),
        (
            "/api/projects/{project}/plans/{plan_id}/tasks/{task_id}/heartbeat",
            ["POST"],
            _heartbeat_task,
        ),
        (
            "/api/projects/{project}/plans/{plan_id}/tasks/{task_id}/release",
            ["POST"],
            _release_task,
        ),
        (
            "/api/projects/{project}/plans/{plan_id}/tasks/{task_id}/status",
            ["POST"],
            _set_task_status,
        ),
        (
            "/api/projects/{project}/plans/{plan_id}/tasks/{task_id}/complete",
            ["POST"],
            _complete_task,
        ),
        (
            "/api/projects/{project}/plans/{plan_id}/complete",
            ["POST"],
            _complete_plan,
        ),
        (
            "/api/projects/{project}/plans/{plan_id}/tasks/{task_id}/history",
            ["GET"],
            _get_task_history,
        ),
    ]
    for path, methods, handler in routes:
        mcp.custom_route(path, methods)(handler)
