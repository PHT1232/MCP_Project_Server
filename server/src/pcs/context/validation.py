"""Write-time schema validation (FR3b, FR9b, FR9g, FR13).

Hard-rejects oversize ``headline`` / ``detail``. If only one field is supplied,
the other is derived by truncation — never by an LLM call (FR3b).
"""

from __future__ import annotations

from pcs.context.types import (
    ALL_SECTIONS,
    DETAIL_MAX_CHARS,
    HEADLINE_MAX_CHARS,
    REQUIREMENT_STATUSES,
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
