"""``pcs`` entry point — run the MCP server over stdio or streamable HTTP.

pcs stdio   # co-located agents; no network (FR42)
pcs http    # streamable-HTTP MCP + /api, bound per bind_mode (NFR3, NFR14, FR41)
"""

from __future__ import annotations

import argparse

from pcs.bind import apply_listen_host
from pcs.config import get_settings
from pcs.logging import configure_logging, logger


def main() -> None:
    parser = argparse.ArgumentParser(prog="pcs", description="Project Context MCP Server.")
    sub = parser.add_subparsers(dest="transport", required=True)
    sub.add_parser("stdio", help="serve MCP over stdio (no listen socket; FR42)")
    sub.add_parser("http", help="serve streamable-HTTP MCP + /api on bind_host")
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(settings.log_level)

    from pcs.mcp import mcp

    if args.transport == "stdio":
        logger.info(
            "starting",
            extra={
                "context": {
                    "transport": "stdio",
                    "bind_mode": settings.bind_mode,
                }
            },
        )
        mcp.run(transport="stdio")
        return

    # Serve our wrapped app (frontend + index-watch lifespan), not
    # FastMCP.run(), which would build a bare streamable_http_app without them.
    import uvicorn

    from pcs.mcp import build_http_app

    host = settings.bind_host
    apply_listen_host(mcp, host)
    logger.info(
        "starting",
        extra={
            "context": {
                "transport": "streamable-http",
                "host": host,
                "port": settings.port,
                "bind_mode": settings.bind_mode,
            }
        },
    )
    uvicorn.run(
        build_http_app(),
        host=host,
        port=settings.port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
