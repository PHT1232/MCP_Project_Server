# Configuration reference

The server uses `pydantic-settings`: environment names are the uppercase field names prefixed with `PCS_`; a `.env` in the server process working directory is also read. Defaults below come from `server/src/pcs/config.py`.

## Server process

| Variable | Type | Default | Meaning |
|---|---|---:|---|
| `PCS_DATABASE_URL` | string | `postgresql+psycopg://pcs:pcs@localhost:5432/pcs` | SQLAlchemy PostgreSQL URL. |
| `PCS_HOST` | string | `127.0.0.1` | Compatibility field; not used for the actual HTTP bind. Use bind settings below. |
| `PCS_PORT` | integer | `8080` | HTTP MCP, `/api`, and UI port. |
| `PCS_BIND_MODE` | `localhost` or `tailscale` | `localhost` | Selects loopback/explicit bind or validated tailnet bind. |
| `PCS_BIND_ADDRESS` | string | empty | In `localhost` mode, empty means `127.0.0.1`. Compose sets `0.0.0.0` inside the container and publishes loopback-only on the host. Ignored in `tailscale` mode. |
| `PCS_TAILSCALE_IP` | IPv4 string | empty | Explicit tailnet address. Must be in `100.64.0.0/10`. |
| `PCS_TAILSCALE_IFACE` | string | `tailscale0` | Interface probed after `tailscale ip -4` when no explicit address is set. |
| `PCS_TAILSCALE_SERVE` | boolean | `false` | Configuration marker only; current server/Compose code does not start `tailscale serve`. |
| `PCS_MCP_ALLOWED_HOSTS` | comma-separated hosts | empty | Additional MCP `Host` headers allowed by DNS-rebinding protection. Localhost is always allowed. Use exact hosts or `host:*`; bare `*` is rejected. |
| `PCS_MCP_ALLOWED_ORIGINS` | comma-separated origins | empty | Additional MCP browser origins allowed by DNS-rebinding protection. Localhost HTTP origins are always allowed. |
| `PCS_STATIC_DIR` | path | empty | Built frontend directory. Empty or nonexistent disables static UI serving. |
| `PCS_LOG_LEVEL` | string | `INFO` | Structured `pcs` logger level, normally `DEBUG`, `INFO`, `WARNING`, or `ERROR`. |
| `PCS_INDEX_IGNORE` | comma-separated patterns | empty | Additional gitignore-style exclusions. |
| `PCS_INDEX_ALLOW` | comma-separated patterns | empty | If set, only matching paths are indexed. |
| `PCS_INDEX_MAX_FILE_BYTES` | integer | `1000000` | Files larger than this are recorded as skipped. |
| `PCS_INDEX_WATCH` | boolean | `true` | Start incremental filesystem watches in HTTP mode. |
| `PCS_REQUIREMENTS_FILE` | path | `.project-context/requirements.md` | Requirements file. Relative paths resolve below each project root; absolute paths are accepted. `..` is rejected. |
| `PCS_SCIP_INDEXERS` | comma-separated mappings | empty | `language=binary` overrides, for example `python=scip-python`. Empty probes default binaries and uses fallback tags when unavailable. |

## Embeddings and summarization

| Variable | Type | Default | Meaning |
|---|---|---:|---|
| `PCS_EMBEDDING_BACKEND` | empty, `openai`, or `hashing` | empty | Empty disables semantic search. `openai` calls an OpenAI-compatible `/embeddings` endpoint. `hashing` is local, offline, and lower quality. |
| `PCS_EMBEDDING_BASE_URL` | URL | `https://api.openai.com/v1` | Base URL for the `openai` embedding backend; omit trailing `/`. |
| `PCS_EMBEDDING_API_KEY` | secret string | empty | Bearer token sent only to the embedding base URL. |
| `PCS_EMBEDDING_MODEL` | string | `text-embedding-3-small` | Embedding model identifier. |
| `PCS_EMBEDDING_DIMENSIONS` | integer | `1536` | Stored vector dimension; must match the provider/model. |
| `PCS_EMBEDDING_BATCH_SIZE` | integer | `64` | Chunks per embedding request. |
| `PCS_EMBEDDING_TIMEOUT_SECONDS` | number | `30` | Per-request timeout. |
| `PCS_SUMMARY_BACKEND` | empty or `openai` | empty | Empty uses deterministic truncation. `openai` calls an OpenAI-compatible `/chat/completions` endpoint. |
| `PCS_SUMMARY_BASE_URL` | URL | `https://api.openai.com/v1` | Summarization base URL; omit trailing `/`. |
| `PCS_SUMMARY_API_KEY` | secret string | empty | Bearer token sent only to the summary base URL. |
| `PCS_SUMMARY_MODEL` | string | `gpt-4o-mini` | Chat model used for long-entry summarization. |

Configuring either remote backend sends relevant project code or context to that endpoint. Do not commit API keys.

## Per-project settings

These are stored per project and changed with MCP `configure_project` or `PATCH /api/projects/{project}`:

