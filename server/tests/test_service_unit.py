"""Pure-function unit tests for validation and briefing assembly (no DB)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from pcs.context.assembly import assemble_briefing, cap_to_tokens, estimate_tokens
from pcs.context.service import BRIEFING_TOKEN_CAP
from pcs.context.types import (
    HEADLINE_MAX_CHARS,
    SECTION_BLOCKERS,
    SECTION_BUGS,
    SECTION_CONVENTIONS,
    SECTION_FOCUS,
    SECTION_OVERVIEW,
    AssemblyEntry,
    ValidationError,
)
from pcs.context.validation import derive_headline_detail, validate_section


def test_cap_to_tokens_is_a_noop_under_budget() -> None:
    text = "short briefing"
    assert cap_to_tokens(text) == text


def test_cap_to_tokens_hard_caps_at_the_1500_token_budget() -> None:
    oversized = "x" * (BRIEFING_TOKEN_CAP * 4 + 500)
    capped = cap_to_tokens(oversized)
    assert len(capped) < len(oversized)
    assert "truncated to the 1500-token cap" in capped


def test_headline_over_limit_is_hard_rejected() -> None:
    with pytest.raises(ValidationError, match="headline exceeds"):
        derive_headline_detail(headline="h" * (HEADLINE_MAX_CHARS + 1), detail="ok")


def test_detail_over_limit_is_hard_rejected() -> None:
    with pytest.raises(ValidationError, match="detail exceeds"):
        derive_headline_detail(headline="ok", detail="d" * 8001)


def test_missing_headline_is_derived_by_truncation() -> None:
    detail = "A" * 200 + "\nmore"
    headline, resolved = derive_headline_detail(headline=None, detail=detail)
    assert len(headline) == HEADLINE_MAX_CHARS
    assert headline.endswith("…")
    assert resolved == detail


def test_missing_detail_copies_headline() -> None:
    headline, detail = derive_headline_detail(headline="Ship the checkout rewrite", detail=None)
    assert headline == "Ship the checkout rewrite"
    assert detail == headline


def test_unknown_section_is_rejected() -> None:
    with pytest.raises(ValidationError, match="unknown section"):
        validate_section("secrets")


def test_assembly_includes_ranked_sections_and_ids() -> None:
    now = datetime.now(UTC)
    text = assemble_briefing(
        project_name="acme",
        budget_tokens=1500,
        entries=[
            AssemblyEntry("ov", SECTION_OVERVIEW, "Web app", "ACME web app.", 0, now),
            AssemblyEntry("fo", SECTION_FOCUS, "Checkout", "Rewrite checkout.", 0, now),
            AssemblyEntry("bl", SECTION_BLOCKERS, "API down", "Payments API 5xx.", 5, now),
            AssemblyEntry("bu", SECTION_BUGS, "Cart tax", "Tax double-counted.", 0, now),
            AssemblyEntry("co", SECTION_CONVENTIONS, "No any", "Don't use any.", 0, now),
        ],
    )
    assert text.startswith("# acme — project briefing")
    assert "## Overview" in text
    assert "## Blockers" in text
    assert "## Current focus" in text
    assert "## Bugs" in text
    assert "## Conventions" in text
    assert "[bl]" in text
    assert "[fo]" in text
    assert estimate_tokens(text) <= 1500


def test_assembly_collapses_over_budget_with_drilldown_pointer() -> None:
    now = datetime.now(UTC)
    bugs = [
        AssemblyEntry(
            f"bug-{i}",
            SECTION_BUGS,
            f"Bug headline number {i:02d} " + ("x" * 80),
            f"verbatim detail for bug {i} that must stay in the store",
            0,
            now,
        )
        for i in range(25)
    ]
    text = assemble_briefing(project_name="acme", budget_tokens=500, entries=bugs)
    assert estimate_tokens(text) <= 500
    assert "get_section" in text
    assert "more" in text
    # Headlines that fitted still carry their id (FR9f).
    assert "[bug-" in text
