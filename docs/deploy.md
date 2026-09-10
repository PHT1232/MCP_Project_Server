# Deploying `pcs`

The system ships as a Docker Compose stack: PostgreSQL (with `pgvector`) plus
the server, which also serves the built web UI (FR40, NFR3, NFR13). Access is
loopback by default; an optional Tailscale sidecar joins your tailnet (FR41,
NFR14, D16).

## What gets persisted

Named volumes (FR40):

| Volume | Purpose |
|--------|---------|
| `pcs_pgdata` | PostgreSQL data, including curated context **and** the code index (NFR12) |
| `pcs_index` | On-disk index artifacts (`/var/lib/pcs/index`) — reserved for T04 embedding cache |
| `pcs_ts_state` | Tailscale node state (overlay only) |

Nothing secret is baked into the image. Passwords, Tailscale auth keys, and
embedding URLs come from the environment or a mounted `.env` (FR40).

## Project repo mounts (NFR5)

Compose bind-mounts:

- `PCS_REPOS_DIR` → `/repos` **read-only** (code the indexer may read)
- `PCS_REQUIREMENTS_DIR` → `/repos/.project-context` **read-write** (requirements
  template file only, FR16a)

Relative paths are resolved from `deploy/docker-compose.yml`. Defaults point at
the `repos/` placeholder in this repo. Register projects with
`root_path=/repos` or `/repos/<subdir>`.

The server never executes project code (NFR5).

## Localhost stack (AC25, AC26 off)

```bash
docker compose -f deploy/docker-compose.yml up --build --wait
```

- Host ports: `127.0.0.1:8080` (HTTP MCP + `/api` + UI) and `127.0.0.1:5432`
  (Postgres, for `just migrate` from the host).
- `PCS_BIND_MODE=localhost` → process bind `127.0.0.1` inside the container.
- Not published on `0.0.0.0`, LAN, or the public internet.

Health: `GET http://127.0.0.1:8080/api/health` reports `bind_mode` and
`bind_host`.

stdio MCP is unchanged: `uv run pcs stdio` on the host, or a client attached to
that process. HTTP bind mode does not affect stdio (FR42).

## Tailscale overlay (AC26 on)

Requires a [Tailscale auth key](https://tailscale.com/kb/1085/auth-keys) and
`/dev/net/tun` on the host.

```bash
export TS_AUTHKEY=tskey-auth-...
docker compose \
  -f deploy/docker-compose.yml \
  -f deploy/docker-compose.tailscale.yml \
  up --build --wait
```

This starts a **Tailscale sidecar**. The server shares that network namespace and
sets `PCS_BIND_MODE=tailscale`, so it listens on the tailnet IPv4 (typically
`100.x`, resolved from `tailscale0` or `PCS_TAILSCALE_IP`). Other devices on
**your** tailnet reach it by MagicDNS name (`TS_HOSTNAME`, default `pcs`).

- Funnel is **not** enabled and must not be added to `TS_EXTRA_ARGS`.
- Compose still does not publish `0.0.0.0`.
- Postgres stays on the internal compose network (static `172.30.0.2`); the
  sidecar has `extra_hosts: postgres:172.30.0.2` so the server can still reach
  the database after `network_mode: service:tailscale`.

### Optional HTTPS (`tailscale serve`)

`deploy/ts-serve.json` is a template that proxies to `http://127.0.0.1:8080`.
That matches a process listening on loopback **inside the sidecar namespace**.
If you want Serve/HTTPS instead of binding `100.x` directly:

1. Set `PCS_BIND_MODE=localhost` (loopback in the shared netns).
2. Mount the serve config: `TS_SERVE_CONFIG=/config/serve.json` and a volume
   onto `deploy/ts-serve.json` (replace `${TS_CERT_DOMAIN}` with your MagicDNS
   name).

Do not pass `--funnel`.

## Published image vs build-from-source (FR40)

The compose `server` service both **builds** `deploy/Dockerfile.server` and
accepts `PCS_IMAGE`:

```bash
export PCS_IMAGE=ghcr.io/example/pcs-server:v1
docker compose -f deploy/docker-compose.yml up --wait
```

To publish: build `deploy/Dockerfile.server` from the repo root (it copies
`server/` + `web/` and bakes the Vite `dist/` into the image). No `.env` or
auth keys are copied (see `.dockerignore`).

`deploy/Dockerfile.web` is an optional nginx image if you split static serving;
the default stack does **not** use it — the server process serves `/` and
`/assets` (NFR13).

## Host-mode (no Docker for the app)

```bash
just setup && just up && just migrate
cd server && uv run pcs http          # 127.0.0.1:8080
# or
PCS_BIND_MODE=tailscale uv run pcs http   # binds tailnet IPv4
uv run pcs stdio                         # always available
```

## Configuration

Every variable the process reads is in [`.env.example`](../.env.example)
(`PCS_` prefix, plus compose `POSTGRES_*` / `TS_*`). Mount a file or inject
env; do not rebuild the image to change config (FR40).
