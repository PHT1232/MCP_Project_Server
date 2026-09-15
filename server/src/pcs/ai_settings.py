"""Secure persisted global AI provider settings (T20, INV-AISET-1..5)."""

from __future__ import annotations

import asyncio
import base64
import binascii
import hmac
import ipaddress
import json
import math
import os
import socket
from dataclasses import asdict, dataclass
from typing import Literal, cast
from urllib.parse import urlsplit, urlunsplit

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from pcs.config import Settings, get_settings

Source = Literal["persisted", "environment", "default"]
_SECRET_UNSET = object()
_ENVELOPE_VERSION = 1
_ADVISORY_LOCK = 0x50435320
MAX_URL_LENGTH = 2048
MAX_MODEL_LENGTH = 200
MAX_BACKEND_LENGTH = 32
MAX_API_KEY_LENGTH = 8192
MAX_DIMENSIONS = 65536
MAX_BATCH_SIZE = 2048
MAX_TIMEOUT_SECONDS = 300.0


class AiSettingsError(ValueError):
    """Response-safe settings error that contains no submitted secret."""


class MasterKeyRequiredError(AiSettingsError):
    """A persisted secret cannot be written without encryption configuration."""


@dataclass(frozen=True)
class ProviderSettings:
    """Resolved provider settings; ``api_key`` is runtime-only and never serialized."""

    backend: str
    base_url: str
    model: str
    timeout_seconds: float
    api_key: str
    source: Source
    dimensions: int | None = None
    batch_size: int | None = None

    def public_dict(self) -> dict[str, object]:
        result = asdict(self)
        result.pop("api_key")
        result["api_key_configured"] = bool(self.api_key)
        return {key: value for key, value in result.items() if value is not None}

    @property
    def identity(self) -> tuple[str, str, str, int | None]:
        """Compatibility identity, including endpoint because providers can differ."""
        return (self.backend, self.base_url, self.model, self.dimensions)


@dataclass(frozen=True)
class RuntimeAiSettings:
    """Current DB-resolved providers and derived global compatibility state."""

    embedding: ProviderSettings
    summary: ProviderSettings
    reindex_required: bool

    def public_dict(self) -> dict[str, object]:
        return {
            "embedding": self.embedding.public_dict(),
            "summary": self.summary.public_dict(),
            "reindex_required": self.reindex_required,
        }


def reset_runtime_ai_settings() -> None:
    """Compatibility no-op: runtime settings are deliberately never process-cached."""


def _source(cfg: Settings, prefix: str) -> Source:
    fields = {
        "embedding": (cfg.embedding_backend, cfg.embedding_base_url, cfg.embedding_model),
        "summary": (cfg.summary_backend, cfg.summary_base_url, cfg.summary_model),
    }[prefix]
    defaults = {
        "embedding": ("", "https://api.openai.com/v1", "text-embedding-3-small"),
        "summary": ("", "https://api.openai.com/v1", "gpt-4o-mini"),
    }[prefix]
    return "environment" if fields != defaults else "default"


def _environment(cfg: Settings) -> RuntimeAiSettings:
    return RuntimeAiSettings(
        ProviderSettings(
            cfg.embedding_backend,
            cfg.embedding_base_url,
            cfg.embedding_model,
            cfg.embedding_timeout_seconds,
            cfg.embedding_api_key,
            _source(cfg, "embedding"),
            cfg.embedding_dimensions,
            cfg.embedding_batch_size,
        ),
        ProviderSettings(
            cfg.summary_backend,
            cfg.summary_base_url,
            cfg.summary_model,
            cfg.summary_timeout_seconds,
            cfg.summary_api_key,
            _source(cfg, "summary"),
        ),
        False,
    )


def _decode_key(raw: str, variable: str) -> bytes | None:
    if not raw.strip():
        return None
    try:
        encoded = raw.strip().encode("ascii")
        decoded = base64.b64decode(encoded, altchars=b"-_", validate=True)
        if base64.urlsafe_b64encode(decoded).rstrip(b"=") != encoded.rstrip(b"="):
            raise ValueError
    except (UnicodeError, binascii.Error, ValueError) as exc:
        raise AiSettingsError(f"{variable} must be canonical URL-safe base64") from exc
    if len(decoded) != 32:
        raise AiSettingsError(f"{variable} must decode to exactly 32 bytes")
    return decoded


