"""Generic task-relevance scoring for context-store entries (T25 follow-up).

Shared by ``requirements.briefing`` (scoring requirements for
``get_task_contract``) and ``planning.handoff`` (scoring conventions/decisions
for the task handoff prompt) so the two don't independently drift on what
"relevant to this task" means. No MCP/HTTP imports (AGENTS.md).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession

from pcs.context.assembly import estimate_tokens
from pcs.context.service import get_section
from pcs.context.types import CHARS_PER_TOKEN, EntryView

__all__ = [
    "CONTEXT_ENTRIES_TOKEN_CAP",
    "CONTEXT_ENTRIES_TOKEN_FLOOR",
    "CONTEXT_ENTRY_MIN_TOKENS",
    "MAX_CONTEXT_ENTRIES_PER_SECTION",
    "PATHISH_RE",
    "RELATED_ENTRY_BOOST",
    "WORD_RE",
    "fit_text",
    "path_overlap",
    "paths_from_text",
    "score_context_entry",
    "select_relevant_context_entries",
    "tokens",
]

WORD_RE = re.compile(r"[A-Za-z0-9_]{3,}")
PATHISH_RE = re.compile(r"[\w./-]+\.[A-Za-z0-9]+|[\w-]+/[\w./-]+")

# A convention/decision explicitly tied (via related_entry_id) to one of this
# task's own requirements is a high-precision, domain-specific signal — it
# should win ties with mere ranked-path overlap (100).
RELATED_ENTRY_BOOST: Final = 120
MAX_CONTEXT_ENTRIES_PER_SECTION: Final = 2
CONTEXT_ENTRIES_TOKEN_CAP: Final = 400
CONTEXT_ENTRIES_TOKEN_FLOOR: Final = 60
CONTEXT_ENTRY_MIN_TOKENS: Final = 20


def tokens(*parts: str) -> list[str]:
    blob = " ".join(parts)
    return [m.group(0).lower() for m in WORD_RE.finditer(blob)]


def paths_from_text(*blobs: str) -> set[str]:
    found: set[str] = set()
    for blob in blobs:
        for match in PATHISH_RE.finditer(blob):
            found.add(match.group(0).lower())
    return found


def path_overlap(linked: Sequence[str], candidates: Sequence[str]) -> bool:
    if not linked or not candidates:
        return False
    left = [p.lower().lstrip("./") for p in linked]
    right = [p.lower().lstrip("./") for p in candidates]
    for a in left:
        for b in right:
            if a == b or a.endswith("/" + b) or b.endswith("/" + a) or a in b or b in a:
                return True
    return False


def fit_text(text: str, max_tokens: int) -> str:
    if max_tokens <= 0:
        return ""
    if estimate_tokens(text) <= max_tokens:
        return text
    max_chars = max_tokens * CHARS_PER_TOKEN
    if max_chars <= 1:
        return ""
    return text[: max_chars - 1].rstrip() + "…"


def score_context_entry(
    entry: EntryView,
    *,
    task: str,
    focus_text: str,
    focus_paths: Sequence[str],
    ranked_paths: Sequence[str],
    related_requirement_ids: frozenset[str],
) -> tuple[int, int]:
    """Return ``(match_score, priority)``. Match is path/focus/task overlap.

    Same signal set as ``briefing._score_requirement``: ranked_paths overlap
    (+100), focus_paths overlap (+70), task-substring linked_files (+80),
    title substring in task (+40) or token overlap (+25), focus/title token
    overlap (+15). Plus a domain-specific boost (+120) when this entry is
    explicitly linked (``related_entry_id``) to one of the task's own
    requirements — see module docstring. ``priority`` is ``entry.priority``,
    the generic tiebreak replacing the requirement-only status boost.
    """
    match = 0
    task_l = task.lower()
    if entry.linked_files:
        if path_overlap(entry.linked_files, ranked_paths):
            match += 100
        if path_overlap(entry.linked_files, focus_paths):
            match += 70
        if any(f.lower() in task_l for f in entry.linked_files):
            match += 80
    title_l = entry.headline.lower()
    task_tokens = set(tokens(task))
    if title_l and title_l in task_l:
        match += 40
    elif task_tokens and set(tokens(entry.headline)) & task_tokens:
        match += 25
    if focus_text and set(tokens(entry.headline)) & set(tokens(focus_text)):
        match += 15
    if entry.related_entry_id and entry.related_entry_id in related_requirement_ids:
        match += RELATED_ENTRY_BOOST
    return match, entry.priority


async def select_relevant_context_entries(
    session: AsyncSession,
    *,
    project: str,
    section: str,
    task: str,
    focus_text: str,
    focus_paths: Sequence[str],
    ranked_paths: Sequence[str],
    related_requirement_ids: frozenset[str],
    max_items: int = MAX_CONTEXT_ENTRIES_PER_SECTION,
) -> tuple[list[EntryView], int]:
    """Rank ``section``'s entries by relevance to ``task``; cap at ``max_items``.

    Mirrors ``briefing._select_requirements``'s orchestration: never dumps
    unrelated entries when there's no relevance signal (``match > 0`` filter)
    — an empty catalog match means nothing is shown, not everything.
    """
    catalog = await get_section(session, project=project, section=section)
    scored: list[tuple[int, int, str, EntryView]] = []
    for entry in catalog:
        match, priority = score_context_entry(
            entry,
            task=task,
            focus_text=focus_text,
            focus_paths=focus_paths,
            ranked_paths=ranked_paths,
            related_requirement_ids=related_requirement_ids,
        )
        scored.append((match, priority, entry.id, entry))

    relevant = [row for row in scored if row[0] > 0]
    if not relevant:
        return [], 0
    relevant.sort(key=lambda row: (-row[0], -row[1], -row[3].updated_at.timestamp(), row[2]))
    omitted = max(0, len(relevant) - max_items)
    return [row[3] for row in relevant[:max_items]], omitted
