"""FastMCP app: context-store tools + resources over stdio and streamable HTTP.

Tool bodies delegate to :mod:`pcs.context.service` (unit-tested without this
layer) and emit the mandatory audit line for every call (NFR6). Unknown/missing
``project`` raises :class:`~pcs.context.service.ProjectNotFoundError`, whose
message lists the registered projects (D3, FR8, AC16).
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette

from pcs.config import get_settings
from pcs.mcp.resources import register_resources
from pcs.mcp.tools import register_tools
from pcs.web_api import register_routes

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
register_resources(mcp)
register_routes(mcp)


def build_http_app() -> Starlette:
    """The streamable-HTTP MCP app with the ``/api`` routes mounted."""
    return mcp.streamable_http_app()
