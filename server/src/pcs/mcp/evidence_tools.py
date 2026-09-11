"""MCP tools for the evidence ledger and close gate (T12).

Thin wrappers: resolve caller → session_scope → ``pcs.requirements.evidence``
→ ``log_tool_call`` (NFR6). No SQL here.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from mcp.server.fastmcp import Context, FastMCP
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from pcs.mcp.support import caller, run_tool
from pcs.requirements import evidence

_SHA_PATTERN = r"^[0-9a-fA-F]{7,40}$"
_FINGERPRINT_PATTERN = r"^[0-9a-fA-F]{1,64}$"

EvidenceKind = Literal["test", "command", "review", "manual", "file"]
EvidenceResult = Literal["passed", "failed", "manual-pending"]
ViolationSeverity = Literal["blocking", "warning"]


def register_evidence_tools(mcp: FastMCP) -> None:
    """Attach evidence, violation, and close-gate tools."""

    @mcp.tool()
    async def record_requirement_evidence(
        criterion_id: str,
        kind: EvidenceKind,
        result: EvidenceResult,
        source_commit: Annotated[
            str,
            Field(min_length=7, max_length=40, pattern=_SHA_PATTERN),
        ],
        project: str | None = None,
        command_ref: Annotated[str | None, Field(max_length=200)] = None,
        test_ref: Annotated[str | None, Field(max_length=200)] = None,
        file_ref: Annotated[str | None, Field(max_length=240)] = None,
        worktree_fingerprint: Annotated[
            str | None, Field(max_length=64, pattern=_FINGERPRINT_PATTERN)
        ] = None,
        artifact_ref: Annotated[str | None, Field(max_length=500)] = None,
        ctx: Context[Any, Any] | None = None,
    ) -> dict[str, object]:
        """Append compact evidence. Does not change requirement status (D4, T12)."""

        async def op(session: AsyncSession) -> dict[str, object]:
            view = await evidence.record_evidence(
                session,
                project=project or "",
                criterion_id=criterion_id,
                kind=kind,
                result=result,
                source_commit=source_commit,
                author=caller(ctx),
                command_ref=command_ref,
                test_ref=test_ref,
                file_ref=file_ref,
                worktree_fingerprint=worktree_fingerprint,
                artifact_ref=artifact_ref,
            )
            return view.as_dict()

        return await run_tool("record_requirement_evidence", project, ctx, op)

    @mcp.tool()
    async def get_requirement_evidence(
        requirement_id: str,
        project: str | None = None,
        ctx: Context[Any, Any] | None = None,
    ) -> dict[str, object]:
        """Compact evidence, violations, and close-gate state for one requirement."""

        async def op(session: AsyncSession) -> dict[str, object]:
            return await evidence.get_requirement_evidence(
                session, project=project or "", requirement_id=requirement_id
            )

        return await run_tool("get_requirement_evidence", project, ctx, op)

    @mcp.tool()
    async def add_requirement_violation(
        invariant_id: str,
        summary: Annotated[str, Field(min_length=1, max_length=200)],
        project: str | None = None,
        severity: ViolationSeverity = "blocking",
        file_ref: Annotated[str | None, Field(max_length=240)] = None,
        line_no: Annotated[int | None, Field(ge=1)] = None,
        ctx: Context[Any, Any] | None = None,
    ) -> dict[str, object]:
        """Record a review violation against one invariant (T12)."""

        async def op(session: AsyncSession) -> dict[str, object]:
            view = await evidence.add_violation(
                session,
                project=project or "",
                invariant_id=invariant_id,
                summary=summary,
                severity=severity,
                author=caller(ctx),
                file_ref=file_ref,
                line_no=line_no,
            )
            return view.as_dict()

        return await run_tool("add_requirement_violation", project, ctx, op)

    @mcp.tool()
    async def resolve_requirement_violation(
        violation_id: str,
        project: str | None = None,
        ctx: Context[Any, Any] | None = None,
    ) -> dict[str, object]:
        """Resolve a violation without deleting history (T12)."""

        async def op(session: AsyncSession) -> dict[str, object]:
            view = await evidence.resolve_violation(
                session,
                project=project or "",
                violation_id=violation_id,
                author=caller(ctx),
            )
            return view.as_dict()

        return await run_tool("resolve_requirement_violation", project, ctx, op)

    @mcp.tool()
    async def evaluate_close_gate(
        requirement_id: str,
        project: str | None = None,
        ctx: Context[Any, Any] | None = None,
    ) -> dict[str, object]:
        """Deterministic close-gate evaluation. Does not change status (D4)."""

        async def op(session: AsyncSession) -> dict[str, object]:
            view = await evidence.evaluate_close_gate(
                session, project=project or "", requirement_id=requirement_id
            )
            return view.as_dict()

        return await run_tool("evaluate_close_gate", project, ctx, op)
