"""MCP surface (`pcs.mcp`).

Registers the curated-context tools and ``context://{project}/*`` resources over
stdio and streamable HTTP, and mounts the non-MCP ``/api`` routes on the HTTP app.
"""

from pcs.mcp.server import build_http_app, mcp

__all__ = ["build_http_app", "mcp"]
