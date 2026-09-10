"""FastMCP app: context-store tools + resources over stdio and streamable HTTP.

Tool bodies delegate to :mod:`pcs.context.service` (unit-tested without this
layer) and emit the mandatory audit line for every call (NFR6). Unknown/missing
``project`` raises :class:`~pcs.context.service.ProjectNotFoundError`, whose
message lists the registered projects (D3, FR8, AC16).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette

from pcs.config import get_settings
from pcs.index import watch as index_watch
from pcs.mcp.index_tools import register_index_tools
from pcs.mcp.resources import register_resources
from pcs.mcp.tools import register_tools
from pcs.web_api import register_routes
from pcs.web_api.index_routes import register_index_routes

_settings = get_settings()

mcp: FastMCP = FastMCP(
    "pcs",
    instructions=(
        "Project Context MCP Server. Every call must name its project explicitly "
        "(name or id). Fetch a briefing with get_project_briefing; drill into "
        "verbatim detail with get_section / get_entry / context:// resources. "
        "Writes go through add_*/update_*/resolve_* (never inferred)."
    ),
    host=_settings.bind_host,
    port=_settings.port,
)

register_tools(mcp)
register_index_tools(mcp)
register_resources(mcp)
register_routes(mcp)
register_index_routes(mcp)


def build_http_app() -> Starlette:
    """The streamable-HTTP MCP app with the ``/api`` routes mounted."""
    app = mcp.streamable_http_app()
    inner = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app_: Starlette) -> AsyncIterator[None]:
        await index_watch.start_all()
        try:
            async with inner(app_):
                yield
        finally:
            await index_watch.stop_all()

    app.router.lifespan_context = lifespan
    return app
