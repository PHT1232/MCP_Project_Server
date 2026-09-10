"""Deterministic project-briefing assembly (FR9c, FR9e, FR9f, NFR2).

Ranks and trims headlines to the token budget with no LLM. Items that do not
fit collapse to a count plus a ``get_section`` / ``get_entry`` drill-down
pointer. The stored copy is never mutated.
"""

from __future__ import annotations

from collections.abc import Sequence

from pcs.context.summarizer import Summarizer, fallback_truncate, get_summarizer
from pcs.context.types import (
    ALL_SECTIONS,
    BRIEFING_TOKEN_CAP,
    CHARS_PER_TOKEN,
    REQ_BLOCKED,
    REQ_DONE,
    REQ_IN_PROGRESS,
    REQ_NOT_STARTED,
    SECTION_BLOCKERS,
    SECTION_BUGS,
    SECTION_CONVENTIONS,
    SECTION_DECISIONS,
    SECTION_FOCUS,
    SECTION_GLOSSARY,
    SECTION_HEADINGS,
    SECTION_OVERVIEW,
    SECTION_REQUIREMENTS,
    AssemblyEntry,
)

# FR9c default rank order (overview is always first so AC1's identity lands).
_RANK: tuple[str, ...] = (
    SECTION_OVERVIEW,
    SECTION_BLOCKERS,
    SECTION_FOCUS,
    SECTION_BUGS,
    SECTION_CONVENTIONS,
    SECTION_DECISIONS,
    SECTION_REQUIREMENTS,
    SECTION_GLOSSARY,
)


