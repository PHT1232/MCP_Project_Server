"""T24 adapter integration tests (AC-PLAN-7, FR43-FR48, NFR6)."""

from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from typing import Any, cast
from unittest.mock import patch

import pytest
from mcp.server.fastmcp.exceptions import ToolError
from sqlalchemy import text
from starlette.testclient import TestClient

from pcs.context import service as context_service
from pcs.db.base import session_scope
from pcs.mcp import build_http_app, mcp
from pcs.mcp.planning_tools import EMPTY_MUTATION, UNKNOWN_FIELDS
from pcs.planning import (
    EVENT_CANCELLED,
    EVENT_CLAIMED,
    EVENT_COMPLETED,
    EVENT_CREATED,
    EVENT_DEPENDENCY_ADDED,
    EVENT_HEARTBEAT,
    EVENT_RECLAIMED,
    EVENT_RELEASED,
    EVENT_STATUS_CHANGED,
    EVENT_UPDATED,
    TASK_EVENT_TYPES,
    TASK_STATUS_CLAIMED,
    TASK_STATUS_IN_PROGRESS,
    TASK_STATUS_IN_REVIEW,
    DependencySpec,
    TaskSpec,
)
from pcs.planning import service as planning_service

pytestmark = pytest.mark.usefixtures("clean_db")
PROJECT = "plan-api"
SECRET_TOKEN_MARKER = "claim_token"

PLANNING_TOOLS = (
    "create_plan",
    "create_plan_with_tasks",
    "list_plans",
    "get_plan",
    "update_plan",
    "archive_plan",
    "activate_plan",
    "add_plan_task",
    "update_plan_task",
    "add_task_dependency",
    "list_ready_tasks",
    "claim_task",
    "heartbeat_task",
    "release_task",
    "set_task_status",
    "complete_task",
    "complete_plan",
    "get_task_history",
)

NESTED_TASK_PATHS = (
    "/api/projects/{project}/plans/{plan_id}/tasks/{task_id}",
    "/api/projects/{project}/plans/{plan_id}/tasks/{task_id}/claim",
    "/api/projects/{project}/plans/{plan_id}/tasks/{task_id}/heartbeat",
    "/api/projects/{project}/plans/{plan_id}/tasks/{task_id}/release",
    "/api/projects/{project}/plans/{plan_id}/tasks/{task_id}/status",
    "/api/projects/{project}/plans/{plan_id}/tasks/{task_id}/complete",
    "/api/projects/{project}/plans/{plan_id}/tasks/{task_id}/history",
)


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


async def _call(name: str, arguments: dict[str, object]) -> Any:
    with patch("pcs.mcp.planning_tools.caller", return_value="agent-t24"):
        return _tool_payload(await mcp.call_tool(name, arguments))


def _client() -> TestClient:
    return TestClient(build_http_app())


def _http(
    client: TestClient,
    method: str,
    path: str,
    *,
    json_body: dict[str, object] | None = None,
    caller: str = "http-reviewer",
    content: bytes | None = None,
) -> Any:
    headers = {"x-pcs-caller": caller}
    if content is not None:
        headers["content-type"] = "application/json"
        return client.request(method, path, content=content, headers=headers)
    return client.request(method, path, json=json_body, headers=headers)


async def _seed_project(name: str = PROJECT) -> None:
    async with session_scope() as session:
        with suppress(context_service.DuplicateProjectError):
            await context_service.register_project(
                session, name=name, root_path=f"/tmp/{name}", overview=f"Test project {name}"
            )


async def _seed_active_plan(
    *,
    extra_tasks: list[TaskSpec] | None = None,
    dependencies: list[DependencySpec] | None = None,
) -> dict[str, str]:
    await _seed_project()
    tasks = extra_tasks or [
        TaskSpec(local_task_id="t1", title="First", objective="Do first"),
        TaskSpec(local_task_id="t2", title="Second", objective="Do second"),
    ]
    if extra_tasks is None and dependencies is None:
        deps: list[DependencySpec] = [DependencySpec(task_local_id="t2", depends_on_local_id="t1")]
    else:
        deps = list(dependencies or [])
    async with session_scope() as session:
        view = await planning_service.create_plan_with_tasks(
            session,
            project=PROJECT,
            title="Two-task plan",
            goal="Ship both",
            tasks=tasks,
            dependencies=deps,
        )
        await planning_service.activate_plan(session, PROJECT, view.id)
        return {"plan_id": view.id, **{task.local_task_id: task.id for task in view.tasks}}


