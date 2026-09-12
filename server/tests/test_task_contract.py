"""T11 compact contract retrieval - one regression per acceptance item."""

from __future__ import annotations

import importlib
from contextlib import suppress
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, patch

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from pcs.context import service
from pcs.context.assembly import estimate_tokens
from pcs.context.types import (
    CONTRACT_STATEMENT_MAX_CHARS,
    EntryNotFoundError,
    ValidationError,
)
from pcs.db.base import session_scope
from pcs.index import retrieval
from pcs.index import service as index_service
from pcs.mcp import mcp
from pcs.requirements import briefing, contracts
from pcs.requirements.briefing import (
    CONTRACT_TOKEN_CAP,
    CONTRACT_TOKEN_MIN,
    _is_missing_evidence_module,
    close_gate_from_payload,
    get_requirement_contract,
    get_task_contract,
)

pytestmark = pytest.mark.usefixtures("clean_db")

PROJECT = "acme-contract"
OVERVIEW = "Contract retrieval fixture repo."


def _sample_repo(root: Path) -> None:
    (root / "shop").mkdir()
    (root / "shop" / "cart.py").write_text(
        "from shop.pricing import unit_price\n\n"
        "def cart_total(items):\n"
        '    """Compute the total price of every item in the shopping cart."""\n'
        "    return sum(unit_price(item) for item in items)\n",
        encoding="utf-8",
    )
    (root / "shop" / "pricing.py").write_text(
        "def unit_price(item):\n    return item.price * item.quantity\n",
        encoding="utf-8",
    )


def _bulky_repo(root: Path) -> None:
    """Enough indexed source that packed code_tokens can meet the FR22a floor."""
    _sample_repo(root)
    for name in (
        "inventory",
        "orders",
        "discounts",
        "shipping",
        "customers",
        "catalog",
        "payments",
    ):
        body = [f'"""{name} helpers for cart totals, discounts, and pricing."""', ""]
        for i in range(12):
            body.append(f"def {name}_step_{i}(items):")
            body.append(
                f'    """Process {name} step {i} for cart totals, discounts, and pricing."""'
            )
            body.append(f"    return sum(getattr(item, 'price', 0) for item in items) + {i}")
            body.append("")
        (root / "shop" / f"{name}.py").write_text("\n".join(body), encoding="utf-8")


async def _register_project(root: Path | None = None, *, name: str = PROJECT) -> None:
    path = str(root) if root is not None else f"/repos/{name}"
    async with session_scope() as session:
        with suppress(service.DuplicateProjectError):
            await service.register_project(session, name=name, root_path=path, overview=OVERVIEW)


async def _register_and_index(root: Path, *, bulky: bool = False) -> None:
    if bulky:
        _bulky_repo(root)
    else:
        _sample_repo(root)
    await _register_project(root)
    async with session_scope() as session:
        await index_service.reindex(session, project=PROJECT, incremental=False)


async def _seed_requirement(
    *,
    title: str,
    linked_files: list[str] | None = None,
    status: str = "in-progress",
    req_key: str | None = None,
    project: str = PROJECT,
) -> str:
    await _register_project(name=project)
    async with session_scope() as session:
        req = await service.add_entry(
            session,
            project=project,
            section="requirements",
            headline=title,
            linked_files=linked_files or [],
            req_key=req_key,
        )
        await service.set_requirement_status(
            session, project=project, entry_id=req.id, status=status
        )
        return req.id


def _mcp_payload(result: object) -> dict[str, object]:
    if isinstance(result, tuple) and len(result) >= 2 and isinstance(result[1], dict):
        return {str(k): v for k, v in cast(dict[object, object], result[1]).items()}
    raise AssertionError(f"unexpected MCP result: {result!r}")


def _split(result: dict[str, object]) -> dict[str, int]:
    return cast(dict[str, int], result["split"])


async def test_empty_unconfigured_contracts_preserve_prepare_task_behavior(
    tmp_path: Path,
) -> None:
    await _register_and_index(tmp_path)
    async with session_scope() as session:
        result = await retrieval.prepare_task(
            session, project=PROJECT, task="add discount handling to the cart total"
        )
    split = _split(result)
    assert result["contract"] == ""
    assert split["contract_tokens"] == 0
    assert split["contract_cap"] == CONTRACT_TOKEN_CAP
    assert split["context_tokens"] <= split["context_cap"]
    assert split["context_tokens"] + split["code_tokens"] <= split["budget"]
    assert result["code_chunks"]
    assert split["code_budget"] >= split["code_floor"]


