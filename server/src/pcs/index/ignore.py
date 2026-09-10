"""Path safety, .gitignore, and default ignore/allow lists (FR19, NFR5)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pathspec

from pcs.config import get_settings

IgnoreSpec = pathspec.PathSpec[Any]

DEFAULT_IGNORE: tuple[str, ...] = (
    ".git/",
    ".hg/",
    ".svn/",
    "node_modules/",
    "vendor/",
    "venv/",
    ".venv/",
    "dist/",
    "build/",
    "target/",
    "__pycache__/",
    "*.pyc",
    ".mypy_cache/",
    ".ruff_cache/",
    ".pytest_cache/",
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "id_rsa",
    "id_rsa.*",
    "secrets/",
    ".ssh/",
    "*.min.js",
    "*.min.css",
    "package-lock.json",
    "pnpm-lock.yaml",
    "uv.lock",
    "Cargo.lock",
    "poetry.lock",
    "*.woff",
    "*.woff2",
    "*.png",
    "*.jpg",
    "*.jpeg",
    "*.gif",
    "*.webp",
    "*.pdf",
    "*.zip",
    "*.gz",
    "*.tgz",
    "*.so",
    "*.dylib",
    "*.dll",
    "*.exe",
    "*.bin",
)


class PathTraversalError(Exception):
    """A path resolved outside the project root (NFR5)."""


@dataclass
class WalkResult:
    """Indexable files plus skipped paths with reasons (FR19, FR26)."""

    files: list[Path] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)


def resolve_project_root(root_path: str) -> Path:
    """Return the real project root, or raise if it is not a directory."""
    root = Path(root_path).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"project root {root_path!r} is not a directory")
    return root


def resolve_under_root(root: Path, relative: str) -> Path:
    """Resolve ``relative`` inside ``root``; reject traversal (NFR5)."""
    rel = relative.strip()
    if not rel or rel.startswith("/") or rel.startswith("~"):
        raise PathTraversalError(f"path {relative!r} is not repo-relative")
    candidate = (root / rel).resolve()
    if not candidate.is_relative_to(root):
        raise PathTraversalError(f"path {relative!r} escapes project root {root}")
    return candidate


def repo_relative(root: Path, path: Path) -> str:
    """POSIX-style path relative to the project root."""
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise PathTraversalError(f"{path} is outside {root}")
    return resolved.relative_to(root).as_posix()


def _settings_patterns(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def _root_ignore_lines(root: Path) -> list[str]:
    settings = get_settings()
    lines: list[str] = list(DEFAULT_IGNORE)
    lines.extend(_settings_patterns(settings.index_ignore))
    gitignore = root / ".gitignore"
    if gitignore.is_file():
        lines.extend(gitignore.read_text(encoding="utf-8", errors="replace").splitlines())
    return lines


def build_allow_spec() -> IgnoreSpec | None:
    """Optional allow-list; ``None`` means every non-ignored path is eligible (FR19)."""
    patterns = _settings_patterns(get_settings().index_allow)
    if not patterns:
        return None
    return pathspec.PathSpec.from_lines("gitignore", patterns)


def is_ignored(rel_posix: str, spec: IgnoreSpec, allow: IgnoreSpec | None) -> bool:
    """True if the repo-relative path should not be indexed."""
    if allow is not None and not allow.match_file(rel_posix):
        return True
    return spec.match_file(rel_posix)


def _merge_gitignore(parent: IgnoreSpec, directory: Path, root: Path) -> IgnoreSpec:
    gitignore = directory / ".gitignore"
    if not gitignore.is_file():
        return parent
    rel_dir = directory.relative_to(root).as_posix()
    prefixed: list[str] = []
    for raw in gitignore.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("/"):
            prefixed.append(f"{rel_dir}{stripped}")
        else:
            prefixed.append(f"{rel_dir}/{stripped}")
    extra = pathspec.PathSpec.from_lines("gitignore", prefixed)
    return pathspec.PathSpec(list(parent.patterns) + list(extra.patterns))


def walk_repo(root: Path) -> WalkResult:
    """Walk ``root``, honouring gitignore + defaults; prune ignored directories (FR19)."""
    spec = pathspec.PathSpec.from_lines("gitignore", _root_ignore_lines(root))
    allow = build_allow_spec()
    max_bytes = get_settings().index_max_file_bytes
    result = WalkResult()

    def rec(directory: Path, current: IgnoreSpec) -> None:
        local = current if directory == root else _merge_gitignore(current, directory, root)
        try:
            children = sorted(directory.iterdir(), key=lambda p: p.name)
        except OSError:
            rel = repo_relative(root, directory)
            result.skipped.append((rel, "unreadable"))
            return
        for child in children:
            if child.is_symlink():
                continue
            try:
                rel = repo_relative(root, child)
            except PathTraversalError:
                result.skipped.append((str(child), "outside_root"))
                continue
            match_as = f"{rel}/" if child.is_dir() else rel
            if is_ignored(match_as, local, allow) or is_ignored(rel, local, allow):
                result.skipped.append((rel, "ignored"))
                continue
            if child.is_dir():
                rec(child, local)
                continue
            if not child.is_file():
                continue
            try:
                size = child.stat().st_size
            except OSError:
                result.skipped.append((rel, "unreadable"))
                continue
            if size > max_bytes:
                result.skipped.append((rel, "too_large"))
                continue
            result.files.append(child)

    rec(root, spec)
    return result