def _task_path(plan_id: str, task_id: str, suffix: str = "") -> str:
    base = f"/api/projects/{PROJECT}/plans/{plan_id}/tasks/{task_id}"
    return f"{base}{suffix}"


def _assert_no_token_leak(payload: object, token: str | None = None) -> None:
    dumped = json.dumps(payload)
    assert SECRET_TOKEN_MARKER not in dumped
    assert "claim_token_hash" not in dumped
    if token is not None:
        assert token not in dumped


# ---------------------------------------------------------------------------
# AC-PLAN-7 + nested route registration
# ---------------------------------------------------------------------------
def test_ac_plan_7_typed_operations_and_nested_routes_registered() -> None:
    """AC-PLAN-7: MCP tools and nested HTTP routes are registered (FR43-FR48)."""
    app = build_http_app()
    paths = {getattr(route, "path", None) for route in app.routes}
    assert "/api/projects/{project}/plans" in paths
    assert "/api/projects/{project}/plans/with-tasks" in paths
    assert "/api/projects/{project}/plans/{plan_id}" in paths
    assert "/api/projects/{project}/ready-tasks" in paths
    assert "/api/projects/{project}/plans/{plan_id}/ready-tasks" in paths
    for path in NESTED_TASK_PATHS:
        assert path in paths


# ---------------------------------------------------------------------------
# create_plan_with_tasks: unknown-field errors name the offending field(s)
# ---------------------------------------------------------------------------
async def test_create_plan_with_tasks_docstring_documents_payload_shape() -> None:
    """The tool's own registered description documents tasks/dependencies shape.

    An agent introspecting this tool (not reading docs/mcp-reference.md)
    should see enough to build a correct payload without guessing a sibling
    tool's field names.
    """
    tools = {tool.name: tool for tool in await mcp.list_tools()}
    description = tools["create_plan_with_tasks"].description or ""
    for expected in ("local_task_id", "title", "objective", "task_local_id", "depends_on_local_id"):
        assert expected in description
    # Explicitly warns against reusing add_task_dependency's field names.
    assert "add_task_dependency" in description


async def test_create_plan_with_tasks_dependency_typo_names_offending_fields() -> None:
    """Guessing add_task_dependency's field names in `dependencies` is named, not opaque."""
    await _seed_project()
    with pytest.raises(ToolError) as excinfo:
        await _call(
            "create_plan_with_tasks",
            {
                "project": PROJECT,
                "title": "Two-task plan",
                "goal": "Ship both",
                "tasks": [
                    {"local_task_id": "t1", "title": "First", "objective": "Do first"},
                    {"local_task_id": "t2", "title": "Second", "objective": "Do second"},
                ],
                # Real-world mistake: reusing add_task_dependency's field names
                # (task_id/depends_on_task_id) instead of create_plan_with_tasks's
                # own (task_local_id/depends_on_local_id).
                "dependencies": [{"task_id": "t2", "depends_on_task_id": "t1"}],
            },
        )
    message = str(excinfo.value)
    assert "task_id" in message
    assert "depends_on_task_id" in message
    assert "task_local_id" in message
    assert "depends_on_local_id" in message


async def test_create_plan_with_tasks_task_typo_names_offending_field() -> None:
    await _seed_project()
    with pytest.raises(ToolError) as excinfo:
        await _call(
            "create_plan_with_tasks",
            {
                "project": PROJECT,
                "title": "One-task plan",
                "goal": "Ship it",
                "tasks": [{"id": "t1", "title": "First", "objective": "Do first"}],
            },
        )
    message = str(excinfo.value)
    assert "'id'" in message
    assert "local_task_id" in message