async def test_contract_section_caps_at_500_tokens_under_adversarial_input() -> None:
    req_id = await _seed_requirement(title="Cart discounts")
    long_stmt = "KEEP-FLOOR " + ("x" * (CONTRACT_STATEMENT_MAX_CHARS - 20))
    async with session_scope() as session:
        await contracts.create_invariant(
            session,
            project=PROJECT,
            requirement_id=req_id,
            key="INV-LONG",
            statement=long_stmt[:CONTRACT_STATEMENT_MAX_CHARS],
            kind="behavior",
            risk="high",
        )
        for i in range(8):
            await contracts.create_invariant(
                session,
                project=PROJECT,
                requirement_id=req_id,
                key=f"INV-PAD-{i}",
                statement=f"Padding statement {i} " + ("y" * 400),
                kind="behavior",
                risk="low",
            )
        pack = await get_task_contract(
            session,
            project=PROJECT,
            task="cart discounts",
            requirement_ids=[req_id],
            max_tokens=500,
            ranked_paths=(),
        )
    assert pack.token_estimate <= CONTRACT_TOKEN_CAP
    assert estimate_tokens(pack.text) <= CONTRACT_TOKEN_CAP
    assert long_stmt not in pack.text


async def test_prepare_task_total_stays_within_requested_budget(tmp_path: Path) -> None:
    await _register_and_index(tmp_path)
    req_id = await _seed_requirement(title="Cart total discounts", linked_files=["shop/cart.py"])
    async with session_scope() as session:
        await contracts.create_invariant(
            session,
            project=PROJECT,
            requirement_id=req_id,
            key="INV-FLOOR",
            statement="Keep the FR22a code floor when code chunks exist.",
            kind="behavior",
            risk="high",
        )
        result = await retrieval.prepare_task(
            session,
            project=PROJECT,
            task="add discount handling to the cart total",
            max_tokens=2000,
        )
    split = _split(result)
    used = split["context_tokens"] + split["code_tokens"] + split["contract_tokens"]
    assert used <= split["budget"]
    assert split["contract_tokens"] <= split["contract_cap"]
    assert split["context_tokens"] <= split["context_cap"]
    assert result["contract"]


async def test_fr22a_code_floor_holds_when_code_chunks_exist(tmp_path: Path) -> None:
    await _register_and_index(tmp_path, bulky=True)
    req_id = await _seed_requirement(title="Cart discounts", linked_files=["shop/cart.py"])
    async with session_scope() as session:
        await contracts.create_invariant(
            session,
            project=PROJECT,
            requirement_id=req_id,
            key="INV-FLOOR",
            statement="Keep the FR22a code floor when code chunks exist.",
            kind="architecture",
            risk="high",
        )
        result = await retrieval.prepare_task(
            session,
            project=PROJECT,
            task="explain how pricing and cart total work together",
            max_tokens=2000,
        )
    split = _split(result)
    assert result["code_chunks"]
    assert split["code_floor"] == (2000 * 3) // 10
    assert split["code_budget"] >= split["code_floor"]
    assert split["code_tokens"] >= split["code_floor"]
    # Unused contract cap spills to code rather than being reserved.
    assert split["contract_tokens"] < split["contract_cap"]
    assert split["code_budget"] == (
        split["budget"] - split["context_tokens"] - split["contract_tokens"]
    )


async def test_forbidden_and_high_risk_outrank_low_risk_prose_deterministically() -> None:
    req_id = await _seed_requirement(title="Index retrieval")
    async with session_scope() as session:
        await contracts.create_invariant(
            session,
            project=PROJECT,
            requirement_id=req_id,
            key="INV-LOW",
            statement="Wallpaper documentation prose about naming that is low risk. " * 12,
            kind="manual",
            risk="low",
            sort_order=0,
        )
        await contracts.create_invariant(
            session,
            project=PROJECT,
            requirement_id=req_id,
            key="INV-HIGH",
            statement="Preserve the FR22a code floor when chunks exist.",
            kind="behavior",
            risk="high",
            sort_order=1,
        )
        await contracts.create_invariant(
            session,
            project=PROJECT,
            requirement_id=req_id,
            key="INV-FORB",
            statement="Do not edit T12 evidence modules from T11.",
            kind="forbidden-path",
            risk="medium",
            sort_order=2,
        )
        pack = await get_task_contract(
            session,
            project=PROJECT,
            task="index retrieval contracts",
            requirement_ids=[req_id],
            max_tokens=160,
            ranked_paths=(),
        )
    text = pack.text
    assert "Must not:" in text
    assert "INV-FORB" in text
    assert "INV-HIGH" in text
    # Forbidden-path is packed before low-risk prose even when the Must line
    # is rendered first in the compact template.
    assert "Wallpaper documentation prose" not in text
    assert pack.omitted_invariants >= 1


