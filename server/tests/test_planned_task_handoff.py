"""T25 planned-task handoff prompt generation - one test per acceptance item."""

from __future__ import annotations

import json
from contextlib import suppress
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock, patch

import pytest
from mcp.server.fastmcp.exceptions import ToolError
from starlette.testclient import TestClient

from pcs.context import service as context_service
from pcs.context.types import PREPARE_TASK_TOKEN_MIN
from pcs.db.base import session_scope
from pcs.index import hybrid as index_hybrid
from pcs.index import retrieval
from pcs.index import service as index_service
from pcs.mcp import build_http_app, mcp
from pcs.planning import service as planning_service
from pcs.planning.errors import TaskAlreadyTerminalError, TaskNotFoundError
from pcs.planning.types import DependencySpec, TaskSpec
from pcs.requirements import contracts

pytestmark = pytest.mark.usefixtures("clean_db")
PROJECT = "handoff-a"
OTHER_PROJECT = "handoff-b"


def _sample_repo(root: Path) -> None:
    (root / "shop").mkdir()
    (root / "shop" / "cart.py").write_text(
        "def cart_total(items):\n"
        '    """Sum unit_price(item) for every item in the cart."""\n'
        "    return sum(unit_price(item) for item in items)\n\n"
        "def unit_price(item):\n"
        "    return item.price * item.quantity\n",
        encoding="utf-8",
    )


async def _register_project(root: Path | None = None, *, name: str = PROJECT) -> None:
    path = str(root) if root is not None else f"/repos/{name}"
    async with session_scope() as session:
        with suppress(context_service.DuplicateProjectError):
            await context_service.register_project(
                session, name=name, root_path=path, overview="T25 handoff fixture repo."
            )


async def _register_and_index(root: Path, *, name: str = PROJECT) -> None:
    _sample_repo(root)
    await _register_project(root, name=name)
    async with session_scope() as session:
        await index_service.reindex(session, project=name, incremental=False)


async def _seed_plan(*, project: str = PROJECT, with_requirement: bool = False) -> dict[str, str]:
    await _register_project(name=project)
    req_id: str | None = None
    if with_requirement:
        async with session_scope() as session:
            req = await context_service.add_entry(
                session, project=project, section="requirements", headline="Cart totals"
            )
            req_id = req.id
            await contracts.create_invariant(
                session,
                project=project,
                requirement_id=req_id,
                key="INV-CART-1",
                statement="Cart totals must never go negative.",
                kind="behavior",
                risk="high",
            )
    tasks = [
        TaskSpec(
            local_task_id="t1",
            title="Add pricing helper",
            objective="Implement unit_price so cart_total can use it.",
            acceptance_criteria=["unit_price returns item.price * item.quantity"],
        ),
        TaskSpec(
            local_task_id="t2",
            title="Wire pricing into cart total",
            objective="Use unit_price inside shop/cart.py's cart_total function.",
            acceptance_criteria=["cart_total sums unit_price(item) for every item"],
            linked_files=["shop/cart.py"],
            requirement_ids=[req_id] if req_id else [],
        ),
    ]
    async with session_scope() as session:
        plan = await planning_service.create_plan_with_tasks(
            session,
            project=project,
            title="Cart pricing",
            goal="Ship pricing end to end",
            tasks=tasks,
            dependencies=[DependencySpec(task_local_id="t2", depends_on_local_id="t1")],
        )
        await planning_service.activate_plan(session, project, plan.id)
        result = {"plan_id": plan.id, **{t.local_task_id: t.id for t in plan.tasks}}
        if req_id:
            result["req_id"] = req_id
        return result


def _client() -> TestClient:
    return TestClient(build_http_app())


