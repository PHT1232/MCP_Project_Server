"""Serialise requirement blocks back to the file (FR16a).

Writes are surgical: only the managed ``<!-- req … -->`` token line and the
heading's ``R-NNN`` id are ever machine-edited. Human prose, blank lines, and the
preamble are copied through byte-for-byte — never reflowed (FR16a, D15).
"""

from __future__ import annotations

from dataclasses import dataclass

from pcs.requirements.types import ManagedToken, ParsedFile

DEFAULT_TEMPLATE = """\
# Requirements

<!--
This file is kept in two-way sync with the Project Context MCP Server (FR16a, D12).

  * One `### R-NNN — title` heading per requirement.
  * Then one managed `<!-- req status=… files=… blocker=… -->` line.
  * Then free-form prose — yours; the server never reflows it.

`status` is one of: not-started | in-progress | blocked | done
(a missing `<!-- req … -->` line means not-started).

To add a requirement, write a new `### heading` with prose and run a sync — the
server assigns its `R-NNN` id and the metadata line. Titles and prose are yours
to edit; the `<!-- req … -->` line and the heading id belong to the server.
-->
"""


def render_heading(req_key: str, title: str) -> str:
    """``### R-001 — Title`` (em dash, matching the template)."""
    return f"### {req_key} — {title}"


def render_token(token: ManagedToken) -> str:
    """Serialise the managed metadata line."""
    parts = [f"status={token.status}"]
    if token.files:
        parts.append("files=" + ",".join(token.files))
    if token.blocker:
        parts.append(f"blocker={token.blocker}")
    parts.extend(token.extra)
    return "<!-- req " + " ".join(parts) + " -->"


def render_new_block(req_key: str, title: str, token: ManagedToken, prose: str) -> list[str]:
    """Lines for a store-first requirement being written into the file."""
    lines = ["", render_heading(req_key, title), render_token(token)]
    body = prose.strip("\n")
    if body:
        lines.append("")
        lines.extend(body.split("\n"))
    return lines


@dataclass(frozen=True)
class LineEdit:
    """One machine edit. ``insert`` adds a line before ``line``; else it replaces it."""

    line: int
    text: str
    insert: bool = False


def serialise(parsed: ParsedFile, edits: list[LineEdit], appended: list[list[str]]) -> str:
    """Apply ``edits`` and ``appended`` blocks to the parsed file, return new text."""
    lines = list(parsed.lines)
    for edit in sorted(edits, key=lambda e: (e.line, e.insert), reverse=True):
        if edit.insert:
            lines.insert(edit.line, edit.text)
        else:
            lines[edit.line] = edit.text
    for block in appended:
        lines.extend(block)
    # Always leave exactly one trailing newline.
    body = "\n".join(lines).rstrip("\n")
    return body + "\n"
