"""Two-way sync between the requirements file and the store (FR16a, D12, D15).

No MCP/HTTP imports — transports wrap :func:`sync_requirements` (AGENTS.md). The
file owns requirement *existence* and *title/prose*; the store owns *status*,
*links*, and *history*. The merge is 3-way against the snapshot recorded by the
last successful sync (``requirements_sync_state``).
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pcs.config import get_settings
from pcs.context import service as context_service
from pcs.context.service import ProjectNotFoundError, resolve_project
from pcs.context.types import (
    REQ_NOT_STARTED,
    SECTION_REQUIREMENTS,
    STATUS_ARCHIVED,
    STATUS_DELETED,
)
from pcs.db.models import ContextEntry, Project
from pcs.requirements.models import RequirementsSyncState
from pcs.requirements.parser import parse_requirements
from pcs.requirements.template import (
    DEFAULT_TEMPLATE,
    LineEdit,
    render_heading,
    render_new_block,
    render_token,
    serialise,
)
from pcs.requirements.types import (
    ManagedToken,
    ParsedBlock,
    ParsedFile,
    ReconciliationNote,
    RequirementView,
    SyncReport,
)

logger = logging.getLogger("pcs")

_SEQ_RE = re.compile(r"^R-(\d+)$")

__all__ = [
    "list_requirements",
    "resolve_requirements_path",
    "sync_requirements",
    "write_through_requirement_change",
]


async def list_requirements(session: AsyncSession, *, project: str) -> tuple[RequirementView, ...]:
    """Current requirements (store side, no file I/O) for the frontend view (AC14a)."""
    proj = await resolve_project(session, project)
    return await _current_requirements(session, proj.id)


def _now() -> datetime:
    return datetime.now(UTC)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def resolve_requirements_path(root_path: str) -> Path:
    """Where the requirements file lives for a project (FR16a, ``PCS_REQUIREMENTS_FILE``).

    Relative settings resolve under ``root_path``; an absolute setting is used
    verbatim. ``..`` segments are rejected (NFR5).
    """
    setting = get_settings().requirements_file.strip() or ".project-context/requirements.md"
    candidate = Path(setting)
    if candidate.is_absolute():
        return candidate
    if ".." in candidate.parts:
        raise ValueError(f"PCS_REQUIREMENTS_FILE must not contain '..': {setting!r}")
    return Path(root_path).expanduser() / candidate


def _atomic_write(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` via a temp file + rename (FR16a)."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _snap(title: str, prose: str, status: str) -> dict[str, Any]:
    return {"title": title, "prose_hash": _sha256(prose), "status": status}


async def _load_state(session: AsyncSession, project_id: str, path: str) -> RequirementsSyncState:
    state = await session.get(RequirementsSyncState, project_id)
    if state is not None:
        state.file_path = path
        return state
    keys = (
        (
            await session.execute(
                select(ContextEntry.req_key).where(
                    ContextEntry.project_id == project_id,
                    ContextEntry.req_key.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )
    max_seq = 0
    for key in keys:
        match = _SEQ_RE.match(key or "")
        if match is not None:
            max_seq = max(max_seq, int(match.group(1)))
    state = RequirementsSyncState(
        project_id=project_id, file_path=path, next_seq=max_seq + 1, snapshot=[]
    )
    session.add(state)
    await session.flush()
    return state


def _snapshot_map(state: RequirementsSyncState) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in state.snapshot or []:
        key = str(item.get("req_key", ""))
        if key:
            result[key] = dict(item)
    return result


async def _current_requirements(
    session: AsyncSession, project_id: str
) -> tuple[RequirementView, ...]:
    rows = (
        (
            await session.execute(
                select(ContextEntry)
                .where(
                    ContextEntry.project_id == project_id,
                    ContextEntry.section == SECTION_REQUIREMENTS,
                    ContextEntry.status.notin_((STATUS_DELETED, STATUS_ARCHIVED)),
                    ContextEntry.req_key.is_not(None),
                )
                .order_by(ContextEntry.req_key)
            )
        )
        .scalars()
        .all()
    )
    return tuple(
        RequirementView(
            req_key=row.req_key or "",
            entry_id=row.id,
            title=row.headline,
            status=row.requirement_status or REQ_NOT_STARTED,
            lifecycle=row.status,
            linked_files=tuple(str(f) for f in (row.linked_files or [])),
        )
        for row in rows
    )


def _report(
    project: Project,
    path: Path,
    *,
    ok: bool,
    file_existed: bool,
    file_written: bool = False,
    errors: tuple[str, ...] = (),
    requirements: tuple[RequirementView, ...] = (),
    **extra: Any,
) -> SyncReport:
    return SyncReport(
        project_id=project.id,
        project_name=project.name,
        file_path=str(path),
        ok=ok,
        file_existed=file_existed,
        file_written=file_written,
        errors=errors,
        requirements=requirements,
        **extra,
    )


async def sync_requirements(
    session: AsyncSession,
    *,
    project: str,
    author: str = "agent",
    create_if_missing: bool = True,
) -> SyncReport:
    """3-way merge the requirements file against the store (FR16a, AC18, AC22).

    Raises :class:`ProjectNotFoundError` for an unknown project (AC16). Every
    other problem — a missing directory, a malformed file, an unparseable block —
    is returned in the :class:`SyncReport`; a malformed file never partially
    applies.
    """
    proj = await resolve_project(session, project, for_update=True)
    path = resolve_requirements_path(proj.root_path)
    state = await _load_state(session, proj.id, str(path))

    file_existed = path.exists()
    if not file_existed:
        if not create_if_missing:
            return _report(
                proj,
                path,
                ok=False,
                file_existed=False,
                errors=(f"requirements file not found: {path}",),
                requirements=await _current_requirements(session, proj.id),
            )
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(path, DEFAULT_TEMPLATE)
        except OSError as exc:
            return _report(
                proj,
                path,
                ok=False,
                file_existed=False,
                errors=(f"cannot create requirements file at {path}: {exc}",),
                requirements=await _current_requirements(session, proj.id),
            )

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return _report(
            proj,
            path,
            ok=False,
            file_existed=file_existed,
            errors=(f"cannot read requirements file {path}: {exc}",),
            requirements=await _current_requirements(session, proj.id),
        )

    parsed = parse_requirements(text)
    if parsed.fatal_errors:
        return _report(
            proj,
            path,
            ok=False,
            file_existed=True,
            errors=tuple(parsed.fatal_errors),
            requirements=await _current_requirements(session, proj.id),
        )

    result = await _merge(session, proj, path, state, parsed, text, author, file_existed)
    await session.flush()
    return result


async def _merge(
    session: AsyncSession,
    proj: Project,
    path: Path,
    state: RequirementsSyncState,
    parsed: ParsedFile,
    text: str,
    author: str,
    file_existed: bool,
) -> SyncReport:
    store_rows = (
        (
            await session.execute(
                select(ContextEntry)
                .where(
                    ContextEntry.project_id == proj.id,
                    ContextEntry.section == SECTION_REQUIREMENTS,
                    ContextEntry.status != STATUS_DELETED,
                )
                .order_by(ContextEntry.created_at, ContextEntry.id)
            )
        )
        .scalars()
        .all()
    )
    by_key: dict[str, ContextEntry] = {r.req_key: r for r in store_rows if r.req_key}
    keyless = [r for r in store_rows if not r.req_key]

    snapshot = _snapshot_map(state)
    used_keys: set[str] = set(by_key) | {b.req_key for b in parsed.blocks if b.req_key}

    def next_key() -> str:
        while True:
            key = f"R-{state.next_seq:03d}"
            state.next_seq += 1
            if key not in used_keys:
                used_keys.add(key)
                return key

    edits: list[LineEdit] = []
    appended: list[list[str]] = []
    new_snapshot: dict[str, dict[str, Any]] = {}
    created: list[str] = []
    updated: list[str] = []
    archived: list[str] = []
    written_back: list[str] = []
    recon: list[ReconciliationNote] = []
    errors: list[str] = []

    error_block_keys = {b.req_key for b in parsed.blocks if b.error and b.req_key}
    for block in parsed.blocks:
        if block.error:
            head = (
                render_heading(block.req_key, block.title)
                if block.req_key
                else f"### {block.title}"
            )
            errors.append(f"{head!r} (line {block.heading_line + 1}): {block.error}")

    def schedule_token(block: ParsedBlock, desired: ManagedToken) -> bool:
        line = render_token(desired)
        if block.token_line is not None:
            if parsed.lines[block.token_line].strip() == line:
                return False
            edits.append(LineEdit(block.token_line, line))
            return True
        edits.append(LineEdit(block.heading_line + 1, line, insert=True))
        return True

    async def create_from_block(block: ParsedBlock, key: str) -> ContextEntry | None:
        token = block.token or ManagedToken(status=block.status)
        try:
            view = await context_service.add_entry(
                session,
                project=proj.id,
                section=SECTION_REQUIREMENTS,
                headline=block.title,
                detail=block.prose or block.title,
                requirement_status=block.status,
                linked_files=token.files,
                author=author,
                req_key=key,
            )
        except context_service.ValidationError as exc:
            errors.append(f"{block.title!r} (line {block.heading_line + 1}): {exc}")
            return None
        row = await session.get(ContextEntry, view.id)
        assert row is not None
        by_key[key] = row
        edits.append(LineEdit(block.heading_line, render_heading(key, block.title)))
        schedule_token(
            block,
            ManagedToken(
                status=block.status,
                files=tuple(str(f) for f in (row.linked_files or [])),
                blocker=row.related_entry_id,
                extra=token.extra,
            ),
        )
        new_snapshot[key] = _snap(block.title, block.prose, block.status)
        written_back.append(key)
        return row

    handled: set[str] = set()
    for block in parsed.blocks:
        if block.error:
            continue

        if block.req_key is None:
            key = next_key()
            row = await create_from_block(block, key)
            if row is not None:
                created.append(key)
                handled.add(key)
            continue

        key = block.req_key
        handled.add(key)
        row = by_key.get(key)

        if row is None:
            fresh = next_key()
            recon.append(
                ReconciliationNote(key, f"{key} is not a known requirement id; assigned {fresh}")
            )
            made = await create_from_block(block, fresh)
            if made is not None:
                created.append(fresh)
                handled.add(fresh)
            continue

        if row.status == STATUS_ARCHIVED:
            recon.append(
                ReconciliationNote(
                    key,
                    f"{key} was archived; leaving the stale block untouched (not resurrected)",
                )
            )
            continue

        token = block.token or ManagedToken(status=block.status)
        want_detail = block.prose or block.title
        if row.headline != block.title or row.detail != want_detail:
            try:
                await context_service.update_entry(
                    session,
                    project=proj.id,
                    entry_id=row.id,
                    headline=block.title,
                    detail=want_detail,
                    author=author,
                    expected_section=SECTION_REQUIREMENTS,
                )
                updated.append(key)
            except context_service.ValidationError as exc:
                errors.append(f"{key} (line {block.heading_line + 1}): {exc}")

        store_status = row.requirement_status or REQ_NOT_STARTED
        file_status = block.status
        final_status = store_status
        if file_status != store_status:
            snap = snapshot.get(key)
            snap_status = str(snap["status"]) if snap else None
            file_changed = snap_status is not None and file_status != snap_status
            store_changed = snap_status is None or store_status != snap_status
            if file_changed and not store_changed:
                try:
                    await context_service.set_requirement_status(
                        session, project=proj.id, entry_id=row.id, status=file_status, author=author
                    )
                    final_status = file_status
                    updated.append(key)
                except context_service.ValidationError as exc:
                    errors.append(f"{key} (line {block.heading_line + 1}): {exc}")
            else:
                final_status = store_status
                if file_changed and store_changed:
                    recon.append(
                        ReconciliationNote(
                            key,
                            f"status changed in both file ({file_status}) and store "
                            f"({store_status}) since last sync; store wins",
                        )
                    )

        desired = ManagedToken(
            status=final_status,
            files=tuple(str(f) for f in (row.linked_files or [])),
            blocker=row.related_entry_id,
            extra=token.extra,
        )
        if schedule_token(block, desired) and key not in written_back:
            written_back.append(key)
        new_snapshot[key] = _snap(block.title, block.prose, final_status)

    # Store requirements with a key that is not in the file.
    for key, row in list(by_key.items()):
        if key in handled or row.status == STATUS_ARCHIVED:
            continue
        if key in error_block_keys:
            if key in snapshot:
                new_snapshot[key] = snapshot[key]
            continue
        if key in snapshot:
            await context_service.archive_entry(
                session, project=proj.id, entry_id=row.id, author=author
            )
            archived.append(key)
        else:
            appended.append(_new_block_lines(key, row))
            written_back.append(key)
            new_snapshot[key] = _snap(
                row.headline, row.detail, row.requirement_status or REQ_NOT_STARTED
            )

    # Store requirements created via add_requirement that were never keyed.
    for row in keyless:
        if row.status == STATUS_ARCHIVED:
            continue
        key = next_key()
        row.req_key = key
        await session.flush()
        appended.append(_new_block_lines(key, row))
        written_back.append(key)
        new_snapshot[key] = _snap(
            row.headline, row.detail, row.requirement_status or REQ_NOT_STARTED
        )

    file_written = False
    if edits or appended:
        new_text = serialise(parsed, edits, appended)
        if new_text != text:
            try:
                _atomic_write(path, new_text)
                file_written = True
                text = new_text
            except OSError as exc:
                errors.append(f"could not write requirements file {path}: {exc}")

    state.file_sha256 = _sha256(text)
    state.snapshot = [{"req_key": k, **v} for k, v in sorted(new_snapshot.items())]
    state.last_synced_at = _now()

    errors_t = tuple(errors)
    reqs = await _current_requirements(session, proj.id)
    _log_sync(proj, path, created, updated, archived, recon, errors_t)
    return SyncReport(
        project_id=proj.id,
        project_name=proj.name,
        file_path=str(path),
        ok=not errors_t,
        file_existed=file_existed,
        file_written=file_written,
        created=tuple(dict.fromkeys(created)),
        updated=tuple(dict.fromkeys(updated)),
        archived=tuple(dict.fromkeys(archived)),
        written_back=tuple(dict.fromkeys(written_back)),
        reconciliations=tuple(recon),
        errors=errors_t,
        requirements=reqs,
    )


def _new_block_lines(key: str, row: ContextEntry) -> list[str]:
    token = ManagedToken(
        status=row.requirement_status or REQ_NOT_STARTED,
        files=tuple(str(f) for f in (row.linked_files or [])),
        blocker=row.related_entry_id,
    )
    return render_new_block(key, row.headline, token, row.detail)


def _log_sync(
    proj: Project,
    path: Path,
    created: list[str],
    updated: list[str],
    archived: list[str],
    recon: list[ReconciliationNote],
    errors: tuple[str, ...],
) -> None:
    for note in recon:
        logger.info(
            "requirements_reconciliation",
            extra={"context": {"project": proj.id, "req_key": note.req_key, "note": note.message}},
        )
    logger.info(
        "requirements_sync",
        extra={
            "context": {
                "project": proj.id,
                "file": str(path),
                "created": created,
                "updated": updated,
                "archived": archived,
                "reconciliations": len(recon),
                "errors": len(errors),
            }
        },
    )


async def write_through_requirement_change(
    session: AsyncSession, *, project: str, author: str = "agent"
) -> SyncReport | None:
    """Project a store-side requirement change into the file (FR16a).

    Called by ``add_requirement`` / ``set_requirement_status`` /
    ``update_requirement`` / ``resolve_requirement`` after their store write. A
    :class:`ProjectNotFoundError` propagates; any other failure is logged and
    swallowed so the store write is never lost.
    """
    try:
        return await sync_requirements(
            session, project=project, author=author, create_if_missing=True
        )
    except ProjectNotFoundError:
        raise
    except Exception as exc:  # store write must survive a requirements-file problem
        logger.warning(
            "requirements_write_through_failed",
            extra={"context": {"project": project, "error": str(exc)}},
        )
        return None
