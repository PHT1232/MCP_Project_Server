"""HTTP reads (T13) and authoring mutations (T14) for requirement contracts.

Mutations delegate to ``pcs.requirements.contracts``; adapters do not write
rows or reimplement validation (INV-AUTHOR-1). Audit lines omit contract prose
and caller payload (INV-AUTHOR-7).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import TYPE_CHECKING, Any, Final

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from pcs.context import service as context_service
from pcs.context.types import ContractNotFoundError, ValidationError
from pcs.db.base import session_scope
from pcs.logging import log_tool_call
from pcs.mcp.contract_tools import (
    EMPTY_MUTATION,
    EXPLICIT_NULL,
    UNKNOWN_FIELDS,
    audit_outcome,
)
from pcs.requirements import briefing, compliance, contracts

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

_Handler = Callable[[Request], Awaitable[Response]]

INVARIANT_CREATE_FIELDS: Final = frozenset({"statement", "kind", "risk", "key", "sort_order"})
CRITERION_CREATE_FIELDS: Final = frozenset(
    {"statement", "evidence_kind", "key", "required", "independent_review", "sort_order"}
)


def _caller(request: Request) -> str:
    return request.headers.get("x-pcs-caller", "frontend")


def _error_response(exc: Exception) -> JSONResponse:
    if isinstance(exc, context_service.ProjectNotFoundError):
        return JSONResponse({"error": str(exc), "available": exc.available}, status_code=404)
    if isinstance(exc, (context_service.EntryNotFoundError, ContractNotFoundError)):
        return JSONResponse({"error": str(exc)}, status_code=404)
    if isinstance(exc, (ValueError, ValidationError)):
        return JSONResponse({"error": str(exc)}, status_code=400)
    raise exc


async def _json_object(request: Request) -> dict[str, object]:
    try:
        raw = await request.json()
    except Exception:
        raise ValidationError("JSON body must be an object") from None
    if not isinstance(raw, dict):
        raise ValidationError("JSON body must be an object")
    return {str(k): v for k, v in raw.items()}


def _reject_unknown(body: Mapping[str, object], allowed: frozenset[str]) -> None:
    if any(name not in allowed for name in body):
        raise ValidationError(UNKNOWN_FIELDS)


def _as_str(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{field} must be a string")
    return value


def _as_bool(value: object, *, field: str) -> bool:
    if isinstance(value, bool):
        return value
    raise ValidationError(f"{field} must be a boolean")


def _as_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(f"{field} must be an integer")
    return value


def _required_str(body: Mapping[str, object], key: str) -> str:
    if key not in body or body[key] is None:
        raise ValidationError(f"{key} is required")
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
        raise ValidationError(EXPLICIT_NULL)
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
        raise ValidationError(EXPLICIT_NULL)
    return convert(value)


def _merge_kwargs(
    body: Mapping[str, object],
    converters: Mapping[str, Callable[[object], object]],
) -> dict[str, Any]:
    """Pass only JSON-present fields so omitted keys stay (INV-AUTHOR-4)."""
    _reject_unknown(body, frozenset(converters))
    kwargs: dict[str, Any] = {}
    for name, convert in converters.items():
        if name not in body:
            continue
        value = body[name]
        if value is None:
            raise ValidationError(EXPLICIT_NULL)
        kwargs[name] = convert(value)
    if not kwargs:
        raise ValidationError(EMPTY_MUTATION)
    return kwargs


async def _read(request: Request, *, tool: str) -> Response:
    caller = _caller(request)
    project = str(request.path_params["project"])
    requirement_id = str(request.path_params["requirement_id"])
    try:
        async with session_scope() as session:
            if tool == "get_requirement_contract":
                payload = await briefing.get_requirement_contract(
                    session,
                    project=project,
                    requirement_id=requirement_id,
                    include=request.query_params.get("include", "both"),
                )
            else:
                payload = await compliance.compact_requirement_evidence(
                    session, project=project, requirement_id=requirement_id
                )
    except Exception as exc:
        log_tool_call(tool=tool, project=project, caller=caller, outcome=audit_outcome(exc))
        return _error_response(exc)
    log_tool_call(tool=tool, project=project, caller=caller, outcome="ok")
    return JSONResponse(payload)


async def _contract(request: Request) -> Response:
    return await _read(request, tool="get_requirement_contract")


async def _evidence(request: Request) -> Response:
    return await _read(request, tool="get_requirement_evidence")


async def _compliance(request: Request) -> Response:
    caller = _caller(request)
    project = str(request.path_params["project"])
    raw_ids = request.query_params.getlist("requirement_id")
    if not raw_ids:
        csv_ids = request.query_params.get("requirement_ids", "")
        raw_ids = csv_ids.split(",") if csv_ids else []
    try:
        async with session_scope() as session:
            result = await compliance.review_requirement_compliance(
                session, project=project, requirement_ids=raw_ids
            )
            payload = result.as_dict()
    except Exception as exc:
        log_tool_call(
            tool="review_requirement_compliance",
            project=project,
            caller=caller,
            outcome=audit_outcome(exc),
        )
        return _error_response(exc)
    log_tool_call(
        tool="review_requirement_compliance", project=project, caller=caller, outcome="ok"
    )
    return JSONResponse(payload)


async def _mutate(
    request: Request,
    *,
    tool: str,
    status_code: int,
    op: Callable[..., Awaitable[Any]],
) -> Response:
    caller = _caller(request)
    project = str(request.path_params["project"])
    try:
        async with session_scope() as session:
            view = await op(session, project=project, author=caller)
            payload = view.as_dict()
    except Exception as exc:
        log_tool_call(tool=tool, project=project, caller=caller, outcome=audit_outcome(exc))
        return _error_response(exc)
    log_tool_call(tool=tool, project=project, caller=caller, outcome="ok")
    return JSONResponse(payload, status_code=status_code)


async def _create_invariant(request: Request) -> Response:
    requirement_id = str(request.path_params["requirement_id"])

    async def op(session: Any, project: str, author: str) -> Any:
        body = await _json_object(request)
        _reject_unknown(body, INVARIANT_CREATE_FIELDS)
        return await contracts.create_invariant(
            session,
            project=project,
            requirement_id=requirement_id,
            statement=_required_str(body, "statement"),
            kind=_required_str(body, "kind"),
            risk=_required_str(body, "risk"),
            key=_optional_typed(body, "key", lambda value: _as_str(value, field="key")),
            sort_order=_optional_typed(
                body, "sort_order", lambda value: _as_int(value, field="sort_order")
            ),
            author=author,
        )

    return await _mutate(request, tool="create_requirement_invariant", status_code=201, op=op)


async def _update_invariant(request: Request) -> Response:
    invariant_id = str(request.path_params["invariant_id"])

    async def op(session: Any, project: str, author: str) -> Any:
        body = await _json_object(request)
        kwargs = _merge_kwargs(
            body,
            {
                "statement": lambda value: _as_str(value, field="statement"),
                "kind": lambda value: _as_str(value, field="kind"),
                "risk": lambda value: _as_str(value, field="risk"),
                "key": lambda value: _as_str(value, field="key"),
                "sort_order": lambda value: _as_int(value, field="sort_order"),
            },
        )
        return await contracts.update_invariant(
            session,
            project=project,
            invariant_id=invariant_id,
            author=author,
            **kwargs,
        )

    return await _mutate(request, tool="update_requirement_invariant", status_code=200, op=op)


async def _delete_invariant(request: Request) -> Response:
    invariant_id = str(request.path_params["invariant_id"])
    return await _mutate(
        request,
        tool="delete_requirement_invariant",
        status_code=200,
        op=lambda session, project, author: contracts.delete_invariant(
            session, project=project, invariant_id=invariant_id, author=author
        ),
    )


async def _create_criterion(request: Request) -> Response:
    invariant_id = str(request.path_params["invariant_id"])

    async def op(session: Any, project: str, author: str) -> Any:
        body = await _json_object(request)
        _reject_unknown(body, CRITERION_CREATE_FIELDS)
        return await contracts.create_criterion(
            session,
            project=project,
            invariant_id=invariant_id,
            statement=_required_str(body, "statement"),
            evidence_kind=_required_str(body, "evidence_kind"),
            key=_optional_typed(body, "key", lambda value: _as_str(value, field="key")),
            required=_optional_or_default(
                body, "required", lambda value: _as_bool(value, field="required"), True
            ),
            independent_review=_optional_or_default(
                body,
                "independent_review",
                lambda value: _as_str(value, field="independent_review"),
                "not-required",
            ),
            sort_order=_optional_typed(
                body, "sort_order", lambda value: _as_int(value, field="sort_order")
            ),
            author=author,
        )

    return await _mutate(request, tool="create_acceptance_criterion", status_code=201, op=op)


async def _update_criterion(request: Request) -> Response:
    criterion_id = str(request.path_params["criterion_id"])

    async def op(session: Any, project: str, author: str) -> Any:
        body = await _json_object(request)
        kwargs = _merge_kwargs(
            body,
            {
                "statement": lambda value: _as_str(value, field="statement"),
                "evidence_kind": lambda value: _as_str(value, field="evidence_kind"),
                "required": lambda value: _as_bool(value, field="required"),
                "independent_review": lambda value: _as_str(value, field="independent_review"),
                "key": lambda value: _as_str(value, field="key"),
                "sort_order": lambda value: _as_int(value, field="sort_order"),
            },
        )
        return await contracts.update_criterion(
            session,
            project=project,
            criterion_id=criterion_id,
            author=author,
            **kwargs,
        )

    return await _mutate(request, tool="update_acceptance_criterion", status_code=200, op=op)


async def _delete_criterion(request: Request) -> Response:
    criterion_id = str(request.path_params["criterion_id"])
    return await _mutate(
        request,
        tool="delete_acceptance_criterion",
        status_code=200,
        op=lambda session, project, author: contracts.delete_criterion(
            session, project=project, criterion_id=criterion_id, author=author
        ),
    )


def register_requirement_routes(mcp: FastMCP) -> None:
    """Attach requirement contract/evidence/compliance HTTP routes (T13, T14)."""
    routes: list[tuple[str, list[str], _Handler]] = [
        ("/api/projects/{project}/requirements/compliance", ["GET"], _compliance),
        (
            "/api/projects/{project}/requirements/{requirement_id}/contract",
            ["GET"],
            _contract,
        ),
        (
            "/api/projects/{project}/requirements/{requirement_id}/evidence",
            ["GET"],
            _evidence,
        ),
        (
            "/api/projects/{project}/requirements/{requirement_id}/invariants",
            ["POST"],
            _create_invariant,
        ),
        (
            "/api/projects/{project}/requirements/invariants/{invariant_id}",
            ["PATCH"],
            _update_invariant,
        ),
        (
            "/api/projects/{project}/requirements/invariants/{invariant_id}",
            ["DELETE"],
            _delete_invariant,
        ),
        (
            "/api/projects/{project}/requirements/invariants/{invariant_id}/criteria",
            ["POST"],
            _create_criterion,
        ),
        (
            "/api/projects/{project}/requirements/criteria/{criterion_id}",
            ["PATCH"],
            _update_criterion,
        ),
        (
            "/api/projects/{project}/requirements/criteria/{criterion_id}",
            ["DELETE"],
            _delete_criterion,
        ),
    ]
    for path, methods, handler in routes:
        mcp.custom_route(path, methods)(handler)
