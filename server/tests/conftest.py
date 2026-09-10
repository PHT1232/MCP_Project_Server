"""Shared fixtures: a real PostgreSQL (pgvector image) with the baseline applied."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from testcontainers.community.postgres import PostgresContainer

from pcs.config import get_settings
from pcs.db.base import reset_engine, session_scope

PGVECTOR_IMAGE = "pgvector/pgvector:pg16"


def pytest_configure() -> None:
    """Disable the HTTP file watcher in tests; they call reindex directly (FR24)."""
    os.environ.setdefault("PCS_INDEX_WATCH", "false")


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    """Start Postgres once per test session and expose an async SQLAlchemy URL."""
    with PostgresContainer(PGVECTOR_IMAGE, driver="psycopg") as container:
        url = container.get_connection_url()
        os.environ["PCS_DATABASE_URL"] = url
        get_settings.cache_clear()
        yield url
    os.environ.pop("PCS_DATABASE_URL", None)
    get_settings.cache_clear()


@pytest.fixture(scope="session")
def migrated_db(database_url: str) -> str:
    """Apply every migration from empty (proves `just migrate` works from zero)."""
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    return database_url


@pytest_asyncio.fixture
async def clean_db(migrated_db: str) -> AsyncIterator[None]:
    """Truncate all skeleton tables before each test."""
    await reset_engine()
    async with session_scope() as session:
        await session.execute(text("TRUNCATE projects CASCADE"))
    yield
    await reset_engine()