async def test_audit_log_contains_tool_project_caller_outcome() -> None:
    """Every MCP/HTTP planning call emits structured audit fields (NFR6)."""
    await _seed_project()
    seen: list[dict[str, object]] = []

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
                **fields,
            }
        )

    with (
        patch("pcs.mcp.planning_tools.caller", return_value="mcp-agent"),
        patch("pcs.mcp.planning_tools.log_tool_call", spy),
        patch("pcs.web_api.planning_routes.log_tool_call", spy),
    ):
        created = await _call(
            "create_plan", {"project": PROJECT, "title": "Audited", "goal": "Keep secrets out"}
        )
        client = _client()
        listed = _http(client, "GET", f"/api/projects/{PROJECT}/plans")
    assert listed.status_code == 200
    dumped = json.dumps(seen)
    assert "claim_token" not in dumped
    assert any(item["tool"] == "create_plan" and item["outcome"] == "ok" for item in seen)
    assert any(item["tool"] == "list_plans" and item["outcome"] == "ok" for item in seen)
    assert all(item["project"] == PROJECT for item in seen)
    assert all(item["caller"] for item in seen)
    assert created["title"] == "Audited"
    names = {item["tool"] for item in seen}
    assert names <= set(PLANNING_TOOLS) | {"list_plans", "create_plan"}


async def test_update_plan_empty_patch_returns_400() -> None:
    """update_plan updates title/goal; empty patch is 400."""
    await _seed_project()
    created = await _call("create_plan", {"project": PROJECT, "title": "Original", "goal": "Goal"})
    plan_id = created["id"]
    updated = await _call(
        "update_plan",
        {"project": PROJECT, "plan_id": plan_id, "title": "Renamed", "goal": "New goal"},
    )
    assert updated["title"] == "Renamed"
    assert updated["goal"] == "New goal"
    with pytest.raises(ToolError, match="empty mutation"):
        await _call("update_plan", {"project": PROJECT, "plan_id": plan_id})
    client = _client()
    empty = _http(client, "PATCH", f"/api/projects/{PROJECT}/plans/{plan_id}", json_body={})
    assert empty.status_code == 400
    assert EMPTY_MUTATION in empty.json()["error"]
    patched = _http(
        client,
        "PATCH",
        f"/api/projects/{PROJECT}/plans/{plan_id}",
        json_body={"title": "HTTP title"},
    )
    assert patched.status_code == 200
    assert patched.json()["title"] == "HTTP title"


async def test_archive_plan_revokes_active_leases() -> None:
    """archive_plan transitions to archived and revokes active leases."""
    ids = await _seed_active_plan(
        extra_tasks=[
            TaskSpec(local_task_id="t1", title="One", objective="Obj 1"),
            TaskSpec(local_task_id="t2", title="Two", objective="Obj 2"),
        ],
        dependencies=[],
    )
    client = _client()
    claim = _http(
        client,
        "POST",
        _task_path(ids["plan_id"], ids["t1"], "/claim"),
        json_body={"claimed_by": "worker", "lease_seconds": 1800},
    )
    assert claim.status_code == 200
    token = cast(str, claim.json()["claim_token"])
    archived = await _call("archive_plan", {"project": PROJECT, "plan_id": ids["plan_id"]})
    assert archived["status"] == "archived"
    tasks = {task["local_task_id"]: task for task in archived["tasks"]}
    assert tasks["t1"]["status"] == "cancelled"
    assert tasks["t1"]["claimed_by"] is None
    assert tasks["t1"]["lease_expires_at"] is None
    _assert_no_token_leak(archived, token)
    http_archived = _http(client, "GET", f"/api/projects/{PROJECT}/plans/{ids['plan_id']}")
    assert http_archived.status_code == 200
    assert http_archived.json()["status"] == "archived"


def test_all_task_http_routes_are_nested_under_plan() -> None:
    """All task-level HTTP routes use nested /plans/{plan_id}/tasks/{task_id}/..."""
    app = build_http_app()
    paths = {getattr(route, "path", None) for route in app.routes}
    task_paths = {path for path in paths if path and "/tasks/{task_id}" in path}
    assert task_paths
    assert task_paths <= set(NESTED_TASK_PATHS)
    assert all("/plans/{plan_id}/tasks/{task_id}" in path for path in task_paths)


