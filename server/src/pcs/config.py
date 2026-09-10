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

BindMode = Literal["localhost", "tailscale"]


class Settings(BaseSettings):
    """Every configuration value the skeleton reads. See ``.env.example``."""

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
        description="Configured HTTP host. Only honoured verbatim once T08 adds tailscale binding.",
    )
    port: int = Field(
        default=8080,
        description="Port for the streamable-HTTP MCP transport and the /api routes (NFR3).",
    )
    bind_mode: BindMode = Field(
        default="localhost",
        description="'localhost' binds 127.0.0.1 (NFR14). 'tailscale' is a T08 seam.",
    )
    log_level: str = Field(
        default="INFO",
        description="Root level for the structured `pcs` logger (NFR6).",
    )
    index_ignore: str = Field(
        default="",
        description="Comma-separated extra gitwildmatch patterns to skip when indexing (FR19).",
    )
    index_allow: str = Field(
        default="",
        description="If set, only paths matching these gitwildmatch patterns are indexed (FR19).",
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
        """Address the HTTP server actually binds.

        Defaults to ``127.0.0.1`` and never widens on its own (NFR14). Tailscale
        binding is owned by T08 — the seam is this branch.
        """
        if self.bind_mode == "localhost":
            return "127.0.0.1"
        raise NotImplementedError(
            "bind_mode='tailscale' is implemented in T08; use 'localhost' until then."
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton."""
    return Settings()
