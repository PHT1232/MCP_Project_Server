"""MCP tools for the code index: status, reindex, hybrid search, RAG (FR22, FR26, FR27)."""

from __future__ import annotations

from typing import Any, cast

from mcp.server.fastmcp import Context, FastMCP
from sqlalchemy.ext.asyncio import AsyncSession

from pcs.index import retrieval, service
from pcs.index.search import SearchScopeName
from pcs.mcp.support import caller, run_tool

_SCOPES: frozenset[str] = frozenset({"project", "subtree", "files", "focus"})


def register_index_tools(mcp: FastMCP) -> None:
    """Attach ``get_index_status``, ``reindex``, ``search_code``, ``retrieve_context``,
    and ``prepare_task``."""

    @mcp.tool()
    async def get_index_status(
        project: str | None = None,
        ctx: Context[Any, Any] | None = None,
    ) -> dict[str, object]:
        """Index timestamps, file/chunk counts, and skipped-with-reason (FR26)."""

        async def op(session: AsyncSession) -> dict[str, object]:
            view = await service.get_index_status(session, project=project or "")
            return view.as_dict()

        return await run_tool("get_index_status", project, ctx, op)

    @mcp.tool()
    async def reindex(
        project: str | None = None,
        incremental: bool = True,
        ctx: Context[Any, Any] | None = None,
    ) -> dict[str, object]:
        """Rebuild the code index; incremental updates changed files only (FR24, FR27)."""

        async def op(session: AsyncSession) -> dict[str, object]:
            view = await service.reindex(session, project=project or "", incremental=incremental)
            return view.as_dict()

        return await run_tool("reindex", project, ctx, op)

    @mcp.tool()
    async def search_code(
        query: str,
        project: str | None = None,
        scope: str = "project",
        subtree: str | None = None,
        files: list[str] | None = None,
        globs: list[str] | None = None,
        limit: int = 20,
        ctx: Context[Any, Any] | None = None,
    ) -> dict[str, object]:
        """Keyword/structural search (FR20, FR21, FR29). Semantic ranking is T04.

        Args:
            query: Exact/fuzzy text, symbol-ish name, or a path glob.
            project: Exact project name or id (D3).
            scope: ``project``, ``subtree``, ``files``, or ``focus``.
            subtree: Repo-relative directory when ``scope='subtree'``.
            files: Repo-relative paths when ``scope='files'``.
            globs: Optional path globs (e.g. ``**/*.py``).
            limit: Max hits (1-100).
        """

        async def op(session: AsyncSession) -> dict[str, object]:
            if scope not in _SCOPES:
                raise ValueError(f"scope must be one of {sorted(_SCOPES)}; got {scope!r}")
            return await service.search_code(
                session,
                project=project or "",
                query=query,
                scope=cast(SearchScopeName, scope),
                subtree=subtree,
                files=files,
                globs=globs,
                limit=limit,
                caller=caller(ctx),
            )

        return await run_tool("search_code", project, ctx, op)

    @mcp.tool()
    async def retrieve_context(
        task: str,
        project: str | None = None,
        max_tokens: int = 1500,
        scope: str = "project",
        subtree: str | None = None,
        files: list[str] | None = None,
        ctx: Context[Any, Any] | None = None,
    ) -> dict[str, object]:
        """Token-bounded pack of the most relevant code/doc chunks for ``task`` (FR22).

        Ready for prompt injection. Uses hybrid retrieval when an embedding backend
        is configured, keyword-only otherwise (the response says which).
        """

        async def op(session: AsyncSession) -> dict[str, object]:
            if scope not in _SCOPES:
                raise ValueError(f"scope must be one of {sorted(_SCOPES)}; got {scope!r}")
            return await retrieval.retrieve_context(
                session,
                project=project or "",
                task=task,
                max_tokens=max_tokens,
                scope=cast(SearchScopeName, scope),
                subtree=subtree,
                files=files,
                caller=caller(ctx),
            )

        return await run_tool("retrieve_context", project, ctx, op)

    @mcp.tool()
    async def prepare_task(
        task: str | None = None,
        task_id: str | None = None,
        project: str | None = None,
        max_tokens: int | None = None,
        ctx: Context[Any, Any] | None = None,
    ) -> dict[str, object]:
        """Project briefing + relevant-code pack, or a planned-task handoff prompt.

        Exactly one of ``task`` (free text) or ``task_id`` (a planned task's UUID
        from create_plan/add_plan_task, T25) must be given.

        With ``task``: total defaults to the project's ``prepare_task_token_budget``
        (4000). Curated context is capped at 50%; code is floored at 30% when chunks
        exist; unused context budget spills to code. A contract/close-gate section is
        capped at 500 estimated tokens inside the same total; unused contract budget
        spills to code. The actual split is reported.

        With ``task_id``: returns a bounded, role-neutral Markdown handoff prompt
        with the task's objective, acceptance criteria, dependency status, and
        linked requirement contracts — never claim tokens, provider keys, or raw
        diffs (INV-PLAN-5).
        """

        async def op(session: AsyncSession) -> dict[str, object]:
            return await retrieval.prepare_task(
                session,
                project=project or "",
                task=task,
                task_id=task_id,
                max_tokens=max_tokens,
                caller=caller(ctx),
            )

        return await run_tool("prepare_task", project, ctx, op)
