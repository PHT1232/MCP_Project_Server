"""T26 advisory AI plan draft generation - one test per acceptance item."""

from __future__ import annotations

import json
from contextlib import suppress
from typing import Any, cast
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy import func, select
from starlette.testclient import TestClient

from pcs.ai_settings import ProviderSettings, RuntimeAiSettings
from pcs.context import service as context_service
from pcs.db.base import session_scope
from pcs.mcp import build_http_app, mcp
from pcs.planning import generator
from pcs.planning import service as planning_service
from pcs.planning.models import (
    Plan,
    PlanTask,
    PlanTaskEvent,
    PlanTaskRequirement,
    TaskDependency,
)
from pcs.planning.types import DependencySpec, TaskSpec

pytestmark = pytest.mark.usefixtures("clean_db")
PROJECT = "ai-plan-draft"

_VALID_DRAFT_JSON = json.dumps(
    {
        "title": "Ship pricing",
        "goal": "Add unit pricing end to end",
        "tasks": [
            {
                "local_task_id": "t1",
                "title": "Add pricing helper",
                "objective": "Implement unit_price.",
                "acceptance_criteria": ["unit_price returns item.price * item.quantity"],
                "linked_files": ["shop/pricing.py"],
                "requirement_ids": [],
            },
            {
                "local_task_id": "t2",
                "title": "Wire pricing into cart total",
                "objective": "Use unit_price inside cart_total.",
                "acceptance_criteria": ["cart_total sums unit_price(item)"],
                "linked_files": ["shop/cart.py"],
                "requirement_ids": [],
            },
        ],
        "dependencies": [{"task_local_id": "t2", "depends_on_local_id": "t1"}],
        "notes": "Keep pricing pure.",
    }
)

_CONFIGURED_PROVIDER = ProviderSettings(
    backend="openai-compatible",
    base_url="https://api.example.com/v1",
    model="test-model",
    timeout_seconds=5.0,
    api_key="test-key",
    source="persisted",
)
_UNCONFIGURED_PROVIDER = ProviderSettings(
    backend="",
    base_url="",
    model="",
    timeout_seconds=5.0,
    api_key="",
    source="default",
)


async def _register_project(name: str = PROJECT) -> None:
    async with session_scope() as session:
        with suppress(context_service.DuplicateProjectError):
            await context_service.register_project(
                session, name=name, root_path=f"/repos/{name}", overview="T26 fixture repo."
            )


async def _seed_requirement(*, project: str = PROJECT, req_key: str = "R-1") -> str:
    await _register_project(project)
    async with session_scope() as session:
        entry = await context_service.add_entry(
            session, project=project, section="requirements", headline="Pricing", req_key=req_key
        )
        return entry.id


def _settings(configured: bool) -> RuntimeAiSettings:
    provider = _CONFIGURED_PROVIDER if configured else _UNCONFIGURED_PROVIDER
    return RuntimeAiSettings(
        embedding=_UNCONFIGURED_PROVIDER, summary=provider, reindex_required=False
    )


def _mock_settings(configured: bool = True) -> Any:
    return patch(
        "pcs.planning.generator.load_runtime_ai_settings",
        AsyncMock(return_value=_settings(configured)),
    )


def _mock_provider(response_text: str | Exception) -> Any:
    if isinstance(response_text, Exception):
        call = AsyncMock(side_effect=response_text)
    else:
        call = AsyncMock(return_value=response_text)
    return patch("pcs.planning.generator._call_provider", call)


async def _planning_row_counts() -> dict[str, int]:
    async with session_scope() as session:
        counts = {}
        for label, model in (
            ("plans", Plan),
            ("plan_tasks", PlanTask),
            ("task_dependencies", TaskDependency),
            ("plan_task_requirements", PlanTaskRequirement),
            ("plan_task_events", PlanTaskEvent),
        ):
            result = await session.execute(select(func.count()).select_from(model))
            counts[label] = int(result.scalar_one())
        return counts


def _client() -> TestClient:
    return TestClient(build_http_app())


def _http(client: TestClient, path: str, *, json_body: dict[str, object]) -> Any:
    return client.post(path, json=json_body, headers={"x-pcs-caller": "t26-test"})


async def _call(name: str, arguments: dict[str, object]) -> Any:
    with patch("pcs.mcp.planning_tools.caller", return_value="t26-test"):
        result = await mcp.call_tool(name, arguments)
    if isinstance(result, tuple) and len(result) >= 2 and isinstance(result[1], dict):
        payload = cast(dict[object, object], result[1])
        return {str(k): v for k, v in payload.items()}
    raise AssertionError(f"unexpected MCP result: {result!r}")


