"""Repo-file helpers for Codebase Guide artifact writes (INV-GUIDE-5).

Why a second copy: T15 must not refactor ``pcs.requirements.service`` helpers
onto this module (CODEBASE-GUIDE-PLAN non-goal). Requirements sync keeps its
own atomic write; guide generation uses these helpers only.
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path
from uuid import uuid4


def resolve_configured_path(root_path: str, setting: str) -> Path:
    """Resolve a configured path under ``root_path`` (INV-GUIDE-5).

    Relative settings resolve under the project root and must not contain ``..``.
    Absolute settings are used verbatim, matching ``PCS_REQUIREMENTS_FILE``.
    Relative results are the lexical path under the resolved root; callers that
    write must re-check containment at write time via ``atomic_write``.
    """
    cleaned = setting.strip()
    if not cleaned:
        raise ValueError("configured path must not be empty")
    candidate = Path(cleaned)
    if candidate.is_absolute():
        return candidate
    if ".." in candidate.parts:
        raise ValueError(f"configured path must not contain '..': {setting!r}")
    root = Path(root_path).expanduser().resolve()
    joined = root.joinpath(*candidate.parts)
    _assert_under_root(joined, root)
    return joined


def dir_writable(directory: Path) -> bool:
    """True when ``directory`` exists and the process can write into it."""
    return directory.is_dir() and os.access(directory, os.W_OK)


def _assert_under_root(path: Path, root: Path) -> Path:
    """Return ``path.resolve()`` when it stays under ``root``; else raise (INV-GUIDE-5)."""
    root_real = root.expanduser().resolve()
    resolved = path.resolve()
    if not resolved.is_relative_to(root_real):
        raise ValueError(f"configured path escapes project root: {path}")
    return resolved


def _assert_write_contained(path: Path, contain_under: Path) -> None:
    """Reject writes whose parent or destination resolve outside ``contain_under``.

    Re-checked immediately before ``os.replace`` so a symlink planted after path
    resolution cannot smuggle the artifact outside the project root (INV-GUIDE-5).
    """
    root = contain_under.expanduser().resolve()
    parent = path.parent
    if not parent.exists():
        raise ValueError(f"configured path parent does not exist: {parent}")
    parent_real = _assert_under_root(parent, root)
    # Destination name is always under the verified parent; resolve again so a
    # destination symlink that points outside is rejected before replace.
    destination = parent_real / path.name
    if path.exists() or path.is_symlink():
        _assert_under_root(path, root)
    else:
        _assert_under_root(destination, root)


def atomic_write(path: Path, text: str, *, contain_under: Path | None = None) -> None:
    """Replace ``path`` via a same-directory temp file and ``os.replace`` (INV-GUIDE-5).

    When ``contain_under`` is set, containment is enforced immediately before
    replacement and again on the final real path so symlink races cannot leave
    guide content outside the project root. A failed temp write or rejected
    containment check leaves any pre-existing ``path`` untouched.
    """
    if contain_under is not None:
        _assert_write_contained(path, contain_under)

    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        if contain_under is not None:
            root = contain_under.expanduser().resolve()
            _assert_write_contained(path, contain_under)
            _assert_under_root(tmp, root)
        os.replace(tmp, path)
        if contain_under is not None:
            root = contain_under.expanduser().resolve()
            try:
                _assert_under_root(path, root)
            except ValueError:
                # Best-effort cleanup if a race still escaped during replace.
                with contextlib.suppress(OSError):
                    path.unlink(missing_ok=True)
                raise
    finally:
        tmp.unlink(missing_ok=True)