def estimate_tokens(text: str) -> int:
    """Cheap token estimate used everywhere (~4 chars/token, D13)."""
    if not text:
        return 0
    return (len(text) + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN


def cap_to_tokens(text: str, max_tokens: int = BRIEFING_TOKEN_CAP) -> str:
    """Last-resort hard cap. Assembly should already be under budget (FR9c)."""
    max_chars = max_tokens * CHARS_PER_TOKEN
    if len(text) <= max_chars:
        return text
    note = (
        f"\n\n[briefing truncated to the {max_tokens}-token cap — "
        "call get_section / get_entry for the full content]"
    )
    body_budget = max(0, max_chars - len(note))
    return text[:body_budget].rstrip() + note


def assemble_briefing(
    *,
    project_name: str,
    entries: Sequence[AssemblyEntry],
    budget_tokens: int = BRIEFING_TOKEN_CAP,
    sections: Sequence[str] | None = None,
    summarizer: Summarizer | None = None,
) -> str:
    """Build the plain-text briefing from already-filtered visible entries (FR9c).

    ``entries`` must already exclude deleted / resolved / expired rows — this
    function does not touch the store (FR9a, AC4a).
    """
    wanted = _wanted_sections(sections)
    by_section = _group(entries, wanted)
    focus_ids = {e.id for e in by_section.get(SECTION_FOCUS, ())}

    parts: list[str] = [f"# {project_name} — project briefing", ""]
    backend = summarizer if summarizer is not None else get_summarizer()

    for section in _RANK:
        if section not in wanted:
            continue
        chunk = _render_section(
            section,
            by_section.get(section, ()),
            project_name=project_name,
            focus_ids=focus_ids,
            summarizer=backend,
        )
        if not chunk:
            continue
        _append_fitting(parts, chunk, budget_tokens, project_name)

    text = "\n".join(parts).rstrip() + "\n"
    return cap_to_tokens(text, budget_tokens)


def _wanted_sections(sections: Sequence[str] | None) -> set[str]:
    if not sections:
        return set(ALL_SECTIONS)
    wanted = {s.strip() for s in sections if s.strip()}
    unknown = wanted - set(ALL_SECTIONS)
    if unknown:
        # FR6 scoping: ignore unknown names rather than fail the briefing.
        wanted -= unknown
    return wanted or set(ALL_SECTIONS)


def _group(entries: Sequence[AssemblyEntry], wanted: set[str]) -> dict[str, list[AssemblyEntry]]:
    grouped: dict[str, list[AssemblyEntry]] = {s: [] for s in wanted}
    for entry in entries:
        if entry.section in grouped:
            grouped[entry.section].append(entry)
    return grouped


def _append_fitting(parts: list[str], chunk: list[str], budget: int, project_name: str) -> None:
    """Greedy: keep the heading plus as many body lines as fit; collapse the rest."""
    if not chunk:
        return
    heading, *body = chunk
    prefix = [*parts, ""] if parts[-1:] != [""] else list(parts)

    def fits(lines: list[str]) -> bool:
        return estimate_tokens("\n".join(lines)) <= budget

    if not fits([*prefix, heading]):
        return
    accepted = [heading]
    skipped = 0
    for i, line in enumerate(body):
        if fits([*prefix, *accepted, line]):
            accepted.append(line)
        else:
            skipped = len(body) - i
            break
    if skipped:
        collapse = _collapse_line(skipped, _heading_to_section(heading), project_name)
        while not fits([*prefix, *accepted, collapse]) and len(accepted) > 1:
            accepted.pop()
            skipped += 1
            collapse = _collapse_line(skipped, _heading_to_section(heading), project_name)
        if fits([*prefix, *accepted, collapse]):
            accepted.append(collapse)
    if parts[-1:] != [""]:
        parts.append("")
    parts.extend(accepted)


def _heading_to_section(heading: str) -> str:
    title = heading.removeprefix("## ").strip()
    for key, label in SECTION_HEADINGS.items():
        if label == title:
            return key
    return title.lower()


def _collapse_line(count: int, section: str, project_name: str) -> str:
    label = SECTION_HEADINGS.get(section, section).lower()
    return (
        f"+{count} more {label} — call get_section(project={project_name!r}, section={section!r})"
    )


def _render_section(
    section: str,
    entries: Sequence[AssemblyEntry],
    *,
    project_name: str,
    focus_ids: set[str],
    summarizer: Summarizer,
) -> list[str]:
    heading = f"## {SECTION_HEADINGS[section]}"
    if section == SECTION_OVERVIEW:
        return _render_overview(heading, entries, project_name, summarizer)
    if section == SECTION_REQUIREMENTS:
        return _render_requirements(heading, entries, project_name)
    ordered = _order(section, entries, focus_ids)
    if not ordered:
        if section in {SECTION_FOCUS}:
            return [heading, "(no current focus set)"]
        return []
    lines = [heading]
    for entry in ordered:
        extra = ""
        if section == SECTION_REQUIREMENTS and entry.requirement_status:
            extra = f" [{entry.requirement_status}]"
        lines.append(f"- [{entry.id}]{extra} {entry.headline}")
    return lines


def _render_overview(
    heading: str,
    entries: Sequence[AssemblyEntry],
    project_name: str,
    summarizer: Summarizer,
) -> list[str]:
    if not entries:
        return [heading, "(no overview recorded)"]
    entry = entries[0]
    lines = [heading, f"[{entry.id}] {entry.headline}"]
    detail = entry.detail.strip()
    if not detail or detail == entry.headline:
        return lines
    # Prefer verbatim detail (FR9a). If it's long, FR9d seam then FR9e fallback.
    budget_for_detail = 200
    if estimate_tokens(detail) <= budget_for_detail:
        lines.append(detail)
        return lines
    summary = None
    if summarizer.is_available():
        summary = summarizer.summarize(detail, max_tokens=budget_for_detail, cache_key=entry.id)
    if summary:
        lines.append(summary)
    else:
        lines.append(
            fallback_truncate(
                detail,
                max_tokens=budget_for_detail,
                entry_id=entry.id,
                project=project_name,
            )
        )
    return lines


def _render_requirements(
    heading: str,
    entries: Sequence[AssemblyEntry],
    project_name: str,
) -> list[str]:
    del project_name
    if not entries:
        return []
    counts = {
        REQ_DONE: 0,
        REQ_IN_PROGRESS: 0,
        REQ_BLOCKED: 0,
        REQ_NOT_STARTED: 0,
    }
    for entry in entries:
        status = entry.requirement_status or REQ_NOT_STARTED
        counts[status] = counts.get(status, 0) + 1
    total = len(entries)
    summary = (
        f"{counts[REQ_DONE]}/{total} done · "
        f"{counts[REQ_IN_PROGRESS]} in progress · "
        f"{counts[REQ_BLOCKED]} blocked · "
        f"{counts[REQ_NOT_STARTED]} not started"
    )
    lines = [heading, summary]
    highlighted = [e for e in entries if e.requirement_status in {REQ_BLOCKED, REQ_IN_PROGRESS}]
    highlighted.sort(key=lambda e: (0 if e.requirement_status == REQ_BLOCKED else 1, -e.priority))
    for entry in highlighted:
        lines.append(f"- [{entry.id}] [{entry.requirement_status}] {entry.headline}")
    return lines


def _order(
    section: str, entries: Sequence[AssemblyEntry], focus_ids: set[str]
) -> list[AssemblyEntry]:
    items = list(entries)
    if section == SECTION_CONVENTIONS:
        items.sort(
            key=lambda e: (
                0 if e.related_entry_id in focus_ids else 1,
                -e.priority,
                -e.updated_at.timestamp(),
            )
        )
        return items
    if section == SECTION_DECISIONS:
        items.sort(key=lambda e: -e.updated_at.timestamp())
        return items
    items.sort(key=lambda e: (-e.priority, -e.updated_at.timestamp()))
    return items