def _http(
    client: TestClient, method: str, path: str, *, json_body: dict[str, object] | None = None
) -> Any:
    return client.request(method, path, json=json_body, headers={"x-pcs-caller": "handoff-test"})


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------
async def test_free_text_task_remains_backward_compatible(tmp_path: Path) -> None:
    await _register_and_index(tmp_path)
    async with session_scope() as session:
        result = await retrieval.prepare_task(session, project=PROJECT, task="add cart pricing")
    assert set(result) == {
        "project",
        "task",
        "briefing",
        "contract",
        "code_chunks",
        "split",
        "semantic_available",
        "mode",
        "semantic_note",
    }
    assert result["task"] == "add cart pricing"


# ---------------------------------------------------------------------------
# AC-PLAN-8: bounded role-neutral prompt with dependency + contract state
# ---------------------------------------------------------------------------
async def test_task_id_produces_bounded_role_neutral_prompt_with_deps_and_contract(
    tmp_path: Path,
) -> None:
    await _register_and_index(tmp_path)
    ids = await _seed_plan(with_requirement=True)
    async with session_scope() as session:
        result = await retrieval.prepare_task(session, project=PROJECT, task_id=ids["t2"])
    assert result["task_id"] == ids["t2"]
    assert result["plan_id"] == ids["plan_id"]
    prompt = cast(str, result["prompt"])
    assert "Wire pricing into cart total" in prompt
    assert "- [ ] cart_total sums unit_price(item) for every item" in prompt
    assert "t1 (" in prompt  # dependency status line
    assert "INV-CART-1" in prompt  # linked requirement contract statement
    deps = cast(list[dict[str, object]], result["dependencies"])
    assert deps and deps[0]["local_task_id"] == "t1"
    assert deps[0]["completed"] is False
    split = cast(dict[str, int], result["split"])
    assert cast(int, result["token_estimate"]) <= split["budget"]


async def test_task_id_with_requirement_calls_gather_relevant_only_once(
    tmp_path: Path,
) -> None:
    """Perf regression (T-PREPARE-PERF): don't re-run the same search twice.

    render_handoff_prompt already computes ranked code chunks via
    gather_relevant before building the contract; it must pass those ranked
    paths into get_task_contract rather than letting get_task_contract
    silently re-run gather_relevant from scratch (get_task_contract does
    exactly that whenever ranked_paths is omitted) — that duplication used to
    double prepare_task's latency (a real ~7s handoff-prompt request measured
    against this project dropped to ~2.4s once fixed).
    """
    await _register_and_index(tmp_path)
    ids = await _seed_plan(with_requirement=True)

    real_gather_relevant = index_hybrid.gather_relevant
    tracker = AsyncMock(wraps=real_gather_relevant)

    with patch("pcs.planning.handoff.gather_relevant", new=tracker):
        async with session_scope() as session:
            result = await retrieval.prepare_task(session, project=PROJECT, task_id=ids["t2"])

    assert tracker.call_count == 1
    assert "INV-CART-1" in cast(str, result["prompt"])


async def test_canonical_query_excludes_acceptance_criteria_from_retrieval(
    tmp_path: Path,
) -> None:
    """Perf/quality fix (T-PREPARE-PERF): AC text doesn't drive code retrieval.

    Acceptance criteria are checklist items, not a description of what to
    search for — including them in the retrieval query only added length
    (cost) without adding signal, and could even surface it here (creating a
    false impression of relevance). A file whose only matching content is a
    marker that appears solely in an acceptance criterion (not the title,
    objective, or linked_files) must not be preferentially surfaced.
    """
    (tmp_path / "shop").mkdir()
    (tmp_path / "shop" / "cart.py").write_text(
        "def cart_total(items):\n    return sum(unit_price(item) for item in items)\n",
        encoding="utf-8",
    )
    (tmp_path / "shop" / "unrelated.py").write_text(
        "ZQXW_ONLY_IN_ACCEPTANCE_CRITERION = True\n", encoding="utf-8"
    )
    await _register_project(tmp_path)
    async with session_scope() as session:
        await index_service.reindex(session, project=PROJECT, incremental=False)

    tasks = [
        TaskSpec(
            local_task_id="t1",
            title="Add pricing helper",
            objective="Implement unit_price so cart_total can use it.",
            acceptance_criteria=["ZQXW_ONLY_IN_ACCEPTANCE_CRITERION must stay True"],
        ),
    ]
    async with session_scope() as session:
        plan = await planning_service.create_plan_with_tasks(
            session, project=PROJECT, title="Cart pricing", goal="Ship it", tasks=tasks
        )
        await planning_service.activate_plan(session, PROJECT, plan.id)
        task_id = plan.tasks[0].id

    async with session_scope() as session:
        result = await retrieval.prepare_task(session, project=PROJECT, task_id=task_id)

    assert "unrelated.py" not in cast(str, result["prompt"])