async def test_overflow_reports_omitted_counts_and_drill_down_pointers() -> None:
    req_id = await _seed_requirement(title="Many invariants")
    async with session_scope() as session:
        for i in range(12):
            await contracts.create_invariant(
                session,
                project=PROJECT,
                requirement_id=req_id,
                key=f"INV-{i:02d}",
                statement=f"Active invariant {i} must stay visible in overflow.",
                kind="behavior",
                risk="high",
            )
        pack = await get_task_contract(
            session,
            project=PROJECT,
            task="many invariants overflow",
            requirement_ids=[req_id],
            max_tokens=80,
            ranked_paths=(),
        )
    assert pack.truncated
    assert pack.omitted_invariants >= 1
    assert f"+{pack.omitted_invariants} more" in pack.text
    assert "get_requirement_contract" in pack.text
    assert "get_requirement_evidence" in pack.text
    assert pack.as_dict()["drill_down"] == [
        "get_requirement_contract",
        "get_requirement_evidence",
    ]


async def test_full_detail_available_only_through_explicit_drill_down() -> None:
    req_id = await _seed_requirement(title="Login contract")
    full_inv = "Passwordless login stays the only supported sign-in path."
    full_ac = "A pytest covers the passwordless callback without capturing passwords."
    async with session_scope() as session:
        inv = await contracts.create_invariant(
            session,
            project=PROJECT,
            requirement_id=req_id,
            key="INV-AUTH",
            statement=full_inv,
            kind="behavior",
            risk="high",
        )
        await contracts.create_criterion(
            session,
            project=PROJECT,
            invariant_id=inv.id,
            key="AC-1",
            statement=full_ac,
            evidence_kind="test",
        )
        compact = await get_task_contract(
            session,
            project=PROJECT,
            task="login contract",
            requirement_ids=[req_id],
            ranked_paths=(),
        )
        both = await get_requirement_contract(
            session, project=PROJECT, requirement_id=req_id, include="both"
        )
        inv_only = await get_requirement_contract(
            session, project=PROJECT, requirement_id=req_id, include="invariants"
        )
        ac_only = await get_requirement_contract(
            session, project=PROJECT, requirement_id=req_id, include="criteria"
        )
    assert full_ac not in compact.text
    assert "criteria" not in inv_only
    assert "invariants" not in ac_only
    invariants = cast(list[dict[str, object]], both["invariants"])
    criteria = cast(list[dict[str, object]], both["criteria"])
    assert invariants[0]["statement"] == full_inv
    assert criteria[0]["statement"] == full_ac
    with pytest.raises(ValidationError, match="include"):
        async with session_scope() as session:
            await get_requirement_contract(
                session, project=PROJECT, requirement_id=req_id, include="evidence"
            )


async def test_responses_contain_no_raw_command_output_or_diff_bodies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "ac_verified": 1,
        "ac_total": 2,
        "missing_keys": ["AC-2"],
        "validation": "stale",
        "review": "failed",
        "stdout": "FULL COMMAND OUTPUT\n" * 20,
        "diff": "diff --git a/x.py b/x.py\n+++ b/x.py\n@@ -1 +1 @@\n",
        "blocking": [
            {
                "key": "INV-X",
                "summary": "diff --git a/foo b/foo\n+++ b/foo\n@@ -1,3 +1,4 @@\n",
            }
        ],
        "stale_count": 1,
    }
    gate = close_gate_from_payload(payload)
    assert "stdout" not in (gate.blocking[0][1] if gate.blocking else "")
    assert gate.blocking[0][1] == "(omitted)"

    req_id = await _seed_requirement(title="No logs in compact")
    async with session_scope() as session:
        await contracts.create_invariant(
            session,
            project=PROJECT,
            requirement_id=req_id,
            key="INV-X",
            statement="Do not leak evidence logs into compact retrieval.",
            kind="forbidden-path",
            risk="high",
        )
        monkeypatch.setattr(
            briefing,
            "_load_close_gate",
            AsyncMock(return_value=close_gate_from_payload(payload)),
        )
        pack = await get_task_contract(
            session,
            project=PROJECT,
            task="no logs in compact",
            requirement_ids=[req_id],
            ranked_paths=(),
        )
    assert "diff --git" not in pack.text
    assert "FULL COMMAND OUTPUT" not in pack.text
    assert "+++ b/" not in pack.text
    assert pack.review == "failed"


async def test_unrelated_requirements_are_not_selected_when_others_match() -> None:
    cart = await _seed_requirement(title="Cart discounts", linked_files=["shop/cart.py"])
    billing = await _seed_requirement(title="Billing VAT", linked_files=["billing/vat.py"])
    async with session_scope() as session:
        await contracts.create_invariant(
            session,
            project=PROJECT,
            requirement_id=cart,
            key="INV-CART",
            statement="Discount math stays in cart_total.",
            kind="behavior",
            risk="high",
        )
        await contracts.create_invariant(
            session,
            project=PROJECT,
            requirement_id=billing,
            key="INV-VAT",
            statement="Unrelated VAT rounding must not appear in cart tasks.",
            kind="behavior",
            risk="high",
        )
        pack = await get_task_contract(
            session,
            project=PROJECT,
            task="change shop/cart.py discount handling",
            ranked_paths=("shop/cart.py",),
        )
    assert "INV-CART" in pack.text
    assert "INV-VAT" not in pack.text
    assert "Unrelated VAT rounding" not in pack.text
    assert cart in pack.requirement_ids
    assert billing not in pack.requirement_ids


