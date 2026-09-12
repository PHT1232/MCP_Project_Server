# T20 — Admin-managed AI provider settings

Requirement: `1a1ac145-6e0f-4c95-8d0a-935d6ab4734a`
Contract: `INV-AISET-1..5`, `AC-AISET-1..10`
Scope: integrated T20 work in `server/**` and `web/**`, plus `deploy/docker-compose.yml`, `docs/configuration.md`, `docs/http-api.md`, and this task file.

## Acceptance checklist

- [x] Persist global embedding and summarization nonsecret settings in PostgreSQL.
- [x] Encrypt persisted API keys with a server master key; never return or log key values.
- [x] Define missing-master-key bootstrap: environment read fallback and rejected secret writes.
- [x] Implement retain/replace/clear secret semantics.
- [x] Validate environment and persisted provider URLs with an explicit hostname allowlist, call-time all-address DNS checks, and disabled redirects.
- [x] Expose typed `GET/PATCH /api/admin/ai-settings` routes with fail-closed constant-time admin-token authentication and malformed-JSON handling.
- [x] Hot-reload embedding and summarization runtime settings without a process cache or restart.
- [x] Mark embedding identity changes incompatible for every project and clear only after successful compatible full embedding.
- [x] Persist and use embedding batch size; incremental and failed embedding runs retain incompatibility.
- [x] Use a strict AES-256-GCM envelope with canonical base64, field AAD, key IDs, rotation reads, and corrupt-provider isolation.
- [x] Serialize concurrent PATCH operations with a transaction advisory lock.
- [x] Add migration after `0019`; conservatively mark preexisting semantic indexes incompatible.
- [x] Add focused PostgreSQL tests for persistence, encryption, redaction, validation, fallback, reload, concurrency, multiproject compatibility, migration, auth, URL safety, and event-loop DNS behavior.

## Handoff

Remediated independent backend review blockers. Runtime settings are DB-read per operation; persisted values override environment fallback without process caching. PATCH is transaction-serialized and requires `PCS_ADMIN_TOKEN`, using a fixed-length HMAC digest comparison and failing closed when unset. Malformed JSON and invalid settings return redacted `400` responses.

Provider URLs require exact `PCS_AI_PROVIDER_ALLOWED_HOSTS` membership. Environment, persisted, PATCH, embedding, and summary paths validate HTTPS, reject credentials/query/fragment, resolve DNS through `asyncio.to_thread`, reject every non-global answer, pin the actual socket destination to a validated IP while preserving the original TLS SNI/Host identity, and disable redirects.

Secrets use strict versioned AES-256-GCM envelopes with canonical URL-safe base64, exact fields, per-provider AAD, key IDs, and previous-key decrypt-only rotation reads; writes require the current key and current key ID. A corrupt provider secret falls back only for that provider and never appears in logs/errors.

Embedding identity changes mark every project status incompatible. Global `reindex_required` is derived from all project rows. Only a successful full embedding whose total matches current chunks records provider identity and clears that project; failed, partial, or incremental embedding cannot clear it. Indexing uses persisted `embedding_batch_size`. Migration `0020` defaults existing status rows to incompatible.

Finite URL/model/backend/API-key/dimension/batch/timeout limits are enforced before SQL and mirrored by migration constraints. Embedding provider failures produce an observable `error` index state without leaking provider exceptions and preserve incompatibility. Settings responses include `Cache-Control: no-store`.

Frontend exposes global `/settings/ai` without requiring project selection, keeps admin/provider secrets out of TanStack caches, updates from redacted PATCH responses, supports explicit key clearing, and invalidates settings after full reindex. Manual refresh also works on the global settings route.

Validation: migration `0019 → 0020 → 0019 → 0020` roundtrip passed; focused T20 backend tests passed (`31`); `just check` passed with `287` server tests passed / `1` skipped and `76` Vitest tests passed; server/web lint, strict typing, frontend build, Compose validation, and `git diff --check` passed. Independent final review reported no blockers. No commit created.
