"""Typed HTTP reads for requirement contracts, evidence, and compliance (T13)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from pcs.context import service as context_service
from pcs.context.types import ContractNotFoundError, ValidationError
from pcs.db.base import session_scope
from pcs.logging import log_tool_call
from pcs.requirements import briefing, compliance

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


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
        log_tool_call(tool=tool, project=project, caller=caller, outcome=f"error: {exc}")
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
            outcome=f"error: {exc}",
        )
        return _error_response(exc)
    log_tool_call(
        tool="review_requirement_compliance", project=project, caller=caller, outcome="ok"
    )
    return JSONResponse(payload)


def register_requirement_routes(mcp: FastMCP) -> None:
    """Attach T13 read-only requirement HTTP routes."""
    mcp.custom_route("/api/projects/{project}/requirements/{requirement_id}/contract", ["GET"])(
        _contract
    )
    mcp.custom_route("/api/projects/{project}/requirements/{requirement_id}/evidence", ["GET"])(
        _evidence
    )
    mcp.custom_route("/api/projects/{project}/requirements/compliance", ["GET"])(_compliance)
