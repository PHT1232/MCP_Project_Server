"""Git revision + blob helpers for the code index (FR24, FR25)."""

from __future__ import annotations

import asyncio
from pathlib import Path


async def _git(root: Path, *args: str) -> str | None:
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=root,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    out, _ = await proc.communicate()
    if proc.returncode != 0:
        return None
    return out.decode("utf-8", errors="replace").strip()


async def head_commit(root: Path) -> str | None:
    """Return HEAD SHA, or None if the directory is not a git repo."""
    return await _git(root, "rev-parse", "HEAD")


async def blob_for(root: Path, relpath: str) -> str | None:
    """Blob SHA of ``relpath`` at HEAD, if tracked."""
    return await _git(root, "rev-parse", f"HEAD:{relpath}")


async def changed_paths_since(root: Path, since_commit: str | None) -> set[str] | None:
    """Repo-relative paths that changed vs ``since_commit`` plus working-tree dirty files.

    Returns None when git is unavailable (caller should fall back to a full walk).
    """
    if await _git(root, "rev-parse", "--is-inside-work-tree") != "true":
        return None
    paths: set[str] = set()
    if since_commit:
        diff = await _git(root, "diff", "--name-only", since_commit, "HEAD")
        if diff:
            paths.update(line for line in diff.splitlines() if line)
    # Unstaged + untracked (honours .gitignore).
    status = await _git(root, "status", "--porcelain", "-uall")
    if status:
        for line in status.splitlines():
            if len(line) < 4:
                continue
            body = line[3:]
            if " -> " in body:
                body = body.split(" -> ", 1)[1]
            paths.add(body.strip())
    return paths
