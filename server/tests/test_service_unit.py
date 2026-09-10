"""Pure-function unit tests for the context service (no DB)."""

from __future__ import annotations

from pcs.context.service import BRIEFING_TOKEN_CAP, cap_to_tokens


def test_cap_to_tokens_is_a_noop_under_budget() -> None:
    text = "short briefing"
    assert cap_to_tokens(text) == text


def test_cap_to_tokens_hard_caps_at_the_1500_token_budget() -> None:
    oversized = "x" * (BRIEFING_TOKEN_CAP * 4 + 500)
    capped = cap_to_tokens(oversized)
    assert len(capped) < len(oversized)
    assert "truncated to the 1500-token cap" in capped
