"""FastMCP app: context-store tools + resources over stdio and streamable HTTP.

Tool bodies delegate to :mod:`pcs.context.service` (unit-tested without this
layer) and emit the mandatory audit line for every call (NFR6). Unknown/missing
``project`` raises :class:`~pcs.context.service.ProjectNotFoundError`, whose
message lists the registered projects (D3, FR8, AC16).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette

from pcs.config import get_settings
from pcs.index import watch as index_watch
from pcs.mcp.codemap_tools import register_codemap_tools
from pcs.mcp.compliance_tools import register_compliance_tools
from pcs.mcp.contract_tools import register_contract_tools
from pcs.mcp.evidence_tools import register_evidence_tools
from pcs.mcp.index_tools import register_index_tools
from pcs.mcp.planning_tools import register_planning_tools
from pcs.mcp.resources import register_resources
from pcs.mcp.tools import register_tools
from pcs.web_api import register_routes
from pcs.web_api.ai_settings_routes import register_ai_settings_routes
from pcs.web_api.codemap_routes import register_codemap_routes
from pcs.web_api.index_routes import register_index_routes
from pcs.web_api.planning_routes import register_planning_routes
from pcs.web_api.requirements_routes import register_requirement_routes
from pcs.web_api.source_routes import register_source_routes
from pcs.web_static import register_frontend

_settings = get_settings()


# Localhost is always allowed — identical to FastMCP's own auto-generated default
# for host=127.0.0.1 (mcp.server.fastmcp.server.FastMCP.__init__).
_DEFAULT_ALLOWED_HOSTS = ("127.0.0.1:*", "localhost:*", "[::1]:*")
_DEFAULT_ALLOWED_ORIGINS = ("http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*")


def _reject_stray_wildcard(entry: str, var: str) -> None:
    """FastMCP only understands a trailing ``:*`` port wildcard — reject anything else.

    Fails closed on a bare ``*``, ``*.example.com``, ``http://*``, etc. so an
    allowlist entry can never silently widen to "accept any Host" (NFR14).
    """
    core = entry[:-2] if entry.endswith(":*") else entry
    if not core or "*" in core:
        raise ValueError(
            f"{var} entry {entry!r} is invalid: only a trailing ':*' port wildcard "
            "is allowed, never a bare or embedded '*'"
        )


def _host_has_port(host: str) -> bool:
    # Bracketed IPv6 literal: [::1] vs [::1]:8989
    return "]:" in host if host.startswith("[") else ":" in host


def _expand_host_patterns(raw: str, var: str) -> list[str]:
    """Split, validate, and expand a comma-separated Host allowlist.

    A bare host/IP (no explicit port) also gets a ``host:*`` form so it matches
    whether or not the client sends a port — e.g. a Tailscale Serve name reached
    on 443 (``Host: pcs.tail.ts.net``) and the same name via ``bind_mode=tailscale``
    on the app port (``Host: pcs.tail.ts.net:8989``).
    """
    out: list[str] = []
    for entry in (item.strip() for item in raw.split(",")):
        if not entry:
            continue
        _reject_stray_wildcard(entry, var)
        out.append(entry)
        if not entry.endswith(":*") and not _host_has_port(entry):
            out.append(f"{entry}:*")
    return out


def _expand_origin_patterns(raw: str, var: str) -> list[str]:
    """As :func:`_expand_host_patterns`, but each entry must be a full origin."""
    out: list[str] = []
    for entry in (item.strip() for item in raw.split(",")):
        if not entry:
            continue
        _reject_stray_wildcard(entry, var)
        scheme, sep, host = entry.partition("://")
        if not sep or not scheme or not host:
            raise ValueError(f"{var} entry {entry!r} must be a full origin, e.g. https://host")
        out.append(entry)
        if not entry.endswith(":*") and not _host_has_port(host):
            out.append(f"{entry}:*")
    return out


def _mcp_transport_security() -> TransportSecuritySettings:
    """Explicit MCP Host/Origin allowlist that keeps DNS-rebinding protection on.

    Localhost is always accepted. Remote hosts/origins (a Tailscale IP or Serve
    hostname) are opt-in via ``PCS_MCP_ALLOWED_HOSTS`` / ``PCS_MCP_ALLOWED_ORIGINS``
    (NFR14, FR41). An Origin header is *not* required — a native MCP client that
    omits it (e.g. Zed) still passes; only a browser that sends an unlisted
    Origin is refused (FastMCP ``_validate_origin``). A bare/embedded ``*`` in
    either list fails closed at startup.
    """
    extra_hosts = _expand_host_patterns(_settings.mcp_allowed_hosts, "PCS_MCP_ALLOWED_HOSTS")
    extra_origins = _expand_origin_patterns(
        _settings.mcp_allowed_origins, "PCS_MCP_ALLOWED_ORIGINS"
    )
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=list(dict.fromkeys([*_DEFAULT_ALLOWED_HOSTS, *extra_hosts])),
        allowed_origins=list(dict.fromkeys([*_DEFAULT_ALLOWED_ORIGINS, *extra_origins])),
    )


# Host is 127.0.0.1 at import so stdio (and tests) never resolve a tailnet IP
# (FR42). ``pcs http`` overwrites ``mcp.settings.host`` with bind_host first.
mcp: FastMCP = FastMCP(
    "pcs",
    instructions=(
        "Project Context MCP Server. Every call must name its project explicitly "
        "(name or id). Fetch a briefing with get_project_briefing; drill into "
        "verbatim detail with get_section / get_entry / context:// resources. "
        "Writes go through add_*/update_*/resolve_* (never inferred)."
    ),
    host="127.0.0.1",
    port=_settings.port,
    transport_security=_mcp_transport_security(),
)

register_tools(mcp)
register_contract_tools(mcp)
register_compliance_tools(mcp)
register_index_tools(mcp)
register_codemap_tools(mcp)
register_evidence_tools(mcp)
register_planning_tools(mcp)
register_resources(mcp)
register_routes(mcp)
register_ai_settings_routes(mcp)
register_requirement_routes(mcp)
register_index_routes(mcp)
register_codemap_routes(mcp)
register_source_routes(mcp)
register_planning_routes(mcp)


def build_http_app() -> Starlette:
    """The streamable-HTTP MCP app with the ``/api`` routes mounted."""
    app = mcp.streamable_http_app()
    inner = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app_: Starlette) -> AsyncIterator[None]:
        await index_watch.start_all()
        try:
            async with inner(app_):
                yield
        finally:
            await index_watch.stop_all()

    app.router.lifespan_context = lifespan
    register_frontend(app)
    return app