async def test_mismatched_plan_id_returns_404_task_not_found() -> None:
    """Nested URL with a task that does not belong to plan_id returns 404."""
    first = await _seed_active_plan()
    second = await _seed_active_plan(
        extra_tasks=[TaskSpec(local_task_id="x1", title="Other", objective="Obj")],
        dependencies=[],
    )
    client = _client()
    mismatch = _http(
        client,
        "POST",
        _task_path(first["plan_id"], second["x1"], "/claim"),
        json_body={"claimed_by": "agent", "lease_seconds": 1800},
    )
    assert mismatch.status_code == 404
    assert "No task" in mismatch.json()["error"]
    missing = _http(
        client,
        "GET",
        _task_path(first["plan_id"], "00000000-0000-0000-0000-000000000000", "/history"),
    )
    assert missing.status_code == 404


async def test_claim_token_returned_once_and_redacted_on_reads() -> None:
    """claim_task returns the raw token once; later reads omit token and hash."""
    ids = await _seed_active_plan()
    claimed = await _call(
        "claim_task",
        {
            "project": PROJECT,
            "plan_id": ids["plan_id"],
            "task_id": ids["t1"],
            "claimed_by": "worker",
            "lease_seconds": 1800,
        },
    )
    token = claimed["claim_token"]
    assert token
    assert claimed["task"]["claimed_by"] == "worker"
    assert SECRET_TOKEN_MARKER not in json.dumps(claimed["task"])
    client = _client()
    plan = _http(client, "GET", f"/api/projects/{PROJECT}/plans/{ids['plan_id']}")
    ready = _http(client, "GET", f"/api/projects/{PROJECT}/ready-tasks")
    scoped = _http(client, "GET", f"/api/projects/{PROJECT}/plans/{ids['plan_id']}/ready-tasks")
    history = _http(client, "GET", _task_path(ids["plan_id"], ids["t1"], "/history"))
    listed = await _call("list_plans", {"project": PROJECT})
    fetched = await _call("get_plan", {"project": PROJECT, "plan_id": ids["plan_id"]})
    events = await _call(
        "get_task_history",
        {"project": PROJECT, "plan_id": ids["plan_id"], "task_id": ids["t1"]},
    )
    for payload in (
        plan.json(),
        ready.json(),
        scoped.json(),
        history.json(),
        listed,
        fetched,
        events,
    ):
        _assert_no_token_leak(payload, token)


async def test_claim_reclaims_expired_in_review_task() -> None:
    """Expired in_review (lease_expires_at <= now) is reclaimed to claimed."""
    ids = await _seed_active_plan()
    client = _client()
    first = _http(
        client,
        "POST",
        _task_path(ids["plan_id"], ids["t1"], "/claim"),
        json_body={"claimed_by": "author", "lease_seconds": 1800},
    )
    token = first.json()["claim_token"]
    in_progress = _http(
        client,
        "POST",
        _task_path(ids["plan_id"], ids["t1"], "/status"),
        json_body={"status": TASK_STATUS_IN_PROGRESS, "claim_token": token},
    )
    assert in_progress.status_code == 200
    review = _http(
        client,
        "POST",
        _task_path(ids["plan_id"], ids["t1"], "/status"),
        json_body={"status": TASK_STATUS_IN_REVIEW, "claim_token": token},
    )
    assert review.status_code == 200
    async with session_scope() as session:
        await session.execute(
            text(
                "UPDATE plan_tasks SET lease_expires_at = now() - interval '1 second' "
                "WHERE id = :tid"
            ),
            {"tid": ids["t1"]},
        )
    reclaimed = _http(
        client,
        "POST",
        _task_path(ids["plan_id"], ids["t1"], "/claim"),
        json_body={"claimed_by": "reviewer", "lease_seconds": 1800},
    )
    assert reclaimed.status_code == 200
    assert reclaimed.json()["claim_token"] != token
    assert reclaimed.json()["task"]["status"] == TASK_STATUS_CLAIMED
    assert reclaimed.json()["task"]["claimed_by"] == "reviewer"
    stale = _http(
        client,
        "POST",
        _task_path(ids["plan_id"], ids["t1"], "/heartbeat"),
        json_body={"claim_token": token, "lease_seconds": 1800},
    )
    assert stale.status_code == 409