# ---------------------------------------------------------------------------
# AC-PLAN-9: T20 settings, strict schema, zero persistence
# ---------------------------------------------------------------------------
async def test_generate_plan_draft_uses_t20_settings_and_persists_zero_rows() -> None:
    await _register_project()
    before = await _planning_row_counts()
    with _mock_settings(True), _mock_provider(_VALID_DRAFT_JSON):
        async with session_scope() as session:
            result = await generator.generate_plan_draft(
                session, project=PROJECT, goal="Add unit pricing"
            )
    after = await _planning_row_counts()
    assert before == after
    assert result.ok is True
    assert result.provider == "openai-compatible"
    assert result.model == "test-model"
    assert result.draft is not None
    assert result.draft.title == "Ship pricing"
    assert [t.local_task_id for t in result.draft.tasks] == ["t1", "t2"]
    assert result.draft.dependencies[0].task_local_id == "t2"


async def test_database_assertion_zero_rows_across_every_scenario() -> None:
    """AC-PLAN-9: no planning table gains a row regardless of outcome."""
    await _register_project()
    scenarios: list[tuple[bool, str | Exception]] = [
        (True, _VALID_DRAFT_JSON),
        (True, "not json"),
        (True, httpx.ConnectError("boom")),
        (False, _VALID_DRAFT_JSON),
    ]
    before = await _planning_row_counts()
    for configured, provider_response in scenarios:
        with _mock_settings(configured), _mock_provider(provider_response):
            async with session_scope() as session:
                await generator.generate_plan_draft(session, project=PROJECT, goal="Add pricing")
    after = await _planning_row_counts()
    assert (
        before
        == after
        == {
            "plans": 0,
            "plan_tasks": 0,
            "task_dependencies": 0,
            "plan_task_requirements": 0,
            "plan_task_events": 0,
        }
    )


# ---------------------------------------------------------------------------
# AC-PLAN-10 (generation side): advisory only until explicit approval
# ---------------------------------------------------------------------------
async def test_draft_is_advisory_only_persists_via_explicit_create_plan_with_tasks() -> None:
    await _register_project()
    with _mock_settings(True), _mock_provider(_VALID_DRAFT_JSON):
        async with session_scope() as session:
            result = await generator.generate_plan_draft(
                session, project=PROJECT, goal="Add unit pricing"
            )
    assert result.ok is True
    assert result.draft is not None
    before = await _planning_row_counts()
    assert before["plans"] == 0

    # The exact "review, then explicitly approve" seam T28's UI will drive:
    # convert the advisory draft to real specs and call create_plan_with_tasks.
    async with session_scope() as session:
        plan = await planning_service.create_plan_with_tasks(
            session,
            project=PROJECT,
            title=result.draft.title,
            goal=result.draft.goal,
            tasks=[
                TaskSpec(
                    local_task_id=t.local_task_id,
                    title=t.title,
                    objective=t.objective,
                    acceptance_criteria=list(t.acceptance_criteria),
                    linked_files=list(t.linked_files),
                    requirement_ids=list(t.requirement_ids),
                )
                for t in result.draft.tasks
            ],
            dependencies=[
                DependencySpec(
                    task_local_id=d.task_local_id, depends_on_local_id=d.depends_on_local_id
                )
                for d in result.draft.dependencies
            ],
        )
    after = await _planning_row_counts()
    assert after["plans"] == 1
    assert after["plan_tasks"] == 2
    assert plan.title == "Ship pricing"


# ---------------------------------------------------------------------------
# Invalid proposals are rejected, never partially accepted
# ---------------------------------------------------------------------------
async def test_dependency_cycle_rejected() -> None:
    await _register_project()
    cyclic = json.dumps(
        {
            "title": "Cyclic",
            "goal": "g",
            "tasks": [
                {"local_task_id": "a", "title": "A", "objective": "do a"},
                {"local_task_id": "b", "title": "B", "objective": "do b"},
            ],
            "dependencies": [
                {"task_local_id": "a", "depends_on_local_id": "b"},
                {"task_local_id": "b", "depends_on_local_id": "a"},
            ],
        }
    )
    with _mock_settings(True), _mock_provider(cyclic):
        async with session_scope() as session:
            result = await generator.generate_plan_draft(session, project=PROJECT, goal="g")
    assert result.ok is False
    assert result.draft is None
    assert result.warning and "invalid draft" in result.warning.lower()


