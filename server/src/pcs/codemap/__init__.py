"""Code-map API (`pcs.codemap`) — FR32, FR32a, FR33, FR39, D9, D11.

A dependency/structure graph projected on demand from what T03/T04 already
store (``code_index.{files,chunks,symbols,symbol_edges}``) plus the T01 curated
context entries. No new source parsing, no churn / git-history data (D11).

The graph is served with server-side level-of-detail: :func:`get_code_map`
returns the top directory tier and aggregated edges by default, and one subtree
level at a time when a ``scope`` is passed, so the client never holds the whole
graph (D9 / FR32a).
"""

from pcs.codemap.service import get_code_map

__all__ = ["get_code_map"]