async def test_unexpired_lease_claim_returns_409() -> None:
    """Claiming a task with an active unexpired lease, including in_review, is 409."""
    ids = await _seed_active_plan()
    client = _client()
    path = _task_path(ids["plan_id"], ids["t1"], "/claim")
    first = _http(client, "POST", path, json_body={"claimed_by": "one", "lease_seconds": 1800})
    assert first.status_code == 200
    conflict = _http(client, "POST", path, json_body={"claimed_by": "two", "lease_seconds": 1800})
    assert conflict.status_code == 409
    token = first.json()["claim_token"]
    _http(
        client,
        "POST",
        _task_path(ids["plan_id"], ids["t1"], "/status"),
        json_body={"status": TASK_STATUS_IN_PROGRESS, "claim_token": token},
    )
    _http(
        client,
        "POST",
        _task_path(ids["plan_id"], ids["t1"], "/status"),
        json_body={"status": TASK_STATUS_IN_REVIEW, "claim_token": token},
    )
    review_conflict = _http(
        client, "POST", path, json_body={"claimed_by": "reviewer", "lease_seconds": 1800}
    )
    assert review_conflict.status_code == 409


async def test_lease_expires_at_equals_now_is_expired() -> None:
    """lease_expires_at == now() is reclaimable; old token presentation is 409."""
    ids = await _seed_active_plan()
    client = _client()
    claimed = _http(
        client,
        "POST",
        _task_path(ids["plan_id"], ids["t1"], "/claim"),
        json_body={"claimed_by": "worker-1", "lease_seconds": 1800},
    )
    token = claimed.json()["claim_token"]
    async with session_scope() as session:
        await session.execute(
            text("UPDATE plan_tasks SET lease_expires_at = clock_timestamp() WHERE id = :tid"),
            {"tid": ids["t1"]},
        )
    heartbeat = _http(
        client,
        "POST",
        _task_path(ids["plan_id"], ids["t1"], "/heartbeat"),
        json_body={"claim_token": token, "lease_seconds": 1800},
    )
    assert heartbeat.status_code == 409
    reclaimed = _http(
        client,
        "POST",
        _task_path(ids["plan_id"], ids["t1"], "/claim"),
        json_body={"claimed_by": "worker-2", "lease_seconds": 1800},
    )
    assert reclaimed.status_code == 200
    assert reclaimed.json()["task"]["claimed_by"] == "worker-2"


async def test_heartbeat_preserves_claimed_status() -> None:
    """Heartbeat on a claimed task extends the lease and keeps status claimed."""
    ids = await _seed_active_plan()
    claimed = await _call(
        "claim_task",
        {
            "project": PROJECT,
            "plan_id": ids["plan_id"],
            "task_id": ids["t1"],
            "claimed_by": "worker",
            "lease_seconds": 60,
        },
    )
    token = claimed["claim_token"]
    initial_expiry = claimed["task"]["lease_expires_at"]
    heartbeat = await _call(
        "heartbeat_task",
        {
            "project": PROJECT,
            "plan_id": ids["plan_id"],
            "task_id": ids["t1"],
            "claim_token": token,
            "lease_seconds": 300,
        },
    )
    assert heartbeat["status"] == TASK_STATUS_CLAIMED
    assert heartbeat["lease_expires_at"] > initial_expiry
    client = _client()
    http_hb = _http(
        client,
        "POST",
        _task_path(ids["plan_id"], ids["t1"], "/heartbeat"),
        json_body={"claim_token": token, "lease_seconds": 600},
    )
    assert http_hb.status_code == 200
    assert http_hb.json()["status"] == TASK_STATUS_CLAIMED


async def test_status_or_complete_without_token_returns_409() -> None:
    """Active-lease status mutation or completion without a token is 409."""
    ids = await _seed_active_plan()
    client = _client()
    claim = _http(
        client,
        "POST",
        _task_path(ids["plan_id"], ids["t1"], "/claim"),
        json_body={"claimed_by": "worker", "lease_seconds": 1800},
    )
    assert claim.status_code == 200
    status = _http(
        client,
        "POST",
        _task_path(ids["plan_id"], ids["t1"], "/status"),
        json_body={"status": TASK_STATUS_IN_PROGRESS},
    )
    assert status.status_code == 409
    complete = _http(
        client,
        "POST",
        _task_path(ids["plan_id"], ids["t1"], "/complete"),
        json_body={},
    )
    assert complete.status_code == 409
    with pytest.raises(ToolError):
        await _call(
            "complete_task",
            {"project": PROJECT, "plan_id": ids["plan_id"], "task_id": ids["t1"]},
        )