async def test_missing_t12_data_is_review_not_configured() -> None:
    req_id = await _seed_requirement(title="Close gate absent")
    async with session_scope() as session:
        await contracts.create_invariant(
            session,
            project=PROJECT,
            requirement_id=req_id,
            key="INV-1",
            statement="T12 evidence is optional during T11.",
            kind="behavior",
            risk="high",
        )
        pack = await get_task_contract(
            session,
            project=PROJECT,
            task="close gate absent",
            requirement_ids=[req_id],
            ranked_paths=(),
        )
    assert pack.review == "not-configured"
    assert "Review: not-configured" in pack.text
    assert "AC: not-configured" in pack.text


async def test_mcp_contract_tools_are_registered() -> None:
    await _register_project()
    req_id = await _seed_requirement(title="MCP drill-down")
    async with session_scope() as session:
        await contracts.create_invariant(
            session,
            project=PROJECT,
            requirement_id=req_id,
            key="INV-MCP",
            statement="MCP wrappers delegate to briefing.",
            kind="behavior",
            risk="medium",
        )
    names = {t.name for t in await mcp.list_tools()}
    assert "get_requirement_contract" in names
    assert "get_task_contract" in names
    drilled = await mcp.call_tool(
        "get_requirement_contract",
        {"project": PROJECT, "requirement_id": req_id, "include": "invariants"},
    )
    compact = await mcp.call_tool(
        "get_task_contract",
        {"project": PROJECT, "task": "MCP drill-down", "requirement_ids": [req_id]},
    )
    drilled_payload = _mcp_payload(drilled)
    compact_payload = _mcp_payload(compact)
    assert "invariants" in drilled_payload
    assert compact_payload["review"] == "not-configured"


async def test_no_match_relevance_returns_empty_contract() -> None:
    cart = await _seed_requirement(title="Cart discounts", linked_files=["shop/cart.py"])
    async with session_scope() as session:
        await contracts.create_invariant(
            session,
            project=PROJECT,
            requirement_id=cart,
            key="INV-CART",
            statement="Discount math stays in cart_total.",
            kind="behavior",
            risk="high",
        )
        pack = await get_task_contract(
            session,
            project=PROJECT,
            task="rewrite the quantum telemetry collector",
            ranked_paths=("docs/unrelated.md",),
        )
    assert pack.text == ""
    assert pack.requirement_ids == ()
    assert pack.token_estimate == 0


async def test_focus_and_retrieval_isolation_and_key_order() -> None:
    later = await _seed_requirement(
        title="Beta cart", linked_files=["shop/cart.py"], req_key="R-002"
    )
    earlier_key = await _seed_requirement(
        title="Alpha cart", linked_files=["shop/cart.py"], req_key="R-001"
    )
    async with session_scope() as session:
        await contracts.create_invariant(
            session,
            project=PROJECT,
            requirement_id=later,
            key="INV-BETA",
            statement="Beta cart invariant.",
            kind="behavior",
            risk="high",
        )
        await contracts.create_invariant(
            session,
            project=PROJECT,
            requirement_id=earlier_key,
            key="INV-ALPHA",
            statement="Alpha cart invariant.",
            kind="behavior",
            risk="high",
        )
        await service.add_entry(
            session,
            project=PROJECT,
            section="focus",
            headline="Ship the current cart work",
            linked_files=["shop/cart.py"],
        )
        via_focus = await get_task_contract(
            session,
            project=PROJECT,
            task="continue the current work",
            ranked_paths=(),
        )
        via_paths = await get_task_contract(
            session,
            project=PROJECT,
            task="implement the change",
            ranked_paths=("shop/cart.py",),
        )
    assert via_focus.requirement_ids == via_paths.requirement_ids
    assert via_focus.requirement_ids[0] == earlier_key
    assert "INV-ALPHA" in via_focus.text
    assert "INV-BETA" in via_focus.text


