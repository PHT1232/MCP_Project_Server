"""Project context store (REQUIREMENTS.md §7.1-§7.5, §7.2a).

Service-layer logic lives in :mod:`pcs.context.service` — no MCP/HTTP imports.
"""

from pcs.context import service

__all__ = ["service"]
