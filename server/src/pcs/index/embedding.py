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

from pcs.config import Settings, get_settings


class EmbeddingBackend(Protocol):
    """Everything the index needs from an embedding provider."""

    name: str
    dimensions: int

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one unit-normalised vector per input text, order preserved."""
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

        headers = {"content-type": "application/json"}
        if self._api_key:
            headers["authorization"] = f"Bearer {self._api_key}"
        payload: dict[str, object] = {"model": self.name, "input": texts}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{self._base_url}/embeddings", json=payload, headers=headers
            )
            response.raise_for_status()
            data = response.json()
        rows = sorted(data["data"], key=lambda row: int(row.get("index", 0)))
        vectors = [[float(x) for x in row["embedding"]] for row in rows]
        if vectors and len(vectors[0]) != self.dimensions:
            raise ValueError(
                f"embedding backend returned dim {len(vectors[0])}, "
                f"PCS_EMBEDDING_DIMENSIONS={self.dimensions}"
            )
        return vectors


def build_embedding_backend(settings: Settings | None = None) -> EmbeddingBackend | None:
    """Return the configured backend, or ``None`` when semantic search is disabled (D7)."""
    cfg = settings or get_settings()
    choice = cfg.embedding_backend.strip().lower()
    if not choice:
        return None
    if choice == "hashing":
        return HashingEmbeddingBackend(
            dimensions=cfg.embedding_dimensions, model=cfg.embedding_model
        )
    if choice in {"openai", "openai-compatible"}:
        return OpenAIEmbeddingBackend(
            base_url=cfg.embedding_base_url,
            api_key=cfg.embedding_api_key,
            model=cfg.embedding_model,
            dimensions=cfg.embedding_dimensions,
            timeout=cfg.embedding_timeout_seconds,
        )
    raise ValueError(f"unknown PCS_EMBEDDING_BACKEND={choice!r} (expected '', 'openai', 'hashing')")


_OVERRIDE: EmbeddingBackend | None = None
_OVERRIDE_SET = False


def set_embedding_backend_override(
    backend: EmbeddingBackend | None, *, active: bool = True
) -> None:
    """Test seam: force a specific backend (or force "no backend" with ``active=True``)."""
    global _OVERRIDE, _OVERRIDE_SET
    _OVERRIDE = backend
    _OVERRIDE_SET = active


def get_embedding_backend() -> EmbeddingBackend | None:
    """Process-wide embedding backend (FR28). Honours the test override."""
    if _OVERRIDE_SET:
        return _OVERRIDE
    return build_embedding_backend()
