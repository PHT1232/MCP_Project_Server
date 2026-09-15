"""Pluggable embedding-backend interface (FR28, D7, NFR11).

No backend is bundled for real use: with ``PCS_EMBEDDING_BACKEND`` unset the
server runs keyword/structural-only and every surface says so (AC10, AC21).

Backends:

* ``openai`` — POSTs to an OpenAI-compatible ``{base_url}/embeddings`` endpoint.
  Covers the OpenAI API and local servers that speak the same shape
  (llama.cpp ``--embedding``, text-embedding-inference, Ollama's OpenAI compat).
  Code/text leaves the host only to ``PCS_EMBEDDING_BASE_URL`` (NFR11).
* ``hashing`` — a deterministic, offline, zero-dependency n-gram hashing
  vectoriser. Lower quality than a learned model, but needs no download and no
  network; it exists so semantic search is exercisable in CI and usable fully
  air-gapped. Still opt-in — semantic search stays off until it is selected.
"""

from __future__ import annotations

import hashlib
import itertools
import math
import re
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from pcs.ai_settings import (
    AiSettingsError,
    ProviderSettings,
    load_runtime_ai_settings,
    resolve_provider_endpoint,
)
from pcs.config import Settings, get_settings


class EmbeddingProviderError(RuntimeError):
    """Redacted runtime failure from an embedding provider (NFR8, NFR11)."""

    _KINDS = frozenset({"configuration", "connection", "invalid_response", "provider", "timeout"})

    def __init__(self, kind: str = "provider") -> None:
        self.kind = kind if kind in self._KINDS else "provider"
        super().__init__("embedding provider request failed")


class EmbeddingBackend(Protocol):
    """Everything the index needs from an embedding provider."""

    name: str
    dimensions: int

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Return vectors or raise ``EmbeddingProviderError`` for provider failures."""
        ...


_TOKEN = re.compile(r"[A-Za-z0-9_]+")


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


class HashingEmbeddingBackend:
    """Feature-hashing bag-of-words + char-trigram vectoriser (offline, deterministic)."""

    def __init__(self, dimensions: int = 512, model: str = "hashing") -> None:
        self.name = model
        self.dimensions = max(16, dimensions)

    def _vector(self, text: str) -> list[float]:
        vec = [0.0] * self.dimensions
        toks = _tokens(text)
        features: list[str] = list(toks)
        features += [f"{a}_{b}" for a, b in itertools.pairwise(toks)]
        for tok in toks:
            padded = f"^{tok}$"
            features += [padded[i : i + 3] for i in range(max(1, len(padded) - 2))]
        for feat in features:
            digest = hashlib.blake2b(feat.encode("utf-8"), digest_size=8).digest()
            bucket = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] & 1 else -1.0
            vec[bucket] += sign
        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0.0:
            return vec
        return [v / norm for v in vec]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]


class OpenAIEmbeddingBackend:
    """OpenAI-compatible ``/embeddings`` HTTP backend."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        dimensions: int,
        timeout: float,
    ) -> None:
        self.name = model
        self.dimensions = dimensions
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout

    async def embed(self, texts: list[str]) -> list[list[float]]:
        import httpx

        try:
            endpoint = await resolve_provider_endpoint(self._base_url)
        except AiSettingsError as exc:
            raise EmbeddingProviderError("configuration") from exc
        headers = {"content-type": "application/json", **endpoint.request_headers}
        if self._api_key:
            headers["authorization"] = f"Bearer {self._api_key}"
        payload: dict[str, object] = {"model": self.name, "input": texts}
        try:
            async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=False) as client:
                response = await client.post(
                    f"{endpoint.url}/embeddings",
                    json=payload,
                    headers=headers,
                    extensions=endpoint.request_extensions,
                )
                response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise EmbeddingProviderError("timeout") from exc
        except httpx.HTTPStatusError as exc:
            raise EmbeddingProviderError("provider") from exc
        except httpx.RequestError as exc:
            raise EmbeddingProviderError("connection") from exc
        try:
            data = response.json()
            rows = sorted(data["data"], key=lambda row: int(row.get("index", 0)))
            vectors = [[float(x) for x in row["embedding"]] for row in rows]
            if len(vectors) != len(texts):
                raise ValueError("embedding response count does not match input count")
            if vectors and len(vectors[0]) != self.dimensions:
                raise ValueError("embedding dimensions do not match configured dimensions")
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise EmbeddingProviderError("invalid_response") from exc
        return vectors


def build_embedding_backend(
    settings: Settings | ProviderSettings | None = None,
) -> EmbeddingBackend | None:
    """Return configured backend, or ``None`` when semantic search is disabled (D7)."""
    cfg = settings or get_settings()
    if isinstance(cfg, ProviderSettings):
        choice = cfg.backend.strip().lower()
        dimensions = cfg.dimensions or 1536
        model = cfg.model
        base_url = cfg.base_url
        api_key = cfg.api_key
        timeout = cfg.timeout_seconds
    else:
        choice = cfg.embedding_backend.strip().lower()
        dimensions = cfg.embedding_dimensions
        model = cfg.embedding_model
        base_url = cfg.embedding_base_url
        api_key = cfg.embedding_api_key
        timeout = cfg.embedding_timeout_seconds
    if not choice:
        return None
    if choice == "hashing":
        return HashingEmbeddingBackend(dimensions=dimensions, model=model)
    if choice in {"openai", "openai-compatible"}:
        return OpenAIEmbeddingBackend(
            base_url=base_url,
            api_key=api_key,
            model=model,
            dimensions=dimensions,
            timeout=timeout,
        )
    raise ValueError(f"unknown embedding backend {choice!r}")


_OVERRIDE: EmbeddingBackend | None = None
_OVERRIDE_SET = False


def set_embedding_backend_override(
    backend: EmbeddingBackend | None, *, active: bool = True
) -> None:
    """Test seam: force a specific backend (or force "no backend" with ``active=True``)."""
    global _OVERRIDE, _OVERRIDE_SET
    _OVERRIDE = backend
    _OVERRIDE_SET = active


async def get_embedding_backend(session: AsyncSession) -> EmbeddingBackend | None:
    """Return the hot-reloaded persisted embedding backend (AC-AISET-6)."""
    if _OVERRIDE_SET:
        return _OVERRIDE
    runtime = await load_runtime_ai_settings(session)
    return build_embedding_backend(runtime.embedding)