async def test_dependency_marked_completed_once_prerequisite_is_done(tmp_path: Path) -> None:
    await _register_and_index(tmp_path)
    ids = await _seed_plan()
    async with session_scope() as session:
        claim = await planning_service.claim_task(
            session, PROJECT, ids["plan_id"], ids["t1"], claimed_by="worker"
        )
        await planning_service.complete_task(
            session, PROJECT, ids["plan_id"], ids["t1"], claim_token=claim.claim_token
        )
    async with session_scope() as session:
        result = await retrieval.prepare_task(session, project=PROJECT, task_id=ids["t2"])
    deps = cast(list[dict[str, object]], result["dependencies"])
    assert deps[0]["completed"] is True
    assert "t1 (done)" in cast(str, result["prompt"])


# ---------------------------------------------------------------------------
# Exactly one of task / task_id
# ---------------------------------------------------------------------------
async def test_both_task_and_task_id_rejected(tmp_path: Path) -> None:
    await _register_and_index(tmp_path)
    ids = await _seed_plan()
    async with session_scope() as session:
        with pytest.raises(ValueError, match="not both"):
            await retrieval.prepare_task(
                session, project=PROJECT, task="free text", task_id=ids["t1"]
            )


async def test_neither_task_nor_task_id_rejected(tmp_path: Path) -> None:
    await _register_and_index(tmp_path)
    async with session_scope() as session:
        with pytest.raises(ValueError, match="exactly one"):
            await retrieval.prepare_task(session, project=PROJECT)


async def test_mcp_and_http_reject_both_or_neither(tmp_path: Path) -> None:
    await _register_and_index(tmp_path)
    ids = await _seed_plan()
    with (
        patch("pcs.mcp.support.caller", return_value="handoff-test"),
        pytest.raises(ToolError, match="exactly one"),
    ):
        await mcp.call_tool(
            "prepare_task", {"project": PROJECT, "task": "free text", "task_id": ids["t1"]}
        )
    with (
        patch("pcs.mcp.support.caller", return_value="handoff-test"),
        pytest.raises(ToolError, match="exactly one"),
    ):
        await mcp.call_tool("prepare_task", {"project": PROJECT})

    client = _client()
    both = _http(
        client,
        "POST",
        f"/api/projects/{PROJECT}/prepare-task",
        json_body={"task": "free text", "task_id": ids["t1"]},
    )
    assert both.status_code == 400
    neither = _http(client, "POST", f"/api/projects/{PROJECT}/prepare-task", json_body={})
    assert neither.status_code == 400


