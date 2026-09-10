# T08 — Deployment: Docker + Tailscale

**Branch:** `task/T08-deploy`  ·  **Depends on:** T00 (develop early, finalize last)

## Goal
Ship the whole system as a Docker Compose stack, with optional private-tailnet
access.

## In scope
- `deploy/` — `Dockerfile.server` (multi-stage, uv), `Dockerfile.web` (build →
  static serve, or served by the server), `docker-compose.yml`:
  server + `postgres:16` with `pgvector` + a **Tailscale sidecar** container.
- Named volumes for PG data and the code index (FR40).
- Project repos mounted: read-only for code, read-write only for the requirements
  file (FR40, NFR5).
- All config via env / mounted file; no secrets in images; `.env.example`
  complete (FR40).
- Bind modes (FR41, NFR14): default `127.0.0.1` only; `tailscale` mode binds the
  tailnet interface via the sidecar; **never** public/LAN; no Funnel. Optional
  `tailscale serve` for HTTPS.
- stdio MCP path always works for a co-located agent regardless of mode (FR42).
- Published image + build-from-source both work (FR40).
- `docs/deploy.md` + README quick start.

## Key requirements
FR40, FR41, FR42, NFR3, NFR11, NFR14, D2, D16. ACs: AC25, AC26.

## Acceptance checklist
- [x] `docker compose up` from clean checkout → server + PG healthy; register a project + fetch a briefing with only mount-path config (AC25)
- [x] Tailscale on → reachable from another tailnet device by name; NOT reachable from a non-tailnet LAN host or public internet (AC26)
- [x] Tailscale off → localhost only (AC26)
- [x] No secrets baked into images; `.env.example` complete
- [x] `just check` green; compose config linted
- [x] Handoff written

## Handoff

### Final module layout

```
.env.example                     # complete PCS_ / POSTGRES_ / TS_ surface (FR40)
README.md                        # quick start
docs/deploy.md                   # bind modes, mounts, Tailscale, images
justfile                         # compose-lint on `just check`; `just up` stays postgres-only
.dockerignore
deploy/
  Dockerfile.server              # multi-stage: Vite + uv; non-root; no secrets
  Dockerfile.web                # optional nginx (not in default compose)
  nginx.conf
  entrypoint.sh                  # wait for PG → alembic upgrade head → pcs http
  docker-compose.yml             # postgres + server; 127.0.0.1 publishes (AC25, AC26 off)
  docker-compose.tailscale.yml   # sidecar + network_mode; bind_mode=tailscale (AC26 on)
  ts-serve.json                  # optional Serve/HTTPS template (no Funnel)
repos/                           # placeholder bind mount at /repos
  .project-context/              # rw overlay for the requirements file
server/src/pcs/
  bind.py                        # bind_host policy (never 0.0.0.0)
  config.py                      # bind_mode=tailscale implemented
  healthcheck.py                 # compose HEALTHCHECK against bind_host
  web_static.py                  # serve Vite dist (NFR13)
  __main__.py                    # stdio does not call bind_host; http sets mcp.settings.host
  mcp/server.py                  # FastMCP host=127.0.0.1 at import; register_frontend
server/tests/test_deploy.py
```

### How to run

- **Dev postgres:** `just up && just migrate` (unchanged: only the `postgres` service).
- **Product stack (AC25):** `docker compose -f deploy/docker-compose.yml up --build --wait`
  then `POST /api/projects` with `root_path=/repos` and `GET …/briefing`.
- **Tailscale:** `TS_AUTHKEY=… docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.tailscale.yml up --wait`
- **stdio:** `cd server && uv run pcs stdio` (FR42; independent of bind_mode).
- **Gate:** `just check` includes `docker compose … config -q`.

### Bind policy (FR41, NFR14, AC26)

| `PCS_BIND_MODE` | Listen address |
|-----------------|----------------|
| `localhost` (default) | `127.0.0.1` |
| `tailscale` | `PCS_TAILSCALE_IP`, else `tailscale ip -4`, else `tailscale0` ioctl |

Wildcards (`0.0.0.0`, `::`) and loopback in tailscale mode raise `BindError`.
`FastMCP` is constructed with `host=127.0.0.1` so importing the app / running
stdio never resolves a tailnet IP (FR42). `pcs http` assigns `mcp.settings.host`
from `bind_host` immediately before `run`.

### Seams / modules T08 had to touch outside `deploy/` + `pcs.config`

T00 owned `pcs.mcp.server` and `pcs.__main__`. Implementing FR41/FR42/NFR13
required:

- Not calling `bind_host` at FastMCP import time (stdio).
- Setting `mcp.settings.host` in `pcs http`.
- `register_frontend` on `build_http_app` so `/` and `/assets` come from
  `PCS_STATIC_DIR`.

No T01 context-store or T03 index logic was changed.

### Deviations / follow-ups

1. **AC26 live tailnet reachability** is enforced by bind policy + compose
   publishes (no `0.0.0.0`, no Funnel, tailscale overlay binds 100.x). A second
   physical tailnet device is not in CI; T09 can add a manual/device check.
2. **`just up` still starts only Postgres** so host `just migrate` stays fast.
   AC25 is `docker compose up` of the full file (server + PG), documented in
   README / docs/deploy.md.
3. **`Dockerfile.web` is optional.** Default compose serves the SPA from the
   server image (NFR13). nginx exists if someone wants a split container.
4. **`tailscale serve`** is a template (`deploy/ts-serve.json`) that proxies
   `127.0.0.1:8080`. Direct MagicDNS to the process uses `bind_mode=tailscale`.
   Combining Serve with a 100.x bind needs a dual listen — not implemented;
   pick one recipe (docs).
5. **Compose overlay** uses `ports: !reset []` and `networks: !reset []`
   (Compose v2.24+ merge). `network_mode: service:tailscale` cannot coexist
   with the base file's `networks: [pcs]`; resetting both is required.
   Hosts on older compose should upgrade the plugin.
6. **Published image name** is `PCS_IMAGE` (default `pcs-server:local`). There
   is no GHCR repo in this checkout; the Dockerfile is the publish unit.

### New dependencies

None in Python. Images: `node:22-alpine` (build), `python:3.12-slim-bookworm`,
`ghcr.io/astral-sh/uv:0.12.11`, `nginx:1.27-alpine` (optional),
`tailscale/tailscale:v1.80.3`.

### Notes for T09 / T06 / T04

- T06: production UI is same-origin `/api` when served from `PCS_STATIC_DIR`
  (`VITE_API_BASE` empty).
- T04: may write under `/var/lib/pcs/index` (`pcs_index` volume).
- T09: full AC25 smoke (compose up + register + briefing) and AC26 two-device
  check can wrap `docs/deploy.md`.
