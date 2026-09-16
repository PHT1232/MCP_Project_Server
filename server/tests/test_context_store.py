"""Acceptance tests for the curated context store (service layer, real Postgres).

Covers AC1, AC3, AC4, AC4a, AC5, AC6, AC16, AC17 plus expiry, merge, and
read-after-write.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from pcs.context import service
from pcs.context.assembly import estimate_tokens
from pcs.context.types import ACTION_CREATE, ACTION_DELETE, ACTION_UPDATE, STATUS_DELETED
from pcs.db.base import reset_engine, session_scope
from pcs.db.models import ContextEntry

pytestmark = pytest.mark.usefixtures("clean_db")

PROJECT = "acme-web"
OVERVIEW = "ACME's customer-facing web app. React + FastAPI, deployed on Fly.io."
FOCUS = "Migrate the checkout flow off the legacy payments gateway."


async def _seed() -> None:
    async with session_scope() as session:
        await service.register_project(
            session, name=PROJECT, root_path="/repos/acme-web", overview=OVERVIEW
        )
    async with session_scope() as session:
        await service.set_current_focus(session, project=PROJECT, text=FOCUS)


async def test_ac1_briefing_includes_all_active_sections_under_budget() -> None:
    await _seed()
    async with session_scope() as session:
        await service.add_entry(
            session, project=PROJECT, section="blockers", headline="Payments API 5xx"
        )
        await service.add_entry(
            session, project=PROJECT, section="bugs", headline="Cart tax double-counted"
        )
        await service.add_entry(
            session, project=PROJECT, section="conventions", headline="No implicit any"
        )
    async with session_scope() as session:
        briefing = await service.get_project_briefing(session, project=PROJECT)
    assert OVERVIEW.split(".")[0] in briefing or "ACME" in briefing
    assert "Checkout" in briefing or FOCUS[:20] in briefing
    assert "Payments API 5xx" in briefing
    assert "Cart tax" in briefing
    assert "No implicit any" in briefing
    assert "## Overview" in briefing
    assert "## Blockers" in briefing
    assert "## Current focus" in briefing
    assert "## Bugs" in briefing
    assert "## Conventions" in briefing
    assert estimate_tokens(briefing) <= 1500


async def test_ac3_blocker_added_by_one_session_is_in_the_next_briefing() -> None:
    await _seed()
    async with session_scope() as session:
        await service.add_entry(
            session, project=PROJECT, section="blockers", detail="Need a sandbox key from finance"
        )
    async with session_scope() as session:
        briefing = await service.get_project_briefing(session, project=PROJECT)
    assert "sandbox key" in briefing


async def test_ac4_resolve_removes_bug_from_briefing_keeps_archive() -> None:
    await _seed()
    async with session_scope() as session:
        bug = await service.add_entry(
            session, project=PROJECT, section="bugs", headline="Null deref in cart"
        )
        bug_id = bug.id
    async with session_scope() as session:
        await service.resolve_entry(session, project=PROJECT, entry_id=bug_id)
    async with session_scope() as session:
        briefing = await service.get_project_briefing(session, project=PROJECT)
        archived = await service.get_section(
            session, project=PROJECT, section="bugs", include_resolved=True
        )
        history = await service.get_entry_history(session, project=PROJECT, entry_id=bug_id)
    assert "Null deref" not in briefing
    assert any(e.id == bug_id and e.status == "resolved" for e in archived)
    assert any(r.action == "resolve" for r in history)


async def test_ac4a_over_budget_collapses_and_store_is_unchanged() -> None:
    await _seed()
    async with session_scope() as session:
        await service.configure_project(session, project=PROJECT, briefing_token_budget=500)
        originals: list[tuple[str, str]] = []
        for i in range(20):
            entry = await service.add_entry(
                session,
                project=PROJECT,
                section="bugs",
                headline=f"Bug {i:02d} " + ("x" * 90),
                detail=f"VERBATIM-DETAIL-{i}-MUST-NOT-CHANGE",
            )
            originals.append((entry.id, entry.detail))
    async with session_scope() as session:
        briefing = await service.get_project_briefing(session, project=PROJECT)
        after = await service.get_section(session, project=PROJECT, section="bugs")
        first_id, first_detail = originals[0]
        fetched = await service.get_entry(session, project=PROJECT, entry_id=first_id)
    assert estimate_tokens(briefing) <= 500
    assert "get_section" in briefing
    assert "+" in briefing and "more" in briefing
    assert [(e.id, e.detail) for e in after] == originals
    assert fetched.detail == first_detail
    assert fetched.detail == "VERBATIM-DETAIL-0-MUST-NOT-CHANGE"


async def test_ac5_projects_are_isolated() -> None:
    await _seed()
    async with session_scope() as session:
        await service.register_project(
            session, name="other", root_path="/repos/other", overview="A different product"
        )
        await service.add_entry(
            session, project=PROJECT, section="blockers", headline="SECRET-ACME-BLOCKER"
        )
        await service.add_entry(
            session, project="other", section="blockers", headline="SECRET-OTHER-BLOCKER"
        )
    async with session_scope() as session:
        acme = await service.get_project_briefing(session, project=PROJECT)
        other = await service.get_project_briefing(session, project="other")
    assert "SECRET-ACME-BLOCKER" in acme
    assert "SECRET-OTHER-BLOCKER" not in acme
    assert "SECRET-OTHER-BLOCKER" in other
    assert "SECRET-ACME-BLOCKER" not in other


async def test_ac6_engine_reset_preserves_context() -> None:
    await _seed()
    async with session_scope() as session:
        await service.add_entry(
            session, project=PROJECT, section="decisions", headline="Postgres not SQLite"
        )
    await reset_engine()
    async with session_scope() as session:
        briefing = await service.get_project_briefing(session, project=PROJECT)
    assert OVERVIEW.split(".")[0] in briefing or "ACME" in briefing
    assert "Postgres not SQLite" in briefing


async def test_ac16_unknown_and_missing_project_list_registered() -> None:
    await _seed()
    with pytest.raises(service.ProjectNotFoundError) as unknown:
        async with session_scope() as session:
            await service.get_project_briefing(session, project="does-not-exist")
    assert PROJECT in str(unknown.value)
    assert unknown.value.available == [PROJECT]

    with pytest.raises(service.ProjectNotFoundError) as missing:
        async with session_scope() as session:
            await service.get_project_briefing(session, project="")
    assert PROJECT in str(missing.value)


async def test_ac17_two_edits_two_revisions_deleted_gone_from_reads() -> None:
    await _seed()
    async with session_scope() as session:
        entry = await service.add_entry(
            session, project=PROJECT, section="blockers", headline="Need staging access"
        )
        entry_id = entry.id
    async with session_scope() as session:
        await service.update_entry(
            session, project=PROJECT, entry_id=entry_id, headline="Need staging + VPN"
        )
    async with session_scope() as session:
        await service.update_entry(
            session, project=PROJECT, entry_id=entry_id, detail="Ticket OPEN-12 with IT"
        )
    async with session_scope() as session:
        history_before = await service.get_entry_history(
            session, project=PROJECT, entry_id=entry_id
        )
        await service.delete_entry(session, project=PROJECT, entry_id=entry_id)
    async with session_scope() as session:
        with pytest.raises(service.EntryNotFoundError):
            await service.get_entry(session, project=PROJECT, entry_id=entry_id)
        section = await service.get_section(session, project=PROJECT, section="blockers")
        briefing = await service.get_project_briefing(session, project=PROJECT)
        history = await service.get_entry_history(session, project=PROJECT, entry_id=entry_id)
    assert all(e.id != entry_id for e in section)
    assert "Need staging" not in briefing
    updates = [r for r in history if r.action == ACTION_UPDATE]
    assert len(updates) == 2
    assert any(r.action == ACTION_CREATE for r in history)
    assert any(r.action == ACTION_DELETE for r in history)
    assert history[-1].status == STATUS_DELETED
    assert len(history_before) == 3  # create + two updates


async def test_expiry_hides_stale_entries_when_policy_is_age() -> None:
    await _seed()
    async with session_scope() as session:
        entry = await service.add_entry(
            session, project=PROJECT, section="blockers", headline="Old blocker"
        )
        await service.configure_project(
            session, project=PROJECT, expiry_policy="age", expiry_days=1
        )
        row = await session.get(ContextEntry, entry.id)
        assert row is not None
        row.updated_at = datetime.now(UTC) - timedelta(days=3)
    async with session_scope() as session:
        briefing = await service.get_project_briefing(session, project=PROJECT)
        hidden = await service.get_section(session, project=PROJECT, section="blockers")
        shown = await service.get_section(
            session, project=PROJECT, section="blockers", include_resolved=True
        )
    assert "Old blocker" not in briefing
    assert hidden == []
    assert any(e.id == entry.id for e in shown)


async def test_fr17_concurrent_field_updates_merge() -> None:
    await _seed()
    async with session_scope() as session:
        entry = await service.add_entry(
            session,
            project=PROJECT,
            section="bugs",
            headline="Original headline",
            detail="Original detail",
        )
        entry_id = entry.id

    async def patch_headline() -> None:
        async with session_scope() as session:
            await service.update_entry(
                session, project=PROJECT, entry_id=entry_id, headline="Headline from A"
            )

    async def patch_detail() -> None:
        async with session_scope() as session:
            await service.update_entry(
                session, project=PROJECT, entry_id=entry_id, detail="Detail from B"
            )

    await asyncio.gather(patch_headline(), patch_detail())
    async with session_scope() as session:
        merged = await service.get_entry(session, project=PROJECT, entry_id=entry_id)
    assert merged.headline == "Headline from A"
    assert merged.detail == "Detail from B"


async def test_fr18_read_after_write_sees_acknowledged_write() -> None:
    await _seed()
    async with session_scope() as session:
        added = await service.add_entry(
            session, project=PROJECT, section="blockers", headline="Visible immediately"
        )
    async with session_scope() as session:
        briefing = await service.get_project_briefing(session, project=PROJECT)
        fetched = await service.get_entry(session, project=PROJECT, entry_id=added.id)
    assert "Visible immediately" in briefing
    assert fetched.headline == "Visible immediately"


async def test_requirement_status_round_trip() -> None:
    await _seed()
    async with session_scope() as session:
        req = await service.add_entry(
            session,
            project=PROJECT,
            section="requirements",
            headline="Persist context in PostgreSQL",
            requirement_status="in-progress",
        )
        await service.set_requirement_status(
            session, project=PROJECT, entry_id=req.id, status="done"
        )
    async with session_scope() as session:
        fetched = await service.get_entry(session, project=PROJECT, entry_id=req.id)
        briefing = await service.get_project_briefing(session, project=PROJECT)
    assert fetched.requirement_status == "done"
    assert "1/1 done" in briefing


async def test_features_section_round_trip_and_briefing_exclusion() -> None:
    await _seed()
    async with session_scope() as session:
        req = await service.add_entry(
            session,
            project=PROJECT,
            section="requirements",
            headline="Checkout supports Apple Pay",
        )
        feature = await service.add_entry(
            session,
            project=PROJECT,
            section="features",
            headline="Checkout",
            detail="Takes a cart + payment method, returns an order confirmation.",
            linked_files=["src/checkout/handler.py", "src/checkout/payment.py"],
            related_entry_id=req.id,
        )
    async with session_scope() as session:
        listed = await service.get_section(session, project=PROJECT, section="features")
        default_briefing = await service.get_project_briefing(session, project=PROJECT)
        explicit_briefing = await service.get_project_briefing(
            session, project=PROJECT, sections=["features"]
        )
    assert [e.id for e in listed] == [feature.id]
    assert listed[0].linked_files == ("src/checkout/handler.py", "src/checkout/payment.py")
    assert listed[0].related_entry_id == req.id
    # Features never appear in the briefing, even when explicitly requested —
    # they're not in assembly.py's _RANK, protecting the token budget (FR9g).
    assert "Takes a cart + payment method" not in default_briefing
    assert "Takes a cart + payment method" not in explicit_briefing

    async with session_scope() as session:
        updated = await service.update_entry(
            session,
            project=PROJECT,
            entry_id=feature.id,
            detail=(
                "Takes a cart + payment method + shipping address, "
                "returns an order confirmation."
            ),
            expected_section="features",
        )
    assert "shipping address" in updated.detail
    assert updated.linked_files == ("src/checkout/handler.py", "src/checkout/payment.py")

    async with session_scope() as session:
        await service.resolve_entry(
            session, project=PROJECT, entry_id=feature.id, expected_section="features"
        )
    async with session_scope() as session:
        active = await service.get_section(session, project=PROJECT, section="features")
        archived = await service.get_section(
            session, project=PROJECT, section="features", include_resolved=True
        )
    assert active == []
    assert any(e.id == feature.id and e.status == "resolved" for e in archived)