async def test_missing_criterion_maps_to_parent_invariant_not_key_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    req_id = await _seed_requirement(title="Criterion mapping")
    async with session_scope() as session:
        miss = await contracts.create_invariant(
            session,
            project=PROJECT,
            requirement_id=req_id,
            key="INV-ALPHA",
            statement="Alpha needs its missing criterion.",
            kind="behavior",
            risk="medium",
            sort_order=1,
        )
        ok = await contracts.create_invariant(
            session,
            project=PROJECT,
            requirement_id=req_id,
            key="INV-ALPHABET",
            statement="Alphabet must not inherit Alpha's missing AC.",
            kind="behavior",
            risk="medium",
            sort_order=0,
        )
        ac_missing = await contracts.create_criterion(
            session,
            project=PROJECT,
            invariant_id=miss.id,
            key="AC-Z",
            statement="Verify alpha callback.",
            evidence_kind="test",
        )
        await contracts.create_criterion(
            session,
            project=PROJECT,
            invariant_id=ok.id,
            key="AC-OK",
            statement="Alphabet already has evidence.",
            evidence_kind="test",
        )
        payload = {
            "ac_verified": 1,
            "ac_total": 2,
            "missing_keys": ["AC-Z"],
            "missing": [{"id": ac_missing.id, "key": "AC-Z", "invariant_id": miss.id}],
            "validation": "ok",
            "review": "failed",
        }
        monkeypatch.setattr(
            briefing,
            "_load_close_gate",
            AsyncMock(return_value=close_gate_from_payload(payload)),
        )
        pack = await get_task_contract(
            session,
            project=PROJECT,
            task="criterion mapping",
            requirement_ids=[req_id],
            max_tokens=120,
            ranked_paths=(),
        )
    assert "INV-ALPHA" in pack.text
    # Prefix match would have boosted INV-ALPHABET first (sort_order 0).
    if "INV-ALPHABET" in pack.text:
        assert pack.text.index("INV-ALPHA") < pack.text.index("INV-ALPHABET")


async def test_global_overflow_eviction_keeps_highest_rank_and_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    req_id = await _seed_requirement(title="Overflow eviction")
    async with session_scope() as session:
        await contracts.create_invariant(
            session,
            project=PROJECT,
            requirement_id=req_id,
            key="INV-LOW",
            statement="Low-risk wallpaper that should be evicted first. " * 8,
            kind="manual",
            risk="low",
        )
        await contracts.create_invariant(
            session,
            project=PROJECT,
            requirement_id=req_id,
            key="INV-HIGH",
            statement="High-risk must stay above low-risk prose.",
            kind="behavior",
            risk="high",
        )
        await contracts.create_invariant(
            session,
            project=PROJECT,
            requirement_id=req_id,
            key="INV-FORB",
            statement="Do not touch T12 modules.",
            kind="forbidden-path",
            risk="medium",
        )
        payload = {
            "review": "failed",
            "validation": "ok",
            "blocking": [{"key": "INV-BLOCK", "summary": "open blocking violation"}],
            "blocking_count": 1,
        }
        monkeypatch.setattr(
            briefing,
            "_load_close_gate",
            AsyncMock(return_value=close_gate_from_payload(payload)),
        )
        pack = await get_task_contract(
            session,
            project=PROJECT,
            task="overflow eviction",
            requirement_ids=[req_id],
            max_tokens=90,
            ranked_paths=(),
        )
    assert pack.text.startswith("CONTRACT")
    assert "CLOSE GATE" in pack.text
    assert "Details:" in pack.text
    assert "get_requirement_contract" in pack.text
    assert "INV-BLOCK" in pack.text
    assert "INV-LOW" not in pack.text
    assert pack.omitted_invariants >= 1


async def test_below_safe_minimum_is_rejected() -> None:
    req_id = await _seed_requirement(title="Safe minimum reject")
    async with session_scope() as session:
        await contracts.create_invariant(
            session,
            project=PROJECT,
            requirement_id=req_id,
            key="INV-1",
            statement="A statement that cannot fit a 1-token budget.",
            kind="behavior",
            risk="high",
        )
        with pytest.raises(ValidationError, match="max_tokens must be in"):
            await get_task_contract(
                session,
                project=PROJECT,
                task="safe minimum",
                requirement_ids=[req_id],
                max_tokens=1,
                ranked_paths=(),
            )


async def test_accepted_budget_token_estimate_never_exceeds_budget() -> None:
    req_id = await _seed_requirement(title="Budget bound")
    long_stmt = "KEEP-BOUND " + ("x" * 400)
    async with session_scope() as session:
        await contracts.create_invariant(
            session,
            project=PROJECT,
            requirement_id=req_id,
            key="INV-LONG",
            statement=long_stmt,
            kind="behavior",
            risk="high",
        )
        for budget in (CONTRACT_TOKEN_MIN, 120, CONTRACT_TOKEN_CAP):
            pack = await get_task_contract(
                session,
                project=PROJECT,
                task="budget bound",
                requirement_ids=[req_id],
                max_tokens=budget,
                ranked_paths=(),
            )
            assert pack.token_budget == budget
            assert pack.token_estimate <= pack.token_budget
            assert pack.text.startswith("CONTRACT")
            assert "CLOSE GATE" in pack.text
            assert "Details:" in pack.text


async def test_tiny_budget_uses_structured_fallback_not_sliced_headers() -> None:
    req_id = await _seed_requirement(title="Safe minimum")
    async with session_scope() as session:
        await contracts.create_invariant(
            session,
            project=PROJECT,
            requirement_id=req_id,
            key="INV-1",
            statement="A statement that cannot fit a 1-token budget.",
            kind="behavior",
            risk="high",
        )
        pack = await get_task_contract(
            session,
            project=PROJECT,
            task="safe minimum",
            requirement_ids=[req_id],
            max_tokens=CONTRACT_TOKEN_MIN,
            ranked_paths=(),
        )
    assert pack.token_estimate <= pack.token_budget == CONTRACT_TOKEN_MIN
    assert pack.text.startswith("CONTRACT")
    assert "CLOSE GATE" in pack.text
    assert "Details:" in pack.text
    assert not pack.text.startswith("CONTRA\n")
    assert "CONTRA…" not in pack.text


