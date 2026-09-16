"""Draft plan proposal schema and strict local validation (T26, INV-PLAN-6).

Validates an AI provider's untrusted JSON output before anything derived from
it is returned to a caller. Pure — no DB or HTTP I/O, no imports from
``pcs.planning.service``. A :class:`PlanDraft` is never persisted by this
module; only ``create_plan_with_tasks`` (T23) writes rows, and only when a
caller explicitly calls it with data of their own choosing.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final

TITLE_MAX_CHARS: Final = 160
GOAL_MAX_CHARS: Final = 8000
OBJECTIVE_MAX_CHARS: Final = 8000
LOCAL_TASK_ID_MAX_CHARS: Final = 32
NOTES_MAX_CHARS: Final = 4000
TASKS_MIN: Final = 1
TASKS_MAX: Final = 30
AC_MAX_ITEMS: Final = 20
AC_MAX_CHARS: Final = 400
LINKED_FILES_MAX_ITEMS: Final = 20
LINKED_FILE_MAX_CHARS: Final = 400
REQUIREMENT_IDS_MAX_ITEMS: Final = 20
REQUIREMENT_ID_MAX_CHARS: Final = 80

_DRAFT_FIELDS: Final = frozenset({"title", "goal", "tasks", "dependencies", "notes"})
_TASK_FIELDS: Final = frozenset(
    {
        "local_task_id",
        "title",
        "objective",
        "acceptance_criteria",
        "linked_files",
        "requirement_ids",
    }
)
_DEPENDENCY_FIELDS: Final = frozenset({"task_local_id", "depends_on_local_id"})


class DraftValidationError(ValueError):
    """Malformed or invalid AI-provider draft proposal (T26)."""


@dataclass(frozen=True)
class DraftTask:
    """One proposed task within an unpersisted plan draft."""

    local_task_id: str
    title: str
    objective: str
    acceptance_criteria: tuple[str, ...] = ()
    linked_files: tuple[str, ...] = ()
    requirement_ids: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "local_task_id": self.local_task_id,
            "title": self.title,
            "objective": self.objective,
            "acceptance_criteria": list(self.acceptance_criteria),
            "linked_files": list(self.linked_files),
            "requirement_ids": list(self.requirement_ids),
        }


@dataclass(frozen=True)
class DraftDependency:
    """One proposed prerequisite edge, addressed by local task id."""

    task_local_id: str
    depends_on_local_id: str

    def as_dict(self) -> dict[str, object]:
        return {
            "task_local_id": self.task_local_id,
            "depends_on_local_id": self.depends_on_local_id,
        }


@dataclass(frozen=True)
class PlanDraft:
    """A fully validated, still-unpersisted plan proposal (INV-PLAN-6)."""

    title: str
    goal: str
    tasks: tuple[DraftTask, ...]
    dependencies: tuple[DraftDependency, ...] = field(default_factory=tuple)
    notes: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "title": self.title,
            "goal": self.goal,
            "tasks": [t.as_dict() for t in self.tasks],
            "dependencies": [d.as_dict() for d in self.dependencies],
            "notes": self.notes,
        }


def _require_str(obj: Mapping[str, object], key: str, *, max_chars: int) -> str:
    value = obj.get(key)
    if not isinstance(value, str):
        raise DraftValidationError(f"{key!r} must be a string")
    cleaned = value.strip()
    if not cleaned or len(cleaned) > max_chars:
        raise DraftValidationError(f"{key!r} must be between 1 and {max_chars} characters")
    return cleaned


def _string_list(
    value: object, *, field_name: str, max_items: int, max_chars: int
) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or len(value) > max_items:
        raise DraftValidationError(f"{field_name!r} must be a list of at most {max_items} strings")
    out: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise DraftValidationError(f"{field_name!r} entries must be non-empty strings")
        cleaned = item.strip()
        if len(cleaned) > max_chars:
            raise DraftValidationError(f"{field_name!r} entry exceeds {max_chars} characters")
        out.append(cleaned)
    return tuple(out)


def _normalize_linked_file(value: str) -> str:
    normalized = value.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    parts = normalized.split("/")
    if not normalized or normalized.startswith("/") or any(p in ("", "..") for p in parts):
        raise DraftValidationError(f"linked file {value!r} must be a repository-relative path")
    return normalized


def _check_acyclic(local_ids: Sequence[str], edges: Sequence[tuple[str, str]]) -> None:
    """Kahn's algorithm over local task ids. ``edges`` are (task, depends_on)."""
    adjacency: dict[str, list[str]] = {node: [] for node in local_ids}
    in_degree: dict[str, int] = {node: 0 for node in local_ids}
    for task_id, dep_id in edges:
        adjacency[dep_id].append(task_id)
        in_degree[task_id] += 1

    queue = deque(node for node in local_ids if in_degree[node] == 0)
    visited = 0
    while queue:
        current = queue.popleft()
        visited += 1
        for neighbor in adjacency[current]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if visited < len(local_ids):
        raise DraftValidationError("dependencies form a cycle")


