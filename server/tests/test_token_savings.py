"""Token-savings log: recording, listing, aggregation, and the four call sites
(retrieve_context, search_code, prepare_task x2 forms, get_project_briefing)
that record an entry only when an explicit ``caller`` is passed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest
from starlette.testclient import TestClient

from pcs.context import service as context_service
from pcs.db.base import session_scope
from pcs.index import retrieval
from pcs.index import service as index_service
from pcs.mcp import build_http_app, mcp
from pcs.planning import service as planning_service
from pcs.planning.types import TaskSpec
from pcs.token_savings.baseline import full_file_tokens
from pcs.token_savings.service import (
    get_token_savings_summary,
    list_token_savings,
    record_token_savings,
)

pytestmark = pytest.mark.usefixtures("clean_db")
PROJECT = "token-savings"


def _sample_repo(root: Path) -> None:
    # Deliberately larger than a toy snippet: real files, so a budget-bounded
    # chunk pack (or a snippet-only search hit) is genuinely much smaller
    # than the full file — the realistic case token-savings measures. Tiny
    # fixture files would instead be dominated by per-chunk header overhead
    # ("// path:line-line\n"), which is a real but uninteresting edge case
    # (correctly floored at 0 saved tokens, not asserted here).
    (root / "shop").mkdir()
    lines = [
        "def cart_total(items):",
        '    """Sum unit_price(item) for every item in the cart."""',
        "    return sum(unit_price(item) for item in items)",
        "",
        "def unit_price(item):",
        "    return item.price * item.quantity",
        "",
        "def apply_discount(total, percent):",
        "    return total * (1 - percent / 100)",
        "",
    ]
    for i in range(40):
        lines.append(f"def helper_{i}(x):")
        lines.append(f"    # padding function {i} to make this file realistically sized")
        lines.append(f"    return x + {i}")
        lines.append("")
    (root / "shop" / "cart.py").write_text("\n".join(lines), encoding="utf-8")
    checkout_lines = [
        "def checkout(cart):",
        "    from shop.cart import cart_total",
        "    total = cart_total(cart.items)",
        "    return {'total': total, 'status': 'ok'}",
        "",
    ]
    for i in range(40):
        checkout_lines.append(f"def checkout_helper_{i}(x):")
        checkout_lines.append(f"    # padding function {i} to make this file realistically sized")
        checkout_lines.append(f"    return x * {i}")
        checkout_lines.append("")
    (root / "shop" / "checkout.py").write_text("\n".join(checkout_lines), encoding="utf-8")


async def _register_project(root: Path | None = None, *, name: str = PROJECT) -> None:
    path = str(root) if root is not None else f"/repos/{name}"
    async with session_scope() as session:
        await context_service.register_project(
            session, name=name, root_path=path, overview="Token savings fixture repo."
        )


async def _register_and_index(root: Path, *, name: str = PROJECT) -> None:
    _sample_repo(root)
    await _register_project(root, name=name)
    async with session_scope() as session:
        await index_service.reindex(session, project=name, incremental=False)


async def _seed_plan(*, project: str = PROJECT) -> dict[str, str]:
    tasks = [
        TaskSpec(
            local_task_id="t1",
            title="Add pricing helper",
            objective="Implement unit_price so cart_total can use it.",
            acceptance_criteria=["unit_price returns item.price * item.quantity"],
            linked_files=["shop/cart.py"],
        ),
    ]
    async with session_scope() as session:
        plan = await planning_service.create_plan_with_tasks(
            session,
            project=project,
            title="Cart pricing",
            goal="Ship pricing end to end",
            tasks=tasks,
            dependencies=[],
        )
        await planning_service.activate_plan(session, project, plan.id)
        return {"plan_id": plan.id, **{t.local_task_id: t.id for t in plan.tasks}}


def _client() -> TestClient:
    return TestClient(build_http_app())


def _http(
    client: TestClient, method: str, path: str, *, json_body: dict[str, object] | None = None
) -> Any:
    return client.request(method, path, json=json_body, headers={"x-pcs-caller": "ts-test"})


def _tool_payload(result: object) -> Any:
    if isinstance(result, tuple):
        _, structured = result
        if isinstance(structured, dict) and set(structured.keys()) == {"result"}:
            return structured["result"]
        if structured is not None:
            return structured
    if isinstance(result, list) and result and hasattr(result[0], "text"):
        return json.loads(str(result[0].text))
    return result


# ---------------------------------------------------------------------------
# Service layer: record / list / summary
# ---------------------------------------------------------------------------
async def test_record_list_and_summary_basic() -> None:
    await _register_project()
    async with session_scope() as session:
        row = await context_service.resolve_project(session, PROJECT)
        await record_token_savings(
            session,
            project_id=row.id,
            operation="retrieve_context",
            caller="agent-a",
            actual_tokens=100,
            baseline_tokens=1000,
        )
        await record_token_savings(
            session,
            project_id=row.id,
            operation="search_code",
            caller="agent-b",
            actual_tokens=50,
            baseline_tokens=50,
        )
        # baseline < actual (e.g. a tiny file) must floor saved_tokens at 0, not go negative.
        await record_token_savings(
            session,
            project_id=row.id,
            operation="search_code",
            caller="agent-b",
            actual_tokens=80,
            baseline_tokens=20,
        )

    async with session_scope() as session:
        entries = await list_token_savings(session, PROJECT)
        assert len(entries) == 3
        # Most-recent-first.
        assert entries[0]["operation"] == "search_code"
        assert entries[0]["actual_tokens"] == 80
        assert entries[0]["saved_tokens"] == 0  # floored, not negative

        filtered = await list_token_savings(session, PROJECT, operation="retrieve_context")
        assert len(filtered) == 1
        assert filtered[0]["saved_tokens"] == 900

        summary = await get_token_savings_summary(session, PROJECT)
        overall = cast(dict[str, object], summary["overall"])
        assert overall["call_count"] == 3
        assert overall["saved_tokens_total"] == 900  # 900 + 0 + 0
        by_op = {
            cast(dict[str, object], row)["operation"]: cast(dict[str, object], row)
            for row in cast(list[object], summary["by_operation"])
        }
        assert by_op["search_code"]["call_count"] == 2
        assert by_op["search_code"]["saved_tokens_total"] == 0
        assert by_op["retrieve_context"]["saved_tokens_total"] == 900


async def test_record_token_savings_rejects_unknown_operation() -> None:
    await _register_project()
    async with session_scope() as session:
        row = await context_service.resolve_project(session, PROJECT)
        with pytest.raises(ValueError, match="operation must be one of"):
            await record_token_savings(
                session,
                project_id=row.id,
                operation="not_a_real_operation",
                caller="agent",
                actual_tokens=1,
                baseline_tokens=1,
            )


async def test_list_token_savings_rejects_unknown_operation_filter() -> None:
    await _register_project()
    async with session_scope() as session:
        with pytest.raises(ValueError, match="operation must be one of"):
            await list_token_savings(session, PROJECT, operation="bogus")


# ---------------------------------------------------------------------------
# full_file_tokens baseline helper
# ---------------------------------------------------------------------------
def test_full_file_tokens_sums_distinct_paths_and_skips_missing(tmp_path: Path) -> None:
    _sample_repo(tmp_path)
    cart_only = full_file_tokens(str(tmp_path), ["shop/cart.py"])
    total = full_file_tokens(str(tmp_path), ["shop/cart.py", "shop/checkout.py"])
    assert cart_only > 0
    assert total > cart_only
    # A missing/unreadable path contributes 0 rather than raising or changing
    # the sum for the paths that do exist.
    assert full_file_tokens(str(tmp_path), ["shop/cart.py", "does/not/exist.py"]) == cart_only
    assert full_file_tokens(str(tmp_path), []) == 0
    # Path traversal is rejected the same way — contributes nothing, no raise.
    assert full_file_tokens(str(tmp_path), ["../outside.py"]) == 0


# ---------------------------------------------------------------------------
# retrieve_context: only records with an explicit caller
# ---------------------------------------------------------------------------
async def test_retrieve_context_without_caller_records_nothing(tmp_path: Path) -> None:
    await _register_and_index(tmp_path)
    async with session_scope() as session:
        await retrieval.retrieve_context(session, project=PROJECT, task="cart pricing")
    async with session_scope() as session:
        assert await list_token_savings(session, PROJECT) == []


async def test_retrieve_context_with_caller_records_baseline_over_actual(tmp_path: Path) -> None:
    await _register_and_index(tmp_path)
    async with session_scope() as session:
        result = await retrieval.retrieve_context(
            session, project=PROJECT, task="cart pricing total", max_tokens=40, caller="agent-x"
        )
    async with session_scope() as session:
        entries = await list_token_savings(session, PROJECT, operation="retrieve_context")
    assert len(entries) == 1
    entry = entries[0]
    assert entry["caller"] == "agent-x"
    assert entry["actual_tokens"] == result["token_estimate"]
    # Full files are bigger than a 40-token-bounded chunk pack.
    assert cast(int, entry["baseline_tokens"]) >= cast(int, entry["actual_tokens"])
    assert entry["saved_tokens"] == max(
        0, cast(int, entry["baseline_tokens"]) - cast(int, entry["actual_tokens"])
    )


async def test_retrieve_context_no_hits_records_zero_baseline(tmp_path: Path) -> None:
    await _register_and_index(tmp_path)
    async with session_scope() as session:
        await retrieval.retrieve_context(
            session, project=PROJECT, task="nothing-matches-this-query-xyz123", caller="agent-x"
        )
    async with session_scope() as session:
        entries = await list_token_savings(session, PROJECT, operation="retrieve_context")
    assert len(entries) == 1
    assert cast(int, entries[0]["baseline_tokens"]) >= 0


# ---------------------------------------------------------------------------
# search_code
# ---------------------------------------------------------------------------
async def test_search_code_without_caller_records_nothing(tmp_path: Path) -> None:
    await _register_and_index(tmp_path)
    async with session_scope() as session:
        await index_service.search_code(session, project=PROJECT, query="cart_total")
    async with session_scope() as session:
        assert await list_token_savings(session, PROJECT) == []


async def test_search_code_with_caller_records_entry(tmp_path: Path) -> None:
    await _register_and_index(tmp_path)
    async with session_scope() as session:
        payload = await index_service.search_code(
            session, project=PROJECT, query="cart_total", caller="agent-y"
        )
    async with session_scope() as session:
        entries = await list_token_savings(session, PROJECT, operation="search_code")
    assert len(entries) == 1
    assert entries[0]["caller"] == "agent-y"
    if payload["hits"]:
        # Snippet-only actual tokens should be far smaller than full file content.
        assert cast(int, entries[0]["baseline_tokens"]) >= cast(int, entries[0]["actual_tokens"])


# ---------------------------------------------------------------------------
# get_project_briefing
# ---------------------------------------------------------------------------
async def test_get_project_briefing_without_caller_records_nothing() -> None:
    await _register_project()
    async with session_scope() as session:
        await context_service.set_current_focus(session, project=PROJECT, text="Ship checkout.")
    async with session_scope() as session:
        await context_service.get_project_briefing(session, project=PROJECT)
    async with session_scope() as session:
        assert await list_token_savings(session, PROJECT) == []


async def test_get_project_briefing_with_caller_records_entry() -> None:
    await _register_project()
    async with session_scope() as session:
        await context_service.set_current_focus(session, project=PROJECT, text="Ship checkout.")
    async with session_scope() as session:
        text = await context_service.get_project_briefing(
            session, project=PROJECT, caller="agent-z"
        )
    async with session_scope() as session:
        entries = await list_token_savings(session, PROJECT, operation="get_project_briefing")
    assert len(entries) == 1
    assert entries[0]["caller"] == "agent-z"
    assert cast(int, entries[0]["actual_tokens"]) > 0
    # Unbounded baseline assembly can never cost less than the (possibly
    # truncated) actual briefing.
    assert cast(int, entries[0]["baseline_tokens"]) >= cast(int, entries[0]["actual_tokens"])
    assert len(text) > 0


# ---------------------------------------------------------------------------
# prepare_task: free-text form records exactly one entry, not also a nested
# get_project_briefing entry from its internal briefing call.
# ---------------------------------------------------------------------------
async def test_prepare_task_free_text_records_one_entry_no_double_logging(tmp_path: Path) -> None:
    await _register_and_index(tmp_path)
    async with session_scope() as session:
        await context_service.set_current_focus(session, project=PROJECT, text="Ship checkout.")
    async with session_scope() as session:
        result = await retrieval.prepare_task(
            session, project=PROJECT, task="cart pricing", caller="agent-p"
        )
    async with session_scope() as session:
        all_entries = await list_token_savings(session, PROJECT)
        prepare_entries = await list_token_savings(session, PROJECT, operation="prepare_task")
        briefing_entries = await list_token_savings(
            session, PROJECT, operation="get_project_briefing"
        )
    assert len(all_entries) == 1
    assert len(prepare_entries) == 1
    assert len(briefing_entries) == 0  # internal get_project_briefing call must not self-log
    entry = prepare_entries[0]
    split = cast(dict[str, int], result["split"])
    expected_actual = split["context_tokens"] + split["contract_tokens"] + split["code_tokens"]
    assert entry["actual_tokens"] == expected_actual
    assert cast(int, entry["baseline_tokens"]) >= expected_actual


async def test_prepare_task_without_caller_records_nothing(tmp_path: Path) -> None:
    await _register_and_index(tmp_path)
    async with session_scope() as session:
        await retrieval.prepare_task(session, project=PROJECT, task="cart pricing")
    async with session_scope() as session:
        assert await list_token_savings(session, PROJECT) == []


# ---------------------------------------------------------------------------
# prepare_task: task_id (handoff) form
# ---------------------------------------------------------------------------
async def test_prepare_task_task_id_form_records_one_prepare_task_entry(tmp_path: Path) -> None:
    await _register_and_index(tmp_path)
    ids = await _seed_plan()
    async with session_scope() as session:
        result = await retrieval.prepare_task(
            session, project=PROJECT, task_id=ids["t1"], caller="agent-q"
        )
    async with session_scope() as session:
        entries = await list_token_savings(session, PROJECT, operation="prepare_task")
    assert len(entries) == 1
    assert entries[0]["caller"] == "agent-q"
    assert entries[0]["actual_tokens"] == result["token_estimate"]
    assert cast(int, entries[0]["baseline_tokens"]) >= cast(int, entries[0]["actual_tokens"])


# ---------------------------------------------------------------------------
# MCP tools and HTTP routes for reading the log
# ---------------------------------------------------------------------------
async def test_mcp_tools_registered_and_return_log(tmp_path: Path) -> None:
    await _register_and_index(tmp_path)
    async with session_scope() as session:
        await retrieval.retrieve_context(
            session, project=PROJECT, task="cart pricing", caller="mcp-agent"
        )

    tools = {t.name for t in await mcp.list_tools()}
    assert "get_token_savings_log" in tools
    assert "get_token_savings_summary" in tools

    log = _tool_payload(await mcp.call_tool("get_token_savings_log", {"project": PROJECT}))
    assert isinstance(log, list)
    assert len(log) == 1
    assert log[0]["operation"] == "retrieve_context"

    summary = _tool_payload(await mcp.call_tool("get_token_savings_summary", {"project": PROJECT}))
    assert summary["overall"]["call_count"] == 1


async def test_http_routes_return_log_and_summary(tmp_path: Path) -> None:
    await _register_and_index(tmp_path)
    async with session_scope() as session:
        await index_service.search_code(
            session, project=PROJECT, query="cart_total", caller="http-agent"
        )

    client = _client()
    log_resp = _http(client, "GET", f"/api/projects/{PROJECT}/token-savings")
    assert log_resp.status_code == 200
    body = log_resp.json()
    assert len(body) == 1
    assert body[0]["operation"] == "search_code"
    assert body[0]["caller"] == "http-agent"

    filtered = _http(client, "GET", f"/api/projects/{PROJECT}/token-savings?operation=prepare_task")
    assert filtered.status_code == 200
    assert filtered.json() == []

    bad_operation = _http(
        client, "GET", f"/api/projects/{PROJECT}/token-savings?operation=not-real"
    )
    assert bad_operation.status_code == 400

    summary_resp = _http(client, "GET", f"/api/projects/{PROJECT}/token-savings/summary")
    assert summary_resp.status_code == 200
    assert summary_resp.json()["overall"]["call_count"] == 1

    missing = _http(client, "GET", "/api/projects/does-not-exist/token-savings")
    assert missing.status_code == 404
