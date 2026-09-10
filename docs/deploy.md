# Deploying `pcs`

The default Docker Compose stack contains PostgreSQL with pgvector and one Python server that also serves the built React UI (FR40, NFR3, NFR13). Access is host-loopback-only by default. An optional Tailscale sidecar exposes the service to the operator's tailnet without Funnel (FR41, NFR14).

## Localhost stack

```bash
cp .env.example .env
docker compose -f deploy/docker-compose.yml up --build --wait
```

The entrypoint waits for PostgreSQL, runs `alembic upgrade head`, then starts `pcs http`.

- Docker publishes HTTP at `127.0.0.1:${PCS_PORT:-8080}` and PostgreSQL at `127.0.0.1:5432`.
- Inside the server container, Compose sets `PCS_BIND_ADDRESS=0.0.0.0` so Docker can route traffic to it.
- The wildcard container bind does not expose the service to the LAN: the host publish remains explicitly bound to `127.0.0.1`.
- `GET http://127.0.0.1:8080/api/health` reports `bind_mode` and the process `bind_host`.
- HTTP MCP is at `/mcp`; JSON API routes are under `/api`; the UI is at `/`.

stdio MCP is independent of HTTP binding and may be run on the host with `(cd server && uv run pcs stdio)` (FR42).

## Project mounts

Compose mounts:

- `PCS_REPOS_DIR` at `/repos` **read-write** for source indexing and requirements-file sync.

Default is `../repos`, resolved relative to `deploy/docker-compose.yml`. Register `/repos` or `/repos/<subdir>` as the project root.

`/repos` is read-write because the requirements file (FR16a) is a git-tracked artifact the server writes back into each project's own `.project-context/requirements.md` — which works for any project root, not just `/repos`. The server only ever writes that one path-guarded file per project (`..` is rejected); indexing and the source route read only, and the server never executes project code (NFR5). The host directory must be writable by the container's `pcs` user (uid 1000) — if it is owned by another user, `chown` it or run Compose with a matching `user:`.

If you must keep the tree read-only, set `PCS_REQUIREMENTS_FILE` to an absolute path on a writable volume (the file then leaves the repo and loses git-diffability), or accept the degraded mode: the store stays authoritative and the requirements screen reports the file as read-only.

## Persistence and backup

| Volume | Purpose |
|---|---|
| `pcs_pgdata` | PostgreSQL data: curated context and the complete `code_index` schema (NFR12). |
| `pcs_index` | Reserved on-disk index-artifact path at `/var/lib/pcs/index`; current searchable index data lives in PostgreSQL. |
| `pcs_ts_state` | Tailscale node state when the overlay is enabled. |

Back up `pcs_pgdata` using normal PostgreSQL backup tooling. Back up the requirements Markdown files separately if they are part of the operator's source-of-truth workflow. The code index is rebuildable; curated context is not.

`docker compose down` preserves named volumes. `docker compose down -v` irreversibly deletes them.

## Configuration in Compose

See [Configuration reference](configuration.md) for all supported values. The repository `.env.example` is a catalog and Compose-substitution file, but `deploy/docker-compose.yml` does **not** use `env_file:`. It currently forwards this server subset:

- `PCS_DATABASE_URL`
- `PCS_BIND_MODE`
- `PCS_BIND_ADDRESS`
- `PCS_PORT` as container port `8080` and host publish selection
- `PCS_LOG_LEVEL`
- `PCS_STATIC_DIR=/app/web/dist`
- `PCS_TAILSCALE_IP`
- `PCS_TAILSCALE_IFACE`
- `PCS_TAILSCALE_SERVE`
- `PCS_INDEX_WATCH`

Settings such as `PCS_INDEX_IGNORE`, `PCS_INDEX_ALLOW`, `PCS_INDEX_MAX_FILE_BYTES`, `PCS_REQUIREMENTS_FILE`, `PCS_SCIP_INDEXERS`, and all embedding/summary settings are not automatically forwarded from `.env` to the server container. Add them explicitly with a local override, for example:

