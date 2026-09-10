"""HTTP bind-address policy (FR41, NFR14, AC26).

``localhost`` binds ``PCS_BIND_ADDRESS`` (default loopback). ``tailscale`` binds
the tailnet IPv4 — validated to be inside ``100.64.0.0/10`` and never a wildcard
or loopback.

Container deployments run ``bind_mode=localhost`` with ``PCS_BIND_ADDRESS=0.0.0.0``:
the process must listen on the container's routable interface for Docker's
published port to reach it. The NFR14 boundary there is the **host-side** port
publish (``127.0.0.1:8080:8080`` in ``deploy/docker-compose.yml``), not the
in-container bind.
"""

from __future__ import annotations

import fcntl
import ipaddress
import socket
import struct
import subprocess
from functools import lru_cache
from typing import Final, Protocol, runtime_checkable

SIOCGIFADDR: Final = 0x8915
_WILDCARDS: Final[frozenset[str]] = frozenset({"0.0.0.0", "::", "[::]", "::0", "*"})
_LOOPBACK_PREFIXES: Final[tuple[str, ...]] = ("127.", "::1")
# Tailscale hands out addresses from the CGNAT range 100.64.0.0/10 (FR41, NFR14).
_TAILNET: Final = ipaddress.ip_network("100.64.0.0/10")


class BindError(RuntimeError):
    """The process would have bound a disallowed address (NFR14)."""


@runtime_checkable
class _HostSettings(Protocol):
    """Narrow FastMCP ``settings`` to the assignable ``host`` field (FR41)."""

    host: str


def is_wildcard(address: str) -> bool:
    """True if ``address`` would listen on every interface."""
    return address.strip().lower() in _WILDCARDS


def _is_tailnet(address: str) -> bool:
    try:
        return ipaddress.ip_address(address) in _TAILNET
    except ValueError:
        return False


def _guard_tailnet(address: str) -> str:
    """Return ``address`` if it is a bindable tailnet IPv4, else raise (NFR14, AC26)."""
    if is_wildcard(address) or address.startswith(_LOOPBACK_PREFIXES):
        raise BindError(
            f"refusing to bind {address!r} in tailscale mode; "
            "that would expose the server beyond the tailnet (NFR14, AC26)."
        )
    if not _is_tailnet(address):
        raise BindError(
            f"{address!r} is not a Tailscale address (100.64.0.0/10); refusing to bind "
            "it in tailscale mode — that could expose the server on the LAN (NFR14, AC26)."
        )
    return address


def _ioctl_ipv4(iface: str) -> str | None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        packed = struct.pack("256s", iface.encode("ascii")[:15])
        result = fcntl.ioctl(sock.fileno(), SIOCGIFADDR, packed)
        return socket.inet_ntoa(result[20:24])
    except OSError:
        return None
    finally:
        sock.close()


def _tailscale_cli_ipv4() -> str | None:
    try:
        proc = subprocess.run(
            ["tailscale", "ip", "-4"],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0:
        return None
    line = proc.stdout.strip().splitlines()
    return line[0].strip() if line else None


def resolve_tailscale_ipv4(*, configured: str = "", iface: str = "tailscale0") -> str:
    """Return the IPv4 to bind in ``bind_mode=tailscale`` (FR41).

    Order: explicit ``PCS_TAILSCALE_IP``, ``tailscale ip -4``, then ``iface``.
    Every candidate must be a bindable address inside ``100.64.0.0/10`` — a
    wildcard, loopback, or LAN address is rejected so we never fall open.
    """
    candidates = [configured.strip(), _tailscale_cli_ipv4() or "", _ioctl_ipv4(iface) or ""]
    for raw in candidates:
        if not raw:
            continue
        return _guard_tailnet(raw)
    raise BindError(
        "bind_mode='tailscale' but no tailnet IPv4 was found. "
        "Join the tailnet, or set PCS_TAILSCALE_IP to the 100.x address (FR41)."
    )


def _compute_bind_host(
    *,
    mode: str,
    explicit: str,
    tailscale_ip: str,
    tailscale_iface: str,
) -> str:
    if mode == "localhost":
        # Honoured verbatim. Default is loopback; containers set 0.0.0.0 and rely
        # on the loopback-only host port publish for NFR14.
        return explicit.strip() or "127.0.0.1"
    if mode == "tailscale":
        # PCS_BIND_ADDRESS does not apply here — use PCS_TAILSCALE_IP for an
        # explicit tailnet address.
        return resolve_tailscale_ipv4(configured=tailscale_ip, iface=tailscale_iface)
    raise BindError(f"unknown bind_mode {mode!r}; use 'localhost' or 'tailscale'")


@lru_cache(maxsize=4)
def _cached_bind_host(mode: str, explicit: str, tailscale_ip: str, tailscale_iface: str) -> str:
    return _compute_bind_host(
        mode=mode, explicit=explicit, tailscale_ip=tailscale_ip, tailscale_iface=tailscale_iface
    )


def bind_host(
    *,
    mode: str,
    explicit: str = "",
    tailscale_ip: str = "",
    tailscale_iface: str = "tailscale0",
) -> str:
    """Select the listen address for streamable-HTTP (FR41, NFR14).

    Memoised: in ``tailscale`` mode this avoids re-running ``tailscale ip -4`` on
    every ``/api/health`` request. Call :func:`reset_cache` after changing the
    environment (tests do).
    """
    return _cached_bind_host(mode, explicit, tailscale_ip, tailscale_iface)


def reset_cache() -> None:
    """Clear the memoised bind-host resolution (tests, config reloads)."""
    _cached_bind_host.cache_clear()


def apply_listen_host(mcp: object, host: str) -> None:
    """Point FastMCP's streamable-HTTP server at ``host`` (FR41)."""
    settings_obj = getattr(mcp, "settings", None)
    if not isinstance(settings_obj, _HostSettings):
        raise BindError("FastMCP settings.host is missing; cannot apply bind_host")
    settings_obj.host = host
