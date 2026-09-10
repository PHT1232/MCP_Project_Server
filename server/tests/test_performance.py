"""Runnable performance acceptance checks for NFR1, NFR2, NFR9, and NFR10.

The tests use the shared real-PostgreSQL fixture. Index timings force semantic
embeddings off, keeping results deterministic, offline, and focused on index cost.
"""

from __future__ import annotations

import math
import time
from collections.abc import Iterator
from pathlib import Path
from typing import cast

import pytest

from pcs.context import service as context_service
from pcs.context.assembly import estimate_tokens
from pcs.db.base import session_scope
from pcs.index import service as index_service
from pcs.index.embedding import set_embedding_backend_override

pytestmark = pytest.mark.usefixtures("clean_db")

BRIEFING_LIMIT_SECONDS = 0.200
INCREMENTAL_LIMIT_SECONDS = 5.0
FULL_INDEX_LIMIT_SECONDS = 180.0
MEDIUM_REPO_FILES = 100
LINES_PER_FILE = 1_000
MEDIUM_REPO_LOC = MEDIUM_REPO_FILES * LINES_PER_FILE


@pytest.fixture
def no_embedding_backend() -> Iterator[None]:
    """Force deterministic, offline keyword-only indexing for timing checks."""
    set_embedding_backend_override(None, active=True)
    try:
        yield
    finally:
        set_embedding_backend_override(None, active=False)


async def _register_project(*, name: str, root: Path, budget: int = 1_500) -> None:
    async with session_scope() as session:
        await context_service.register_project(
            session,
            name=name,
            root_path=str(root),
            overview="Representative local project used by T09 performance checks.",
        )
        if budget != 1_500:
            await context_service.configure_project(
                session,
                project=name,
                briefing_token_budget=budget,
            )


def _percentile_nearest_rank(samples: list[float], percentile: float) -> float:
    ordered = sorted(samples)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[rank - 1]


def _write_medium_repo(root: Path) -> None:
    """Create approximately 100k physical LOC with one structural chunk per file."""
    package = root / "src" / "medium_repo"
    package.mkdir(parents=True)
    line = "VALUE = 'project context performance fixture'\n"
    body = line * LINES_PER_FILE
    for number in range(MEDIUM_REPO_FILES):
        (package / f"module_{number:03d}.py").write_text(body, encoding="utf-8")


async def test_nfr1_typical_briefing_p95_under_200ms(tmp_path: Path) -> None:
    """A warm typical-project briefing fetch has p95 latency below 200 ms (NFR1)."""
    project = "nfr1-briefing"
    await _register_project(name=project, root=tmp_path)
    async with session_scope() as session:
        for section in ("blockers", "bugs", "conventions", "decisions", "requirements"):
            for number in range(10):
                await context_service.add_entry(
                    session,
                    project=project,
                    section=section,
                    headline=f"{section} item {number}",
                    detail="Enough representative detail to exercise ranking and budget assembly.",
                )

    for _ in range(3):
        async with session_scope() as session:
            await context_service.get_project_briefing(session, project=project)

    samples: list[float] = []
    for _ in range(20):
        started = time.perf_counter()
        async with session_scope() as session:
            briefing = await context_service.get_project_briefing(session, project=project)
        samples.append(time.perf_counter() - started)
        assert briefing

    p95 = _percentile_nearest_rank(samples, 0.95)
    print(
        f"NFR1 briefing: p95={p95 * 1_000:.1f}ms "
        f"min={min(samples) * 1_000:.1f}ms max={max(samples) * 1_000:.1f}ms"
    )
    assert p95 < BRIEFING_LIMIT_SECONDS


async def test_nfr2_briefing_obeys_configured_budget(tmp_path: Path) -> None:
    """Briefing assembly honours a non-default configured token budget (NFR2)."""
    project = "nfr2-budget"
    budget = 600
    await _register_project(name=project, root=tmp_path, budget=budget)
    async with session_scope() as session:
        for number in range(60):
            await context_service.add_entry(
                session,
                project=project,
                section="bugs",
                headline=f"Budget pressure item {number:02d} " + "x" * 70,
                detail="Full detail remains available through drill-down. " * 8,
            )

    async with session_scope() as session:
        briefing = await context_service.get_project_briefing(session, project=project)

    measured_tokens = estimate_tokens(briefing)
    print(f"NFR2 briefing: estimated_tokens={measured_tokens} configured_budget={budget}")
    assert measured_tokens <= budget
    assert "get_section" in briefing


async def test_nfr9_incremental_changed_file_reindexes_within_seconds(
    tmp_path: Path, no_embedding_backend: None
) -> None:
    """A one-file incremental refresh completes within seconds and is fresh (NFR9)."""
    project = "nfr9-incremental"
    source = tmp_path / "src"
    source.mkdir()
    target = source / "app.py"
    target.write_text("def greeting() -> str:\n    return 'before'\n", encoding="utf-8")
    for number in range(40):
        (source / f"helper_{number:02d}.py").write_text(
            f"HELPER_{number} = {number}\n", encoding="utf-8"
        )

    await _register_project(name=project, root=tmp_path)
    async with session_scope() as session:
        await index_service.reindex(session, project=project, incremental=False)

    target.write_text("def greeting() -> str:\n    return 'after-change'\n", encoding="utf-8")
    started = time.perf_counter()
    async with session_scope() as session:
        status = await index_service.reindex(session, project=project, incremental=True)
    elapsed = time.perf_counter() - started

    async with session_scope() as session:
        result = await index_service.search_code(
            session, project=project, query="after-change", limit=5
        )
    hits = cast(list[dict[str, object]], result["hits"])
    print(f"NFR9 incremental reindex: elapsed={elapsed:.3f}s files={status.file_count}")
    assert elapsed < INCREMENTAL_LIMIT_SECONDS
    assert hits
    assert hits[0]["path"] == "src/app.py"
    assert hits[0]["stale"] is False


async def test_nfr10_approximately_100k_loc_full_index_within_minutes(
    tmp_path: Path, no_embedding_backend: None
) -> None:
    """A roughly 100k-LOC repository fully indexes within three minutes (NFR10)."""
    project = "nfr10-medium-repo"
    _write_medium_repo(tmp_path)
    await _register_project(name=project, root=tmp_path)

    started = time.perf_counter()
    async with session_scope() as session:
        status = await index_service.reindex(session, project=project, incremental=False)
    elapsed = time.perf_counter() - started

    print(
        f"NFR10 full index: elapsed={elapsed:.3f}s loc={MEDIUM_REPO_LOC} "
        f"files={status.file_count} chunks={status.chunk_count}"
    )
    assert status.file_count == MEDIUM_REPO_FILES
    assert status.chunk_count >= MEDIUM_REPO_FILES
    assert elapsed < FULL_INDEX_LIMIT_SECONDS
