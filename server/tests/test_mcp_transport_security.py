"""MCP DNS-rebinding allowlist (`PCS_MCP_ALLOWED_HOSTS` / `PCS_MCP_ALLOWED_ORIGINS`).

FastMCP auto-enables DNS-rebinding protection for `host=127.0.0.1`, which by
default only accepts a localhost `Host` header. A remote request through a
Tailscale IP or a Tailscale Serve hostname then gets `421 Misdirected Request`
("Invalid Host header"). `pcs.mcp.server._mcp_transport_security()` widens the
allowlist from configuration while keeping protection on and failing closed on a
`*`.

The request-level tests build a *fresh* `FastMCP` per case so they never touch
the module-level singleton's one-shot session manager.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from starlette.testclient import TestClient

from pcs.config import get_settings
from pcs.mcp import server as mcp_server


@pytest.fixture(autouse=True)
def _clean_allowlist(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Every test starts from the empty (localhost-only) allowlist."""
    monkeypatch.setattr(mcp_server._settings, "mcp_allowed_hosts", "")
    monkeypatch.setattr(mcp_server._settings, "mcp_allowed_origins", "")
    yield
    get_settings.cache_clear()


def _configure(monkeypatch: pytest.MonkeyPatch, *, hosts: str = "", origins: str = "") -> None:
    monkeypatch.setattr(mcp_server._settings, "mcp_allowed_hosts", hosts)
    monkeypatch.setattr(mcp_server._settings, "mcp_allowed_origins", origins)


def _mcp_client() -> TestClient:
    """A TestClient over a throwaway FastMCP built with the current allowlist."""
    from mcp.server.fastmcp import FastMCP

    fresh = FastMCP(
        "pcs-transport-security-test",
        host="127.0.0.1",
        transport_security=mcp_server._mcp_transport_security(),
    )
    return TestClient(fresh.streamable_http_app())


def _reached_mcp_handler(response: object) -> bool:
    """A non-421 response whose body is not the Host rejection = request got through."""
    status = getattr(response, "status_code", None)
    text = getattr(response, "text", "")
    return status != 421 and "Invalid Host header" not in text


# --------------------------------------------------------------------------- #
# Pattern building (`_mcp_transport_security` / helpers)
# --------------------------------------------------------------------------- #


def test_empty_config_is_localhost_only() -> None:
    security = mcp_server._mcp_transport_security()
    assert security.enable_dns_rebinding_protection is True
    assert security.allowed_hosts == list(mcp_server._DEFAULT_ALLOWED_HOSTS)
    assert security.allowed_origins == list(mcp_server._DEFAULT_ALLOWED_ORIGINS)


def test_configured_hosts_and_origins_are_added_localhost_kept(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(
        monkeypatch,
        hosts="100.86.141.82:*, pcs.example-tailnet.ts.net",
        origins="http://100.86.141.82:*, https://pcs.example-tailnet.ts.net",
    )
    security = mcp_server._mcp_transport_security()

    assert "127.0.0.1:*" in security.allowed_hosts  # localhost still allowed
    assert "100.86.141.82:*" in security.allowed_hosts
    # a bare hostname is expanded to match with or without a port
    assert "pcs.example-tailnet.ts.net" in security.allowed_hosts
    assert "pcs.example-tailnet.ts.net:*" in security.allowed_hosts
    assert "http://100.86.141.82:*" in security.allowed_origins
    assert "https://pcs.example-tailnet.ts.net" in security.allowed_origins
    assert "https://pcs.example-tailnet.ts.net:*" in security.allowed_origins


@pytest.mark.parametrize("bad", ["*", "*.tailnet.ts.net", "100.86.*.*", "pcs*", ":*"])
def test_stray_wildcard_in_hosts_fails_closed(monkeypatch: pytest.MonkeyPatch, bad: str) -> None:
    _configure(monkeypatch, hosts=bad)
    with pytest.raises(ValueError, match="wildcard"):
        mcp_server._mcp_transport_security()


@pytest.mark.parametrize("bad", ["*", "http://*", "https://*.ts.net"])
def test_stray_wildcard_in_origins_fails_closed(monkeypatch: pytest.MonkeyPatch, bad: str) -> None:
    _configure(monkeypatch, origins=bad)
    with pytest.raises(ValueError, match="wildcard"):
        mcp_server._mcp_transport_security()


def test_origin_entry_must_be_a_full_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(monkeypatch, origins="pcs.example-tailnet.ts.net")
    with pytest.raises(ValueError, match="full origin"):
        mcp_server._mcp_transport_security()


# --------------------------------------------------------------------------- #
# Request-level behaviour through the middleware (the actual 421)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "host",
    ["evil.example.com", "attacker.test:8989", "100.99.0.5:8989", "pcs.other-tailnet.ts.net"],
)
def test_unlisted_remote_host_gets_421(monkeypatch: pytest.MonkeyPatch, host: str) -> None:
    _configure(monkeypatch, hosts="100.86.141.82:*,pcs.example-tailnet.ts.net")
    with _mcp_client() as client:
        response = client.get("/mcp", headers={"host": host})
    assert response.status_code == 421
    assert "Invalid Host header" in response.text


@pytest.mark.parametrize(
    "host",
    [
        "100.86.141.82:8989",  # direct tailnet IP  (matches 100.86.141.82:*)
        "pcs.example-tailnet.ts.net",  # Tailscale Serve name on 443, no port in Host
        "pcs.example-tailnet.ts.net:8989",  # same name via bind_mode=tailscale on the app port
    ],
)
def test_configured_tailnet_host_reaches_the_mcp_handler(
    monkeypatch: pytest.MonkeyPatch, host: str
) -> None:
    _configure(
        monkeypatch,
        hosts="100.86.141.82:*,pcs.example-tailnet.ts.net",
        origins="http://100.86.141.82:*,https://pcs.example-tailnet.ts.net",
    )
    with _mcp_client() as client:
        response = client.get("/mcp", headers={"host": host})
    assert _reached_mcp_handler(response), (response.status_code, response.text)


def test_localhost_still_accepted_without_any_configuration() -> None:
    with _mcp_client() as client:
        response = client.get("/mcp", headers={"host": "127.0.0.1:8989"})
    assert _reached_mcp_handler(response), (response.status_code, response.text)


def test_native_client_without_origin_is_not_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    """A native MCP client (e.g. Zed) sends no Origin header — it must not be 403/421."""
    _configure(
        monkeypatch,
        hosts="100.86.141.82:*",
        origins="http://100.86.141.82:*",
    )
    with _mcp_client() as client:
        response = client.get("/mcp", headers={"host": "100.86.141.82:8989"})  # no Origin
    assert response.status_code not in {403, 421}, (response.status_code, response.text)


def test_browser_origin_must_be_on_the_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(
        monkeypatch,
        hosts="100.86.141.82:*",
        origins="http://100.86.141.82:*",
    )
    with _mcp_client() as client:
        allowed = client.get(
            "/mcp",
            headers={"host": "100.86.141.82:8989", "origin": "http://100.86.141.82:8989"},
        )
        refused = client.get(
            "/mcp",
            headers={"host": "100.86.141.82:8989", "origin": "http://evil.test"},
        )
    assert allowed.status_code not in {403, 421}
    assert refused.status_code == 403
    assert "Invalid Origin header" in refused.text


def test_bare_wildcard_config_never_produces_a_permissive_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`PCS_MCP_ALLOWED_HOSTS=*` fails closed — the server cannot start with it."""
    _configure(monkeypatch, hosts="*")
    with pytest.raises(ValueError, match="wildcard"):
        _mcp_client()
