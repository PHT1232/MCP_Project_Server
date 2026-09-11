"""MCP registration for deterministic requirement compliance reads (T13)."""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.fastmcp import Context, FastMCP
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from pcs.mcp.support import run_tool
from pcs.requirements import compliance


def register_compliance_tools(mcp: FastMCP) -> None:
    """Attach the T13 compliance review tool."""

    @mcp.tool()
    async def review_requirement_compliance(
        requirement_ids: Annotated[list[str], Field(min_length=1)],
        project: str | None = None,
        ctx: Context[Any, Any] | None = None,
    ) -> dict[str, object]:
        """Review configured AC evidence, freshness, review, and blockers (T13)."""

        async def op(session: AsyncSession) -> dict[str, object]:
            result = await compliance.review_requirement_compliance(
                session, project=project or "", requirement_ids=requirement_ids
            )
            return result.as_dict()

        return await run_tool("review_requirement_compliance", project, ctx, op)