async def test_stale_or_expired_token_returns_409() -> None:
    """Expired token on heartbeat/status/complete returns 409 / StaleClaimTokenError."""
    ids = await _seed_active_plan()
    client = _client()
    claim = _http(
        client,
        "POST",
        _task_path(ids["plan_id"], ids["t1"], "/claim"),
        json_body={"claimed_by": "worker", "lease_seconds": 1800},
    )
    token = claim.json()["claim_token"]
    async with session_scope() as session:
        await session.execute(
            text(
                "UPDATE plan_tasks SET lease_expires_at = now() - interval '1 second' "
                "WHERE id = :tid"
            ),
            {"tid": ids["t1"]},
        )
    heartbeat = _http(
        client,
        "POST",
        _task_path(ids["plan_id"], ids["t1"], "/heartbeat"),
        json_body={"claim_token": token, "lease_seconds": 1800},
    )
    status = _http(
        client,
        "POST",
        _task_path(ids["plan_id"], ids["t1"], "/status"),
        json_body={"status": TASK_STATUS_IN_PROGRESS, "claim_token": token},
    )
    complete = _http(
        client,
        "POST",
        _task_path(ids["plan_id"], ids["t1"], "/complete"),
        json_body={"claim_token": token},
    )
    assert heartbeat.status_code == 409
    assert status.status_code == 409
    assert complete.status_code == 409


async def test_mutation_on_completed_or_archived_plan_returns_409() -> None:
    """Mutations on completed or archived plans return 409 / PlanNotActiveError."""
    ids = await _seed_active_plan(dependencies=[])
    client = _client()
    for local_id in ("t1", "t2"):
        claim = _http(
            client,
            "POST",
            _task_path(ids["plan_id"], ids[local_id], "/claim"),
            json_body={"claimed_by": "worker", "lease_seconds": 1800},
        )
        token = claim.json()["claim_token"]
        done = _http(
            client,
            "POST",
            _task_path(ids["plan_id"], ids[local_id], "/complete"),
            json_body={"claim_token": token},
        )
        assert done.status_code == 200
    completed = _http(client, "POST", f"/api/projects/{PROJECT}/plans/{ids['plan_id']}/complete")
    assert completed.status_code == 200
    frozen = _http(
        client,
        "POST",
        f"/api/projects/{PROJECT}/plans/{ids['plan_id']}/tasks",
        json_body={"local_task_id": "t3", "title": "Late", "objective": "Too late"},
    )
    assert frozen.status_code == 409

    other = await _seed_active_plan(
        extra_tasks=[TaskSpec(local_task_id="a1", title="Archived", objective="Obj")],
        dependencies=[],
    )
    _http(client, "POST", f"/api/projects/{PROJECT}/plans/{other['plan_id']}/archive")
    archived_claim = _http(
        client,
        "POST",
        _task_path(other["plan_id"], other["a1"], "/claim"),
        json_body={"claimed_by": "worker", "lease_seconds": 1800},
    )
    assert archived_claim.status_code == 409


async def test_unknown_fields_malformed_json_and_empty_patch_return_400() -> None:
    """Unknown fields, malformed JSON, and empty patches are HTTP 400."""
    await _seed_project()
    client = _client()
    created = _http(
        client,
        "POST",
        f"/api/projects/{PROJECT}/plans",
        json_body={"title": "Plan", "goal": "Goal"},
    )
    plan_id = created.json()["id"]
    unknown = _http(
        client,
        "PATCH",
        f"/api/projects/{PROJECT}/plans/{plan_id}",
        json_body={"title": "x", "mystery": 1},
    )
    assert unknown.status_code == 400
    assert UNKNOWN_FIELDS in unknown.json()["error"]
    empty = _http(client, "PATCH", f"/api/projects/{PROJECT}/plans/{plan_id}", json_body={})
    assert empty.status_code == 400
    malformed = _http(
        client,
        "PATCH",
        f"/api/projects/{PROJECT}/plans/{plan_id}",
        content=b"{not-json",
    )
    assert malformed.status_code == 400
    missing = _http(
        client,
        "POST",
        "/api/projects/does-not-exist/plans",
        json_body={"title": "x", "goal": "y"},
    )
    assert missing.status_code == 404
    assert "available" in missing.json()


