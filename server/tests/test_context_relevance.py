"""Unit tests for the shared task-relevance scoring helpers (context/relevance.py)."""

from __future__ import annotations

from contextlib import suppress
from datetime import UTC, datetime

import pytest

from pcs.context import service as context_service
from pcs.context.relevance import (
    RELATED_ENTRY_BOOST,
    fit_text,
    path_overlap,
    paths_from_text,
    score_context_entry,
    select_relevant_context_entries,
    tokens,
)
from pcs.context.types import EntryView
from pcs.db.base import session_scope

pytestmark = pytest.mark.usefixtures("clean_db")
PROJECT = "relevance-a"


# ---------------------------------------------------------------------------
# Pure helpers — no DB
# ---------------------------------------------------------------------------
def test_tokens_lowercases_and_splits_on_word_boundaries() -> None:
    assert tokens("Wire Pricing Into Cart-Total!") == ["wire", "pricing", "into", "cart", "total"]


def test_tokens_drops_short_fragments() -> None:
    # _WORD_RE requires 3+ chars — single/double-char tokens are noise.
    assert tokens("a an it cart") == ["cart"]


def test_paths_from_text_extracts_pathish_tokens() -> None:
    found = paths_from_text("see shop/cart.py and also README.md for context")
    assert "shop/cart.py" in found
    assert "readme.md" in found


def test_path_overlap_matches_suffix_and_substring() -> None:
    assert path_overlap(["shop/cart.py"], ["repo/shop/cart.py"]) is True
    assert path_overlap(["./shop/cart.py"], ["shop/cart.py"]) is True
    assert path_overlap(["shop/cart.py"], ["shop/other.py"]) is False


def test_path_overlap_empty_inputs_never_match() -> None:
    assert path_overlap([], ["shop/cart.py"]) is False
    assert path_overlap(["shop/cart.py"], []) is False


def test_fit_text_returns_unchanged_when_within_budget() -> None:
    assert fit_text("short text", 100) == "short text"


def test_fit_text_truncates_with_ellipsis_when_over_budget() -> None:
    long_text = "x" * 200
    fitted = fit_text(long_text, 5)
    assert fitted.endswith("…")
    assert len(fitted) < len(long_text)


def test_fit_text_empty_string_for_zero_or_negative_budget() -> None:
    assert fit_text("anything", 0) == ""
    assert fit_text("anything", -5) == ""


# ---------------------------------------------------------------------------
# select_relevant_context_entries — needs a registered project
# ---------------------------------------------------------------------------
async def _register_project(name: str = PROJECT) -> None:
    async with session_scope() as session:
        with suppress(context_service.DuplicateProjectError):
            await context_service.register_project(
                session, name=name, root_path=f"/repos/{name}", overview="relevance fixture."
            )


async def _add_entry(
    project: str,
    section: str,
    *,
    headline: str,
    detail: str = "detail text",
    linked_files: tuple[str, ...] = (),
    related_entry_id: str | None = None,
    priority: int = 0,
) -> str:
    async with session_scope() as session:
        entry = await context_service.add_entry(
            session,
            project=project,
            section=section,
            headline=headline,
            detail=detail,
            linked_files=list(linked_files),
            related_entry_id=related_entry_id,
            priority=priority,
        )
        return entry.id


async def test_select_relevant_returns_empty_when_no_signal() -> None:
    await _register_project()
    await _add_entry(PROJECT, "conventions", headline="Unrelated topic about deployment")
    async with session_scope() as session:
        selected, omitted = await select_relevant_context_entries(
            session,
            project=PROJECT,
            section="conventions",
            task="wire pricing into cart total",
            focus_text="",
            focus_paths=[],
            ranked_paths=[],
            related_requirement_ids=frozenset(),
        )
    assert selected == []
    assert omitted == 0


async def test_select_relevant_caps_at_max_items_and_reports_omitted() -> None:
    project = "relevance-cap"
    await _register_project(project)
    for i in range(5):
        await _add_entry(
            project,
            "conventions",
            headline=f"cart pricing rule {i}",
            linked_files=("shop/cart.py",),
        )
    async with session_scope() as session:
        selected, omitted = await select_relevant_context_entries(
            session,
            project=project,
            section="conventions",
            task="cart pricing",
            focus_text="",
            focus_paths=[],
            ranked_paths=["shop/cart.py"],
            related_requirement_ids=frozenset(),
            max_items=2,
        )
    assert len(selected) == 2
    assert omitted == 3


async def test_select_relevant_boosts_entry_linked_to_task_requirement() -> None:
    project = "relevance-boost"
    await _register_project(project)
    req = await _add_entry(project, "requirements", headline="Cart totals")
    # Weak text signal (no overlap with task/ranked_paths at all) but linked
    # to the task's own requirement — should still be selected via the boost.
    boosted_id = await _add_entry(
        project,
        "decisions",
        headline="xyzzy plugh unrelated words",
        detail="nothing shares any tokens with the task text",
        related_entry_id=req,
    )
    async with session_scope() as session:
        selected, omitted = await select_relevant_context_entries(
            session,
            project=project,
            section="decisions",
            task="wire pricing into cart total",
            focus_text="",
            focus_paths=[],
            ranked_paths=[],
            related_requirement_ids=frozenset({req}),
        )
    assert [e.id for e in selected] == [boosted_id]
    assert omitted == 0


def _make_entry(
    *,
    headline: str,
    detail: str = "detail",
    linked_files: tuple[str, ...] = (),
    related_entry_id: str | None = None,
    priority: int = 0,
) -> EntryView:
    now = datetime.now(UTC)
    return EntryView(
        id="e1",
        project_id="p1",
        section="conventions",
        headline=headline,
        detail=detail,
        status="open",
        priority=priority,
        author="test",
        created_at=now,
        updated_at=now,
        linked_files=linked_files,
        related_entry_id=related_entry_id,
    )


def test_score_context_entry_no_signal_scores_zero() -> None:
    entry = _make_entry(headline="Unrelated topic", detail="nothing in common")
    match, _ = score_context_entry(
        entry,
        task="wire pricing into cart total",
        focus_text="",
        focus_paths=[],
        ranked_paths=[],
        related_requirement_ids=frozenset(),
    )
    assert match == 0


def test_score_context_entry_ranked_path_overlap_scores_positive() -> None:
    entry = _make_entry(headline="Cart rule", linked_files=("shop/cart.py",))
    match, _ = score_context_entry(
        entry,
        task="wire pricing into cart total",
        focus_text="",
        focus_paths=[],
        ranked_paths=["shop/cart.py"],
        related_requirement_ids=frozenset(),
    )
    assert match >= 100


def test_score_context_entry_related_requirement_id_boost_applies() -> None:
    entry = _make_entry(
        headline="xyzzy plugh unrelated words",
        detail="shares nothing with the task text",
        related_entry_id="req-1",
    )
    match, _ = score_context_entry(
        entry,
        task="wire pricing into cart total",
        focus_text="",
        focus_paths=[],
        ranked_paths=[],
        related_requirement_ids=frozenset({"req-1"}),
    )
    assert match == RELATED_ENTRY_BOOST


def test_score_context_entry_priority_is_returned_as_tiebreak() -> None:
    entry = _make_entry(headline="x", priority=42)
    _, priority = score_context_entry(
        entry,
        task="anything",
        focus_text="",
        focus_paths=[],
        ranked_paths=[],
        related_requirement_ids=frozenset(),
    )
    assert priority == 42
