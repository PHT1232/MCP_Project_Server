"""Typed admin routes for global AI provider settings (T20)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from pcs.ai_settings import (
    AiSettingsError,
    admin_authorized,
    load_runtime_ai_settings,
    update_ai_settings,
)
from pcs.db.base import session_scope
from pcs.logging import log_tool_call

_NO_STORE = {"cache-control": "no-store"}

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


async def _get(request: Request) -> Response:
    caller = request.headers.get("x-pcs-caller", "frontend")
    try:
        async with session_scope() as session:
            result = await load_runtime_ai_settings(session, refresh=True)
    except AiSettingsError as exc:
        log_tool_call(tool="get_ai_settings", project="global", caller=caller, outcome="error")
        return JSONResponse({"error": str(exc)}, status_code=400, headers=_NO_STORE)
    log_tool_call(tool="get_ai_settings", project="global", caller=caller, outcome="ok")
    return JSONResponse(result.public_dict(), headers=_NO_STORE)


async def _patch(request: Request) -> Response:
    caller = request.headers.get("x-pcs-caller", "frontend")
    authorization = request.headers.get("authorization", "")
    bearer = authorization[7:] if authorization.lower().startswith("bearer ") else ""
    token = request.headers.get("x-pcs-admin-token", bearer)
    if not admin_authorized(token):
        log_tool_call(
            tool="update_ai_settings", project="global", caller=caller, outcome="unauthorized"
        )
        return JSONResponse(
            {"error": "admin authorization required"}, status_code=401, headers=_NO_STORE
        )
    try:
        body = await request.json()
        async with session_scope() as session:
            result = await update_ai_settings(session, body)
    except (AiSettingsError, ValueError):
        log_tool_call(tool="update_ai_settings", project="global", caller=caller, outcome="invalid")
        return JSONResponse(
            {"error": "invalid AI settings request"}, status_code=400, headers=_NO_STORE
        )
    log_tool_call(tool="update_ai_settings", project="global", caller=caller, outcome="ok")
    return JSONResponse(result.public_dict(), headers=_NO_STORE)


def register_ai_settings_routes(mcp: FastMCP) -> None:
    """Register AC-AISET-8/9 admin routes."""
    mcp.custom_route("/api/admin/ai-settings", ["GET"])(_get)
    mcp.custom_route("/api/admin/ai-settings", ["PATCH"])(_patch)