def _keys(cfg: Settings) -> list[tuple[str, bytes]]:
    result: list[tuple[str, bytes]] = []
    if not cfg.ai_settings_key_id.strip():
        raise AiSettingsError("PCS_AI_SETTINGS_KEY_ID must be non-empty")
    if cfg.ai_settings_previous_master_key and not cfg.ai_settings_previous_key_id.strip():
        raise AiSettingsError("PCS_AI_SETTINGS_PREVIOUS_KEY_ID must be non-empty")
    if (
        cfg.ai_settings_previous_master_key
        and cfg.ai_settings_key_id == cfg.ai_settings_previous_key_id
    ):
        raise AiSettingsError("AI settings key IDs must be distinct")
    current = _decode_key(cfg.ai_settings_master_key, "PCS_AI_SETTINGS_MASTER_KEY")
    previous = _decode_key(
        cfg.ai_settings_previous_master_key, "PCS_AI_SETTINGS_PREVIOUS_MASTER_KEY"
    )
    if current is not None:
        result.append((cfg.ai_settings_key_id, current))
    if previous is not None:
        result.append((cfg.ai_settings_previous_key_id, previous))
    return result


def _encrypt(secret: str, *, field: str, cfg: Settings) -> bytes:
    key = _decode_key(cfg.ai_settings_master_key, "PCS_AI_SETTINGS_MASTER_KEY")
    key_id = cfg.ai_settings_key_id.strip()
    if key is None or not key_id:
        raise MasterKeyRequiredError("persisted API key writes require a current master key")
    nonce = os.urandom(12)
    ciphertext = AESGCM(key).encrypt(nonce, secret.encode(), field.encode())
    return json.dumps(
        {
            "v": _ENVELOPE_VERSION,
            "kid": key_id,
            "n": base64.urlsafe_b64encode(nonce).decode(),
            "c": base64.urlsafe_b64encode(ciphertext).decode(),
        },
        separators=(",", ":"),
    ).encode()


def _decrypt(blob: bytes | None, *, field: str, cfg: Settings) -> str | None:
    if not blob:
        return ""
    try:
        envelope = json.loads(blob)
        if (
            not isinstance(envelope, dict)
            or set(envelope) != {"v", "kid", "n", "c"}
            or envelope.get("v") != _ENVELOPE_VERSION
            or not isinstance(envelope.get("kid"), str)
            or not isinstance(envelope.get("n"), str)
            or not isinstance(envelope.get("c"), str)
        ):
            return None
        kid = envelope["kid"]
        nonce_text = envelope["n"].encode("ascii")
        ciphertext_text = envelope["c"].encode("ascii")
        nonce = base64.b64decode(nonce_text, altchars=b"-_", validate=True)
        ciphertext = base64.b64decode(ciphertext_text, altchars=b"-_", validate=True)
        if (
            base64.urlsafe_b64encode(nonce) != nonce_text
            or base64.urlsafe_b64encode(ciphertext) != ciphertext_text
        ):
            return None
        if len(nonce) != 12 or len(ciphertext) < 16:
            return None
        for candidate_id, key in _keys(cfg):
            if hmac.compare_digest(candidate_id, str(kid)):
                return AESGCM(key).decrypt(nonce, ciphertext, field.encode()).decode()
    except (KeyError, TypeError, ValueError, UnicodeError, binascii.Error, InvalidTag):
        return None
    return None


def _host_set(value: str) -> frozenset[str]:
    return frozenset(item.strip().lower() for item in value.split(",") if item.strip())


def _allowlist(cfg: Settings) -> frozenset[str]:
    return _host_set(cfg.ai_provider_allowed_hosts)


def _private_allowlist(cfg: Settings) -> frozenset[str]:
    return _host_set(cfg.ai_provider_allowed_private_hosts)


def _check_address(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address, *, allow_private: bool
) -> None:
    prohibited = (
        address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )
    if prohibited or (not allow_private and not address.is_global):
        raise AiSettingsError("provider URL resolves to a prohibited network")


@dataclass(frozen=True)
class ValidatedEndpoint:
    """Provider URL pinned to one validated address with original TLS identity."""

    url: str
    host: str
    authority: str

    @property
    def request_headers(self) -> dict[str, str]:
        return {"host": self.authority}

    @property
    def request_extensions(self) -> dict[str, object]:
        return {"sni_hostname": self.host.encode("ascii")}


