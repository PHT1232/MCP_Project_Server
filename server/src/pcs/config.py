"""Runtime configuration (`pcs.config`).

A single pydantic-settings model, read from the environment (prefix ``PCS_``) or a
mounted ``.env`` file. Nothing in the codebase hard-codes a path, port, or
credential (AGENTS.md server conventions; FR40).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from pcs.bind import bind_host as resolve_bind_host

BindMode = Literal["localhost", "tailscale"]


class Settings(BaseSettings):
    """Every configuration value the process reads. See ``.env.example``."""

    model_config = SettingsConfigDict(
        env_prefix="PCS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = Field(
        default="postgresql+psycopg://pcs:pcs@localhost:5432/pcs",
        description="SQLAlchemy async URL for the PostgreSQL store (D1, FR4).",
    )
    host: str = Field(
        default="127.0.0.1",
        description="Unused for the actual bind; see bind_mode / bind_address / bind_host (NFR14).",
    )
    port: int = Field(
        default=8080,
        description="Port for the streamable-HTTP MCP transport and the /api routes (NFR3).",
    )
    bind_mode: BindMode = Field(
        default="localhost",
        description=(
            "'localhost' binds `bind_address` (default 127.0.0.1). "
            "'tailscale' binds the tailnet IPv4 (FR41, NFR14)."
        ),
    )
    bind_address: str = Field(
        default="",
        description=(
            "Explicit HTTP listen address for bind_mode=localhost. Empty → 127.0.0.1. "
            "Docker deployments set 0.0.0.0 here and rely on the loopback-only host "
            "port publish in deploy/docker-compose.yml for NFR14 (B1)."
        ),
    )
    tailscale_ip: str = Field(
        default="",
        description="Optional explicit tailnet IPv4 when bind_mode=tailscale (FR41).",
    )
    tailscale_iface: str = Field(
        default="tailscale0",
        description="Interface probed for a tailnet IPv4 when PCS_TAILSCALE_IP is unset.",
    )
    tailscale_serve: bool = Field(
        default=False,
        description="When true, the Tailscale sidecar should run tailscale serve for HTTPS (FR41).",
    )
    static_dir: str = Field(
        default="",
        description="Directory of the built web/ frontend to serve (NFR13). Empty disables.",
    )
    log_level: str = Field(
        default="INFO",
        description="Root level for the structured `pcs` logger (NFR6).",
    )
    index_ignore: str = Field(
        default="",
        description="Comma-separated extra gitignore patterns to skip when indexing (FR19).",
    )
    index_allow: str = Field(
        default="",
        description="If set, only paths matching these gitignore patterns are indexed (FR19).",
    )
    index_max_file_bytes: int = Field(
        default=1_000_000,
        description="Skip source files larger than this many bytes (FR19).",
    )
    index_watch: bool = Field(
        default=True,
        description="Watch registered project roots and trigger incremental reindex (FR24).",
    )

    @property
    def bind_host(self) -> str:
        """Address the HTTP server actually binds (FR41, NFR14, AC26).

        ``localhost`` → ``bind_address`` (default ``127.0.0.1``; ``0.0.0.0`` in a
        container behind a loopback-only publish). ``tailscale`` → the tailnet
        IPv4, validated to ``100.64.0.0/10``. stdio MCP does not call this (FR42).
        Memoised in :mod:`pcs.bind`.
        """
        return resolve_bind_host(
            mode=self.bind_mode,
            explicit=self.bind_address,
            tailscale_ip=self.tailscale_ip,
            tailscale_iface=self.tailscale_iface,
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton."""
    return Settings()