async def test_broken_t12_import_is_not_hidden_as_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    req_id = await _seed_requirement(title="Broken evidence import")
    real_import = importlib.import_module

    def fake_import(name: str, package: str | None = None) -> object:
        if name == "pcs.requirements.evidence":
            raise ModuleNotFoundError("No module named 'broken_t12_dep'", name="broken_t12_dep")
        return real_import(name, package)

    monkeypatch.setattr(importlib, "import_module", fake_import)
    async with session_scope() as session:
        await contracts.create_invariant(
            session,
            project=PROJECT,
            requirement_id=req_id,
            key="INV-1",
            statement="T12 import failures must surface.",
            kind="behavior",
            risk="high",
        )
        with pytest.raises(ModuleNotFoundError, match="broken_t12_dep"):
            await get_task_contract(
                session,
                project=PROJECT,
                task="broken evidence import",
                requirement_ids=[req_id],
                ranked_paths=(),
            )
    assert _is_missing_evidence_module(
        ModuleNotFoundError("missing evidence", name="pcs.requirements.evidence")
    )
    assert not _is_missing_evidence_module(
        ModuleNotFoundError("missing dep", name="broken_t12_dep")
    )


async def test_explicit_ids_are_deduped_and_done_ids_are_included() -> None:
    first = await _seed_requirement(title="First", req_key="R-010")
    second = await _seed_requirement(title="Second", req_key="R-011")
    third = await _seed_requirement(title="Third", req_key="R-012")
    fourth = await _seed_requirement(title="Fourth", req_key="R-013")
    done = await _seed_requirement(title="Done one", status="done", req_key="R-014")
    async with session_scope() as session:
        for req_id, key in (
            (first, "INV-A"),
            (second, "INV-B"),
            (third, "INV-C"),
            (fourth, "INV-D"),
            (done, "INV-DONE"),
        ):
            await contracts.create_invariant(
                session,
                project=PROJECT,
                requirement_id=req_id,
                key=key,
                statement=f"{key} statement.",
                kind="behavior",
                risk="high",
            )
        await service.set_requirement_status(session, project=PROJECT, entry_id=done, status="done")
        packed = await get_task_contract(
            session,
            project=PROJECT,
            task="explicit ids",
            requirement_ids=[first, first, second, first, third, fourth],
            ranked_paths=(),
        )
        done_pack = await get_task_contract(
            session,
            project=PROJECT,
            task="explicit done",
            requirement_ids=[done],
            ranked_paths=(),
        )
        auto = await get_task_contract(
            session,
            project=PROJECT,
            task="quantum telemetry",
            ranked_paths=(),
        )
    assert packed.requirement_ids == (first, second, third)
    assert packed.omitted_requirements == 1
    assert "INV-DONE" in done_pack.text
    assert auto.requirement_ids == ()


async def test_contract_tools_are_project_isolated() -> None:
    other = "other-contract"
    local = await _seed_requirement(title="Local", project=PROJECT)
    foreign = await _seed_requirement(title="Foreign", project=other)
    async with session_scope() as session:
        await contracts.create_invariant(
            session,
            project=other,
            requirement_id=foreign,
            key="INV-X",
            statement="Other project secret.",
            kind="behavior",
            risk="high",
        )
        with pytest.raises(EntryNotFoundError):
            await get_requirement_contract(
                session, project=PROJECT, requirement_id=foreign, include="both"
            )
        with pytest.raises(EntryNotFoundError):
            await get_task_contract(
                session,
                project=PROJECT,
                task="isolation",
                requirement_ids=[foreign],
                ranked_paths=(),
            )
        ok = await get_requirement_contract(
            session, project=PROJECT, requirement_id=local, include="invariants"
        )
    assert ok["requirement_id"] == local
    assert "Other project secret" not in str(ok)