async def resolve_provider_endpoint(
    value: object, *, cfg: Settings | None = None
) -> ValidatedEndpoint:
    """Validate scheme/host and every DNS result off the event loop (INV-AISET-4)."""
    settings = cfg or get_settings()
    if not isinstance(value, str) or not value.strip():
        raise AiSettingsError("base_url must be a non-empty string")
    normalized = value.strip()
    if len(normalized) > MAX_URL_LENGTH:
        raise AiSettingsError("base_url exceeds maximum length")
    parsed = urlsplit(normalized)
    if parsed.scheme.lower() != "https" and not (
        settings.ai_settings_allow_http and parsed.scheme == "http"
    ):
        raise AiSettingsError("base_url must use HTTPS")
    if parsed.username is not None or parsed.password is not None:
        raise AiSettingsError("base_url must not contain credentials")
    if parsed.fragment or parsed.query:
        raise AiSettingsError("base_url must not contain a query or fragment")
    host = (parsed.hostname or "").lower()
    if not host or host not in _allowlist(settings):
        raise AiSettingsError("provider hostname is not in PCS_AI_PROVIDER_ALLOWED_HOSTS")
    allow_private = host in _private_allowlist(settings)
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        _check_address(literal, allow_private=allow_private)
    try:
        rows = await asyncio.to_thread(
            socket.getaddrinfo, host, parsed.port or 443, 0, socket.SOCK_STREAM
        )
    except OSError as exc:
        raise AiSettingsError("provider hostname could not be resolved safely") from exc
    addresses = {ipaddress.ip_address(row[4][0]) for row in rows}
    if not addresses:
        raise AiSettingsError("provider hostname could not be resolved safely")
    for address in addresses:
        _check_address(address, allow_private=allow_private)
    address = sorted(addresses, key=str)[0]
    literal_host = f"[{address}]" if address.version == 6 else str(address)
    netloc = literal_host if parsed.port is None else f"{literal_host}:{parsed.port}"
    pinned = urlunsplit((parsed.scheme, netloc, parsed.path.rstrip("/"), "", ""))
    host_header = host if parsed.port is None else f"{host}:{parsed.port}"
    return ValidatedEndpoint(pinned, host, host_header)


async def validate_provider_url(value: object, *, cfg: Settings | None = None) -> str:
    """Validate a provider URL without retaining its resolved address."""
    await resolve_provider_endpoint(value, cfg=cfg)
    return cast(str, value).strip().rstrip("/")


def _string(body: dict[str, object], key: str, *, maximum: int) -> str:
    value = body.get(key)
    if not isinstance(value, str) or not value.strip():
        raise AiSettingsError(f"{key} must be a non-empty string")
    result = value.strip()
    if len(result) > maximum:
        raise AiSettingsError(f"{key} exceeds maximum length")
    return result


def _number(
    body: dict[str, object], key: str, *, maximum: float, integer: bool = False
) -> float | int:
    value = body.get(key)
    expected = int if integer else (int, float)
    if (
        isinstance(value, bool)
        or not isinstance(value, expected)
        or not math.isfinite(float(value))
        or value <= 0
        or value > maximum
    ):
        raise AiSettingsError(f"{key} must be a positive {'integer' if integer else 'number'}")
    return int(value) if integer else float(value)


def _secret(body: dict[str, object]) -> object:
    if "api_key" not in body:
        return _SECRET_UNSET
    value = body["api_key"]
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > MAX_API_KEY_LENGTH:
        raise AiSettingsError("api_key must be non-empty, null to clear, or omitted to retain")
    return value


async def _provider(
    body: object, current: ProviderSettings, *, embedding: bool, cfg: Settings
) -> tuple[ProviderSettings, object]:
    if not isinstance(body, dict):
        raise AiSettingsError("provider settings must be an object")
    expected = {"backend", "base_url", "model", "timeout_seconds", "api_key"}
    if embedding:
        expected |= {"dimensions", "batch_size"}
    unknown = set(body) - expected
    missing = expected - {"api_key"} - set(body)
    if unknown or missing:
        raise AiSettingsError("provider settings contain unknown or missing fields")
    backend = _string(body, "backend", maximum=MAX_BACKEND_LENGTH).lower()
    allowed = {"openai", "openai-compatible"} | ({"hashing"} if embedding else set())
    if backend not in allowed:
        raise AiSettingsError("unsupported provider backend")
    base_url = (
        await validate_provider_url(body["base_url"], cfg=cfg)
        if backend != "hashing"
        else _string(body, "base_url", maximum=MAX_URL_LENGTH)
    )
    return ProviderSettings(
        backend,
        base_url,
        _string(body, "model", maximum=MAX_MODEL_LENGTH),
        cast(float, _number(body, "timeout_seconds", maximum=MAX_TIMEOUT_SECONDS)),
        current.api_key,
        "persisted",
        cast(int, _number(body, "dimensions", maximum=MAX_DIMENSIONS, integer=True))
        if embedding
        else None,
        cast(int, _number(body, "batch_size", maximum=MAX_BATCH_SIZE, integer=True))
        if embedding
        else None,
    ), _secret(body)


