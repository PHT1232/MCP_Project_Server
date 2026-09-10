"""Structured logging for the `pcs` logger (NFR6).

One JSON line per event on stderr (stdout is reserved for the stdio MCP
protocol). :func:`log_tool_call` emits the mandatory per-call audit record —
project id, caller, and outcome — that every MCP tool must produce.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

logger = logging.getLogger("pcs")


class JsonFormatter(logging.Formatter):
    """Render a record as a compact JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        context = getattr(record, "context", None)
        if isinstance(context, dict):
            payload.update(context)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    """Install the JSON handler on the `pcs` logger. Idempotent."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    pcs_logger = logging.getLogger("pcs")
    pcs_logger.handlers = [handler]
    pcs_logger.setLevel(level.upper())
    pcs_logger.propagate = False


def log_tool_call(
    *,
    tool: str,
    project: str | None,
    caller: str,
    outcome: str,
    **fields: Any,
) -> None:
    """Emit the mandatory audit line for one MCP tool call (NFR6)."""
    logger.info(
        "tool_call",
        extra={
            "context": {
                "tool": tool,
                "project": project,
                "caller": caller,
                "outcome": outcome,
                **fields,
            }
        },
    )
