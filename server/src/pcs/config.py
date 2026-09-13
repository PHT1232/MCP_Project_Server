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
    mcp_allowed_hosts: str = Field(
        default="",
        description=(
            "Comma-separated additional Host headers accepted by MCP DNS-rebinding protection. "
            "Localhost is always allowed; add the exact tailnet IP/hostname with an optional :*."
        ),
    )
    mcp_allowed_origins: str = Field(
        default="",
        description=(
            "Comma-separated additional browser Origin headers accepted by MCP DNS-rebinding "
            "protection. Localhost origins are always allowed."
        ),
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
    requirements_file: str = Field(
        default=".project-context/requirements.md",
        description=(
            "Requirements template file (FR16a, D12). Relative paths resolve under the "
            "project's root_path; an absolute path is used as-is. Created from a template "
            "on register_project if absent. The server keeps it in two-way sync with the "
            "requirements section of the store (D15)."
        ),
    )
    embedding_backend: str = Field(
        default="",
        description=(
            "Embedding backend for semantic search (FR28, D7). Empty → semantic search "
            "is disabled and only keyword/structural search runs (AC10, AC21). "
            "'openai' → an OpenAI-compatible /embeddings HTTP endpoint. "
            "'hashing' → a bundled zero-dependency local n-gram hashing vectoriser "
            "(opt-in, lower quality; useful offline / for CI)."
        ),
    )
    embedding_base_url: str = Field(
        default="https://api.openai.com/v1",
        description="Base URL for embedding_backend='openai' (OpenAI-compatible). No trailing /.",
    )
    embedding_api_key: str = Field(
        default="",
        description="Bearer token for embedding_backend='openai'. Sent only to embedding_base_url.",
    )
    embedding_model: str = Field(
        default="text-embedding-3-small",
        description="Model name passed to the embedding endpoint (or 'hashing').",
    )
    embedding_dimensions: int = Field(
        default=1536,
        description="Vector dimension stored in pgvector. Must match the configured model.",
    )
    embedding_batch_size: int = Field(
        default=64,
        description="Chunks embedded per backend request during indexing (NFR10).",
    )
    embedding_timeout_seconds: float = Field(
        default=30.0,
        description="Per-request timeout for the embedding HTTP backend.",
    )
    summary_backend: str = Field(
        default="",
        description=(
            "FR9d LLM-summarisation backend for long context entries. Empty → deterministic "
            "truncation fallback (FR9e). 'openai' → an OpenAI-compatible /chat/completions "
            "endpoint. Data leaves the host only via this endpoint (NFR11)."
        ),
    )
    summary_base_url: str = Field(
        default="https://api.openai.com/v1",
        description="Base URL for summary_backend='openai' (OpenAI-compatible). No trailing /.",
    )
    summary_api_key: str = Field(
        default="",
        description="Bearer token for summary_backend='openai'. Sent only to summary_base_url.",
    )
    summary_timeout_seconds: float = Field(
        default=30.0,
        description="Per-request timeout for the summary HTTP backend.",
    )
    ai_settings_master_key: str = Field(
        default="",
        description="URL-safe base64 32-byte key encrypting persisted AI API keys (T20).",
    )
    ai_settings_allow_http: bool = Field(
        default=False,
        description=("Development-only HTTP endpoint allowance; private targets stay blocked."),
    )
    ai_provider_allowed_hosts: str = Field(
        default="api.openai.com",
        description="Comma-separated exact host allowlist for outbound AI providers.",
    )
    ai_provider_allowed_private_hosts: str = Field(
        default="",
        description=(
            "Exact allowlisted provider hosts permitted to resolve to private or Tailscale "
            "addresses; loopback and unsafe special-use addresses remain blocked."
        ),
    )
    admin_token: str = Field(
        default="", description="Bearer or X-PCS-Admin-Token required for admin writes."
    )
    ai_settings_key_id: str = Field(default="current", description="Current AI secret key id.")
    ai_settings_previous_master_key: str = Field(
        default="", description="Optional previous URL-safe base64 key for rotation reads."
    )
    ai_settings_previous_key_id: str = Field(
        default="previous", description="Key id for the optional previous key."
    )
    summary_model: str = Field(
        default="gpt-4o-mini",
        description="Chat model used for FR9d summarisation.",
    )
    scip_indexers: str = Field(
        default="",
        description=(
            "Comma-separated 'language=binary' overrides for SCIP indexers (FR23c). "
            "Empty → probe the default binary names on PATH; missing → tree-sitter tags "
            "fallback (AC23)."
        ),
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
