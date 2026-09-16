"""Context-store types, errors, and section constants (FR2, FR3, FR8, FR11, FR13).

No ORM or I/O — imported by the service, MCP, and HTTP layers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final

# FR2 — every project context contains these sections.
SECTION_OVERVIEW: Final = "overview"
SECTION_FOCUS: Final = "focus"
SECTION_BLOCKERS: Final = "blockers"
SECTION_BUGS: Final = "bugs"
SECTION_CONVENTIONS: Final = "conventions"
SECTION_DECISIONS: Final = "decisions"
SECTION_REQUIREMENTS: Final = "requirements"
SECTION_GLOSSARY: Final = "glossary"
# Per-feature docs (description, implementing files via linked_files, and the
# requirement it satisfies via related_entry_id). Deliberately excluded from
# _RANK in assembly.py, so it never appears in get_project_briefing regardless
# of the `sections` argument — read it back via get_section(project, "features")
# to protect the briefing token budget (FR9g).
SECTION_FEATURES: Final = "features"

ALL_SECTIONS: Final[tuple[str, ...]] = (
    SECTION_OVERVIEW,
    SECTION_FOCUS,
    SECTION_BLOCKERS,
    SECTION_BUGS,
    SECTION_CONVENTIONS,
    SECTION_DECISIONS,
    SECTION_REQUIREMENTS,
    SECTION_GLOSSARY,
    SECTION_FEATURES,
)

SECTION_HEADINGS: Final[dict[str, str]] = {
    SECTION_OVERVIEW: "Overview",
    SECTION_FOCUS: "Current focus",
    SECTION_BLOCKERS: "Blockers",
    SECTION_BUGS: "Bugs",
    SECTION_CONVENTIONS: "Conventions",
    SECTION_DECISIONS: "Decisions",
    SECTION_REQUIREMENTS: "Requirements",
    SECTION_GLOSSARY: "Glossary",
    SECTION_FEATURES: "Features",
}

# Lifecycle status (FR3, FR11). "deleted" is a soft-delete; the row is kept.
# "archived" (FR16a, AC22) is a requirement whose block was removed from the
# requirements file — kept in history, never resurrected.
STATUS_OPEN: Final = "open"
STATUS_RESOLVED: Final = "resolved"
STATUS_DELETED: Final = "deleted"
STATUS_ARCHIVED: Final = "archived"
LIFECYCLE_STATUSES: Final[frozenset[str]] = frozenset(
    {STATUS_OPEN, STATUS_RESOLVED, STATUS_DELETED, STATUS_ARCHIVED}
)
# Statuses hidden from normal reads (briefing, get_section) but kept in history.
HIDDEN_STATUSES: Final[frozenset[str]] = frozenset({STATUS_DELETED, STATUS_ARCHIVED})

# FR2 / FR16a requirement status tokens (store form; T02 maps the file tokens).
REQ_NOT_STARTED: Final = "not-started"
REQ_IN_PROGRESS: Final = "in-progress"
REQ_BLOCKED: Final = "blocked"
REQ_DONE: Final = "done"
REQUIREMENT_STATUSES: Final[frozenset[str]] = frozenset(
    {REQ_NOT_STARTED, REQ_IN_PROGRESS, REQ_BLOCKED, REQ_DONE}
)

# T10 — requirement contract model (invariants + acceptance criteria).
INVARIANT_KIND_BEHAVIOR: Final = "behavior"
INVARIANT_KIND_ARCHITECTURE: Final = "architecture"
INVARIANT_KIND_DATA_BOUNDARY: Final = "data-boundary"
INVARIANT_KIND_FORBIDDEN_PATH: Final = "forbidden-path"
INVARIANT_KIND_INTEGRATION: Final = "integration"
INVARIANT_KIND_MANUAL: Final = "manual"
INVARIANT_KINDS: Final[frozenset[str]] = frozenset(
    {
        INVARIANT_KIND_BEHAVIOR,
        INVARIANT_KIND_ARCHITECTURE,
        INVARIANT_KIND_DATA_BOUNDARY,
        INVARIANT_KIND_FORBIDDEN_PATH,
        INVARIANT_KIND_INTEGRATION,
        INVARIANT_KIND_MANUAL,
    }
)

RISK_LOW: Final = "low"
RISK_MEDIUM: Final = "medium"
RISK_HIGH: Final = "high"
RISK_LEVELS: Final[frozenset[str]] = frozenset({RISK_LOW, RISK_MEDIUM, RISK_HIGH})

EVIDENCE_KIND_TEST: Final = "test"
EVIDENCE_KIND_COMMAND: Final = "command"
EVIDENCE_KIND_REVIEW: Final = "review"
EVIDENCE_KIND_MANUAL: Final = "manual"
EVIDENCE_KIND_FILE: Final = "file"
EVIDENCE_KINDS: Final[frozenset[str]] = frozenset(
    {
        EVIDENCE_KIND_TEST,
        EVIDENCE_KIND_COMMAND,
        EVIDENCE_KIND_REVIEW,
        EVIDENCE_KIND_MANUAL,
        EVIDENCE_KIND_FILE,
    }
)

INDEPENDENT_REVIEW_NOT_REQUIRED: Final = "not-required"
INDEPENDENT_REVIEW_REQUIRED: Final = "required"
INDEPENDENT_REVIEW_POLICIES: Final[frozenset[str]] = frozenset(
    {INDEPENDENT_REVIEW_NOT_REQUIRED, INDEPENDENT_REVIEW_REQUIRED}
)

CONTRACT_ENTITY_INVARIANT: Final = "invariant"
CONTRACT_ENTITY_CRITERION: Final = "criterion"
CONTRACT_ENTITY_KINDS: Final[frozenset[str]] = frozenset(
    {CONTRACT_ENTITY_INVARIANT, CONTRACT_ENTITY_CRITERION}
)

CONTRACT_KEY_MAX_CHARS: Final = 64
CONTRACT_STATEMENT_MAX_CHARS: Final = 2000
CONTRACT_AUTHOR_MAX_CHARS: Final = 120

ACTION_CREATE: Final = "create"
ACTION_UPDATE: Final = "update"
ACTION_RESOLVE: Final = "resolve"
ACTION_DELETE: Final = "delete"
ACTION_ARCHIVE: Final = "archive"
REVISION_ACTIONS: Final[frozenset[str]] = frozenset(
    {ACTION_CREATE, ACTION_UPDATE, ACTION_RESOLVE, ACTION_DELETE, ACTION_ARCHIVE}
)

EXPIRY_OFF: Final = "off"
EXPIRY_AGE: Final = "age"
EXPIRY_POLICIES: Final[frozenset[str]] = frozenset({EXPIRY_OFF, EXPIRY_AGE})

# FR9g / D13 defaults. Per-project rows may override.
BRIEFING_TOKEN_CAP: Final = 1500
BRIEFING_TOKEN_MIN: Final = 500
BRIEFING_TOKEN_MAX: Final = 4000
PREPARE_TASK_TOKEN_CAP: Final = 4000
PREPARE_TASK_TOKEN_MIN: Final = 1000
PREPARE_TASK_TOKEN_MAX: Final = 16_000
HEADLINE_MAX_CHARS: Final = 120
DETAIL_MAX_CHARS: Final = 8000
# Agent-authored Mermaid sequenceDiagram syntax on a features-section entry.
DIAGRAM_MAX_CHARS: Final = 8000
CHARS_PER_TOKEN: Final = 4


class ProjectNotFoundError(Exception):
    """A call named a project that is not registered (D3, FR8, AC16)."""

    def __init__(self, project: str, available: list[str]) -> None:
        self.project = project
        self.available = available
        listed = ", ".join(available) if available else "(none registered yet)"
        label = project if project else "(missing)"
        super().__init__(
            f"Unknown project {label!r}. Registered projects: {listed}. "
            "Pass an exact project name or id on every call (D3)."
        )


class DuplicateProjectError(Exception):
    """A project with this name is already registered (FR14)."""


class EntryNotFoundError(Exception):
    """The named entry does not exist (or is not visible) in this project."""

    def __init__(self, entry_id: str, project: str) -> None:
        self.entry_id = entry_id
        self.project = project
        super().__init__(
            f"No entry {entry_id!r} in project {project!r}. "
            "Use get_section to list ids, or get_entry_history for deleted entries."
        )


class ValidationError(Exception):
    """Malformed write — rejected with an actionable message (FR13)."""


class ContractNotFoundError(Exception):
    """An invariant or criterion is missing (or hidden) in this project."""

    def __init__(self, entity: str, entity_id: str, project: str) -> None:
        self.entity = entity
        self.entity_id = entity_id
        self.project = project
        super().__init__(
            f"No {entity} {entity_id!r} in project {project!r}. "
            "Use list_invariants / list_criteria, or include_deleted for soft-deleted rows."
        )


@dataclass(frozen=True)
class ProjectSummary:
    """Lightweight view of a project row returned across the API boundary."""

    id: str
    name: str
    root_path: str
    status_line: str = ""
    briefing_token_budget: int = BRIEFING_TOKEN_CAP
    prepare_task_token_budget: int = PREPARE_TASK_TOKEN_CAP
    headline_max_chars: int = HEADLINE_MAX_CHARS
    detail_max_chars: int = DETAIL_MAX_CHARS
    expiry_policy: str = EXPIRY_OFF
    expiry_days: int | None = None


@dataclass(frozen=True)
class EntryView:
    """Public snapshot of one context entry (FR3, FR3b)."""

    id: str
    project_id: str
    section: str
    headline: str
    detail: str
    status: str
    priority: int
    author: str
    created_at: datetime
    updated_at: datetime
    requirement_status: str | None = None
    linked_files: tuple[str, ...] = ()
    related_entry_id: str | None = None
    req_key: str | None = None
    diagram: str | None = None

    def as_dict(self) -> dict[str, object]:
        """JSON-ready dict (ISO timestamps)."""
        return {
            "id": self.id,
            "project_id": self.project_id,
            "section": self.section,
            "headline": self.headline,
            "detail": self.detail,
            "status": self.status,
            "priority": self.priority,
            "author": self.author,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "requirement_status": self.requirement_status,
            "linked_files": list(self.linked_files),
            "related_entry_id": self.related_entry_id,
            "req_key": self.req_key,
            "diagram": self.diagram,
        }


@dataclass(frozen=True)
class RevisionView:
    """One immutable audit-log revision (FR11, D5)."""

    id: str
    entry_id: str
    action: str
    headline: str
    detail: str
    status: str
    priority: int
    author: str
    created_at: datetime
    requirement_status: str | None = None
    linked_files: tuple[str, ...] = ()
    related_entry_id: str | None = None
    diagram: str | None = None

    def as_dict(self) -> dict[str, object]:
        """JSON-ready dict (ISO timestamps)."""
        return {
            "id": self.id,
            "entry_id": self.entry_id,
            "action": self.action,
            "headline": self.headline,
            "detail": self.detail,
            "status": self.status,
            "priority": self.priority,
            "author": self.author,
            "created_at": self.created_at.isoformat(),
            "requirement_status": self.requirement_status,
            "linked_files": list(self.linked_files),
            "related_entry_id": self.related_entry_id,
            "diagram": self.diagram,
        }


@dataclass(frozen=True)
class AssemblyEntry:
    """Minimal entry shape consumed by deterministic briefing assembly (FR9c)."""

    id: str
    section: str
    headline: str
    detail: str
    priority: int
    updated_at: datetime
    related_entry_id: str | None = None
    requirement_status: str | None = None


@dataclass(frozen=True)
class InvariantView:
    """Public snapshot of one requirement invariant (T10)."""

    id: str
    project_id: str
    requirement_id: str
    key: str
    statement: str
    kind: str
    risk: str
    sort_order: int
    status: str
    author: str
    created_at: datetime
    updated_at: datetime

    def as_dict(self) -> dict[str, object]:
        """JSON-ready dict (ISO timestamps)."""
        return {
            "id": self.id,
            "project_id": self.project_id,
            "requirement_id": self.requirement_id,
            "key": self.key,
            "statement": self.statement,
            "kind": self.kind,
            "risk": self.risk,
            "sort_order": self.sort_order,
            "status": self.status,
            "author": self.author,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass(frozen=True)
class CriterionView:
    """Public snapshot of one acceptance criterion (T10)."""

    id: str
    project_id: str
    invariant_id: str
    key: str
    statement: str
    evidence_kind: str
    required: bool
    independent_review: str
    sort_order: int
    status: str
    author: str
    created_at: datetime
    updated_at: datetime

    def as_dict(self) -> dict[str, object]:
        """JSON-ready dict (ISO timestamps)."""
        return {
            "id": self.id,
            "project_id": self.project_id,
            "invariant_id": self.invariant_id,
            "key": self.key,
            "statement": self.statement,
            "evidence_kind": self.evidence_kind,
            "required": self.required,
            "independent_review": self.independent_review,
            "sort_order": self.sort_order,
            "status": self.status,
            "author": self.author,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass(frozen=True)
class ContractRevisionView:
    """One immutable contract-mutation audit row (T10)."""

    id: str
    project_id: str
    requirement_id: str
    entity_kind: str
    entity_id: str
    action: str
    snapshot: dict[str, object]
    author: str
    created_at: datetime

    def as_dict(self) -> dict[str, object]:
        """JSON-ready dict (ISO timestamps)."""
        return {
            "id": self.id,
            "project_id": self.project_id,
            "requirement_id": self.requirement_id,
            "entity_kind": self.entity_kind,
            "entity_id": self.entity_id,
            "action": self.action,
            "snapshot": dict(self.snapshot),
            "author": self.author,
            "created_at": self.created_at.isoformat(),
        }
