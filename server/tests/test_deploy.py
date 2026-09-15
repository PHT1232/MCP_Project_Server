"""Deploy / bind-mode tests (FR40-FR42, NFR14, AC25, AC26)."""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from pcs import bind as bind_mod
from pcs.bind import BindError, bind_host, is_wildcard, resolve_tailscale_ipv4
from pcs.config import get_settings
from pcs.web_static import register_frontend

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "deploy" / "docker-compose.yml"
COMPOSE_TS = ROOT / "deploy" / "docker-compose.tailscale.yml"
DOCKERFILE = ROOT / "deploy" / "Dockerfile.server"


@pytest.fixture(autouse=True)
def _clear_settings() -> Iterator[None]:
    get_settings.cache_clear()
    bind_mod.reset_cache()
    yield
    get_settings.cache_clear()
    bind_mod.reset_cache()


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


def test_b1_localhost_bind_address_is_honoured(monkeypatch: pytest.MonkeyPatch) -> None:
    """Containers set PCS_BIND_ADDRESS=0.0.0.0 so the published port is reachable (B1)."""
    monkeypatch.setenv("PCS_BIND_MODE", "localhost")
    monkeypatch.setenv("PCS_BIND_ADDRESS", "0.0.0.0")
    get_settings.cache_clear()
    bind_mod.reset_cache()
    assert get_settings().bind_host == "0.0.0.0"
    assert bind_host(mode="localhost", explicit="0.0.0.0") == "0.0.0.0"


def test_b1_compose_server_binds_a_routable_address() -> None:
    text = COMPOSE.read_text(encoding="utf-8")
    assert "PCS_BIND_ADDRESS: ${PCS_BIND_ADDRESS:-0.0.0.0}" in text
    assert "PCS_MCP_ALLOWED_HOSTS: ${PCS_MCP_ALLOWED_HOSTS:-}" in text
    assert "PCS_MCP_ALLOWED_ORIGINS: ${PCS_MCP_ALLOWED_ORIGINS:-}" in text
    assert "PCS_AI_SETTINGS_ALLOW_HTTP: ${PCS_AI_SETTINGS_ALLOW_HTTP:-false}" in text
    assert (
        "PCS_AI_PROVIDER_ALLOWED_PRIVATE_HOSTS: ${PCS_AI_PROVIDER_ALLOWED_PRIVATE_HOSTS:-}" in text
    )


def test_b1_bind_address_is_ignored_in_tailscale_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 0.0.0.0 from the base compose must not leak into tailscale mode (overlay)."""
    monkeypatch.setenv("PCS_BIND_MODE", "tailscale")
    monkeypatch.setenv("PCS_BIND_ADDRESS", "0.0.0.0")
    monkeypatch.setenv("PCS_TAILSCALE_IP", "100.100.5.5")
    get_settings.cache_clear()
    bind_mod.reset_cache()
    assert get_settings().bind_host == "100.100.5.5"


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


def test_s2_tailscale_rejects_lan_ip() -> None:
    """A misconfigured PCS_TAILSCALE_IP on the LAN must not be bound (NFR14)."""
    with pytest.raises(BindError, match="not a Tailscale address"):
        resolve_tailscale_ipv4(configured="192.168.1.5")
    with pytest.raises(BindError, match="not a Tailscale address"):
        resolve_tailscale_ipv4(configured="10.0.0.4")
    # A real CGNAT address is accepted.
    assert resolve_tailscale_ipv4(configured="100.100.1.20") == "100.100.1.20"


def test_s3_tailscale_resolution_is_memoised(monkeypatch: pytest.MonkeyPatch) -> None:
    """/api/health must not shell out to `tailscale ip -4` on every call (S3)."""
    calls = {"n": 0}

    def fake_cli() -> str:
        calls["n"] += 1
        return "100.64.9.9"

    monkeypatch.setattr(bind_mod, "_tailscale_cli_ipv4", fake_cli)
    monkeypatch.setattr(bind_mod, "_ioctl_ipv4", lambda _iface: None)
    bind_mod.reset_cache()
    first = bind_host(mode="tailscale")
    second = bind_host(mode="tailscale")
    assert first == second == "100.64.9.9"
    assert calls["n"] == 1


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
    # No wildcard *host* publish — 0.0.0.0 only appears as the container-internal
    # PCS_BIND_ADDRESS (B1), never in a `ports:` mapping.
    for line in text.splitlines():
        if "0.0.0.0" in line:
            assert "PCS_BIND_ADDRESS" in line, f"unexpected wildcard: {line.strip()}"
    assert "Funnel" not in text or "must not" in text
    assert "pcs_pgdata" in text
    assert "pcs_index" in text
    # /repos is mounted read-write: the requirements file (FR16a) is written back
    # into each project's own .project-context/, at any root — not just /repos.
    assert "target: /repos" in text
    assert "read_only: true" not in text
    assert "/repos/.project-context" not in text
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


def test_b2_build_http_app_registers_the_spa(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The app `pcs http` serves (build_http_app) carries the SPA routes (B2).

    Cannot open a TestClient here — StreamableHTTPSessionManager.run() is
    one-shot per process and test_integration already uses it.
    """
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>pcs-spa</html>", encoding="utf-8")
    monkeypatch.setenv("PCS_STATIC_DIR", str(dist))
    get_settings.cache_clear()
    from pcs.mcp import build_http_app

    app = build_http_app()
    paths = [getattr(r, "path", None) for r in app.routes]
    assert "/" in paths
    assert "/{path:path}" in paths  # SPA fallback for client-side routes
    assert paths.index("/api/health") < paths.index("/{path:path}")  # API wins


async def test_b2_spa_shell_excludes_api_and_mcp_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>pcs-spa</html>", encoding="utf-8")
    monkeypatch.setenv("PCS_STATIC_DIR", str(dist))
    get_settings.cache_clear()
    from starlette.applications import Starlette
    from starlette.testclient import TestClient as _TC

    app = Starlette()
    register_frontend(app)
    with _TC(app) as client:
        assert client.get("/projects/abc").status_code == 200  # SPA route
        assert b"pcs-spa" in client.get("/projects/abc").content
        assert client.get("/api/anything").status_code == 404  # not the shell
        assert client.get("/mcp").status_code == 404


def test_b2_http_entrypoint_uses_build_http_app_not_mcp_run() -> None:
    """`pcs http` must serve the wrapped app (frontend + watch lifespan), not
    FastMCP.run() which builds a bare streamable_http_app (B2/B3)."""
    src = (ROOT / "server" / "src" / "pcs" / "__main__.py").read_text(encoding="utf-8")
    assert "build_http_app(" in src
    assert 'transport="streamable-http"' not in src


def test_images_do_not_mention_auth_keys() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    assert "tskey" not in dockerfile.lower()
    assert "TS_AUTHKEY" not in dockerfile
    assert "POSTGRES_PASSWORD" not in dockerfile


def test_s1_runtime_image_installs_git() -> None:
    """The code index shells out to git; the runtime image must ship it (S1)."""
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    runtime = dockerfile.split("# --- runtime ---", 1)[1]
    assert "install -y --no-install-recommends git" in runtime
