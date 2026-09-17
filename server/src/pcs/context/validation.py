"""Write-time schema validation (FR3b, FR9b, FR9g, FR13).

Hard-rejects oversize ``headline`` / ``detail``. If only one field is supplied,
the other is derived by truncation — never by an LLM call (FR3b).
"""

from __future__ import annotations

import re

from pcs.context.types import (
    ALL_SECTIONS,
    DETAIL_MAX_CHARS,
    DIAGRAM_MAX_CHARS,
    HEADLINE_MAX_CHARS,
    REQUIREMENT_STATUSES,
    SECTION_FEATURES,
    SECTION_REQUIREMENTS,
    ValidationError,
)


def derive_headline_detail(
    *,
    headline: str | None,
    detail: str | None,
    headline_max: int = HEADLINE_MAX_CHARS,
    detail_max: int = DETAIL_MAX_CHARS,
) -> tuple[str, str]:
    """Return ``(headline, detail)`` or raise :class:`ValidationError` (FR3b, FR9g).

    A caller-supplied headline above ``headline_max`` is a hard reject. A
    headline derived from ``detail`` is truncated to fit.
    """
    raw_headline = (headline or "").strip()
    raw_detail = (detail or "").strip()
    if not raw_headline and not raw_detail:
        raise ValidationError("provide a headline and/or detail (FR3b)")

    if raw_headline:
        if len(raw_headline) > headline_max:
            raise ValidationError(
                f"headline exceeds {headline_max} characters (FR9g/D13); "
                "shorten it and retry — the server will not truncate a supplied headline"
            )
        resolved_headline = raw_headline
    else:
        first_line = raw_detail.split("\n", 1)[0]
        resolved_headline = _truncate(first_line, headline_max)

    if raw_detail:
        if len(raw_detail) > detail_max:
            raise ValidationError(
                f"detail exceeds {detail_max} characters (FR9g/D13); "
                "shorten it and retry — the server will not truncate a supplied detail"
            )
        resolved_detail = raw_detail
    else:
        resolved_detail = resolved_headline

    return resolved_headline, resolved_detail


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    if limit <= 1:
        return text[:limit]
    return text[: limit - 1].rstrip() + "…"


def validate_section(section: str) -> str:
    """Return a known section name or raise (FR2, FR13)."""
    key = section.strip()
    if key not in ALL_SECTIONS:
        allowed = ", ".join(ALL_SECTIONS)
        raise ValidationError(f"unknown section {section!r}; expected one of: {allowed}")
    return key


def validate_requirement_status(status: str) -> str:
    """Return a canonical requirement-status token or raise (FR2, FR13)."""
    key = status.strip()
    aliases = {
        "not_started": "not-started",
        "not started": "not-started",
        "in_progress": "in-progress",
        "in progress": "in-progress",
    }
    key = aliases.get(key, key)
    if key not in REQUIREMENT_STATUSES:
        allowed = ", ".join(sorted(REQUIREMENT_STATUSES))
        raise ValidationError(f"invalid requirement status {status!r}; expected one of: {allowed}")
    return key


def default_requirement_status(section: str, supplied: str | None) -> str | None:
    """Requirements default to ``not-started``; other sections have no req status."""
    if section != SECTION_REQUIREMENTS:
        if supplied:
            raise ValidationError("requirement_status is only valid on the requirements section")
        return None
    if supplied is None or not supplied.strip():
        return "not-started"
    return validate_requirement_status(supplied)


_BLOCK_OPENERS = frozenset({"loop", "alt", "opt", "par", "critical", "break", "rect", "box"})
_BLOCK_CONTINUATIONS = frozenset({"else", "and", "option"})

_ACTOR = r'(?:"[^"]+"|[\w.\-]+)'
_ARROW_RE = re.compile(
    rf"^{_ACTOR}\s*(?:-->>|->>|-->|->|--x|-x|--\)|-\))[+-]?\s*{_ACTOR}\s*:.*$",
    re.IGNORECASE,
)
_PARTICIPANT_RE = re.compile(
    r"^(?:participant|actor|create\s+(?:participant|actor)|destroy)\s+\S.*$",
    re.IGNORECASE,
)
_NOTE_RE = re.compile(r"^Note\s+(?:left of|right of|over)\s+.+:.*$", re.IGNORECASE)
_ACTIVATE_RE = re.compile(r"^(?:activate|deactivate)\s+\S+$", re.IGNORECASE)
_DIRECTIVE_RE = re.compile(r"^(?:autonumber\b.*|title\b.*|%%.*)$", re.IGNORECASE)


