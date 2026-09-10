"""``pcs`` entry point — run the MCP server over stdio or streamable HTTP.

pcs stdio   # co-located agents; no network (FR42)
pcs http    # streamable-HTTP MCP + /api, bound to 127.0.0.1 (NFR3, NFR14)
"""

from __future__ import annotations

import argparse

from pcs.config import get_settings
from pcs.logging import configure_logging, logger


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="pcs", description="Project Context MCP Server (walking skeleton)."
    )
    sub = parser.add_subparsers(dest="transport", required=True)
    sub.add_parser("stdio", help="serve MCP over stdio")
    sub.add_parser("http", help="serve streamable-HTTP MCP + /api on the localhost bind")
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(settings.log_level)

    from pcs.mcp import mcp

    if args.transport == "stdio":
        logger.info("starting", extra={"context": {"transport": "stdio"}})
        mcp.run(transport="stdio")
    else:
        logger.info(
            "starting",
            extra={
                "context": {
                    "transport": "streamable-http",
                    "host": settings.bind_host,
                    "port": settings.port,
                }
            },
        )
        mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