# ---------------------------------------------------------------------------
# Cross-project / nonexistent task_id -> not found
# ---------------------------------------------------------------------------
async def test_cross_project_task_id_returns_not_found(
    tmp_path: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    await _register_and_index(tmp_path)
    ids = await _seed_plan()
    other_root = tmp_path_factory.mktemp("other")
    await _register_and_index(other_root, name=OTHER_PROJECT)

    async with session_scope() as session:
        with pytest.raises(TaskNotFoundError):
            await retrieval.prepare_task(session, project=OTHER_PROJECT, task_id=ids["t1"])

    client = _client()
    response = _http(
        client,
        "POST",
        f"/api/projects/{OTHER_PROJECT}/prepare-task",
        json_body={"task_id": ids["t1"]},
    )
    assert response.status_code == 404


async def test_nonexistent_task_id_returns_not_found(tmp_path: Path) -> None:
    await _register_and_index(tmp_path)
    async with session_scope() as session:
        with pytest.raises(TaskNotFoundError):
            await retrieval.prepare_task(
                session, project=PROJECT, task_id="00000000-0000-0000-0000-000000000000"
            )


# ---------------------------------------------------------------------------
# A completed/cancelled task refuses to generate a "build this" prompt
# ---------------------------------------------------------------------------
async def test_completed_task_id_refuses_handoff_prompt(tmp_path: Path) -> None:
    """Observed live: prepare_task happily regenerated a full implementation
    prompt for a task pcs already recorded as completed by a different agent
    — an agent handed that prompt would redo finished work. The task's own
    status must gate the prompt, not just its acceptance criteria text."""
    await _register_and_index(tmp_path)
    ids = await _seed_plan()
    async with session_scope() as session:
        claim = await planning_service.claim_task(
            session, PROJECT, ids["plan_id"], ids["t1"], claimed_by="worker"
        )
        await planning_service.complete_task(
            session, PROJECT, ids["plan_id"], ids["t1"], claim_token=claim.claim_token
        )
    async with session_scope() as session:
        with pytest.raises(TaskAlreadyTerminalError, match="already 'completed'"):
            await retrieval.prepare_task(session, project=PROJECT, task_id=ids["t1"])

    client = _client()
    response = _http(
        client, "POST", f"/api/projects/{PROJECT}/prepare-task", json_body={"task_id": ids["t1"]}
    )
    assert response.status_code == 409


# ---------------------------------------------------------------------------
# Prompt instructs on AGENTS.md, scope, evidence recording
# ---------------------------------------------------------------------------
async def test_prompt_mentions_agents_md_scope_and_evidence_recording(tmp_path: Path) -> None:
    await _register_and_index(tmp_path)
    ids = await _seed_plan()
    async with session_scope() as session:
        result = await retrieval.prepare_task(session, project=PROJECT, task_id=ids["t1"])
    prompt = cast(str, result["prompt"])
    assert "AGENTS.md" in prompt
    assert "file scope" in prompt.lower()
    assert "acceptance criteri" in prompt.lower()
    # t1 has no linked requirement — record_requirement_evidence must not appear
    # as a dead reference next to "(no linked requirement contracts)".
    assert "record_requirement_evidence" not in prompt
    assert "complete_task" in prompt


async def test_prompt_embeds_concrete_pcs_lifecycle_calls(tmp_path: Path) -> None:
    """The prompt is designed to be copy-pasted into a different, cold-started
    agent/session with none of this project's own instructions loaded — it
    must spell out claim_task/heartbeat_task/complete_task with the actual
    project/plan_id/task_id filled in rather than only pointing at AGENTS.md,
    since that indirection was observed to get skipped in practice."""
    await _register_and_index(tmp_path)
    ids = await _seed_plan()
    async with session_scope() as session:
        result = await retrieval.prepare_task(session, project=PROJECT, task_id=ids["t1"])
    prompt = cast(str, result["prompt"])
    assert f'project="{PROJECT}"' in prompt
    assert f'plan_id="{ids["plan_id"]}"' in prompt
    assert f'task_id="{ids["t1"]}"' in prompt
    assert "claim_task(" in prompt
    assert "heartbeat_task" in prompt
    assert "search_code" in prompt
    assert "retrieve_context" in prompt
    assert "get_code_map" in prompt


async def test_prompt_frames_pcs_tool_use_as_mandatory(tmp_path: Path) -> None:
    """A plain description of available tools was observed to still get
    skipped by weaker models (Haiku 4.5) — the prompt must explicitly say
    tool use is required, not just informational, and give it its own
    heading so it reads as a hard requirement rather than background."""
    await _register_and_index(tmp_path)
    ids = await _seed_plan()
    async with session_scope() as session:
        result = await retrieval.prepare_task(session, project=PROJECT, task_id=ids["t1"])
    prompt = cast(str, result["prompt"])
    assert "### Required: use pcs" in prompt
    assert "mandatory" in prompt.lower()


async def test_prompt_mentions_evidence_only_when_requirement_linked(tmp_path: Path) -> None:
    await _register_and_index(tmp_path)
    ids = await _seed_plan(with_requirement=True)
    async with session_scope() as session:
        result = await retrieval.prepare_task(session, project=PROJECT, task_id=ids["t2"])
    prompt = cast(str, result["prompt"])
    assert "record_requirement_evidence" in prompt


# ---------------------------------------------------------------------------
# Relevant conventions/decisions surfaced in the prompt (not just pcs tool
# usage) — an agent given only the copied prompt should see the project's
# own accumulated conventions/decisions relevant to the task, not just be
# told pcs has a get_section tool it could call.
# ---------------------------------------------------------------------------
async def _add_context_entry(
    project: str,
    section: str,
    *,
    headline: str,
    detail: str = "Some project-specific detail worth knowing before touching this code.",
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


async def test_convention_with_matching_linked_files_appears_in_prompt(tmp_path: Path) -> None:
    await _register_and_index(tmp_path)
    ids = await _seed_plan()
    await _add_context_entry(
        PROJECT,
        "conventions",
        headline="cart.py always validates non-negative totals",
        linked_files=("shop/cart.py",),
    )
    async with session_scope() as session:
        result = await retrieval.prepare_task(session, project=PROJECT, task_id=ids["t2"])
    prompt = cast(str, result["prompt"])
    assert "### Relevant conventions" in prompt
    assert "cart.py always validates non-negative totals" in prompt


async def test_unrelated_convention_is_omitted(tmp_path: Path) -> None:
    await _register_and_index(tmp_path)
    ids = await _seed_plan()
    await _add_context_entry(
        PROJECT,
        "conventions",
        headline="Unrelated: logo upload files must be under 2MB",
        linked_files=("modules/branding/logo.py",),
    )
    async with session_scope() as session:
        result = await retrieval.prepare_task(session, project=PROJECT, task_id=ids["t1"])
    prompt = cast(str, result["prompt"])
    assert "### Relevant conventions" not in prompt
    assert "logo upload" not in prompt


async def test_no_signal_means_no_conventions_or_decisions_sections(tmp_path: Path) -> None:
    await _register_and_index(tmp_path)
    ids = await _seed_plan()
    await _add_context_entry(
        PROJECT, "conventions", headline="Totally unrelated topic about deployment scripts"
    )
    await _add_context_entry(
        PROJECT, "decisions", headline="Totally unrelated topic about logo rendering"
    )
    async with session_scope() as session:
        result = await retrieval.prepare_task(session, project=PROJECT, task_id=ids["t1"])
    prompt = cast(str, result["prompt"])
    assert "### Relevant conventions" not in prompt
    assert "### Relevant decisions" not in prompt


async def test_decision_boosted_by_related_requirement_id(tmp_path: Path) -> None:
    await _register_and_index(tmp_path)
    ids = await _seed_plan(with_requirement=True)
    await _add_context_entry(
        PROJECT,
        "decisions",
        headline="Cart totals decision with no textual overlap at all",
        detail="xyzzy plugh unrelated words that share nothing with the task text.",
        related_entry_id=ids["req_id"],
    )
    async with session_scope() as session:
        result = await retrieval.prepare_task(session, project=PROJECT, task_id=ids["t2"])
    prompt = cast(str, result["prompt"])
    assert "### Relevant decisions" in prompt
    assert "Cart totals decision with no textual overlap at all" in prompt


async def test_context_entries_token_budget_respected(tmp_path: Path) -> None:
    await _register_and_index(tmp_path)
    ids = await _seed_plan()
    big_detail = "shop/cart.py pricing rule detail. " * 200  # ~1500+ tokens raw
    for i in range(3):
        await _add_context_entry(
            PROJECT,
            "decisions",
            headline=f"Cart pricing decision {i}",
            detail=big_detail,
            linked_files=("shop/cart.py",),
        )
    async with session_scope() as session:
        result = await retrieval.prepare_task(session, project=PROJECT, task_id=ids["t2"])
    split = cast(dict[str, object], result["split"])
    assert cast(int, result["token_estimate"]) <= cast(int, split["budget"])
    assert cast(int, split["context_entries_tokens"]) <= 400  # CONTEXT_ENTRIES_TOKEN_CAP


async def test_oversized_decision_gets_truncation_marker_and_drill_down_line(
    tmp_path: Path,
) -> None:
    await _register_and_index(tmp_path)
    ids = await _seed_plan()
    big_detail = "shop/cart.py pricing rule detail. " * 200
    await _add_context_entry(
        PROJECT,
        "decisions",
        headline="Cart pricing decision",
        detail=big_detail,
        linked_files=("shop/cart.py",),
    )
    async with session_scope() as session:
        result = await retrieval.prepare_task(session, project=PROJECT, task_id=ids["t2"])
    prompt = cast(str, result["prompt"])
    assert "…" in prompt
    assert 'call get_section(section="decisions")' in prompt


# ---------------------------------------------------------------------------
# Zero leaked claim token *values*, secrets, or raw diffs. The prompt does
# legitimately mention the word "claim_token" as an instructional concept
# (telling the receiving agent to capture the one claim_task itself returns
# it) — what must never appear is an actual, already-issued secret value.
# ---------------------------------------------------------------------------
async def test_prompt_contains_zero_secrets_or_raw_diffs(tmp_path: Path) -> None:
    await _register_and_index(tmp_path)
    ids = await _seed_plan()
    async with session_scope() as session:
        claim = await planning_service.claim_task(
            session, PROJECT, ids["plan_id"], ids["t1"], claimed_by="worker"
        )
    async with session_scope() as session:
        result = await retrieval.prepare_task(session, project=PROJECT, task_id=ids["t1"])
    dumped = json.dumps(result)
    assert claim.claim_token not in dumped
    prompt = cast(str, result["prompt"])
    assert "diff --git" not in prompt
    assert "\n+++ " not in prompt
    assert "\n--- " not in prompt


# ---------------------------------------------------------------------------
# Token budget respected; code floor preserved when chunks exist
# ---------------------------------------------------------------------------
async def test_token_budget_respected_and_code_floor_preserved_when_chunks_exist(
    tmp_path: Path,
) -> None:
    await _register_and_index(tmp_path)
    ids = await _seed_plan()
    async with session_scope() as session:
        result = await retrieval.prepare_task(
            session, project=PROJECT, task_id=ids["t2"], max_tokens=PREPARE_TASK_TOKEN_MIN
        )
    split = cast(dict[str, int], result["split"])
    assert split["budget"] == PREPARE_TASK_TOKEN_MIN
    assert cast(int, result["token_estimate"]) <= split["budget"]
    assert split["code_tokens"] > 0
    assert "### Relevant code" in cast(str, result["prompt"])


async def test_invalid_max_tokens_rejected(tmp_path: Path) -> None:
    await _register_and_index(tmp_path)
    ids = await _seed_plan()
    async with session_scope() as session:
        with pytest.raises(ValueError, match="max_tokens"):
            await retrieval.prepare_task(session, project=PROJECT, task_id=ids["t1"], max_tokens=1)