async def test_concurrent_claim_conflict_returns_409() -> None:
    """Two concurrent claims yield one winner and a clean 409/ToolError loser."""
    ids = await _seed_active_plan()

    async def _try_mcp(worker: str) -> str | None:
        try:
            result = await _call(
                "claim_task",
                {
                    "project": PROJECT,
                    "plan_id": ids["plan_id"],
                    "task_id": ids["t1"],
                    "claimed_by": worker,
                    "lease_seconds": 1800,
                },
            )
            return cast(str, result["claim_token"])
        except ToolError:
            return None

    mcp_results = await asyncio.gather(_try_mcp("worker-A"), _try_mcp("worker-B"))
    assert len([token for token in mcp_results if token is not None]) == 1
    assert len([token for token in mcp_results if token is None]) == 1

    other = await _seed_active_plan(
        extra_tasks=[TaskSpec(local_task_id="r1", title="Race", objective="Obj")],
        dependencies=[],
    )
    client = _client()
    path = _task_path(other["plan_id"], other["r1"], "/claim")

    async def _try_http(worker: str) -> int:
        response = await asyncio.to_thread(
            lambda: _http(
                client,
                "POST",
                path,
                json_body={"claimed_by": worker, "lease_seconds": 1800},
            )
        )
        return int(response.status_code)

    statuses = await asyncio.gather(_try_http("http-A"), _try_http("http-B"))
    assert sorted(statuses) == [200, 409]


async def test_get_task_history_covers_all_event_types() -> None:
    """get_task_history is chronological, token-safe, and covers all 10 event types."""
    await _seed_project()
    created = await _call(
        "create_plan_with_tasks",
        {
            "project": PROJECT,
            "title": "History plan",
            "goal": "Cover events",
            "tasks": [
                {"local_task_id": "t1", "title": "First", "objective": "Do first"},
                {"local_task_id": "t2", "title": "Second", "objective": "Do second"},
            ],
            "dependencies": [{"task_local_id": "t2", "depends_on_local_id": "t1"}],
        },
    )
    plan_id = created["id"]
    tasks = {task["local_task_id"]: task["id"] for task in created["tasks"]}
    t1 = tasks["t1"]
    t2 = tasks["t2"]
    await _call(
        "update_plan_task",
        {"project": PROJECT, "plan_id": plan_id, "task_id": t1, "title": "Updated first"},
    )
    await _call("activate_plan", {"project": PROJECT, "plan_id": plan_id})
    claim = await _call(
        "claim_task",
        {
            "project": PROJECT,
            "plan_id": plan_id,
            "task_id": t1,
            "claimed_by": "agent-1",
            "lease_seconds": 1800,
        },
    )
    token = claim["claim_token"]
    await _call(
        "heartbeat_task",
        {
            "project": PROJECT,
            "plan_id": plan_id,
            "task_id": t1,
            "claim_token": token,
            "lease_seconds": 1800,
        },
    )
    await _call(
        "release_task",
        {"project": PROJECT, "plan_id": plan_id, "task_id": t1, "claim_token": token},
    )
    await _call(
        "claim_task",
        {
            "project": PROJECT,
            "plan_id": plan_id,
            "task_id": t1,
            "claimed_by": "agent-1",
            "lease_seconds": 1800,
        },
    )
    async with session_scope() as session:
        await session.execute(
            text(
                "UPDATE plan_tasks SET lease_expires_at = now() - interval '1 second' "
                "WHERE id = :tid"
            ),
            {"tid": t1},
        )
    reclaimed = await _call(
        "claim_task",
        {
            "project": PROJECT,
            "plan_id": plan_id,
            "task_id": t1,
            "claimed_by": "agent-2",
            "lease_seconds": 1800,
        },
    )
    token2 = reclaimed["claim_token"]
    await _call(
        "set_task_status",
        {
            "project": PROJECT,
            "plan_id": plan_id,
            "task_id": t1,
            "status": TASK_STATUS_IN_PROGRESS,
            "claim_token": token2,
        },
    )
    await _call(
        "complete_task",
        {"project": PROJECT, "plan_id": plan_id, "task_id": t1, "claim_token": token2},
    )
    await _call(
        "set_task_status",
        {
            "project": PROJECT,
            "plan_id": plan_id,
            "task_id": t2,
            "status": "cancelled",
            "reason": "drop",
        },
    )
    history = await _call(
        "get_task_history",
        {"project": PROJECT, "plan_id": plan_id, "task_id": t1},
    )
    t2_history = await _call(
        "get_task_history",
        {"project": PROJECT, "plan_id": plan_id, "task_id": t2},
    )
    client = _client()
    http_history = _http(client, "GET", _task_path(plan_id, t1, "/history"))
    assert http_history.status_code == 200
    assert http_history.json() == history
    combined = [*history, *t2_history]
    types = {event["event_type"] for event in combined}
    assert types == set(TASK_EVENT_TYPES)
    assert {
        EVENT_CREATED,
        EVENT_UPDATED,
        EVENT_DEPENDENCY_ADDED,
        EVENT_CLAIMED,
        EVENT_HEARTBEAT,
        EVENT_RELEASED,
        EVENT_RECLAIMED,
        EVENT_STATUS_CHANGED,
        EVENT_COMPLETED,
        EVENT_CANCELLED,
    } <= types
    created_at = [event["created_at"] for event in history]
    assert created_at == sorted(created_at)
    for event in combined:
        assert set(event) >= {
            "id",
            "event_type",
            "actor",
            "old_status",
            "new_status",
            "payload",
            "created_at",
        }
        assert isinstance(event["payload"], dict)
    _assert_no_token_leak(combined, token)
    _assert_no_token_leak(combined, token2)


