"""Requirements template file — parser + two-way sync with the store (FR16a, D12, D15).

The file (``.project-context/requirements.md`` by default) owns requirement
*existence* and *title/prose*; the context store owns *status*, *links*, and
*history*. :func:`pcs.requirements.service.sync_requirements` runs a 3-way merge
against the last-synced snapshot.
"""

from pcs.requirements.service import (
    list_requirements,
    resolve_requirements_path,
    sync_requirements,
    write_through_requirement_change,
)
from pcs.requirements.types import RequirementView, SyncReport

__all__ = [
    "RequirementView",
    "SyncReport",
    "list_requirements",
    "resolve_requirements_path",
    "sync_requirements",
    "write_through_requirement_change",
]
