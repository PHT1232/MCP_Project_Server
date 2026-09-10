"""Parse ``.project-context/requirements.md`` into blocks (FR16a).

Only the ``### R-NNN — title`` heading, the single ``<!-- req … -->`` metadata
line, and free-form prose are recognised. Optional leading YAML frontmatter and
any prose before the first ``###`` heading are treated as an opaque preamble and
never touched. A block the parser cannot read is marked with ``error`` and the
caller retains its last-good state (FR16a).
"""

from __future__ import annotations

from pcs.requirements.types import (
    FILE_STATUSES,
    HEADING_RE,
    ID_IN_HEADING_RE,
    MANAGED_LINE_RE,
    ManagedToken,
    ParsedBlock,
    ParsedFile,
    default_file_status,
)


def parse_requirements(text: str) -> ParsedFile:
    """Parse the file body. Never raises — problems land in ``fatal_errors`` / ``error``."""
    trailing_newline = text.endswith(("\n", "\r"))
    lines = text.splitlines()

    heading_idx = [i for i, line in enumerate(lines) if HEADING_RE.match(line)]
    preamble_end = heading_idx[0] if heading_idx else len(lines)

    parsed = ParsedFile(lines=lines, trailing_newline=trailing_newline, preamble_end=preamble_end)

    bounds = [*heading_idx, len(lines)]
    seen_keys: dict[str, int] = {}
    for pos, start in enumerate(heading_idx):
        end = bounds[pos + 1]
        block = _parse_block(lines, start, end)
        if block.req_key is not None:
            if block.req_key in seen_keys:
                parsed.fatal_errors.append(
                    f"duplicate requirement id {block.req_key} "
                    f"(lines {seen_keys[block.req_key] + 1} and {start + 1})"
                )
            else:
                seen_keys[block.req_key] = start
        parsed.blocks.append(block)
    return parsed


def _parse_block(lines: list[str], start: int, end: int) -> ParsedBlock:
    heading_text = HEADING_RE.match(lines[start])
    assert heading_text is not None  # start came from the same regex
    raw = heading_text.group("text")

    id_match = ID_IN_HEADING_RE.match(raw)
    if id_match is not None:
        req_key: str | None = id_match.group("key")
        title = id_match.group("title").strip()
    else:
        req_key = None
        title = raw.strip()

    body = lines[start + 1 : end]
    token: ManagedToken | None = None
    token_line: int | None = None
    error: str | None = None

    first_content = _first_non_blank(body)
    if first_content is not None:
        offset, line = first_content
        managed = MANAGED_LINE_RE.match(line)
        if managed is not None:
            token, error = _parse_token(managed.group("body"))
            token_line = start + 1 + offset

    prose_lines = [
        line for i, line in enumerate(body) if token_line is None or (start + 1 + i) != token_line
    ]
    prose = "\n".join(prose_lines).strip()

    if not title:
        error = error or "heading has no title text"

    return ParsedBlock(
        title=title,
        prose=prose,
        heading_line=start,
        req_key=req_key,
        token=token,
        token_line=token_line,
        error=error,
    )


def _first_non_blank(body: list[str]) -> tuple[int, str] | None:
    for i, line in enumerate(body):
        if line.strip():
            return i, line
    return None


def _parse_token(body: str) -> tuple[ManagedToken | None, str | None]:
    status = default_file_status()
    files: tuple[str, ...] = ()
    blocker: str | None = None
    extra: list[str] = []

    for part in body.split():
        if "=" not in part:
            return None, f"malformed req token {part!r} (expected key=value)"
        key, _, value = part.partition("=")
        if key == "status":
            if value not in FILE_STATUSES:
                allowed = ", ".join(sorted(FILE_STATUSES))
                return None, f"invalid status {value!r}; expected one of: {allowed}"
            status = value
        elif key == "files":
            files = tuple(f.strip() for f in value.split(",") if f.strip())
        elif key == "blocker":
            blocker = value.strip() or None
        else:
            extra.append(part)

    return ManagedToken(status=status, files=files, blocker=blocker, extra=tuple(extra)), None
