"""Dataclasses and constants for the requirements file (FR16a, D12, D15)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Final

from pcs.context.types import (
    REQ_DONE,
    REQ_NOT_STARTED,
    REQUIREMENT_STATUSES,
)

__all__ = [
    "FILE_STATUSES",
    "HEADING_RE",
    "ID_IN_HEADING_RE",
    "MANAGED_LINE_RE",
    "ManagedToken",
    "ParsedBlock",
    "ParsedFile",
    "ReconciliationNote",
    "RequirementView",
    "SyncReport",
    "default_file_status",
]

# The file's ``status=`` token uses the same vocabulary as the store (FR16a).
FILE_STATUSES: Final[frozenset[str]] = REQUIREMENT_STATUSES

# ``### R-001 - Title`` / ``### Some new requirement``
HEADING_RE: Final = re.compile(r"^###[ \t]+(?P<text>.*\S)[ \t]*$")
# Leading ``R-NNN`` id + a separator: em dash (U+2014), en dash (U+2013),
# hyphen, or colon.
ID_IN_HEADING_RE: Final = re.compile(
    "^(?P<key>R-\\d+)[ \\t]*[\u2014\u2013:-][ \\t]*(?P<title>.*\\S)[ \\t]*$"
)
# The single managed metadata line. Everything between ``req`` and ``-->``.
MANAGED_LINE_RE: Final = re.compile(r"^<!--[ \t]*req\b(?P<body>.*?)-->[ \t]*$")


def default_file_status() -> str:
    """A block with no managed metadata line is ``not-started`` (FR16a)."""
    return REQ_NOT_STARTED


@dataclass(frozen=True)
class ManagedToken:
    """Parsed ``<!-- req status=… files=… blocker=… -->`` line (FR16a)."""

    status: str
    files: tuple[str, ...] = ()
    blocker: str | None = None
    # Unrecognised ``key=value`` tokens, preserved verbatim on rewrite.
    extra: tuple[str, ...] = ()


@dataclass
class ParsedBlock:
    """One ``###`` requirement block with line offsets for surgical rewrites."""

    title: str
    prose: str
    heading_line: int
    req_key: str | None = None
    token: ManagedToken | None = None
    token_line: int | None = None
    error: str | None = None

    @property
    def status(self) -> str:
        return self.token.status if self.token is not None else default_file_status()


@dataclass
class ParsedFile:
    """The whole file: preamble (verbatim) + blocks + fatal errors."""

    lines: list[str]
    trailing_newline: bool
    preamble_end: int
    blocks: list[ParsedBlock] = field(default_factory=list)
    fatal_errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ReconciliationNote:
    """A status/existence conflict resolved during sync (FR16a, AC22)."""

    req_key: str
    message: str

    def as_dict(self) -> dict[str, object]:
        return {"req_key": self.req_key, "message": self.message}


@dataclass(frozen=True)
class RequirementView:
    """One requirement's synced state — for the frontend view (AC14a)."""

    req_key: str
    entry_id: str
    title: str
    status: str
    lifecycle: str
    linked_files: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "req_key": self.req_key,
            "entry_id": self.entry_id,
            "title": self.title,
            "status": self.status,
            "lifecycle": self.lifecycle,
            "linked_files": list(self.linked_files),
        }


@dataclass(frozen=True)
class SyncReport:
    """Outcome of one ``sync_requirements`` call (FR16a, AC18, AC22)."""

    project_id: str
    project_name: str
    file_path: str
    ok: bool
    file_existed: bool
    file_written: bool
    created: tuple[str, ...] = ()
    updated: tuple[str, ...] = ()
    archived: tuple[str, ...] = ()
    written_back: tuple[str, ...] = ()
    reconciliations: tuple[ReconciliationNote, ...] = ()
    errors: tuple[str, ...] = ()
    requirements: tuple[RequirementView, ...] = ()

    @property
    def total_count(self) -> int:
        return len(self.requirements)

    @property
    def done_count(self) -> int:
        return sum(1 for r in self.requirements if r.status == REQ_DONE)

    def as_dict(self) -> dict[str, object]:
        return {
            "project_id": self.project_id,
            "project_name": self.project_name,
            "file_path": self.file_path,
            "ok": self.ok,
            "file_existed": self.file_existed,
            "file_written": self.file_written,
            "created": list(self.created),
            "updated": list(self.updated),
            "archived": list(self.archived),
            "written_back": list(self.written_back),
            "reconciliations": [n.as_dict() for n in self.reconciliations],
            "errors": list(self.errors),
            "requirements": [r.as_dict() for r in self.requirements],
            "done_count": self.done_count,
            "total_count": self.total_count,
        }