async def test_mcp_contract_tools_audit_schema_and_errors() -> None:
    req_id = await _seed_requirement(title="MCP audit")
    async with session_scope() as session:
        await contracts.create_invariant(
            session,
            project=PROJECT,
            requirement_id=req_id,
            key="INV-MCP",
            statement="Audit the contract tools.",
            kind="behavior",
            risk="medium",
        )
    tools = {tool.name: tool for tool in await mcp.list_tools()}
    req_schema = tools["get_requirement_contract"].inputSchema
    task_schema = tools["get_task_contract"].inputSchema
    assert "include" in req_schema["properties"]
    assert "requirement_ids" in task_schema["properties"]
    max_tokens_schema = task_schema["properties"]["max_tokens"]
    assert max_tokens_schema["minimum"] == CONTRACT_TOKEN_MIN
    assert max_tokens_schema["maximum"] == CONTRACT_TOKEN_CAP

    seen: list[dict[str, str]] = []

    def spy(
        *,
        tool: str,
        project: str | None,
        caller: str,
        outcome: str,
        **fields: object,
    ) -> None:
        seen.append(
            {
                "tool": tool,
                "project": project or "",
                "caller": caller,
                "outcome": outcome,
            }
        )

    with (
        patch("pcs.mcp.support.log_tool_call", spy),
        patch("pcs.mcp.contract_tools.log_tool_call", spy),
    ):
        await mcp.call_tool(
            "get_task_contract",
            {"project": PROJECT, "task": "MCP audit", "requirement_ids": [req_id]},
        )
        with pytest.raises(ToolError):
            await mcp.call_tool(
                "get_requirement_contract",
                {"project": PROJECT, "requirement_id": req_id, "include": "evidence"},
            )
        with pytest.raises(ToolError):
            await mcp.call_tool(
                "get_task_contract",
                {"project": "does-not-exist", "task": "nope"},
            )
        with pytest.raises(ToolError, match="max_tokens"):
            await mcp.call_tool(
                "get_task_contract",
                {"project": PROJECT, "task": "too small", "max_tokens": 1},
            )
    outcomes = {(row["tool"], row["outcome"]) for row in seen}
    assert ("get_task_contract", "ok") in outcomes
    assert any(
        row["tool"] == "get_requirement_contract" and row["outcome"].startswith("error:")
        for row in seen
    )
    assert any(
        row["tool"] == "get_task_contract" and row["outcome"].startswith("error:") for row in seen
    )


async def test_duplicate_ac_keys_across_requirements_use_criterion_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    left = await _seed_requirement(
        title="Left cart", linked_files=["shop/cart.py"], req_key="R-020"
    )
    right = await _seed_requirement(
        title="Right billing", linked_files=["shop/cart.py"], req_key="R-021"
    )
    async with session_scope() as session:
        inv_left = await contracts.create_invariant(
            session,
            project=PROJECT,
            requirement_id=left,
            key="INV-LEFT",
            statement="Left parent of the missing AC-1.",
            kind="behavior",
            risk="medium",
        )
        inv_right = await contracts.create_invariant(
            session,
            project=PROJECT,
            requirement_id=right,
            key="INV-RIGHT",
            statement="Right parent must not inherit Left's AC-1.",
            kind="behavior",
            risk="medium",
        )
        ac_left = await contracts.create_criterion(
            session,
            project=PROJECT,
            invariant_id=inv_left.id,
            key="AC-1",
            statement="Left AC-1.",
            evidence_kind="test",
        )
        await contracts.create_criterion(
            session,
            project=PROJECT,
            invariant_id=inv_right.id,
            key="AC-1",
            statement="Right AC-1.",
            evidence_kind="test",
        )
        payload = {
            "ac_verified": 1,
            "ac_total": 2,
            "missing": [{"id": ac_left.id, "key": "AC-1"}],
            "validation": "ok",
            "review": "failed",
        }
        monkeypatch.setattr(
            briefing,
            "_load_close_gate",
            AsyncMock(return_value=close_gate_from_payload(payload)),
        )
        pack = await get_task_contract(
            session,
            project=PROJECT,
            task="cart work",
            requirement_ids=[left, right],
            max_tokens=160,
            ranked_paths=(),
        )
    assert "INV-LEFT" in pack.text
    if "INV-RIGHT" in pack.text:
        assert pack.text.index("INV-LEFT") < pack.text.index("INV-RIGHT")


