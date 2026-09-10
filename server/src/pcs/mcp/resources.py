"""MCP resources ``context://{project}/*`` (FR7, FR9f)."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from pcs.context import service
from pcs.context.types import ALL_SECTIONS, SECTION_HEADINGS
from pcs.db.base import session_scope


def register_resources(mcp: FastMCP) -> None:
    """Attach one resource template per context section, plus entry history."""
    for section in ALL_SECTIONS:
        _register_section_resource(mcp, section)

    @mcp.resource("context://{project}/history/{entry_id}")
    async def history_resource(project: str, entry_id: str) -> str:
        """Immutable revision history of one entry (FR11)."""
        async with session_scope() as session:
            revisions = await service.get_entry_history(session, project=project, entry_id=entry_id)
        lines = [f"# history of {entry_id}", ""]
        if not revisions:
            lines.append("(no revisions)")
            return "\n".join(lines) + "\n"
        for rev in revisions:
            lines.extend(
                [
                    f"## {rev.action} @ {rev.created_at.isoformat()} by {rev.author}",
                    f"status: {rev.status}",
                    f"headline: {rev.headline}",
                    "",
                    rev.detail,
                    "",
                ]
            )
        return "\n".join(lines)


def _register_section_resource(mcp: FastMCP, section: str) -> None:
    uri = f"context://{{project}}/{section}"
    heading = SECTION_HEADINGS[section]

    async def reader(project: str) -> str:
        async with session_scope() as session:
            entries = await service.get_section(session, project=project, section=section)
        return service.format_section_text(section, entries)

    reader.__name__ = f"resource_{section}"
    reader.__doc__ = f"Verbatim {heading} section for a project (FR7, FR9f)."
    mcp.resource(uri)(reader)
