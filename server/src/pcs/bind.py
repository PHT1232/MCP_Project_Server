"""HTTP bind-address policy (FR41, NFR14, AC26).

``localhost`` always binds loopback. ``tailscale`` binds the tailnet IPv4 and
never a wildcard or LAN/public address.
"""

from __future__ import annotations

import fcntl
import socket
import struct
import subprocess
from typing import Final, Protocol, runtime_checkable

SIOCGIFADDR: Final = 0x8915
_WILDCARDS: Final[frozenset[str]] = frozenset({"0.0.0.0", "::", "[::]", "::0", "*"})
_LOOPBACK_PREFIXES: Final[tuple[str, ...]] = ("127.", "::1")


class BindError(RuntimeError):
    """The process would have bound a disallowed address (NFR14)."""


@runtime_checkable
class _HostSettings(Protocol):
    """Narrow FastMCP ``settings`` to the assignable ``host`` field (FR41)."""

    host: str


def is_wildcard(address: str) -> bool:
    """True if ``address`` would listen on every interface."""
    return address.strip().lower() in _WILDCARDS


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
    Wildcards and loopback are rejected so we never fall open to LAN/public.
    """
    candidates = [configured.strip(), _tailscale_cli_ipv4() or "", _ioctl_ipv4(iface) or ""]
    for raw in candidates:
        if not raw:
            continue
        if is_wildcard(raw) or raw.startswith(_LOOPBACK_PREFIXES):
            raise BindError(
                f"refusing to bind {raw!r} in tailscale mode; "
                "that would expose the server beyond the tailnet (NFR14, AC26)."
            )
        return raw
    raise BindError(
        "bind_mode='tailscale' but no tailnet IPv4 was found. "
        "Join the tailnet, or set PCS_TAILSCALE_IP to the 100.x address (FR41)."
    )


def bind_host(
    *,
    mode: str,
    tailscale_ip: str = "",
    tailscale_iface: str = "tailscale0",
) -> str:
    """Select the listen address for streamable-HTTP (FR41, NFR14)."""
    if mode == "localhost":
        return "127.0.0.1"
    if mode == "tailscale":
        return resolve_tailscale_ipv4(configured=tailscale_ip, iface=tailscale_iface)
    raise BindError(f"unknown bind_mode {mode!r}; use 'localhost' or 'tailscale'")


def apply_listen_host(mcp: object, host: str) -> None:
    """Point FastMCP's streamable-HTTP server at ``host`` (FR41)."""
    settings_obj = getattr(mcp, "settings", None)
    if not isinstance(settings_obj, _HostSettings):
        raise BindError("FastMCP settings.host is missing; cannot apply bind_host")
    settings_obj.host = host
