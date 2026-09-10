"""Read-only file source for the T07 node inspector (FR34, AC13).

The node inspector shows a file's source, syntax-highlighted on the client. This
is the one server addition T07 is permitted: there was no route that returned a
file's text. No git history / blame — static content only (D11).

Safety (NFR5): the ``path`` must resolve under the project root via
``resolve_under_root`` (rejects ``..`` / absolute / ``~``) *and* be a non-skipped
row in ``code_index.files`` for the project. The bytes are read from disk (so the
viewer sees the working tree) and capped at :data:`MAX_SOURCE_BYTES`.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from pcs.context.service import resolve_project
from pcs.index.ignore import resolve_project_root, resolve_under_root
from pcs.index.schema import ensure_index_schema

# Cap the returned text so the inspector payload stays bounded (NFR13).
MAX_SOURCE_BYTES = 512 * 1024


class SourceNotIndexedError(LookupError):
    """The requested path is not a readable indexed file in this project (HTTP 404)."""


async def get_source(session: AsyncSession, *, project: str, path: str) -> dict[str, object]:
    """Return ``{path, language, content, truncated}`` for one indexed file (FR34).

    Raises:
        pcs.context.service.ProjectNotFoundError: unknown project (D3).
        pcs.index.ignore.PathTraversalError: ``path`` escapes the project root.
        ValueError: ``path`` missing.
        SourceNotIndexedError: not an indexed file, or unreadable on disk.
    """
    row = await resolve_project(session, project)
    await ensure_index_schema(session)

    rel = (path or "").strip()
    if not rel:
        raise ValueError("path query parameter is required")

    # Traversal guard first (NFR5) — raises PathTraversalError for '..'/absolute/'~'.
    root = resolve_project_root(row.root_path)
    resolved = resolve_under_root(root, rel)

    file_row = (
        await session.execute(
            text(
                "SELECT language, skipped FROM code_index.files "
                "WHERE project_id = :pid AND path = :p"
            ),
            {"pid": row.id, "p": rel},
        )
    ).first()
    if file_row is None or bool(file_row.skipped):
        raise SourceNotIndexedError(f"{rel!r} is not an indexed file in project {row.name!r}")

    try:
        raw = resolved.read_bytes()
    except OSError as exc:  # gone from disk since the last index, unreadable, ...
        raise SourceNotIndexedError(f"{rel!r} cannot be read: {exc}") from exc

    truncated = len(raw) > MAX_SOURCE_BYTES
    content = raw[:MAX_SOURCE_BYTES].decode("utf-8", errors="replace")
    language = str(file_row.language) if file_row.language is not None else None
    return {
        "path": rel,
        "language": language,
        "content": content,
        "truncated": truncated,
    }
