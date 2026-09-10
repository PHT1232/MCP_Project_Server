"""Project context store -- walking-skeleton subset (sections 7.1-7.2).

T00 implements only: register a project, set the current focus, assemble a
plain-text briefing (overview + focus). T01 owns the full store.
"""

from pcs.context import service

__all__ = ["service"]