| Field | Default | Valid range/values |
|---|---:|---|
| `briefing_token_budget` | `1500` | `500`–`4000` |
| `prepare_task_token_budget` | `4000` | `1000`–`16000` |
| `headline_max_chars` | `120` | Positive integer enforced by the service. |
| `detail_max_chars` | `8000` | Positive integer enforced by the service. |
| `expiry_policy` | `off` | `off` or `age` |
| `expiry_days` | `null` | Required positive integer for age-based expiry. |

## Compose-only variables

| Variable | Default | Meaning |
|---|---:|---|
| `PCS_REPOS_DIR` | `../repos` | Host directory mounted **read-write** at `/repos`. Relative paths resolve from `deploy/docker-compose.yml`. Read-write because the requirements file (FR16a) is written back into each project's own `.project-context/`; indexing and the source route only read. The host directory must be writable by the container's `pcs` user (uid 1000). |
| `PCS_IMAGE` | empty | Image name substituted into Compose; see deployment notes about the simultaneous `build` declaration. |
| `POSTGRES_USER` | `pcs` | PostgreSQL user. |
| `POSTGRES_PASSWORD` | `pcs` | PostgreSQL password; change outside local development. |
| `POSTGRES_DB` | `pcs` | PostgreSQL database. |
| `TS_AUTHKEY` | empty | Tailscale auth key consumed by the sidecar. |
| `TS_HOSTNAME` | `pcs` | Tailscale node hostname. |
| `TS_EXTRA_ARGS` | `--accept-dns=false` | Extra `tailscaled` arguments. Never add Funnel. |
| `TS_SERVE_CONFIG` | empty | Path inside the sidecar to a mounted, rendered Serve JSON config. No mount is supplied by the current overlay. |

Important: `deploy/docker-compose.yml` does not declare `env_file:` and forwards only database, bind, port, log, static, Tailscale, MCP allowlist, and watch settings. Values such as `PCS_INDEX_IGNORE`, embedding, summary, SCIP, and requirements-file settings in the repository `.env` are not automatically passed into the container. Add them under the server service in a local Compose override when needed.

## Frontend build and development

| Variable | Default | Meaning |
|---|---:|---|
| `VITE_API_BASE` | empty | Browser API base URL, compiled into the frontend. Empty uses same-origin `/api`. |
| `VITE_API_TARGET` | `http://127.0.0.1:8080` | Vite development-server proxy target for `/api`. |

Production uses same-origin API calls because the Python server serves both UI and API.

### Persisted global AI settings (T20)

`GET /api/admin/ai-settings` resolves the global embedding and summarization providers. `PATCH /api/admin/ai-settings` stores them server-side. A persisted provider takes precedence over environment configuration; environment values are fallback only while no persisted row exists. Updates apply without restart and clear process-local provider caches.

Set `PCS_AI_SETTINGS_MASTER_KEY` to a URL-safe base64 encoding of exactly 32 random bytes before writing API keys. API keys are encrypted with AES-256-GCM before PostgreSQL storage and are write-only: responses expose only `api_key_configured`. Omitting `api_key` retains the stored secret, a non-empty string replaces it, and `null` clears it. When the master key is absent, nonsecret persisted settings remain usable, encrypted persisted secrets cannot be decrypted, environment API keys provide read/runtime fallback, and attempts to persist a new secret return `400` without echoing it.

Generate a key with a secrets-management tool and inject it through the process environment. Do not store the key beside the database or commit it. Losing or rotating this key without first replacing persisted secrets makes existing ciphertext unreadable.

Provider URLs require HTTPS and an exact hostname in `PCS_AI_PROVIDER_ALLOWED_HOSTS`; they reject credentials, queries, fragments, and non-global literal addresses. Before every outbound call, PCS resolves DNS off the event loop and rejects the call if any returned address is loopback, private, link-local, reserved, multicast, or unspecified. The request then connects directly to one validated IP while retaining the original hostname for HTTP `Host` and TLS SNI/certificate verification, eliminating a DNS check/use race. HTTP redirects are disabled. `PCS_AI_SETTINGS_ALLOW_HTTP=true` is a development-only scheme allowance and does not permit private targets.

Changing embedding backend, model, or dimensions marks every semantic index incompatible. Keyword search remains available, but semantic search stays unavailable per project until a full, compatible reindex completes. The global response remains `reindex_required=true` until all indexed projects complete that reindex.

`PATCH` requires `PCS_ADMIN_TOKEN` through `Authorization: Bearer` or `X-PCS-Admin-Token`; missing configuration fails closed. `PCS_AI_SETTINGS_KEY_ID` labels new ciphertext. During rotation, set `PCS_AI_SETTINGS_PREVIOUS_MASTER_KEY` and its distinct `PCS_AI_SETTINGS_PREVIOUS_KEY_ID` so old ciphertext remains readable while replacement writes use the current key. Persisted `embedding.batch_size` controls indexing requests. Compatibility remains required until every project completes a successful full embedding with the active backend, URL, model, and dimensions; incremental or failed embedding runs never clear it.

Persisted limits are: URL 2048 characters, model 200, backend 32, API key 8192, dimensions 65536, batch size 2048, and timeout 300 seconds. NaN and infinity are rejected. These limits are mirrored by PostgreSQL constraints. Previous master keys are decrypt-only; all new secret writes require the current master key and emit `PCS_AI_SETTINGS_KEY_ID`.