async def test_cross_project_or_non_requirement_ids_rejected() -> None:
    other_req_id = await _seed_requirement(project="other-project", req_key="R-OTHER")
    await _register_project()
    draft = json.loads(_VALID_DRAFT_JSON)
    draft["tasks"][0]["requirement_ids"] = [other_req_id]
    with _mock_settings(True), _mock_provider(json.dumps(draft)):
        async with session_scope() as session:
            result = await generator.generate_plan_draft(session, project=PROJECT, goal="g")
    assert result.ok is False
    assert result.draft is None
    assert result.warning and "unknown requirement id" in result.warning.lower()


async def test_malformed_json_response_rejected() -> None:
    await _register_project()
    with _mock_settings(True), _mock_provider("not json at all"):
        async with session_scope() as session:
            result = await generator.generate_plan_draft(session, project=PROJECT, goal="g")
    assert result.ok is False
    assert result.draft is None
    assert result.warning and "invalid draft" in result.warning.lower()


async def test_unknown_top_level_field_rejected() -> None:
    await _register_project()
    draft = json.loads(_VALID_DRAFT_JSON)
    draft["unexpected"] = "nope"
    with _mock_settings(True), _mock_provider(json.dumps(draft)):
        async with session_scope() as session:
            result = await generator.generate_plan_draft(session, project=PROJECT, goal="g")
    assert result.ok is False
    assert result.warning and "unknown fields" in result.warning.lower()


# ---------------------------------------------------------------------------
# Provider unconfigured / unreachable -> clear warning, never a crash
# ---------------------------------------------------------------------------
async def test_unconfigured_provider_returns_clear_warning() -> None:
    await _register_project()
    with _mock_settings(False):
        async with session_scope() as session:
            result = await generator.generate_plan_draft(session, project=PROJECT, goal="g")
    assert result.ok is False
    assert result.draft is None
    assert result.warning and "no summary ai provider" in result.warning.lower()


async def test_unreachable_provider_returns_clear_warning_without_crashing() -> None:
    await _register_project()
    with _mock_settings(True), _mock_provider(httpx.ConnectError("boom")):
        async with session_scope() as session:
            result = await generator.generate_plan_draft(session, project=PROJECT, goal="g")
    assert result.ok is False
    assert result.draft is None
    assert result.warning and "failed" in result.warning.lower()


# ---------------------------------------------------------------------------
# Bounds validation
# ---------------------------------------------------------------------------
async def test_empty_goal_and_out_of_range_max_tasks_rejected() -> None:
    await _register_project()
    async with session_scope() as session:
        with pytest.raises(ValueError, match="goal"):
            await generator.generate_plan_draft(session, project=PROJECT, goal="   ")
    async with session_scope() as session:
        with pytest.raises(ValueError, match="max_tasks"):
            await generator.generate_plan_draft(session, project=PROJECT, goal="g", max_tasks=999)


# ---------------------------------------------------------------------------
# MCP + HTTP dispatch
# ---------------------------------------------------------------------------
async def test_mcp_and_http_generate_plan_draft_agree() -> None:
    await _register_project()
    with _mock_settings(True), _mock_provider(_VALID_DRAFT_JSON):
        mcp_result = await _call(
            "generate_plan_draft", {"project": PROJECT, "goal": "Add unit pricing"}
        )
        client = _client()
        http_result = _http(
            client,
            f"/api/projects/{PROJECT}/plans/generate-draft",
            json_body={"goal": "Add unit pricing"},
        )
    assert http_result.status_code == 200
    http_payload = http_result.json()
    assert mcp_result["ok"] is True
    assert http_payload["ok"] is True
    assert mcp_result["draft"]["title"] == http_payload["draft"]["title"]


async def test_generate_plan_draft_registered_as_mcp_tool_and_http_route() -> None:
    tools = await mcp.list_tools()
    assert any(t.name == "generate_plan_draft" for t in tools)
    app = build_http_app()
    paths = {getattr(route, "path", None) for route in app.routes}
    assert "/api/projects/{project}/plans/generate-draft" in paths


async def test_http_unknown_field_and_bad_max_tasks_return_400() -> None:
    await _register_project()
    client = _client()
    unknown = _http(
        client,
        f"/api/projects/{PROJECT}/plans/generate-draft",
        json_body={"goal": "g", "nope": 1},
    )
    assert unknown.status_code == 400
    bad_bounds = _http(
        client,
        f"/api/projects/{PROJECT}/plans/generate-draft",
        json_body={"goal": "g", "max_tasks": 999},
    )
    assert bad_bounds.status_code == 400
