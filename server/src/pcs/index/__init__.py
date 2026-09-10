"""Code index public API (T03 keyword + T04 symbols/semantic).

T04 wraps :func:`pcs.index.search.keyword_search` for the keyword half and adds
the SCIP-style symbol model, embedding pipeline, hybrid ranking, and the
``retrieve_context`` / ``prepare_task`` RAG surface.
"""

from pcs.index.embedding import EmbeddingBackend, get_embedding_backend
from pcs.index.hybrid import HybridResult, hybrid_search
from pcs.index.retrieval import prepare_task, retrieve_context
from pcs.index.search import SearchHit, SearchResult, keyword_search
from pcs.index.service import (
    IndexStatusView,
    get_index_status,
    index_if_root_exists,
    reindex,
    search_code,
)

__all__ = [
    "EmbeddingBackend",
    "HybridResult",
    "IndexStatusView",
    "SearchHit",
    "SearchResult",
    "get_embedding_backend",
    "get_index_status",
    "hybrid_search",
    "index_if_root_exists",
    "keyword_search",
    "prepare_task",
    "reindex",
    "retrieve_context",
    "search_code",
]
