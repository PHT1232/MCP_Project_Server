"""FR9d LLM-summarization seam.

T01 implements the graceful fallback (FR9e): with no backend configured, a
long ``detail`` is deterministically truncated and a drill-down pointer is
appended. T04 wires the real backend behind :func:`summarize_detail`.
"""

from __future__ import annotations

from pcs.context.types import CHARS_PER_TOKEN


class Summarizer:
    """Opt-in last-resort summarizer (FR9d). Off by default until T04."""

    def is_available(self) -> bool:
        """Whether an LLM backend is configured. T01 always returns False."""
        return False

    def summarize(self, text: str, *, max_tokens: int, cache_key: str) -> str | None:
        """Return a cached/computed summary, or ``None`` to trigger FR9e fallback.

        ``cache_key`` is the entry content hash T04 will key the cache on. T01
        ignores it.
        """
        del text, max_tokens, cache_key
        return None


_DEFAULT = Summarizer()


def get_summarizer() -> Summarizer:
    """Process-wide summarizer. T04 replaces this with a backend-aware instance."""
    return _DEFAULT


def fallback_truncate(text: str, *, max_tokens: int, entry_id: str, project: str) -> str:
    """Deterministic truncation plus a drill-down pointer (FR9e, FR9f)."""
    max_chars = max(0, max_tokens) * CHARS_PER_TOKEN
    pointer = f"\n… truncated; full detail: get_entry(project={project!r}, entry_id={entry_id!r})"
    if len(text) <= max_chars:
        return text
    body_budget = max(0, max_chars - len(pointer))
    return text[:body_budget].rstrip() + pointer