def _validate_resolved_provider(provider: ProviderSettings, *, embedding: bool) -> None:
    allowed = {"openai", "openai-compatible"} | ({"hashing", ""} if embedding else {""})
    if provider.backend not in allowed or len(provider.backend) > MAX_BACKEND_LENGTH:
        raise AiSettingsError("unsupported provider backend")
    if len(provider.base_url) > MAX_URL_LENGTH:
        raise AiSettingsError("base_url exceeds maximum length")
    if not provider.model or len(provider.model) > MAX_MODEL_LENGTH:
        raise AiSettingsError("model has invalid length")
    if len(provider.api_key) > MAX_API_KEY_LENGTH:
        raise AiSettingsError("api_key exceeds maximum length")
    if not math.isfinite(provider.timeout_seconds) or not (
        0 < provider.timeout_seconds <= MAX_TIMEOUT_SECONDS
    ):
        raise AiSettingsError("timeout_seconds is outside the allowed range")
    if embedding:
        if provider.dimensions is None or not (0 < provider.dimensions <= MAX_DIMENSIONS):
            raise AiSettingsError("dimensions is outside the allowed range")
        if provider.batch_size is None or not (0 < provider.batch_size <= MAX_BATCH_SIZE):
            raise AiSettingsError("batch_size is outside the allowed range")


async def load_runtime_ai_settings(
    session: AsyncSession, *, refresh: bool = False
) -> RuntimeAiSettings:
    """Read DB on every operation so every process observes PATCH immediately (AC-AISET-6)."""
    del refresh
    cfg = get_settings()
    env = _environment(cfg)
    row = (
        (await session.execute(text("SELECT * FROM ai_provider_settings WHERE id = 1")))
        .mappings()
        .one_or_none()
    )
    status_exists = bool(
        (
            await session.execute(
                text(
                    "SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_class c "
                    "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname='code_index' AND c.relname='status')"
                )
            )
        ).scalar_one()
    )
    incompatible = False
    if status_exists:
        incompatible = bool(
            (
                await session.execute(
                    text("SELECT EXISTS (SELECT 1 FROM code_index.status WHERE reindex_required)")
                )
            ).scalar_one()
        )
    if row is None:
        _validate_resolved_provider(env.embedding, embedding=True)
        _validate_resolved_provider(env.summary, embedding=False)
        if env.embedding.backend and env.embedding.backend != "hashing":
            await validate_provider_url(env.embedding.base_url, cfg=cfg)
        if env.summary.backend:
            await validate_provider_url(env.summary.base_url, cfg=cfg)
        return RuntimeAiSettings(env.embedding, env.summary, incompatible)
    embedding_secret = _decrypt(
        row["embedding_api_key_encrypted"], field="embedding.api_key", cfg=cfg
    )
    summary_secret = _decrypt(row["summary_api_key_encrypted"], field="summary.api_key", cfg=cfg)
    embedding = ProviderSettings(
        str(row["embedding_backend"]),
        str(row["embedding_base_url"]),
        str(row["embedding_model"]),
        float(row["embedding_timeout_seconds"]),
        env.embedding.api_key if embedding_secret is None else embedding_secret,
        "persisted",
        int(row["embedding_dimensions"]),
        int(row["embedding_batch_size"]),
    )
    summary = ProviderSettings(
        str(row["summary_backend"]),
        str(row["summary_base_url"]),
        str(row["summary_model"]),
        float(row["summary_timeout_seconds"]),
        env.summary.api_key if summary_secret is None else summary_secret,
        "persisted",
    )
    _validate_resolved_provider(embedding, embedding=True)
    _validate_resolved_provider(summary, embedding=False)
    if embedding.backend != "hashing":
        await validate_provider_url(embedding.base_url, cfg=cfg)
    if summary.backend:
        await validate_provider_url(summary.base_url, cfg=cfg)
    return RuntimeAiSettings(embedding, summary, incompatible)


