"""T20 / INV-AISET-1..5 focused persisted AI settings tests."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import threading
from unittest.mock import patch

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from pcs.ai_settings import (
    AiSettingsError,
    MasterKeyRequiredError,
    _decrypt,
    _encrypt,
    admin_authorized,
    load_runtime_ai_settings,
    reset_runtime_ai_settings,
    update_ai_settings,
    validate_provider_url,
)
from pcs.config import get_settings
from pcs.db.base import session_scope
from pcs.index.embedding import OpenAIEmbeddingBackend
from pcs.web_api.ai_settings_routes import _patch

KEY = base64.urlsafe_b64encode(b"k" * 32).decode()


def embedding(secret: object = "secret-value", **changes: object) -> dict[str, object]:
    result: dict[str, object] = {
        "backend": "openai",
        "base_url": "https://example.com/v1",
        "model": "embed-a",
        "dimensions": 256,
        "batch_size": 8,
        "timeout_seconds": 4.0,
    }
    if secret != "omitted":
        result["api_key"] = secret
    result.update(changes)
    return result


def summary(secret: object = "summary-secret") -> dict[str, object]:
    return {
        "backend": "openai",
        "base_url": "https://www.example.com/v1",
        "model": "sum-a",
        "timeout_seconds": 5.0,
        "api_key": secret,
    }


@pytest.fixture(autouse=True)
def master_key() -> object:
    os.environ["PCS_AI_SETTINGS_MASTER_KEY"] = KEY
    os.environ["PCS_AI_PROVIDER_ALLOWED_HOSTS"] = "example.com,www.example.com,api.openai.com"
    os.environ.pop("PCS_AI_PROVIDER_ALLOWED_PRIVATE_HOSTS", None)
    os.environ["PCS_ADMIN_TOKEN"] = "admin-secret"
    get_settings.cache_clear()
    reset_runtime_ai_settings()
    yield
    os.environ.pop("PCS_AI_SETTINGS_MASTER_KEY", None)
    os.environ.pop("PCS_AI_PROVIDER_ALLOWED_HOSTS", None)
    os.environ.pop("PCS_AI_PROVIDER_ALLOWED_PRIVATE_HOSTS", None)
    os.environ.pop("PCS_ADMIN_TOKEN", None)
    get_settings.cache_clear()
    reset_runtime_ai_settings()


@pytest.mark.usefixtures("clean_db")
async def test_persists_encrypted_and_survives_runtime_restart() -> None:
    async with session_scope() as session:
        saved = await update_ai_settings(session, {"embedding": embedding(), "summary": summary()})
        assert "api_key" not in saved.embedding.public_dict()
        raw = (
            await session.execute(
                text("SELECT embedding_api_key_encrypted FROM ai_provider_settings")
            )
        ).scalar_one()
        assert b"secret-value" not in bytes(raw)
    reset_runtime_ai_settings()
    async with session_scope() as session:
        loaded = await load_runtime_ai_settings(session)
        assert loaded.embedding.model == "embed-a"
        assert loaded.embedding.api_key == "secret-value"


@pytest.mark.usefixtures("clean_db")
async def test_secret_retain_replace_and_clear() -> None:
    async with session_scope() as session:
        await update_ai_settings(session, {"embedding": embedding()})
        retained = await update_ai_settings(session, {"embedding": embedding("omitted")})
        assert retained.embedding.api_key == "secret-value"
        replaced = await update_ai_settings(session, {"embedding": embedding("replacement")})
        assert replaced.embedding.api_key == "replacement"
        cleared = await update_ai_settings(session, {"embedding": embedding(None)})
        assert cleared.embedding.api_key == ""


@pytest.mark.usefixtures("clean_db")
async def test_missing_master_key_rejects_secret_without_echo() -> None:
    os.environ.pop("PCS_AI_SETTINGS_MASTER_KEY")
    get_settings.cache_clear()
    async with session_scope() as session:
        with pytest.raises(MasterKeyRequiredError) as caught:
            await update_ai_settings(session, {"embedding": embedding("do-not-echo")})
    assert "do-not-echo" not in str(caught.value)


@pytest.mark.usefixtures("clean_db")
@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "https://user:pass@example.com",
        "https://example.com/#frag",
        "https://127.0.0.1/v1",
        "https://10.0.0.1/v1",
        "https://169.254.1.2/v1",
        "https://localhost/v1",
    ],
)
async def test_ssrf_urls_rejected(url: str) -> None:
    async with session_scope() as session:
        with pytest.raises(AiSettingsError):
            await update_ai_settings(session, {"embedding": embedding(base_url=url)})


@pytest.mark.usefixtures("clean_db")
async def test_environment_fallback_only_without_persisted_row() -> None:
    os.environ["PCS_EMBEDDING_MODEL"] = "env-model"
    get_settings.cache_clear()
    reset_runtime_ai_settings()
    async with session_scope() as session:
        env = await load_runtime_ai_settings(session)
        assert env.embedding.model == "env-model"
        await update_ai_settings(session, {"embedding": embedding(None)})
    os.environ["PCS_EMBEDDING_MODEL"] = "changed-env"
    get_settings.cache_clear()
    reset_runtime_ai_settings()
    async with session_scope() as session:
        persisted = await load_runtime_ai_settings(session)
        assert persisted.embedding.model == "embed-a"
    os.environ.pop("PCS_EMBEDDING_MODEL", None)


@pytest.mark.usefixtures("clean_db")
async def test_embedding_identity_change_marks_all_indexes_incompatible() -> None:
    async with session_scope() as session:
        await session.execute(
            text(
                "INSERT INTO projects (id,name,root_path) VALUES "
                "(:a,'ai-a','/tmp/a'),(:b,'ai-b','/tmp/b')"
            ),
            {
                "a": "00000000-0000-0000-0000-0000000000a1",
                "b": "00000000-0000-0000-0000-0000000000b2",
            },
        )
        await session.execute(
            text(
                "INSERT INTO code_index.status (project_id,reindex_required) "
                "VALUES (:a,false),(:b,false)"
            ),
            {
                "a": "00000000-0000-0000-0000-0000000000a1",
                "b": "00000000-0000-0000-0000-0000000000b2",
            },
        )
        await update_ai_settings(session, {"embedding": embedding(None)})
        flags = (
            (await session.execute(text("SELECT reindex_required FROM code_index.status")))
            .scalars()
            .all()
        )
        assert flags == [True, True]
        assert (await load_runtime_ai_settings(session, refresh=True)).reindex_required is True


def test_admin_auth_fails_closed_and_compares_real_token() -> None:
    assert admin_authorized("admin-secret") is True
    assert admin_authorized("") is False
    assert admin_authorized("wrong") is False
    os.environ.pop("PCS_ADMIN_TOKEN")
    get_settings.cache_clear()
    assert admin_authorized("") is False
    assert admin_authorized("admin-secret") is False


def test_crypto_envelope_is_strict_field_bound_and_rotation_aware() -> None:
    cfg = get_settings()
    blob = _encrypt("secret-value", field="embedding.api_key", cfg=cfg)
    assert _decrypt(blob, field="embedding.api_key", cfg=cfg) == "secret-value"
    assert _decrypt(blob, field="summary.api_key", cfg=cfg) is None
    envelope = json.loads(blob)
    envelope["extra"] = True
    assert _decrypt(json.dumps(envelope).encode(), field="embedding.api_key", cfg=cfg) is None
    envelope.pop("extra")
    envelope["c"] = envelope["c"].rstrip("=")
    assert _decrypt(json.dumps(envelope).encode(), field="embedding.api_key", cfg=cfg) is None
    os.environ["PCS_AI_SETTINGS_MASTER_KEY"] = base64.urlsafe_b64encode(b"n" * 32).decode()
    os.environ["PCS_AI_SETTINGS_KEY_ID"] = "new"
    os.environ["PCS_AI_SETTINGS_PREVIOUS_MASTER_KEY"] = KEY
    os.environ["PCS_AI_SETTINGS_PREVIOUS_KEY_ID"] = "current"
    get_settings.cache_clear()
    assert _decrypt(blob, field="embedding.api_key", cfg=get_settings()) == "secret-value"
    rotated = _encrypt("new-secret", field="embedding.api_key", cfg=get_settings())
    assert json.loads(rotated)["kid"] == "new"
    os.environ.pop("PCS_AI_SETTINGS_MASTER_KEY")
    get_settings.cache_clear()
    with pytest.raises(MasterKeyRequiredError):
        _encrypt("must-not-use-previous", field="embedding.api_key", cfg=get_settings())


async def test_exact_private_host_allowlist_permits_tailscale_only() -> None:
    os.environ["PCS_AI_PROVIDER_ALLOWED_HOSTS"] = "100.113.232.34,127.0.0.1"
    os.environ["PCS_AI_PROVIDER_ALLOWED_PRIVATE_HOSTS"] = "100.113.232.34,127.0.0.1"
    os.environ["PCS_AI_SETTINGS_ALLOW_HTTP"] = "true"
    get_settings.cache_clear()

    assert (
        await validate_provider_url("http://100.113.232.34:11434/v1")
        == "http://100.113.232.34:11434/v1"
    )
    with pytest.raises(AiSettingsError, match="prohibited network"):
        await validate_provider_url("http://127.0.0.1:11434/v1")


async def test_private_address_requires_private_host_allowlist() -> None:
    os.environ["PCS_AI_PROVIDER_ALLOWED_HOSTS"] = "100.113.232.34"
    os.environ["PCS_AI_SETTINGS_ALLOW_HTTP"] = "true"
    get_settings.cache_clear()

    with pytest.raises(AiSettingsError, match="prohibited network"):
        await validate_provider_url("http://100.113.232.34:11434/v1")


async def test_url_dns_lookup_runs_off_event_loop() -> None:
    main_thread = threading.get_ident()

    def resolved(*_args: object) -> list[tuple[object, object, object, object, tuple[str, int]]]:
        assert threading.get_ident() != main_thread
        return [(object(), object(), object(), object(), ("93.184.216.34", 443))]

    with patch("pcs.ai_settings.socket.getaddrinfo", side_effect=resolved):
        assert await validate_provider_url("https://example.com/v1") == "https://example.com/v1"


async def test_embedding_connection_is_pinned_against_dns_rebinding() -> None:
    dns_answers = ["93.184.216.34", "127.0.0.1"]
    captured: list[httpx.Request] = []

    def resolved(*_args: object) -> list[tuple[object, object, object, object, tuple[str, int]]]:
        answer = dns_answers.pop(0)
        return [(object(), object(), object(), object(), (answer, 443))]

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0]}]})

    transport = httpx.MockTransport(handler)
    original_client = httpx.AsyncClient

    def client(**_kwargs: object) -> httpx.AsyncClient:
        return original_client(transport=transport)

    backend = OpenAIEmbeddingBackend(
        base_url="https://example.com/v1", api_key="", model="m", dimensions=1, timeout=1
    )
    with (
        patch("pcs.ai_settings.socket.getaddrinfo", side_effect=resolved),
        patch("httpx.AsyncClient", side_effect=client),
    ):
        assert await backend.embed(["x"]) == [[1.0]]

    request = captured[0]
    assert request.url.host == "93.184.216.34"
    assert request.headers["host"] == "example.com"
    assert request.extensions["sni_hostname"] == b"example.com"
    assert dns_answers == ["127.0.0.1"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("backend", "x" * 33),
        ("base_url", "https://example.com/" + "x" * 2048),
        ("model", "x" * 201),
        ("api_key", "x" * 8193),
        ("dimensions", 65537),
        ("batch_size", 2049),
        ("timeout_seconds", 301),
        ("timeout_seconds", float("nan")),
        ("timeout_seconds", float("inf")),
    ],
)
@pytest.mark.usefixtures("clean_db")
async def test_strict_upper_bounds_return_safe_errors(field: str, value: object) -> None:
    payload = embedding(None, **{field: value})
    async with session_scope() as session:
        with pytest.raises(AiSettingsError) as caught:
            await update_ai_settings(session, {"embedding": payload})
    assert str(value) not in str(caught.value)


@pytest.mark.usefixtures("clean_db")
async def test_concurrent_patch_serializes_without_lost_provider_update() -> None:
    async def update(payload: dict[str, object]) -> None:
        async with session_scope() as session:
            await update_ai_settings(session, payload)

    await asyncio.gather(
        update({"embedding": embedding(None)}),
        update({"summary": summary(None)}),
    )
    async with session_scope() as session:
        loaded = await load_runtime_ai_settings(session)
    assert loaded.embedding.model == "embed-a"
    assert loaded.summary.model == "sum-a"


@pytest.mark.usefixtures("clean_db")
def test_patch_auth_and_malformed_json_are_fail_closed() -> None:
    client = TestClient(
        Starlette(routes=[Route("/api/admin/ai-settings", _patch, methods=["PATCH"])])
    )
    assert client.patch("/api/admin/ai-settings", content="{").status_code == 401
    assert (
        client.patch(
            "/api/admin/ai-settings", headers={"x-pcs-admin-token": "wrong"}, json={}
        ).status_code
        == 401
    )
    response = client.patch(
        "/api/admin/ai-settings",
        headers={"x-pcs-admin-token": "admin-secret", "content-type": "application/json"},
        content="{",
    )
    assert response.status_code == 400
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {"error": "invalid AI settings request"}
    oversized = embedding(None, model="x" * 201)
    response = client.patch(
        "/api/admin/ai-settings",
        headers={"x-pcs-admin-token": "admin-secret"},
        json={"embedding": oversized},
    )
    assert response.status_code == 400
    assert response.json() == {"error": "invalid AI settings request"}
    assert "x" * 201 not in response.text


def test_migration_roundtrip(database_url: str) -> None:
    """AC-AISET-10: migration cleanly downgrades and upgrades."""
    config = Config("alembic.ini")
    command.downgrade(config, "0019_evidence_quality")
    sync_url = database_url.replace("postgresql+psycopg", "postgresql+psycopg")
    engine = create_engine(sync_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO projects (id,name,root_path) "
                "VALUES (:id,'migration-index','/tmp/index')"
            ),
            {"id": "00000000-0000-0000-0000-000000000020"},
        )
        connection.execute(
            text(
                "INSERT INTO code_index.status "
                "(project_id,semantic_model,embedded_chunk_count) "
                "VALUES (:id,'legacy',1)"
            ),
            {"id": "00000000-0000-0000-0000-000000000020"},
        )
    engine.dispose()
    command.upgrade(config, "0020_ai_provider_settings")
    engine = create_engine(sync_url)
    with engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT reindex_required FROM code_index.status WHERE project_id=:id"),
                {"id": "00000000-0000-0000-0000-000000000020"},
            ).scalar_one()
            is True
        )
    engine.dispose()
    command.upgrade(config, "head")


@pytest.mark.usefixtures("clean_db")
async def test_full_embedding_success_records_identity_batch_and_clears(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pathlib import Path

    from sqlalchemy import func, select
    from sqlalchemy.ext.asyncio import AsyncSession

    from pcs.context import service as context_service
    from pcs.index import service as index_service
    from pcs.index.models import IndexChunk, IndexStatus

    root = Path(str(tmp_path))
    source = "def sample():\n    return 1\n"
    (root / "sample.py").write_text(source, encoding="utf-8")
    (root / "duplicate.py").write_text(source, encoding="utf-8")
    async with session_scope() as session:
        project = await context_service.register_project(
            session, name="ai-full", root_path=str(root), overview="full"
        )
        await update_ai_settings(
            session,
            {
                "embedding": embedding(
                    None,
                    backend="hashing",
                    base_url="local",
                    model="recorded-model",
                    dimensions=32,
                    batch_size=3,
                )
            },
        )

    batches: list[int] = []

    async def successful_embed(
        session: AsyncSession, *, project_id: str, backend: object, batch_size: int
    ) -> tuple[int, int]:
        del backend
        batches.append(batch_size)
        chunks = list(
            (
                await session.execute(select(IndexChunk).where(IndexChunk.project_id == project_id))
            ).scalars()
        )
        assert len(chunks) >= 2
        shared_hash = chunks[0].chunk_hash
        assert shared_hash is not None
        for chunk in chunks:
            chunk.chunk_hash = shared_hash
        await session.flush()
        distinct = await session.execute(
            select(func.count(func.distinct(IndexChunk.chunk_hash))).where(
                IndexChunk.project_id == project_id,
                IndexChunk.chunk_hash.is_not(None),
            )
        )
        total = int(distinct.scalar_one())
        return total, total

    monkeypatch.setattr(index_service, "embed_pending_chunks", successful_embed)
    async with session_scope() as session:
        result = await index_service.reindex(session, project="ai-full", incremental=False)
        status = await session.get(IndexStatus, project.id)
        assert status is not None
        assert status.reindex_required is False
        assert status.semantic_provider == "hashing"
        assert status.semantic_base_url == "local"
        assert status.semantic_model == "recorded-model"
        assert status.semantic_dimensions == 32
    assert result.state == "idle"
    assert batches == [3]


@pytest.mark.usefixtures("clean_db")
async def test_failed_full_embedding_is_observable_and_stays_incompatible(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession

    from pcs.context import service as context_service
    from pcs.index import service as index_service
    from pcs.index.models import IndexStatus

    root = Path(str(tmp_path))
    (root / "sample.py").write_text("value = 1\n", encoding="utf-8")
    async with session_scope() as session:
        project = await context_service.register_project(
            session, name="ai-failed", root_path=str(root), overview="failed"
        )
        await update_ai_settings(
            session,
            {"embedding": embedding(None, backend="hashing", base_url="local", dimensions=32)},
        )

    async def failed_embed(session: AsyncSession, **_kwargs: object) -> tuple[int, int]:
        await session.execute(
            text("UPDATE code_index.status SET semantic_model='partial' WHERE project_id=:pid"),
            {"pid": project.id},
        )
        await session.execute(text("SELECT 1 / 0 /* secret provider response */"))
        raise AssertionError("unreachable")

    monkeypatch.setattr(index_service, "embed_pending_chunks", failed_embed)
    with caplog.at_level("WARNING", logger="pcs"):
        async with session_scope() as session:
            result = await index_service.reindex(session, project="ai-failed", incremental=False)
            status = await session.get(IndexStatus, project.id)
            assert status is not None
            assert status.state == "error"
            assert status.reindex_required is True
            assert status.semantic_model != "partial"
            assert (await session.execute(text("SELECT 1"))).scalar_one() == 1
    assert result.state == "error"
    assert "secret provider response" not in caplog.text
    async with session_scope() as session:
        persisted = await session.get(IndexStatus, project.id)
        assert persisted is not None
        assert persisted.state == "error"
        assert persisted.reindex_required is True

    async def provider_failure(**_kwargs: object) -> tuple[int, int]:
        raise RuntimeError("secret provider response")

    caplog.clear()
    monkeypatch.setattr(index_service, "embed_pending_chunks", provider_failure)
    with caplog.at_level("WARNING", logger="pcs"):
        async with session_scope() as session:
            retried = await index_service.reindex(session, project="ai-failed", incremental=False)
    assert retried.state == "error"
    assert "secret provider response" not in caplog.text


@pytest.mark.usefixtures("clean_db")
async def test_incremental_embedding_never_clears_incompatibility(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pathlib import Path

    from pcs.context import service as context_service
    from pcs.index import service as index_service
    from pcs.index.embedding import HashingEmbeddingBackend, set_embedding_backend_override
    from pcs.index.models import IndexStatus

    root = Path(str(tmp_path))
    source = root / "sample.py"
    source.write_text("value = 1\n", encoding="utf-8")
    async with session_scope() as session:
        project = await context_service.register_project(
            session, name="ai-incremental", root_path=str(root), overview="incremental"
        )
    set_embedding_backend_override(HashingEmbeddingBackend(dimensions=32, model="old"))
    try:
        async with session_scope() as session:
            await index_service.reindex(session, project="ai-incremental", incremental=False)
    finally:
        set_embedding_backend_override(None, active=False)
    async with session_scope() as session:
        await update_ai_settings(
            session,
            {"embedding": embedding(None, backend="hashing", base_url="local", dimensions=32)},
        )
    source.write_text("value = 2\n", encoding="utf-8")

    async def successful_embed(**_kwargs: object) -> tuple[int, int]:
        return 1, 1

    monkeypatch.setattr(index_service, "embed_pending_chunks", successful_embed)
    async with session_scope() as session:
        await index_service.reindex(session, project="ai-incremental", incremental=True)
        status = await session.get(IndexStatus, project.id)
        assert status is not None and status.reindex_required is True