async def test_mcp_and_http_response_shapes_match() -> None:
    """MCP tools and HTTP routes return equivalent typed JSON shapes."""
    await _seed_project()
    mcp_plan = await _call(
        "create_plan_with_tasks",
        {
            "project": PROJECT,
            "title": "Parity",
            "goal": "Same shape",
            "tasks": [{"local_task_id": "t1", "title": "Only", "objective": "Obj"}],
        },
    )
    client = _client()
    http_plan = _http(
        client,
        "POST",
        f"/api/projects/{PROJECT}/plans/with-tasks",
        json_body={
            "title": "Parity HTTP",
            "goal": "Same shape",
            "tasks": [{"local_task_id": "t1", "title": "Only", "objective": "Obj"}],
        },
    )
    assert http_plan.status_code == 201
    assert set(mcp_plan) == set(http_plan.json())
    assert set(mcp_plan["tasks"][0]) == set(http_plan.json()["tasks"][0])
    await _call("activate_plan", {"project": PROJECT, "plan_id": mcp_plan["id"]})
    _http(
        client,
        "POST",
        f"/api/projects/{PROJECT}/plans/{http_plan.json()['id']}/activate",
    )
    mcp_ready = await _call("list_ready_tasks", {"project": PROJECT, "plan_id": mcp_plan["id"]})
    http_ready = _http(
        client,
        "GET",
        f"/api/projects/{PROJECT}/plans/{http_plan.json()['id']}/ready-tasks",
    )
    assert http_ready.status_code == 200
    assert set(mcp_ready[0]) == set(http_ready.json()[0])
    mcp_claim = await _call(
        "claim_task",
        {
            "project": PROJECT,
            "plan_id": mcp_plan["id"],
            "task_id": mcp_plan["tasks"][0]["id"],
            "claimed_by": "mcp-worker",
            "lease_seconds": 1800,
        },
    )
    http_claim = _http(
        client,
        "POST",
        _task_path(http_plan.json()["id"], http_plan.json()["tasks"][0]["id"], "/claim"),
        json_body={"claimed_by": "http-worker", "lease_seconds": 1800},
    )
    assert http_claim.status_code == 200
    assert set(mcp_claim) == set(http_claim.json()) == {"task", "claim_token"}
    mcp_history = await _call(
        "get_task_history",
        {
            "project": PROJECT,
            "plan_id": mcp_plan["id"],
            "task_id": mcp_plan["tasks"][0]["id"],
        },
    )
    http_history = _http(
        client,
        "GET",
        _task_path(mcp_plan["id"], mcp_plan["tasks"][0]["id"], "/history"),
    )
    assert http_history.json() == mcp_history
    tools = await mcp.list_tools()
    names = {tool.name for tool in tools}
    assert set(PLANNING_TOOLS) <= names