async def update_ai_settings(session: AsyncSession, body: object) -> RuntimeAiSettings:
    """Serialize and atomically merge provider sections and secrets (INV-AISET-1..5)."""
    if not isinstance(body, dict) or not body or set(body) - {"embedding", "summary"}:
        raise AiSettingsError("JSON body must contain only embedding and/or summary")
    await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _ADVISORY_LOCK})
    current = await load_runtime_ai_settings(session)
    cfg = get_settings()
    embedding, e_secret = current.embedding, _SECRET_UNSET
    summary, s_secret = current.summary, _SECRET_UNSET
    if "embedding" in body:
        embedding, e_secret = await _provider(body["embedding"], embedding, embedding=True, cfg=cfg)
    if "summary" in body:
        summary, s_secret = await _provider(body["summary"], summary, embedding=False, cfg=cfg)
    existing = (
        (
            await session.execute(
                text(
                    "SELECT embedding_api_key_encrypted, summary_api_key_encrypted "
                    "FROM ai_provider_settings WHERE id=1 FOR UPDATE"
                )
            )
        )
        .mappings()
        .one_or_none()
    )

    def ciphertext(value: object, field: str, column: str) -> bytes | None:
        if value is _SECRET_UNSET:
            return None if existing is None else cast(bytes | None, existing[column])
        if value is None:
            return None
        return _encrypt(cast(str, value), field=field, cfg=cfg)

    changed = embedding.identity != current.embedding.identity
    statement = text(
        """
        INSERT INTO ai_provider_settings (
          id, embedding_backend, embedding_base_url, embedding_model, embedding_dimensions,
          embedding_batch_size, embedding_timeout_seconds, embedding_api_key_encrypted,
          summary_backend, summary_base_url, summary_model, summary_timeout_seconds,
          summary_api_key_encrypted, updated_at
        ) VALUES (1,:eb,:eu,:em,:ed,:eba,:et,:ek,:sb,:su,:sm,:st,:sk,now())
        ON CONFLICT(id) DO UPDATE SET
          embedding_backend=excluded.embedding_backend,
          embedding_base_url=excluded.embedding_base_url, embedding_model=excluded.embedding_model,
          embedding_dimensions=excluded.embedding_dimensions,
          embedding_batch_size=excluded.embedding_batch_size,
          embedding_timeout_seconds=excluded.embedding_timeout_seconds,
          embedding_api_key_encrypted=excluded.embedding_api_key_encrypted,
          summary_backend=excluded.summary_backend, summary_base_url=excluded.summary_base_url,
          summary_model=excluded.summary_model,
          summary_timeout_seconds=excluded.summary_timeout_seconds,
          summary_api_key_encrypted=excluded.summary_api_key_encrypted, updated_at=now()
        """
    )
    await session.execute(
        statement,
        {
            "eb": embedding.backend,
            "eu": embedding.base_url,
            "em": embedding.model,
            "ed": embedding.dimensions,
            "eba": embedding.batch_size,
            "et": embedding.timeout_seconds,
            "ek": ciphertext(e_secret, "embedding.api_key", "embedding_api_key_encrypted"),
            "sb": summary.backend,
            "su": summary.base_url,
            "sm": summary.model,
            "st": summary.timeout_seconds,
            "sk": ciphertext(s_secret, "summary.api_key", "summary_api_key_encrypted"),
        },
    )
    if changed:
        await session.execute(text("UPDATE code_index.status SET reindex_required=true"))
    return await load_runtime_ai_settings(session)


def admin_authorized(token: str) -> bool:
    """Constant-time admin token comparison; absent configuration fails closed."""
    configured = get_settings().admin_token.encode("utf-8")
    supplied = token.encode("utf-8")
    # Always perform one fixed-length digest comparison, including missing config/input.
    configured_digest = hmac.digest(b"pcs-admin-auth", configured, "sha256")
    supplied_digest = hmac.digest(b"pcs-admin-auth", supplied, "sha256")
    return bool(configured and supplied and hmac.compare_digest(configured_digest, supplied_digest))
