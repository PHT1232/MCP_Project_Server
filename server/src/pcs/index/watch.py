"""File-watch trigger for incremental reindex (FR24).

Tests drive freshness via ``reindex(incremental=True)``; this module only runs
while the HTTP app is up.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from pcs.config import get_settings
from pcs.db.base import session_scope

logger = logging.getLogger("pcs")

_tasks: dict[str, asyncio.Task[None]] = {}
_lock = asyncio.Lock()


async def _watch_loop(project_id: str, root: Path) -> None:
    from watchfiles import awatch

    from pcs.index.service import reindex

    try:
        async for _changes in awatch(root, debounce=800, recursive=True):
            try:
                async with session_scope() as session:
                    await reindex(session, project=project_id, incremental=True)
            except (FileNotFoundError, Exception) as exc:
                logger.warning(
                    "watch_reindex_failed",
                    extra={"context": {"project": project_id, "error": str(exc)}},
                )
    except asyncio.CancelledError:
        raise


async def ensure_watch(project_id: str, root_path: str) -> None:
    """Start (or replace) a watcher for ``root_path`` if watching is enabled."""
    if not get_settings().index_watch:
        return
    path = Path(root_path).expanduser()
    if not path.is_dir():
        return
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return
    async with _lock:
        previous = _tasks.pop(project_id, None)
        if previous is not None:
            previous.cancel()
        _tasks[project_id] = asyncio.create_task(
            _watch_loop(project_id, path.resolve()), name=f"pcs-index-watch-{project_id}"
        )


async def start_all() -> None:
    """Watch every registered project root (HTTP startup)."""
    if not get_settings().index_watch:
        return
    from pcs.context.service import list_projects

    async with session_scope() as session:
        projects = await list_projects(session)
    for project in projects:
        await ensure_watch(project.id, project.root_path)


async def stop_watch(project_id: str) -> None:
    """Cancel the in-process watcher for one project, if any."""
    async with _lock:
        task = _tasks.pop(project_id, None)
    if task is None:
        return
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def stop_all() -> None:
    """Cancel every watcher (HTTP shutdown)."""
    async with _lock:
        tasks = list(_tasks.values())
        _tasks.clear()
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
