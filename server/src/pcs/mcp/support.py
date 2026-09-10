"""Shared helpers for MCP tool/resource wrappers (NFR6)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from mcp.server.fastmcp import Context
from sqlalchemy.ext.asyncio import AsyncSession

from pcs.db.base import session_scope
from pcs.logging import log_tool_call


def caller(ctx: Context[Any, Any] | None) -> str:
    """Best-effort MCP client identity for the audit log (NFR6).

    ``ctx`` is ``None`` when a tool is invoked outside a live request (e.g. tests
    calling ``mcp.call_tool`` directly); the audit line still records "unknown".
    """
    if ctx is None:
        return "unknown"
    try:
        params = ctx.session.client_params
        if params is not None and params.clientInfo is not None:
            return str(params.clientInfo.name)
    except (AttributeError, ValueError):
        return "unknown"
    return getattr(ctx, "client_id", None) or "unknown"


async def run_tool[T](
    tool: str,
    project: str | None,
    ctx: Context[Any, Any] | None,
    op: Callable[[AsyncSession], Awaitable[T]],
) -> T:
    """Run ``op`` inside :func:`session_scope` and emit the NFR6 audit line."""
    who = caller(ctx)
    try:
        async with session_scope() as session:
            result = await op(session)
    except Exception as exc:
        log_tool_call(tool=tool, project=project, caller=who, outcome=f"error: {exc}")
        raise
    log_tool_call(tool=tool, project=project, caller=who, outcome="ok")
    return result
