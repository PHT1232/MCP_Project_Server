"""Token-savings log: actual vs. baseline token counts for budget-bounded
retrieval calls (retrieve_context, search_code, prepare_task,
get_project_briefing).

This package's ``__init__`` intentionally re-exports only from
``token_savings.models`` (no dependency beyond ``pcs.db.base``). Importing
``token_savings.baseline`` or ``token_savings.service`` here would pull in
``pcs.context.service`` at package-init time — and ``pcs.db.models`` imports
``pcs.token_savings.models`` directly, which runs this ``__init__`` first;
that would create a real circular import (``pcs.context.service`` itself
imports names from ``pcs.db.models``, which is still mid-initialization at
that point). Callers needing ``full_file_tokens``/``record_token_savings``/
etc. import them directly from ``pcs.token_savings.baseline`` /
``pcs.token_savings.service``.
"""

from __future__ import annotations

from pcs.token_savings.models import OPERATIONS, TokenSavingsLogEntry

__all__ = [
    "OPERATIONS",
    "TokenSavingsLogEntry",
]
