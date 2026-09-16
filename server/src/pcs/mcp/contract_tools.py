"""MCP tools for requirement-contract retrieval (T11) and authoring (T14).

Thin wrappers: resolve caller → session_scope → ``pcs.requirements.briefing``
or ``pcs.requirements.contracts`` → ``log_tool_call`` (NFR6). No SQL here.
Mutations never duplicate service validation (INV-AUTHOR-1).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated, Any, Literal

from mcp.server.fastmcp import Context, FastMCP
from pydantic import Field
from pydantic.experimental.missing_sentinel import MISSING
from sqlalchemy.ext.asyncio import AsyncSession

from pcs.context import service as context_service
from pcs.context.types import ContractNotFoundError, ValidationError
from pcs.db.base import session_scope
from pcs.logging import estimate_response_tokens, log_tool_call
from pcs.mcp.support import caller
from pcs.requirements import briefing, contracts

InvariantKind = Literal[
    "behavior",
    "architecture",
    "data-boundary",
    "forbidden-path",
    "integration",
    "manual",
]
RiskLevel = Literal["low", "medium", "high"]
EvidenceKind = Literal["test", "command", "review", "manual", "file"]
IndependentReview = Literal["not-required", "required"]

EMPTY_MUTATION = "empty mutation; omit fields to keep them, or supply at least one change"
EXPLICIT_NULL = "explicit null is rejected; omit the field to leave it unchanged"
UNKNOWN_FIELDS = "request contains unknown fields"


def _patch_value(value: object) -> object | None:
    """Map omitted MCP fields to service omission and reject explicit null in-tool."""
    if value is MISSING:
        return None
    if value is None:
        raise ValidationError(EXPLICIT_NULL)
    return value


def _patch_str(value: object, *, field: str) -> str | None:
    value = _patch_value(value)
    if value is not None and not isinstance(value, str):
        raise ValidationError(f"{field} must be a string")
    return value


def _patch_int(value: object, *, field: str) -> int | None:
    value = _patch_value(value)
    if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
        raise ValidationError(f"{field} must be an integer")
    return value


def _patch_bool(value: object, *, field: str) -> bool | None:
    value = _patch_value(value)
    if value is not None and not isinstance(value, bool):
        raise ValidationError(f"{field} must be a boolean")
    return value


def audit_outcome(exc: BaseException) -> str:
    """Safe audit outcome: category only, never caller payload (INV-AUTHOR-7)."""
    if isinstance(exc, context_service.ProjectNotFoundError):
        return "error: project-not-found"
    if isinstance(exc, (context_service.EntryNotFoundError, ContractNotFoundError)):
        return "error: not-found"
    if isinstance(exc, (ValidationError, ValueError)):
        return "error: validation"
    return "error: failed"


def _require_update(*values: object) -> None:
    """Reject a merge-update that supplied no fields (INV-AUTHOR-4)."""
    if all(value is None for value in values):
        raise ValidationError(EMPTY_MUTATION)


async def _run_logged[T](
    tool: str,
    project: str | None,
    who: str,
    op: Callable[[AsyncSession], Awaitable[T]],
) -> T:
    """Session helper whose audit errors are categories only (INV-AUTHOR-7)."""
    try:
        async with session_scope() as session:
            result = await op(session)
    except Exception as exc:
        log_tool_call(tool=tool, project=project, caller=who, outcome=audit_outcome(exc))
        raise
    log_tool_call(
        tool=tool,
        project=project,
        caller=who,
        outcome="ok",
        response_tokens=estimate_response_tokens(result),
    )
    return result


def register_contract_tools(mcp: FastMCP) -> None:
    """Attach contract read tools (T11) and authoring mutations (T14)."""

    @mcp.tool()
    async def get_requirement_contract(
        requirement_id: str,
        project: str | None = None,
        include: str = "both",
        ctx: Context[Any, Any] | None = None,
    ) -> dict[str, object]:
        """Verbatim invariant/criterion drill-down for one requirement (T11).

        Args:
            requirement_id: Store entry id of the requirement.
            project: Exact project name or id (D3).
            include: ``invariants``, ``criteria``, or ``both`` (default).
        """

        async def op(session: AsyncSession) -> dict[str, object]:
            return await briefing.get_requirement_contract(
                session,
                project=project or "",
                requirement_id=requirement_id,
                include=include,
            )

        return await _run_logged("get_requirement_contract", project, caller(ctx), op)

    @mcp.tool()
    async def get_task_contract(
        task: str,
        project: str | None = None,
        requirement_ids: list[str] | None = None,
        max_tokens: Annotated[
            int,
            Field(ge=briefing.CONTRACT_TOKEN_MIN, le=briefing.CONTRACT_TOKEN_CAP),
        ] = 500,
        ctx: Context[Any, Any] | None = None,
    ) -> dict[str, object]:
        """Relevant active contract statements plus a compact close-gate (T11).

        Capped at 80-500 estimated tokens. Values below 80 are rejected so every
        accepted budget satisfies ``token_estimate <= token_budget``. T12
        evidence, if absent, is reported as ``review: not-configured``. Full
        statements stay on ``get_requirement_contract``.

        Args:
            task: Current task description used for relevance ranking.
            project: Exact project name or id (D3).
            requirement_ids: Optional explicit requirement entry ids (max 3 used).
            max_tokens: Compact budget, 80-500 (default 500).
        """

        async def op(session: AsyncSession) -> dict[str, object]:
            view = await briefing.get_task_contract(
                session,
                project=project or "",
                task=task,
                requirement_ids=requirement_ids,
                max_tokens=max_tokens,
            )
            return view.as_dict()

        return await _run_logged("get_task_contract", project, caller(ctx), op)

    @mcp.tool()
    async def create_requirement_invariant(
        requirement_id: str,
        statement: str,
        kind: InvariantKind,
        risk: RiskLevel,
        project: str | None = None,
        key: str | None = None,
        sort_order: int | None = None,
        ctx: Context[Any, Any] | None = None,
    ) -> dict[str, object]:
        """Create one invariant via ``contracts.create_invariant`` (T14)."""

        who = caller(ctx)

        async def op(session: AsyncSession) -> dict[str, object]:
            view = await contracts.create_invariant(
                session,
                project=project or "",
                requirement_id=requirement_id,
                statement=statement,
                kind=kind,
                risk=risk,
                key=key,
                sort_order=sort_order,
                author=who,
            )
            return view.as_dict()

        return await _run_logged("create_requirement_invariant", project, who, op)

    @mcp.tool()
    async def update_requirement_invariant(
        invariant_id: str,
        project: str | None = None,
        statement: object = MISSING,
        kind: object = MISSING,
        risk: object = MISSING,
        key: object = MISSING,
        sort_order: object = MISSING,
        ctx: Context[Any, Any] | None = None,
    ) -> dict[str, object]:
        """Merge-update one invariant; omitted fields stay (T14, INV-AUTHOR-4)."""

        who = caller(ctx)

        async def op(session: AsyncSession) -> dict[str, object]:
            values = (
                _patch_str(statement, field="statement"),
                _patch_str(kind, field="kind"),
                _patch_str(risk, field="risk"),
                _patch_str(key, field="key"),
                _patch_int(sort_order, field="sort_order"),
            )
            _require_update(*values)
            view = await contracts.update_invariant(
                session,
                project=project or "",
                invariant_id=invariant_id,
                statement=values[0],
                kind=values[1],
                risk=values[2],
                key=values[3],
                sort_order=values[4],
                author=who,
            )
            return view.as_dict()

        return await _run_logged("update_requirement_invariant", project, who, op)

    @mcp.tool()
    async def delete_requirement_invariant(
        invariant_id: str,
        project: str | None = None,
        ctx: Context[Any, Any] | None = None,
    ) -> dict[str, object]:
        """Soft-delete one invariant and cascade its open criteria (T14)."""

        who = caller(ctx)

        async def op(session: AsyncSession) -> dict[str, object]:
            view = await contracts.delete_invariant(
                session,
                project=project or "",
                invariant_id=invariant_id,
                author=who,
            )
            return view.as_dict()

        return await _run_logged("delete_requirement_invariant", project, who, op)

    @mcp.tool()
    async def create_acceptance_criterion(
        invariant_id: str,
        statement: str,
        evidence_kind: EvidenceKind,
        project: str | None = None,
        key: str | None = None,
        required: bool = True,
        independent_review: IndependentReview = "not-required",
        sort_order: int | None = None,
        ctx: Context[Any, Any] | None = None,
    ) -> dict[str, object]:
        """Create one acceptance criterion via ``contracts.create_criterion`` (T14)."""

        who = caller(ctx)

        async def op(session: AsyncSession) -> dict[str, object]:
            view = await contracts.create_criterion(
                session,
                project=project or "",
                invariant_id=invariant_id,
                statement=statement,
                evidence_kind=evidence_kind,
                key=key,
                required=required,
                independent_review=independent_review,
                sort_order=sort_order,
                author=who,
            )
            return view.as_dict()

        return await _run_logged("create_acceptance_criterion", project, who, op)

    @mcp.tool()
    async def update_acceptance_criterion(
        criterion_id: str,
        project: str | None = None,
        statement: object = MISSING,
        evidence_kind: object = MISSING,
        required: object = MISSING,
        independent_review: object = MISSING,
        key: object = MISSING,
        sort_order: object = MISSING,
        ctx: Context[Any, Any] | None = None,
    ) -> dict[str, object]:
        """Merge-update one criterion; omitted fields stay (T14, INV-AUTHOR-4)."""

        who = caller(ctx)

        async def op(session: AsyncSession) -> dict[str, object]:
            values = (
                _patch_str(statement, field="statement"),
                _patch_str(evidence_kind, field="evidence_kind"),
                _patch_bool(required, field="required"),
                _patch_str(independent_review, field="independent_review"),
                _patch_str(key, field="key"),
                _patch_int(sort_order, field="sort_order"),
            )
            _require_update(*values)
            view = await contracts.update_criterion(
                session,
                project=project or "",
                criterion_id=criterion_id,
                statement=values[0],
                evidence_kind=values[1],
                required=values[2],
                independent_review=values[3],
                key=values[4],
                sort_order=values[5],
                author=who,
            )
            return view.as_dict()

        return await _run_logged("update_acceptance_criterion", project, who, op)

    @mcp.tool()
    async def delete_acceptance_criterion(
        criterion_id: str,
        project: str | None = None,
        ctx: Context[Any, Any] | None = None,
    ) -> dict[str, object]:
        """Soft-delete one criterion; revision history is kept (T14)."""

        who = caller(ctx)

        async def op(session: AsyncSession) -> dict[str, object]:
            view = await contracts.delete_criterion(
                session,
                project=project or "",
                criterion_id=criterion_id,
                author=who,
            )
            return view.as_dict()

        return await _run_logged("delete_acceptance_criterion", project, who, op)
