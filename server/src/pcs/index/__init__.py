"""Code index public API (T03). T04 wraps :func:`pcs.index.search.keyword_search`."""

from pcs.index.search import SearchHit, SearchResult, keyword_search
from pcs.index.service import (
    IndexStatusView,
    get_index_status,
    index_if_root_exists,
    reindex,
    search_code,
)

__all__ = [
    "IndexStatusView",
    "SearchHit",
    "SearchResult",
    "get_index_status",
    "index_if_root_exists",
    "keyword_search",
    "reindex",
    "search_code",
]