def parse_plan_draft(raw: object) -> PlanDraft:
    """Strictly validate an AI provider's parsed-JSON draft response (T26).

    Raises :class:`DraftValidationError` on any schema violation, unknown
    field, bounds violation, dangling dependency reference, or cycle. Never
    partially accepts a malformed proposal.
    """
    if not isinstance(raw, dict):
        raise DraftValidationError("draft response must be a JSON object")
    unknown = set(raw) - _DRAFT_FIELDS
    if unknown:
        raise DraftValidationError(f"draft response has unknown fields: {sorted(unknown)}")

    title = _require_str(raw, "title", max_chars=TITLE_MAX_CHARS)
    goal = _require_str(raw, "goal", max_chars=GOAL_MAX_CHARS)

    raw_tasks = raw.get("tasks")
    if not isinstance(raw_tasks, list) or not (TASKS_MIN <= len(raw_tasks) <= TASKS_MAX):
        raise DraftValidationError(f"'tasks' must be a list of {TASKS_MIN}-{TASKS_MAX} objects")

    tasks: list[DraftTask] = []
    seen_ids: set[str] = set()
    for item in raw_tasks:
        if not isinstance(item, dict):
            raise DraftValidationError("each task must be an object")
        unknown_task = set(item) - _TASK_FIELDS
        if unknown_task:
            raise DraftValidationError(f"task has unknown fields: {sorted(unknown_task)}")
        local_id = _require_str(item, "local_task_id", max_chars=LOCAL_TASK_ID_MAX_CHARS)
        if local_id in seen_ids:
            raise DraftValidationError(f"duplicate local_task_id {local_id!r} in draft")
        seen_ids.add(local_id)
        task_title = _require_str(item, "title", max_chars=TITLE_MAX_CHARS)
        objective = _require_str(item, "objective", max_chars=OBJECTIVE_MAX_CHARS)
        acceptance_criteria = _string_list(
            item.get("acceptance_criteria"),
            field_name="acceptance_criteria",
            max_items=AC_MAX_ITEMS,
            max_chars=AC_MAX_CHARS,
        )
        linked_files = tuple(
            _normalize_linked_file(p)
            for p in _string_list(
                item.get("linked_files"),
                field_name="linked_files",
                max_items=LINKED_FILES_MAX_ITEMS,
                max_chars=LINKED_FILE_MAX_CHARS,
            )
        )
        requirement_ids = _string_list(
            item.get("requirement_ids"),
            field_name="requirement_ids",
            max_items=REQUIREMENT_IDS_MAX_ITEMS,
            max_chars=REQUIREMENT_ID_MAX_CHARS,
        )
        tasks.append(
            DraftTask(
                local_task_id=local_id,
                title=task_title,
                objective=objective,
                acceptance_criteria=acceptance_criteria,
                linked_files=linked_files,
                requirement_ids=requirement_ids,
            )
        )

    raw_deps = raw.get("dependencies") if raw.get("dependencies") is not None else []
    if not isinstance(raw_deps, list):
        raise DraftValidationError("'dependencies' must be a list of objects")
    dependencies: list[DraftDependency] = []
    for item in raw_deps:
        if not isinstance(item, dict):
            raise DraftValidationError("each dependency must be an object")
        unknown_dep = set(item) - _DEPENDENCY_FIELDS
        if unknown_dep:
            raise DraftValidationError(f"dependency has unknown fields: {sorted(unknown_dep)}")
        task_local_id = _require_str(item, "task_local_id", max_chars=LOCAL_TASK_ID_MAX_CHARS)
        depends_on_local_id = _require_str(
            item, "depends_on_local_id", max_chars=LOCAL_TASK_ID_MAX_CHARS
        )
        if task_local_id == depends_on_local_id:
            raise DraftValidationError(f"self-dependency on {task_local_id!r}")
        if task_local_id not in seen_ids or depends_on_local_id not in seen_ids:
            raise DraftValidationError(
                "dependency references a local_task_id not defined in 'tasks'"
            )
        dependencies.append(DraftDependency(task_local_id, depends_on_local_id))

    _check_acyclic(
        [t.local_task_id for t in tasks],
        [(d.task_local_id, d.depends_on_local_id) for d in dependencies],
    )

    notes_raw = raw.get("notes")
    notes: str | None = None
    if notes_raw is not None:
        if not isinstance(notes_raw, str):
            raise DraftValidationError("'notes' must be a string or null")
        notes = notes_raw.strip()[:NOTES_MAX_CHARS] or None

    return PlanDraft(
        title=title,
        goal=goal,
        tasks=tuple(tasks),
        dependencies=tuple(dependencies),
        notes=notes,
    )