async def test_unknown_criterion_id_does_not_boost_colliding_selected_ac_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected = await _seed_requirement(title="Selected cart", req_key="R-030")
    foreign = await _seed_requirement(title="Foreign billing", req_key="R-031")
    async with session_scope() as session:
        owned = await contracts.create_invariant(
            session,
            project=PROJECT,
            requirement_id=selected,
            key="INV-SELECTED",
            statement="Selected parent of AC-1; must not inherit a foreign id.",
            kind="behavior",
            risk="medium",
            sort_order=1,
        )
        await contracts.create_invariant(
            session,
            project=PROJECT,
            requirement_id=selected,
            key="INV-PEER",
            statement="Peer ranks first unless the colliding AC-1 is wrongly boosted.",
            kind="behavior",
            risk="medium",
            sort_order=0,
        )
        await contracts.create_criterion(
            session,
            project=PROJECT,
            invariant_id=owned.id,
            key="AC-1",
            statement="Selected AC-1.",
            evidence_kind="test",
        )
        foreign_inv = await contracts.create_invariant(
            session,
            project=PROJECT,
            requirement_id=foreign,
            key="INV-FOREIGN",
            statement="Foreign parent of a colliding AC-1.",
            kind="behavior",
            risk="medium",
        )
        foreign_ac = await contracts.create_criterion(
            session,
            project=PROJECT,
            invariant_id=foreign_inv.id,
            key="AC-1",
            statement="Foreign AC-1.",
            evidence_kind="test",
        )
        payload = {
            "ac_verified": 0,
            "ac_total": 1,
            "missing": [
                {
                    "id": foreign_ac.id,
                    "key": "AC-1",
                    "invariant_id": owned.id,
                    "invariant_key": "INV-SELECTED",
                }
            ],
            "validation": "ok",
            "review": "failed",
        }
        monkeypatch.setattr(
            briefing,
            "_load_close_gate",
            AsyncMock(return_value=close_gate_from_payload(payload)),
        )
        pack = await get_task_contract(
            session,
            project=PROJECT,
            task="unknown criterion id",
            requirement_ids=[selected],
            max_tokens=160,
            ranked_paths=(),
        )
    assert "INV-PEER" in pack.text
    assert "INV-SELECTED" in pack.text
    assert pack.text.index("INV-PEER") < pack.text.index("INV-SELECTED")
    assert "INV-FOREIGN" not in pack.text


async def test_conflicting_payload_parent_uses_authoritative_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    req_id = await _seed_requirement(title="Conflicting parent")
    async with session_scope() as session:
        owner = await contracts.create_invariant(
            session,
            project=PROJECT,
            requirement_id=req_id,
            key="INV-OWNER",
            statement="Authoritative parent of the stale criterion.",
            kind="behavior",
            risk="medium",
            sort_order=1,
        )
        decoy = await contracts.create_invariant(
            session,
            project=PROJECT,
            requirement_id=req_id,
            key="INV-DECOY",
            statement="Payload wrongly claims this parent.",
            kind="behavior",
            risk="medium",
            sort_order=0,
        )
        ac = await contracts.create_criterion(
            session,
            project=PROJECT,
            invariant_id=owner.id,
            key="AC-1",
            statement="Owned by INV-OWNER.",
            evidence_kind="test",
        )
        payload = {
            "ac_verified": 0,
            "ac_total": 1,
            "missing": [
                {
                    "id": ac.id,
                    "key": "AC-1",
                    "invariant_id": decoy.id,
                    "invariant_key": "INV-DECOY",
                }
            ],
            "validation": "ok",
            "review": "failed",
        }
        monkeypatch.setattr(
            briefing,
            "_load_close_gate",
            AsyncMock(return_value=close_gate_from_payload(payload)),
        )
        pack = await get_task_contract(
            session,
            project=PROJECT,
            task="conflicting parent",
            requirement_ids=[req_id],
            max_tokens=160,
            ranked_paths=(),
        )
    assert "INV-OWNER" in pack.text
    if "INV-DECOY" in pack.text:
        assert pack.text.index("INV-OWNER") < pack.text.index("INV-DECOY")


async def test_stale_criterion_raises_parent_invariant_in_ranking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    req_id = await _seed_requirement(title="Stale ranking")
    async with session_scope() as session:
        stale_inv = await contracts.create_invariant(
            session,
            project=PROJECT,
            requirement_id=req_id,
            key="INV-STALE",
            statement="Parent of the stale criterion.",
            kind="behavior",
            risk="medium",
            sort_order=1,
        )
        fresh = await contracts.create_invariant(
            session,
            project=PROJECT,
            requirement_id=req_id,
            key="INV-FRESH",
            statement="Fresh evidence, same risk, should rank later.",
            kind="behavior",
            risk="medium",
            sort_order=0,
        )
        stale_ac = await contracts.create_criterion(
            session,
            project=PROJECT,
            invariant_id=stale_inv.id,
            key="AC-STALE",
            statement="This criterion's evidence is stale.",
            evidence_kind="test",
        )
        await contracts.create_criterion(
            session,
            project=PROJECT,
            invariant_id=fresh.id,
            key="AC-FRESH",
            statement="Fresh criterion.",
            evidence_kind="test",
        )
        payload = {
            "ac_verified": 1,
            "ac_total": 2,
            "stale": [{"id": stale_ac.id, "key": "AC-STALE", "invariant_id": stale_inv.id}],
            "stale_count": 1,
            "validation": "stale",
            "review": "failed",
        }
        monkeypatch.setattr(
            briefing,
            "_load_close_gate",
            AsyncMock(return_value=close_gate_from_payload(payload)),
        )
        pack = await get_task_contract(
            session,
            project=PROJECT,
            task="stale ranking",
            requirement_ids=[req_id],
            max_tokens=160,
            ranked_paths=(),
        )
    assert pack.review == "failed"
    assert "Validation: stale" in pack.text
    assert "INV-STALE" in pack.text
    if "INV-FRESH" in pack.text:
        assert pack.text.index("INV-STALE") < pack.text.index("INV-FRESH")
