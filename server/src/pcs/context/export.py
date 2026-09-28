"""Stateless full-project context export (Markdown + JSON).

Assembles every :data:`~pcs.context.types.ALL_SECTIONS` section verbatim —
no briefing-style truncation — for download / agent handoff. Requirements
entries stay entry-level only (no invariants, acceptance criteria, or
evidence nested under them).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession

from pcs.context import service
from pcs.context.types import (
    ALL_SECTIONS,
    SECTION_HEADINGS,
    EntryView,
    ProjectSummary,
    ValidationError,
)

EXPORT_FORMAT_MARKDOWN: Final = "markdown"
EXPORT_FORMAT_JSON: Final = "json"
EXPORT_FORMATS: Final[frozenset[str]] = frozenset({EXPORT_FORMAT_MARKDOWN, EXPORT_FORMAT_JSON})

_FILENAME_SAFE: Final = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True)
class ProjectExport:
    """In-memory full context dump used by both renderers."""

    project: ProjectSummary
    exported_at: datetime
    sections: dict[str, list[EntryView]]

    def as_dict(self) -> dict[str, object]:
        """JSON-ready tree: project metadata + all nine sections' entries."""
        return {
            "project": {
                "id": self.project.id,
                "name": self.project.name,
                "root_path": self.project.root_path,
                "status_line": self.project.status_line,
            },
            "exported_at": self.exported_at.isoformat(),
            "sections": {
                section: [entry.as_dict() for entry in entries]
                for section, entries in self.sections.items()
            },
        }


def validate_export_format(fmt: str) -> str:
    """Normalize and accept only ``markdown`` or ``json``.

    Raises:
        ValidationError: when ``fmt`` is empty or not one of the allowed values.
    """
    key = (fmt or "").strip().lower()
    if key not in EXPORT_FORMATS:
        allowed = ", ".join(sorted(EXPORT_FORMATS))
        raise ValidationError(f"invalid export format {fmt!r}; expected one of: {allowed}")
    return key


def export_filename(project_name: str, fmt: str) -> str:
    """Filesystem-safe download name for the chosen format."""
    safe = _FILENAME_SAFE.sub("-", project_name.strip()).strip("-._") or "project"
    ext = "md" if fmt == EXPORT_FORMAT_MARKDOWN else "json"
    return f"{safe}-context.{ext}"


def export_media_type(fmt: str) -> str:
    """MIME type for the rendered body."""
    if fmt == EXPORT_FORMAT_MARKDOWN:
        return "text/markdown; charset=utf-8"
    return "application/json; charset=utf-8"


async def assemble_project_export(
    session: AsyncSession,
    *,
    project: str,
) -> ProjectExport:
    """Load all nine sections with full entry detail (no truncation).

    Uses :func:`pcs.context.service.get_section` so soft-deleted / archived
    rows stay hidden; resolved entries are included for a complete dump.
    Requirements stay as plain entries — contract/evidence tables are not
    queried.
    """
    row = await service.resolve_project(session, project)
    project_summary = ProjectSummary(
        id=row.id,
        name=row.name,
        root_path=row.root_path,
        briefing_token_budget=row.briefing_token_budget,
        prepare_task_token_budget=row.prepare_task_token_budget,
        headline_max_chars=row.headline_max_chars,
        detail_max_chars=row.detail_max_chars,
        expiry_policy=row.expiry_policy,
        expiry_days=row.expiry_days,
    )
    sections: dict[str, list[EntryView]] = {}
    for section in ALL_SECTIONS:
        sections[section] = await service.get_section(
            session,
            project=row.id,
            section=section,
            include_resolved=True,
        )
    return ProjectExport(
        project=project_summary,
        exported_at=datetime.now(tz=UTC),
        sections=sections,
    )


def render_export_markdown(export: ProjectExport) -> str:
    """Render the assembled export as Markdown with every section heading."""
    lines: list[str] = [
        f"# {export.project.name} — project context export",
        "",
        f"Exported at: {export.exported_at.isoformat()}",
        f"Project id: `{export.project.id}`",
        f"Root path: `{export.project.root_path}`",
        "",
    ]
    for section in ALL_SECTIONS:
        heading = SECTION_HEADINGS[section]
        lines.append(f"## {heading}")
        lines.append("")
        entries = export.sections.get(section, [])
        if not entries:
            lines.append("_(empty)_")
            lines.append("")
            continue
        for entry in entries:
            lines.extend(_render_entry_markdown(entry))
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_export_json(export: ProjectExport) -> str:
    """Serialize the assembled export as pretty-printed JSON text."""
    return json.dumps(export.as_dict(), indent=2, ensure_ascii=False) + "\n"


async def export_project_context(
    session: AsyncSession,
    *,
    project: str,
    format: str = EXPORT_FORMAT_MARKDOWN,
) -> dict[str, object]:
    """Assemble + render; return the MCP/HTTP-shared payload envelope."""
    fmt = validate_export_format(format)
    export = await assemble_project_export(session, project=project)
    if fmt == EXPORT_FORMAT_MARKDOWN:
        content = render_export_markdown(export)
    else:
        content = render_export_json(export)
    return {
        "format": fmt,
        "filename": export_filename(export.project.name, fmt),
        "media_type": export_media_type(fmt),
        "content": content,
        "project": {
            "id": export.project.id,
            "name": export.project.name,
            "root_path": export.project.root_path,
        },
        "exported_at": export.exported_at.isoformat(),
    }


def _render_entry_markdown(entry: EntryView) -> list[str]:
    """Verbatim headline + detail for one entry (no token trimming)."""
    lines = [f"### {entry.headline}", ""]
    detail = entry.detail.strip()
    if detail and detail != entry.headline:
        lines.append(detail)
        lines.append("")
    meta: list[str] = [
        f"- id: `{entry.id}`",
        f"- status: `{entry.status}`",
        f"- priority: `{entry.priority}`",
        f"- author: `{entry.author}`",
        f"- updated_at: `{entry.updated_at.isoformat()}`",
    ]
    if entry.requirement_status is not None:
        meta.append(f"- requirement_status: `{entry.requirement_status}`")
    if entry.req_key is not None:
        meta.append(f"- req_key: `{entry.req_key}`")
    if entry.related_entry_id is not None:
        meta.append(f"- related_entry_id: `{entry.related_entry_id}`")
    if entry.linked_files:
        joined = ", ".join(f"`{path}`" for path in entry.linked_files)
        meta.append(f"- linked_files: {joined}")
    if entry.diagram:
        meta.append("- diagram:")
        lines.extend(meta)
        lines.append("")
        lines.append("```mermaid")
        lines.append(entry.diagram.rstrip())
        lines.append("```")
        return lines
    lines.extend(meta)
    return lines
