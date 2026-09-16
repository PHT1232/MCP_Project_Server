"""Baseline token computation: what full, untruncated content would have cost.

Pure helpers with no DB writes. Callers feed these into
``pcs.token_savings.service.record_token_savings`` alongside the tokens
actually returned, to get a savings delta. Every helper here is best-effort:
an unreadable or moved file contributes nothing to the baseline rather than
raising, since a baseline estimate must never break the retrieval call it
describes.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from pcs.context.assembly import estimate_tokens
from pcs.index.ignore import PathTraversalError, resolve_project_root, resolve_under_root

logger = logging.getLogger("pcs")

READ_ENCODING: str = "utf-8"


def full_file_tokens(root_path: str, paths: Iterable[str]) -> int:
    """Sum ``estimate_tokens`` over the full on-disk content of each distinct path.

    Used as the baseline for code-retrieval operations (retrieve_context,
    search_code, and the code-pack portion of prepare_task): what it would
    have cost to read every relevant file in full, instead of the
    budget-bounded chunks PCS actually returned.
    """
    distinct = {p for p in paths if p}
    if not distinct:
        return 0
    try:
        root = resolve_project_root(root_path)
    except FileNotFoundError:
        return 0
    total = 0
    for rel_path in distinct:
        try:
            resolved = resolve_under_root(root, rel_path)
            content = resolved.read_text(encoding=READ_ENCODING, errors="replace")
        except (OSError, PathTraversalError, UnicodeDecodeError):
            continue
        total += estimate_tokens(content)
    return total