```yaml
services:
  server:
    environment:
      PCS_INDEX_MAX_FILE_BYTES: ${PCS_INDEX_MAX_FILE_BYTES:-1000000}
      PCS_EMBEDDING_BACKEND: ${PCS_EMBEDDING_BACKEND:-}
      PCS_EMBEDDING_BASE_URL: ${PCS_EMBEDDING_BASE_URL:-https://api.openai.com/v1}
      PCS_EMBEDDING_API_KEY: ${PCS_EMBEDDING_API_KEY:-}
      PCS_EMBEDDING_MODEL: ${PCS_EMBEDDING_MODEL:-text-embedding-3-small}
      PCS_EMBEDDING_DIMENSIONS: ${PCS_EMBEDDING_DIMENSIONS:-1536}
```

Pass the override after the base file with `-f path/to/override.yml`. Remote embedding or summary providers receive relevant project code or context. Keep their keys outside version control.

## Tailscale overlay

Requires a Tailscale auth key and `/dev/net/tun` on the host:

```bash
export TS_AUTHKEY=tskey-auth-...
docker compose \
  -f deploy/docker-compose.yml \
  -f deploy/docker-compose.tailscale.yml \
  up --build --wait
```

The overlay:

- Starts `tailscale/tailscale:v1.80.3` with persistent state.
- Places PostgreSQL at internal address `172.30.0.2`.
- Shares the Tailscale network namespace with the server.
- Forces `PCS_BIND_MODE=tailscale`, which resolves and validates a `100.64.0.0/10` address.
- Removes the server's host port publish and bridge-network attachment.
- Does not enable Funnel. Do not add Funnel to `TS_EXTRA_ARGS`.

Tailnet clients normally connect using the MagicDNS name from `TS_HOSTNAME` (default `pcs`) and port `8080`.

### HTTPS with Tailscale Serve

The repository includes `deploy/ts-serve.json`, but the shipped overlay does not provide a runnable Serve setup: it does not mount that file, it forces `PCS_BIND_MODE=tailscale`, and `${TS_CERT_DOMAIN}` inside JSON is not rendered by Compose. `PCS_TAILSCALE_SERVE` also does not start Serve by itself.

A deployment-specific override must:

1. Render `${TS_CERT_DOMAIN}` in `deploy/ts-serve.json` to a concrete MagicDNS certificate domain.
2. Mount the rendered file into the `tailscale` service.
3. Set `TS_SERVE_CONFIG` to that in-container path.
4. Override the server to `PCS_BIND_MODE=localhost` so the proxy target `http://127.0.0.1:8080` is listening inside the shared network namespace.
5. Keep Funnel disabled.

Do not follow the direct-tailnet-bind instructions and the Serve-loopback instructions simultaneously.

## Prebuilt images

`deploy/docker-compose.yml` declares both:

```yaml
image: ${PCS_IMAGE:-pcs-server:local}
build:
  context: ..
  dockerfile: deploy/Dockerfile.server
```

Setting `PCS_IMAGE` changes the image tag/reference but does not remove the `build` declaration. Compose may use a local/pulled image or build depending on command flags and pull policy. For deterministic production deployment, use an override that removes or replaces `build`, then pull the pinned image before `up`.

To build directly from source:

```bash
docker build -f deploy/Dockerfile.server -t pcs-server:local .
```

The multi-stage image builds the frontend, installs the Python application, includes `git` for indexing, runs as the non-root `pcs` user, and does not copy `.env`. `deploy/Dockerfile.web` is optional and unused by the default stack.

## Host mode

Use Docker only for PostgreSQL, then run migrations and application processes on the host:

```bash
just setup
just up
just migrate
(cd server && uv run pcs http)
```

Default HTTP binding is `127.0.0.1:8080`. For direct tailnet binding:

```bash
(cd server && PCS_BIND_MODE=tailscale uv run pcs http)
```

Set `PCS_TAILSCALE_IP` when automatic resolution through `tailscale ip -4` or `tailscale0` is unavailable. The address must be within `100.64.0.0/10`.
