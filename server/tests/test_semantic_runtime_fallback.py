"""Regression coverage for semantic-query runtime degradation (NFR8, NFR11)."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import NoReturn, Self, cast
from unittest.mock import patch

import httpx
import pytest
from mcp.server.fastmcp.exceptions import ToolError
from sqlalchemy import func, select

from pcs.ai_settings import ValidatedEndpoint
from pcs.context import service as context_service
from pcs.db.base import session_scope
from pcs.index import embedding as embedding_module
from pcs.index import hybrid as hybrid_module
from pcs.index import retrieval, service
from pcs.index.embedding import (
    EmbeddingProviderError,
    HashingEmbeddingBackend,
    OpenAIEmbeddingBackend,
    set_embedding_backend_override,
)
from pcs.index.models import IndexEmbedding, IndexStatus
from pcs.index.search import keyword_search as real_keyword_search
from pcs.mcp import mcp

pytestmark = pytest.mark.usefixtures("clean_db")

PROJECT = "semantic-runtime-fallback"
SENSITIVE_FAILURE = (
    "POST https://user:password@embedding.internal/v1 failed; "
    'api_key=sk-secret; body={"secret":"raw-provider-payload"}'
)


class FailingBackend:
    """Backend that fails only after a healthy backend has populated the index."""

    name = "safe-query-model"
    dimensions = 64

    def __init__(self, failure: Callable[[], BaseException]) -> None:
        self._failure = failure

    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise self._failure()


class FailingHttpClient:
    """Minimal async-client double that raises one httpx provider failure."""

    def __init__(self, failure: httpx.HTTPError) -> None:
        self._failure = failure

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def post(self, *args: object, **kwargs: object) -> NoReturn:
        raise self._failure


class ResponseHttpClient:
    """Minimal async-client double that returns one provider response."""

    def __init__(self, response: httpx.Response) -> None:
        self._response = response

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def post(self, *args: object, **kwargs: object) -> httpx.Response:
        return self._response


def _sample_repo(root: Path) -> None:
    (root / "src").mkdir()
    (root / "src" / "cart.py").write_text(
        "def cart_total(items):\n"
        '    """Calculate the checkout total for cart items."""\n'
        "    return sum(item.price for item in items)\n",
        encoding="utf-8",
    )
    (root / "src" / "pricing.py").write_text(
        "def apply_discount(total, rate):\n    return total * (1 - rate)\n",
        encoding="utf-8",
    )
    (root / "README.md").write_text("# Store\nCheckout and pricing service.\n", encoding="utf-8")


@pytest.fixture(autouse=True)
def reset_embedding_override() -> Iterator[None]:
    """Keep the process-wide backend test seam isolated."""
    set_embedding_backend_override(None, active=False)
    try:
        yield
    finally:
        set_embedding_backend_override(None, active=False)


async def _register(root: Path) -> None:
    _sample_repo(root)
    async with session_scope() as session:
        await context_service.register_project(
            session,
            name=PROJECT,
            root_path=str(root),
            overview="Semantic runtime fallback fixture.",
        )


async def _index_with_embeddings(root: Path) -> None:
    await _register(root)
    set_embedding_backend_override(HashingEmbeddingBackend(dimensions=64, model="safe-query-model"))
    async with session_scope() as session:
        status = await service.reindex(session, project=PROJECT, incremental=False)
    assert status.embedded_chunk_count > 0
    assert (await _persisted_index_state())[3] is False


async def _persisted_index_state() -> tuple[object, ...]:
    async with session_scope() as session:
        project = await context_service.resolve_project(session, PROJECT)
        status = await session.get(IndexStatus, project.id)
        assert status is not None
        embedding_count = int(
            (await session.execute(select(func.count()).select_from(IndexEmbedding))).scalar_one()
        )
        return (
            status.state,
            status.semantic_model,
            status.embedded_chunk_count,
            status.reindex_required,
            embedding_count,
        )


def _tool_payload(result: object) -> dict[str, object]:
    if isinstance(result, tuple):
        content, structured = result
        if isinstance(structured, dict):
            return {str(key): value for key, value in structured.items()}
        result = content
    if isinstance(result, list) and result:
        result = getattr(result[0], "text", result[0])
    payload: object = json.loads(str(result))
    assert isinstance(payload, dict)
    return {str(key): value for key, value in payload.items()}


async def test_working_backend_preserves_hybrid_fusion(tmp_path: Path) -> None:
    """Healthy semantic queries keep the existing fusion behavior (FR20)."""
    await _index_with_embeddings(tmp_path)

    async with session_scope() as session:
        payload = await service.search_code(session, project=PROJECT, query="cart_total")

    assert payload["mode"] == "hybrid"
    assert payload["semantic_available"] is True
    hits = cast(list[dict[str, object]], payload["hits"])
    assert hits
    assert any(
        set(cast(list[str], hit["retrieval_modes"])) == {"keyword", "semantic"} for hit in hits
    )


async def test_no_backend_preserves_keyword_fallback(tmp_path: Path) -> None:
    """An unconfigured backend retains AC10 behavior."""
    await _register(tmp_path)
    set_embedding_backend_override(None, active=True)
    async with session_scope() as session:
        await service.reindex(session, project=PROJECT, incremental=False)
        payload = await service.search_code(session, project=PROJECT, query="cart_total")

    assert payload["mode"] == "keyword"
    assert payload["semantic_available"] is False
    assert cast(list[object], payload["hits"])


async def test_unembedded_index_preserves_keyword_fallback(tmp_path: Path) -> None:
    """A newly configured backend does not query semantic search before reindex."""
    await _register(tmp_path)
    set_embedding_backend_override(None, active=True)
    async with session_scope() as session:
        await service.reindex(session, project=PROJECT, incremental=False)
    set_embedding_backend_override(HashingEmbeddingBackend(dimensions=64, model="new-model"))

    async with session_scope() as session:
        payload = await service.search_code(session, project=PROJECT, query="cart_total")

    assert payload["mode"] == "keyword"
    assert payload["semantic_available"] is False
    assert "embedded" in str(payload["semantic_note"]).lower()
    assert cast(list[object], payload["hits"])


def _timeout() -> BaseException:
    return TimeoutError(SENSITIVE_FAILURE)


def _connection_error() -> BaseException:
    return ConnectionError(SENSITIVE_FAILURE)


def _provider_error() -> BaseException:
    return embedding_module.EmbeddingProviderError("provider")


@pytest.mark.parametrize(
    ("failure", "kind"),
    [
        (httpx.ReadTimeout(SENSITIVE_FAILURE), "timeout"),
        (httpx.ConnectError(SENSITIVE_FAILURE), "connection"),
        (
            httpx.HTTPStatusError(
                SENSITIVE_FAILURE,
                request=httpx.Request("POST", "https://provider.test/embeddings"),
                response=httpx.Response(503, json={"secret": "raw-provider-payload"}),
            ),
            "provider",
        ),
    ],
)
async def test_openai_adapter_wraps_http_failures_with_redacted_taxonomy(
    failure: httpx.HTTPError,
    kind: str,
) -> None:
    """The concrete adapter never exposes httpx request/response details (NFR11)."""

    async def resolve(_value: object) -> ValidatedEndpoint:
        return ValidatedEndpoint("https://203.0.113.1/v1", "provider.test", "provider.test")

    backend = OpenAIEmbeddingBackend(
        base_url="https://provider.test/v1",
        api_key="sk-secret",
        model="safe-query-model",
        dimensions=64,
        timeout=1,
    )
    with (
        patch("pcs.index.embedding.resolve_provider_endpoint", new=resolve),
        patch("httpx.AsyncClient", return_value=FailingHttpClient(failure)),
        pytest.raises(EmbeddingProviderError) as excinfo,
    ):
        await backend.embed(["query"])

    assert excinfo.value.kind == kind
    assert str(excinfo.value) == "embedding provider request failed"
    assert "sk-secret" not in str(excinfo.value)


async def test_openai_adapter_rejects_empty_provider_response() -> None:
    """A 200 response without the requested query vector is still a provider failure."""

    async def resolve(_value: object) -> ValidatedEndpoint:
        return ValidatedEndpoint("https://203.0.113.1/v1", "provider.test", "provider.test")

    backend = OpenAIEmbeddingBackend(
        base_url="https://provider.test/v1",
        api_key="sk-secret",
        model="safe-query-model",
        dimensions=64,
        timeout=1,
    )
    response = httpx.Response(
        200,
        json={"data": [], "raw_secret": "raw-provider-payload"},
        request=httpx.Request("POST", "https://provider.test/embeddings"),
    )
    with (
        patch("pcs.index.embedding.resolve_provider_endpoint", new=resolve),
        patch("httpx.AsyncClient", return_value=ResponseHttpClient(response)),
        pytest.raises(EmbeddingProviderError) as excinfo,
    ):
        await backend.embed(["query"])

    assert excinfo.value.kind == "invalid_response"
    assert "raw-provider-payload" not in str(excinfo.value)


@pytest.mark.parametrize(
    "failure",
    [_timeout, _connection_error, _provider_error],
    ids=["timeout", "connection", "provider"],
)
async def test_runtime_embedding_failure_returns_keyword_hits_without_mutating_index(
    tmp_path: Path,
    failure: Callable[[], BaseException],
) -> None:
    """Provider runtime failures degrade only the current query (NFR8, NFR10)."""
    await _index_with_embeddings(tmp_path)
    before = await _persisted_index_state()
    set_embedding_backend_override(FailingBackend(failure))

    async with session_scope() as session:
        payload = await service.search_code(session, project=PROJECT, query="cart_total")

    assert payload["mode"] == "keyword"
    assert payload["semantic_available"] is False
    note = str(payload["semantic_note"])
    assert "temporarily unavailable" in note.lower()
    assert "keyword" in note.lower()
    hits = cast(list[dict[str, object]], payload["hits"])
    assert hits and hits[0]["path"] == "src/cart.py"
    assert await _persisted_index_state() == before


async def test_runtime_fallback_probes_terms_and_keeps_relevance_consumers_valid(
    tmp_path: Path,
) -> None:
    """FR22 consumers keep keyword expansion after a semantic runtime failure."""
    await _index_with_embeddings(tmp_path)
    set_embedding_backend_override(FailingBackend(_timeout))
    task = "Investigate frobnicator behavior around cart_total"

    with patch("pcs.index.hybrid.keyword_search", wraps=real_keyword_search) as keyword:
        async with session_scope() as session:
            gathered = await hybrid_module.gather_relevant(
                session,
                project=PROJECT,
                task=task,
            )
        async with session_scope() as session:
            retrieved = await retrieval.retrieve_context(
                session,
                project=PROJECT,
                task=task,
            )
        async with session_scope() as session:
            prepared = await retrieval.prepare_task(
                session,
                project=PROJECT,
                task=task,
            )

    queries = [str(call.kwargs["query"]) for call in keyword.await_args_list]
    assert task in queries
    assert "cart_total" in queries
    # Regression: the per-term fallback fan-out must pass fuzzy=False — its
    # similarity() tier averaged ~787ms/term against a real large index vs
    # ~141ms/term without it (a 5.6x cost measured live), turning a long task
    # description's many terms into the dominant latency of the whole call,
    # in exactly the scenario (embedding provider down) that already pays
    # its own timeout before this loop even starts.
    per_term_calls = [call for call in keyword.await_args_list if call.kwargs["query"] != task]
    assert per_term_calls
    assert all(call.kwargs.get("fuzzy") is False for call in per_term_calls)
    assert len(gathered.ranked) < 3
    assert gathered.ranked
    assert retrieved["mode"] == "keyword"
    assert retrieved["chunks"]
    assert "keyword" in str(retrieved["semantic_note"]).lower()
    assert prepared["mode"] == "keyword"
    assert prepared["code_chunks"]
    assert "keyword" in str(prepared["semantic_note"]).lower()


async def test_path_and_scope_validation_are_not_converted_to_fallback(tmp_path: Path) -> None:
    """Security/input failures remain failures rather than NFR8 degradation."""
    await _index_with_embeddings(tmp_path)
    set_embedding_backend_override(FailingBackend(_timeout))

    async with session_scope() as session:
        with pytest.raises(ValueError, match=r"escapes|repo-relative"):
            await service.search_code(
                session,
                project=PROJECT,
                query="cart_total",
                scope="subtree",
                subtree="../secrets",
            )
    with pytest.raises(ToolError, match="scope must be one of"):
        await mcp.call_tool(
            "search_code",
            {"project": PROJECT, "query": "cart_total", "scope": "invalid"},
        )


async def test_unrelated_backend_programming_error_still_propagates(tmp_path: Path) -> None:
    """The fallback catch remains narrow around expected provider failures."""
    await _index_with_embeddings(tmp_path)
    set_embedding_backend_override(
        FailingBackend(lambda: AssertionError("unrelated embedding adapter bug"))
    )

    async with session_scope() as session:
        with pytest.raises(AssertionError, match="adapter bug"):
            await service.search_code(session, project=PROJECT, query="cart_total")


async def test_semantic_failure_warning_is_structured_and_redacted(
    tmp_path: Path,
) -> None:
    """NFR6 warning identifies the provider failure without NFR11 leakage."""
    await _index_with_embeddings(tmp_path)
    set_embedding_backend_override(FailingBackend(_timeout))

    with patch.object(hybrid_module.logger, "warning") as warning:
        async with session_scope() as session:
            await service.search_code(session, project=PROJECT, query="cart_total")

    warning.assert_called_once()
    assert warning.call_args.args == ("semantic_query_failed",)
    extra = cast(dict[str, object], warning.call_args.kwargs["extra"])
    context = cast(dict[str, object], extra["context"])
    assert context["project"]
    assert context["model"] == "safe-query-model"
    assert context["backend"] == "FailingBackend"
    assert context["error_type"] == "timeout"
    rendered = json.dumps(context)
    for secret in ("user:password", "embedding.internal", "sk-secret", "raw-provider-payload"):
        assert secret not in rendered


async def test_mcp_search_code_returns_payload_when_query_embedding_times_out(
    tmp_path: Path,
) -> None:
    """The MCP boundary no longer turns a provider timeout into a ToolError (FR22)."""
    await _index_with_embeddings(tmp_path)
    set_embedding_backend_override(FailingBackend(_timeout))

    result = await mcp.call_tool(
        "search_code",
        {"project": PROJECT, "query": "cart_total"},
    )
    payload = _tool_payload(result)

    assert payload["mode"] == "keyword"
    assert payload["semantic_available"] is False
    assert cast(list[object], payload["hits"])
    assert "Error executing tool search_code:" not in str(result)