def _validate_diagram_syntax(text: str) -> None:
    """Heuristically reject a malformed Mermaid ``sequenceDiagram`` (agent-authored).

    Not a full grammar parser — no such dependency exists in this backend, and
    a real one is out of scope. This is a pragmatic guard against the mistakes
    actually seen in practice: a missing header, a bare ``;`` (Mermaid treats
    it as a statement separator and silently corrupts the line at render
    time — the incident that motivated this function), unbalanced blocks, and
    unrecognized statement shapes. Deliberately lenient elsewhere — no
    required participant pre-declaration (Mermaid auto-declares on first
    use), no else/and/option-vs-parent-block checking, case-insensitive
    keywords — to keep false-positive risk on real diagrams near zero.
    """
    lines = text.splitlines()

    first_line = lines[0].strip()
    if first_line != "sequenceDiagram":
        raise ValidationError(
            "diagram must start with a 'sequenceDiagram' header as its first line; "
            f"first line was {first_line!r} — add 'sequenceDiagram' on its own line "
            "before any participant/message lines"
        )

    stack: list[tuple[str, int]] = []
    for n, raw_line in enumerate(lines, start=1):
        stripped = raw_line.strip()
        if not stripped:
            continue

        if ";" in raw_line:
            raise ValidationError(
                f"diagram line {n} contains a literal ';': {stripped!r} — Mermaid "
                "sequence diagrams treat ';' as a statement separator and will "
                "silently split or corrupt this line at render time; remove the "
                "semicolon (rewrite as two separate statement lines, or use ',' "
                "/ '—' instead) and retry"
            )

        if stripped == "sequenceDiagram":
            continue

        first_word = stripped.split(None, 1)[0].lower()
        if first_word in _BLOCK_OPENERS:
            stack.append((first_word, n))
            continue
        if first_word in _BLOCK_CONTINUATIONS:
            continue
        if stripped.lower() == "end":
            if not stack:
                raise ValidationError(
                    f"diagram line {n} has an 'end' with no matching open block — "
                    "remove it, or add a matching loop/alt/opt/par/critical/break/"
                    "rect/box above it"
                )
            stack.pop()
            continue

        if (
            _ARROW_RE.match(stripped)
            or _PARTICIPANT_RE.match(stripped)
            or _NOTE_RE.match(stripped)
            or _ACTIVATE_RE.match(stripped)
            or _DIRECTIVE_RE.match(stripped)
        ):
            continue

        raise ValidationError(
            f"diagram line {n} doesn't look like valid Mermaid sequence-diagram "
            f"syntax: {stripped!r} — expected a participant/actor declaration, a "
            "message ('A->>B: text'), a Note ('Note over A: text'), "
            "activate/deactivate, or a block keyword (loop/alt/opt/par/critical/"
            "break/rect/box/else/and/option/end)"
        )

    if stack:
        kind, n = stack[0]
        raise ValidationError(
            f"diagram has {len(stack)} unclosed block(s); the first is {kind!r} "
            f"opened at line {n} — every loop/alt/opt/par/critical/break/rect/box "
            "needs a matching 'end'"
        )


def bound_diagram(
    section: str, diagram: str | None, max_chars: int = DIAGRAM_MAX_CHARS
) -> str | None:
    """Agent-authored Mermaid ``sequenceDiagram`` text, features-section only.

    Hard-rejects over ``max_chars`` (like ``detail`` — never truncated) and
    hard-rejects malformed Mermaid syntax (see :func:`_validate_diagram_syntax`).
    Empty/whitespace clears the field.
    """
    if section != SECTION_FEATURES:
        if diagram:
            raise ValidationError("diagram is only valid on the features section")
        return None
    cleaned = (diagram or "").strip()
    if not cleaned:
        return None
    if len(cleaned) > max_chars:
        raise ValidationError(
            f"diagram exceeds {max_chars} characters (FR9g/D13); "
            "shorten it and retry — the server will not truncate a supplied diagram"
        )
    _validate_diagram_syntax(cleaned)
    return cleaned
