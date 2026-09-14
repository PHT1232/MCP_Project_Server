"""FR9d LLM-summarization seam — now backend-aware (T04).

With no backend configured (``PCS_SUMMARY_BACKEND`` empty) this behaves exactly
as T01 shipped it: :meth:`Summarizer.is_available` is ``False`` and assembly
falls back to deterministic truncation (FR9e). When a backend is configured,
:meth:`Summarizer.summarize` calls an OpenAI-compatible ``/chat/completions``
endpoint, caches the result keyed by the entry content hash (FR9d), and returns
``None`` on any failure so the FR9e fallback still applies. Data leaves the host
only to ``PCS_SUMMARY_BASE_URL`` (NFR11).

The cache here is process-local; a persistent cache table is a follow-up.
"""

from __future__ import annotations

import logging

from pcs.ai_settings import ProviderSettings, resolve_provider_endpoint
from pcs.config import Settings, get_settings
from pcs.context.types import CHARS_PER_TOKEN

logger = logging.getLogger("pcs")


class Summarizer:
    """Opt-in last-resort summarizer (FR9d)."""

    def __init__(self, settings: Settings | ProviderSettings | None = None) -> None:
        self._settings = settings or get_settings()
        self._cache: dict[tuple[str, int], str] = {}

    def is_available(self) -> bool:
        """Whether an LLM backend is configured (FR9d). Empty setting → False (FR9e)."""
        return bool(
            (
                self._settings.backend
                if isinstance(self._settings, ProviderSettings)
                else self._settings.summary_backend
            ).strip()
        )

    def summarize(self, text: str, *, max_tokens: int, cache_key: str) -> str | None:
        """Return a cached/computed summary, or ``None`` to trigger FR9e fallback."""
        if not self.is_available():
            return None
        key = (cache_key, max_tokens)
        if key in self._cache:
            return self._cache[key]
        summary = self._call_backend(text, max_tokens=max_tokens)
        if summary is None:
            return None
        cap_chars = max(0, max_tokens) * CHARS_PER_TOKEN
        summary = summary.strip()[:cap_chars] or None
        if summary is not None:
            self._cache[key] = summary
        return summary

    def _call_backend(self, text: str, *, max_tokens: int) -> str | None:
        backend = (
            (
                self._settings.backend
                if isinstance(self._settings, ProviderSettings)
                else self._settings.summary_backend
            )
            .strip()
            .lower()
        )
        if backend not in {"openai", "openai-compatible"}:
            logger.warning("summary_backend_unknown", extra={"context": {"backend": backend}})
            return None
        try:
            import httpx

            headers = {"content-type": "application/json"}
            api_key = (
                self._settings.api_key
                if isinstance(self._settings, ProviderSettings)
                else self._settings.summary_api_key
            )
            if api_key:
                headers["authorization"] = f"Bearer {api_key}"
            prompt = (
                "Summarise the following project-context note in at most "
                f"{max_tokens} tokens. Keep concrete facts, IDs, and file paths. "
                "Return prose only.\n\n" + text
            )
            payload = {
                "model": self._settings.model
                if isinstance(self._settings, ProviderSettings)
                else self._settings.summary_model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": 0.0,
            }
            base_url = (
                self._settings.base_url
                if isinstance(self._settings, ProviderSettings)
                else self._settings.summary_base_url
            )
            import asyncio

            endpoint = asyncio.run(resolve_provider_endpoint(base_url))
            headers.update(endpoint.request_headers)
            with httpx.Client(
                follow_redirects=False,
                timeout=self._settings.timeout_seconds
                if isinstance(self._settings, ProviderSettings)
                else self._settings.summary_timeout_seconds,
            ) as client:
                response = client.post(
                    f"{endpoint.url}/chat/completions",
                    json=payload,
                    headers=headers,
                    extensions=endpoint.request_extensions,
                )
                response.raise_for_status()
                data = response.json()
            return str(data["choices"][0]["message"]["content"])
        except Exception:
            logger.warning("summary_call_failed")
            return None


_INSTANCE: Summarizer | None = None


def get_summarizer() -> Summarizer:
    """Process-wide backend-aware summarizer (FR9d seam, replaced by T04)."""
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = Summarizer()
    return _INSTANCE


def reset_summarizer() -> None:
    """Drop the cached instance (used by tests that change settings)."""
    global _INSTANCE
    _INSTANCE = None


def fallback_truncate(text: str, *, max_tokens: int, entry_id: str, project: str) -> str:
    """Deterministic truncation plus a drill-down pointer (FR9e, FR9f)."""
    max_chars = max(0, max_tokens) * CHARS_PER_TOKEN
    pointer = f"\n… truncated; full detail: get_entry(project={project!r}, entry_id={entry_id!r})"
    if len(text) <= max_chars:
        return text
    body_budget = max(0, max_chars - len(pointer))
    return text[:body_budget].rstrip() + pointer
