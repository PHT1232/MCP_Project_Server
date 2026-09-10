"""Deploy / bind-mode tests (FR40-FR42, NFR14, AC25, AC26)."""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from pcs.bind import BindError, bind_host, is_wildcard, resolve_tailscale_ipv4
from pcs.config import get_settings
from pcs.web_static import register_frontend

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "deploy" / "docker-compose.yml"
COMPOSE_TS = ROOT / "deploy" / "docker-compose.tailscale.yml"


@pytest.fixture(autouse=True)
def _clear_settings() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_wildcard_detection() -> None:
    assert is_wildcard("0.0.0.0")
    assert is_wildcard("::")
    assert not is_wildcard("127.0.0.1")
    assert not is_wildcard("100.64.0.1")


def test_localhost_bind_is_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PCS_BIND_MODE", "localhost")
    get_settings.cache_clear()
    assert get_settings().bind_host == "127.0.0.1"
    assert bind_host(mode="localhost") == "127.0.0.1"


def test_tailscale_uses_configured_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PCS_BIND_MODE", "tailscale")
    monkeypatch.setenv("PCS_TAILSCALE_IP", "100.64.1.20")
    get_settings.cache_clear()
    assert get_settings().bind_host == "100.64.1.20"


def test_ac26_tailscale_rejects_wildcard_and_loopback() -> None:
    with pytest.raises(BindError, match="beyond the tailnet"):
        resolve_tailscale_ipv4(configured="0.0.0.0")
    with pytest.raises(BindError, match="beyond the tailnet"):
        resolve_tailscale_ipv4(configured="127.0.0.1")


def test_tailscale_missing_ip_is_an_error() -> None:
    with (
        patch("pcs.bind._tailscale_cli_ipv4", return_value=None),
        patch("pcs.bind._ioctl_ipv4", return_value=None),
        pytest.raises(BindError, match="no tailnet IPv4"),
    ):
        resolve_tailscale_ipv4(configured="")


def test_fr42_stdio_import_does_not_resolve_tailscale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Importing the MCP app must not call bind_host (FR42)."""
    monkeypatch.setenv("PCS_BIND_MODE", "tailscale")
    monkeypatch.delenv("PCS_TAILSCALE_IP", raising=False)
    get_settings.cache_clear()
    from pcs.mcp.server import mcp

    assert mcp.settings.host == "127.0.0.1"


def test_ac25_compose_stack_has_server_postgres_and_safe_mounts() -> None:
    text = COMPOSE.read_text(encoding="utf-8")
    assert "image: pgvector/pgvector:pg16" in text
    assert "dockerfile: deploy/Dockerfile.server" in text
    assert "127.0.0.1:${PCS_PORT:-8080}:8080" in text
    assert "127.0.0.1:5432:5432" in text
    assert "0.0.0.0" not in text
    assert "Funnel" not in text or "must not" in text
    assert "pcs_pgdata" in text
    assert "pcs_index" in text
    assert "read_only: true" in text
    assert "target: /repos/.project-context" in text
    assert "read_only: false" in text
    assert "alembic" in (ROOT / "deploy" / "entrypoint.sh").read_text(encoding="utf-8")
    assert "pcs http" in (ROOT / "deploy" / "entrypoint.sh").read_text(encoding="utf-8")


def test_ac26_tailscale_overlay_never_publishes_lan() -> None:
    text = COMPOSE_TS.read_text(encoding="utf-8")
    assert "network_mode: service:tailscale" in text
    assert "PCS_BIND_MODE: tailscale" in text
    assert "0.0.0.0" not in text
    assert "--funnel" not in text.lower()
    assert "Funnel is not passed" in text
    assert "tailscale/tailscale" in text


def test_compose_files_lint() -> None:
    """AC25: compose files render (docker compose config)."""
    base = [
        "docker",
        "compose",
        "-f",
        str(COMPOSE),
        "config",
        "-q",
    ]
    subprocess.run(base, check=True, cwd=ROOT)
    subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(COMPOSE),
            "-f",
            str(COMPOSE_TS),
            "config",
            "-q",
        ],
        check=True,
        cwd=ROOT,
    )


def test_frontend_is_served_when_static_dir_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dist = tmp_path / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text("<html>pcs</html>", encoding="utf-8")
    (assets / "app.js").write_text("console.log(1)", encoding="utf-8")
    monkeypatch.setenv("PCS_STATIC_DIR", str(dist))
    get_settings.cache_clear()
    from starlette.applications import Starlette

    app = Starlette()
    register_frontend(app)
    with TestClient(app) as client:
        home = client.get("/")
        assert home.status_code == 200
        assert b"pcs" in home.content
        asset = client.get("/assets/app.js")
        assert asset.status_code == 200


def test_images_do_not_mention_auth_keys() -> None:
    dockerfile = (ROOT / "deploy" / "Dockerfile.server").read_text(encoding="utf-8")
    assert "tskey" not in dockerfile.lower()
    assert "TS_AUTHKEY" not in dockerfile
    assert "POSTGRES_PASSWORD" not in dockerfile
