"""MCP surface (`pcs.mcp`).

Exposes exactly the three T00 tools — ``register_project``,
``set_current_focus``, ``get_project_briefing`` — over stdio and streamable
HTTP, and mounts the non-MCP ``/api`` routes on the HTTP app.
"""

from pcs.mcp.server import build_http_app, mcp

__all__ = ["build_http_app", "mcp"]
