"""T29 cross-layer integration, isolation, migration, and security tests.

``test_planning_core.py`` (T23) and ``test_planning_api.py`` (T24) already
exhaustively cover the service- and MCP/HTTP-adapter-level acceptance
criteria (DAG validation, lease lifecycle, boundary conditions, token
enforcement, event taxonomy, DB-level composite-FK isolation, migration
upgrade/downgrade) — see each file's own module docstring. This file adds
only what neither already proves:

- One continuous end-to-end narrative spanning MCP *and* HTTP, a manually
  created plan *and* an approved-AI-draft plan (``create_plan_with_tasks``,
  what T28's "Review & Create" calls), activation, ready-task discovery,
  full claim->complete lifecycles, downstream unlock, plan completion, and
  D4 requirement-status independence — proving the layers actually compose,
  not just that each one works in isolation (AC-PLAN-13).
- Cross-*project* isolation at the HTTP boundary specifically (the existing
  DB composite-FK tests prove cross-plan/cross-project isolation at the
  storage layer; ``test_mismatched_plan_id_returns_404_task_not_found``
  proves cross-*plan* 404s within one project — neither proves every nested
  task route also 404s when the *project* segment doesn't own the plan).
- A real ``alembic downgrade -1`` / ``upgrade head`` round trip through the
  T20/T23 merge point (``0024_merge_t20_t23``), which
  ``test_migration_upgrade_and_downgrade``'s fixed-revision downgrade skips
  past entirely.
- A secrets-in-logs sweep across a full claim -> heartbeat -> release ->
  reclaim -> complete lifecycle (MCP and HTTP), asserting actual token
  *values* never appear in any captured log line or its formatted JSON —
  ``test_audit_log_contains_tool_project_caller_outcome`` (T24) only
  exercises ``create_plan``/``list_plans``, which never carry a token.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any
from unittest.mock import patch

import pytest
from alembic import command
from alembic.config import Config
from alembic.util.exc import CommandError
from starlette.testclient import TestClient

from pcs.context import service as ctx_service
from pcs.db.base import reset_engine, session_scope
from pcs.logging import JsonFormatter
from pcs.mcp import build_http_app, mcp
from pcs.planning import (
    TaskSpec,
    create_plan,
    create_plan_with_tasks,
    get_plan,
)

pytestmark = pytest.mark.usefixtures("clean_db")
PROJECT_A = "integration-alpha"
PROJECT_B = "integration-beta"


async def _seed_project(name: str) -> None:
    async with session_scope() as session:
        await ctx_service.register_project(
            session, name=name, root_path=f"/tmp/{name}", overview=f"Test project {name}"
        )


def _tool_payload(result: object) -> object:
    if isinstance(result, tuple):
        _, structured = result
        if isinstance(structured, dict) and set(structured.keys()) == {"result"}:
            return structured["result"]
        if structured is not None:
            return structured
    if isinstance(result, list) and result and hasattr(result[0], "text"):
        return json.loads(str(result[0].text))
    return result


async def _call(name: str, arguments: dict[str, object]) -> Any:
    with patch("pcs.mcp.planning_tools.caller", return_value="integration-agent"):
        return _tool_payload(await mcp.call_tool(name, arguments))


def _client() -> TestClient:
    return TestClient(build_http_app())


def _http(
    client: TestClient,
    method: str,
    path: str,
    *,
    json_body: dict[str, object] | None = None,
) -> Any:
    headers = {"x-pcs-caller": "integration-http"}
    return client.request(method, path, json=json_body, headers=headers)


# ---------------------------------------------------------------------------
# AC-PLAN-13: full cross-layer lifecycle
# ---------------------------------------------------------------------------
async def test_full_lifecycle_manual_and_approved_ai_draft_end_to_end() -> None:
    """Manual (MCP) + approved-AI-draft (HTTP) plans, both driven to completion."""
    await _seed_project(PROJECT_A)
    async with session_scope() as session:
        req = await ctx_service.add_entry(
            session,
            project=PROJECT_A,
            section="requirements",
            headline="Ship checkout",
            requirement_status="in-progress",
        )

    # 1. Manual plan, created and driven entirely via MCP tools.
    manual = await _call(
        "create_plan", {"project": PROJECT_A, "title": "Manual Plan", "goal": "Manual goal"}
    )
    m1 = await _call(
        "add_plan_task",
        {
            "project": PROJECT_A,
            "plan_id": manual["id"],
            "local_task_id": "m1",
            "title": "Task M1",
            "objective": "Do M1",
            "requirement_ids": [req.id],
        },
    )
    await _call("activate_plan", {"project": PROJECT_A, "plan_id": manual["id"]})

    # 2. "Approved AI draft" plan: create_plan_with_tasks is exactly what
    #    T28's "Review & Create" calls after a T26 generate_plan_draft the
    #    caller approved — the provider call itself is already covered
    #    end-to-end (real provider, real UI) in T26/T28's own evidence.
    #    Driven entirely via HTTP this time, to prove both transports reach
    #    the same domain.
    client = _client()
    created_resp = _http(
        client,
        "POST",
        f"/api/projects/{PROJECT_A}/plans/with-tasks",
        json_body={
            "title": "AI Plan",
            "goal": "AI goal",
            "tasks": [
                {"local_task_id": "a1", "title": "Task A1", "objective": "Do A1"},
                {"local_task_id": "a2", "title": "Task A2", "objective": "Do A2"},
            ],
            "dependencies": [{"task_local_id": "a2", "depends_on_local_id": "a1"}],
        },
    )
    assert created_resp.status_code == 201
    ai_plan = created_resp.json()
    a1_id = next(t["id"] for t in ai_plan["tasks"] if t["local_task_id"] == "a1")
    a2_id = next(t["id"] for t in ai_plan["tasks"] if t["local_task_id"] == "a2")
    assert (
        _http(
            client, "POST", f"/api/projects/{PROJECT_A}/plans/{ai_plan['id']}/activate"
        ).status_code
        == 200
    )

    # 3. Ready-task discovery spans both plans; a2 is blocked on a1. Checked
    #    through both transports, since list_ready_tasks is a bare-list
    #    return (unlike the dict-returning tools called elsewhere here).
    ready_mcp = await _call("list_ready_tasks", {"project": PROJECT_A})
    ready_http = _http(client, "GET", f"/api/projects/{PROJECT_A}/ready-tasks").json()
    assert {t["id"] for t in ready_mcp} == {t["id"] for t in ready_http}
    ready_ids = {t["id"] for t in ready_http}
    assert m1["id"] in ready_ids
    assert a1_id in ready_ids
    assert a2_id not in ready_ids

    # 4. Manual plan's task lifecycle, entirely via MCP, to completion.
    claim1 = await _call(
        "claim_task",
        {
            "project": PROJECT_A,
            "plan_id": manual["id"],
            "task_id": m1["id"],
            "claimed_by": "agent-1",
            "lease_seconds": 1800,
        },
    )
    token1 = claim1["claim_token"]
    await _call(
        "set_task_status",
        {
            "project": PROJECT_A,
            "plan_id": manual["id"],
            "task_id": m1["id"],
            "status": "in_progress",
            "claim_token": token1,
        },
    )
    await _call(
        "complete_task",
        {"project": PROJECT_A, "plan_id": manual["id"], "task_id": m1["id"], "claim_token": token1},
    )
    completed_manual = await _call("complete_plan", {"project": PROJECT_A, "plan_id": manual["id"]})
    assert completed_manual["status"] == "completed"

    # 5. AI plan's task lifecycle, entirely via HTTP, proving downstream
    #    unlock and plan completion work through that transport too.
    claim_a1 = _http(
        client,
        "POST",
        f"/api/projects/{PROJECT_A}/plans/{ai_plan['id']}/tasks/{a1_id}/claim",
        json_body={"claimed_by": "agent-2", "lease_seconds": 1800},
    )
    assert claim_a1.status_code == 200
    token_a1 = claim_a1.json()["claim_token"]
    assert (
        _http(
            client,
            "POST",
            f"/api/projects/{PROJECT_A}/plans/{ai_plan['id']}/tasks/{a1_id}/complete",
            json_body={"claim_token": token_a1},
        ).status_code
        == 200
    )

    ready_after = _http(client, "GET", f"/api/projects/{PROJECT_A}/ready-tasks").json()
    assert any(t["id"] == a2_id for t in ready_after)

    claim_a2 = _http(
        client,
        "POST",
        f"/api/projects/{PROJECT_A}/plans/{ai_plan['id']}/tasks/{a2_id}/claim",
        json_body={"claimed_by": "agent-2", "lease_seconds": 1800},
    )
    token_a2 = claim_a2.json()["claim_token"]
    assert (
        _http(
            client,
            "POST",
            f"/api/projects/{PROJECT_A}/plans/{ai_plan['id']}/tasks/{a2_id}/complete",
            json_body={"claim_token": token_a2},
        ).status_code
        == 200
    )
    assert (
        _http(
            client, "POST", f"/api/projects/{PROJECT_A}/plans/{ai_plan['id']}/complete"
        ).status_code
        == 200
    )

    # 6. D4: neither task nor plan completion touched the linked requirement.
    async with session_scope() as session:
        entry = await ctx_service.get_entry(session, project=PROJECT_A, entry_id=req.id)
        assert entry.requirement_status == "in-progress"

    # 7. History is complete and chronologically ordered for the manual task,
    #    and both transports agree on its shape.
    history_mcp = await _call(
        "get_task_history", {"project": PROJECT_A, "plan_id": manual["id"], "task_id": m1["id"]}
    )
    history_http = _http(
        client,
        "GET",
        f"/api/projects/{PROJECT_A}/plans/{manual['id']}/tasks/{m1['id']}/history",
    ).json()
    assert [e["id"] for e in history_mcp] == [e["id"] for e in history_http]
    timestamps = [e["created_at"] for e in history_http]
    assert timestamps == sorted(timestamps)
    assert {e["event_type"] for e in history_http} >= {
        "created",
        "status_changed",
        "claimed",
        "completed",
    }


# ---------------------------------------------------------------------------
# Cross-project isolation at the HTTP boundary
# ---------------------------------------------------------------------------
async def test_cross_project_requests_cannot_access_or_mutate_plans_or_tasks() -> None:
    """Every plan- and task-scoped route 404s when the URL's project doesn't own it."""
    await _seed_project(PROJECT_A)
    await _seed_project(PROJECT_B)

    async with session_scope() as session:
        plan = await create_plan_with_tasks(
            session,
            PROJECT_A,
            "Owned by A",
            "Goal",
            [TaskSpec(local_task_id="t1", title="T1", objective="Obj")],
        )
        await session.commit()
    task_id = plan.tasks[0].id
    client = _client()

    plan_level: list[tuple[str, str, dict[str, object] | None]] = [
        ("GET", f"/api/projects/{PROJECT_B}/plans/{plan.id}", None),
        ("PATCH", f"/api/projects/{PROJECT_B}/plans/{plan.id}", {"title": "Hijacked"}),
        ("POST", f"/api/projects/{PROJECT_B}/plans/{plan.id}/activate", None),
        ("POST", f"/api/projects/{PROJECT_B}/plans/{plan.id}/archive", None),
        ("POST", f"/api/projects/{PROJECT_B}/plans/{plan.id}/complete", None),
        (
            "POST",
            f"/api/projects/{PROJECT_B}/plans/{plan.id}/tasks",
            {
                "local_task_id": "intruder",
                "title": "T",
                "objective": "O",
            },
        ),
        # NOTE: plan-scoped GET .../ready-tasks is intentionally excluded —
        # list_ready_tasks(plan_id=...) is designed to return [] for any
        # plan_id that doesn't match an active plan in the given project
        # (same as a plan_id that doesn't exist at all), not to 404. The
        # AC-PLAN-1 404 requirement is specifically for the task-scoped
        # `.../plans/{plan_id}/tasks/{task_id}/*` routes below.
    ]
    for method, path, body in plan_level:
        resp = _http(client, method, path, json_body=body)
        assert resp.status_code == 404, f"{method} {path} -> {resp.status_code}: {resp.text}"

    task_level: list[tuple[str, str, dict[str, object] | None]] = [
        ("PATCH", "", {"title": "Hijacked task"}),
        ("POST", "/claim", {"claimed_by": "intruder", "lease_seconds": 1800}),
        ("POST", "/heartbeat", {"claim_token": "whatever"}),
        ("POST", "/release", {"claim_token": "whatever"}),
        ("POST", "/status", {"status": "in_progress"}),
        ("POST", "/complete", {}),
        ("GET", "/history", None),
    ]
    for method, suffix, body in task_level:
        path = f"/api/projects/{PROJECT_B}/plans/{plan.id}/tasks/{task_id}{suffix}"
        resp = _http(client, method, path, json_body=body)
        assert resp.status_code == 404, f"{method} {path} -> {resp.status_code}: {resp.text}"

    # Sanity: the same plan under its real, owning project works fine —
    # proves the 404s above are project isolation, not a malformed URL.
    assert _http(client, "GET", f"/api/projects/{PROJECT_A}/plans/{plan.id}").status_code == 200


# ---------------------------------------------------------------------------
# Migration round trip through the T20/T23 merge point
# ---------------------------------------------------------------------------
def test_migration_downgrade_through_merge_point_and_reupgrade() -> None:
    """`alembic downgrade <target> / upgrade head` round-trips cleanly with
    zero data loss through the T20/T23 merge point (`0024_merge_t20_t23` —
    a pure no-op join of the two independently developed branches), landing
    on `0023_plan_task_orchestration` (T23's own head, one hop below the
    merge) and re-converging back to the single head.

    Targets the merge point **by name** rather than assuming it's the
    current head — later migrations (e.g. `0025_token_savings_log`) land on
    top of it, so "head" and "the merge point" are two different things and
    this test must not conflate them.

    NOTE on the literal `uv run alembic downgrade -1` from T29's own
    Verification section: it does **not** work when the current position is
    the merge point itself — confirmed directly
    (`alembic.util.exc.CommandError: Ambiguous walk`) and by running the
    exact command against the live `pcs` database at a moment its head was
    that merge point (it aborted cleanly before any write — alembic raises
    during revision *resolution*, before touching the DB). `-1` is only
    unambiguous on a single linear branch; at a merge point alembic can't
    infer which parent branch "one step back" means, and requires an
    explicit target revision instead. This is a real, reproducible
    discrepancy between the task spec's literal verification command and
    this repo's migration topology whenever the merge point is current — a
    documentation correction, not a migration bug (`0024`'s downgrade() is
    intentionally a no-op; there is nothing for a relative walk to undo).

    A plain (non-async) test, matching `test_migration_upgrade_and_downgrade`
    in test_planning_core.py: alembic's async `env.py` calls
    ``asyncio.run(...)`` itself, which fails if a pytest-asyncio event loop
    is already running. The async setup/verification below run in their own
    short-lived loops instead, via `asyncio.run`.
    """

    async def seed() -> str:
        await _seed_project(PROJECT_A)
        async with session_scope() as session:
            plan = await create_plan(session, PROJECT_A, "Survives migration round trip", "Goal")
            return plan.id

    async def reload_title(plan_id: str) -> str:
        async with session_scope() as session:
            reloaded = await get_plan(session, PROJECT_A, plan_id)
            return reloaded.title

    plan_id = asyncio.run(seed())
    asyncio.run(reset_engine())  # drop the engine bound to seed()'s now-closed loop

    config = Config("alembic.ini")
    # Step down to exactly the merge point, then confirm a further relative
    # step from *there* is genuinely ambiguous (0024 has two parents).
    command.downgrade(config, "0024_merge_t20_t23")
    with pytest.raises(CommandError, match="Ambiguous walk"):
        command.downgrade(config, "-1")

    command.downgrade(config, "0023_plan_task_orchestration")
    command.upgrade(config, "head")

    assert asyncio.run(reload_title(plan_id)) == "Survives migration round trip"


# ---------------------------------------------------------------------------
# Zero secret leaks across a full claim lifecycle, in both transports
# ---------------------------------------------------------------------------
async def test_zero_secret_leaks_in_logs_across_full_claim_lifecycle() -> None:
    """No claim token (or its hash) appears in any audit log line — as raw
    fields, as the spy's captured dict, or once formatted through the real
    `JsonFormatter` — across claim -> heartbeat -> release (MCP) and
    reclaim -> status -> complete (HTTP)."""
    await _seed_project(PROJECT_A)
    seen: list[dict[str, object]] = []

    def spy(*, tool: str, project: str | None, caller: str, outcome: str, **fields: object) -> None:
        seen.append(
            {"tool": tool, "project": project or "", "caller": caller, "outcome": outcome, **fields}
        )

    tokens: list[str] = []
    with (
        patch("pcs.mcp.planning_tools.caller", return_value="secret-sweep-agent"),
        patch("pcs.mcp.planning_tools.log_tool_call", spy),
        patch("pcs.web_api.planning_routes.log_tool_call", spy),
    ):
        created = await _call(
            "create_plan", {"project": PROJECT_A, "title": "Sweep", "goal": "Goal"}
        )
        task = await _call(
            "add_plan_task",
            {
                "project": PROJECT_A,
                "plan_id": created["id"],
                "local_task_id": "s1",
                "title": "S1",
                "objective": "Obj",
            },
        )
        await _call("activate_plan", {"project": PROJECT_A, "plan_id": created["id"]})
        claim = await _call(
            "claim_task",
            {
                "project": PROJECT_A,
                "plan_id": created["id"],
                "task_id": task["id"],
                "claimed_by": "agent-1",
                "lease_seconds": 1800,
            },
        )
        tokens.append(str(claim["claim_token"]))
        await _call(
            "heartbeat_task",
            {
                "project": PROJECT_A,
                "plan_id": created["id"],
                "task_id": task["id"],
                "claim_token": tokens[-1],
            },
        )
        await _call(
            "release_task",
            {
                "project": PROJECT_A,
                "plan_id": created["id"],
                "task_id": task["id"],
                "claim_token": tokens[-1],
            },
        )

        client = _client()
        reclaim = _http(
            client,
            "POST",
            f"/api/projects/{PROJECT_A}/plans/{created['id']}/tasks/{task['id']}/claim",
            json_body={"claimed_by": "agent-2", "lease_seconds": 1800},
        )
        tokens.append(reclaim.json()["claim_token"])
        _http(
            client,
            "POST",
            f"/api/projects/{PROJECT_A}/plans/{created['id']}/tasks/{task['id']}/status",
            json_body={"status": "in_progress", "claim_token": tokens[-1]},
        )
        _http(
            client,
            "POST",
            f"/api/projects/{PROJECT_A}/plans/{created['id']}/tasks/{task['id']}/complete",
            json_body={"claim_token": tokens[-1]},
        )

    assert len(tokens) == 2 and all(tokens)
    dumped = json.dumps(seen)
    assert "claim_token" not in dumped
    assert "claim_token_hash" not in dumped
    for token in tokens:
        assert token not in dumped

    for item in seen:
        record = logging.LogRecord("pcs", logging.INFO, __file__, 0, "tool_call", (), None)
        record.__dict__["context"] = item
        formatted = JsonFormatter().format(record)
        for token in tokens:
            assert token not in formatted
