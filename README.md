# Project Context MCP Server (`pcs`)

Shared, compact project briefing for AI agents, plus a code index and a small
web UI. Spec: [REQUIREMENTS.md](REQUIREMENTS.md). How to work in this repo:
[AGENTS.md](AGENTS.md).

## Quick start (Docker)

From a clean checkout, with Docker Compose v2:

```bash
cp .env.example .env          # optional; defaults work for local
docker compose -f deploy/docker-compose.yml up --build --wait
```

The API and UI listen on **http://127.0.0.1:8080** only (not LAN/public).

Register a project and fetch a briefing (mount path is `/repos` inside the
container — the `./repos` placeholder, or set `PCS_REPOS_DIR`):

```bash
curl -s http://127.0.0.1:8080/api/health
curl -s -X POST http://127.0.0.1:8080/api/projects \
  -H 'content-type: application/json' \
  -d '{"name":"demo","root_path":"/repos","overview":"Local demo project."}'
curl -s http://127.0.0.1:8080/api/projects/demo/briefing
```

stdio MCP (co-located agent, no network) still works on the host:

```bash
cd server && uv sync && uv run pcs stdio
```

Full deploy notes, Tailscale, and bind modes: [docs/deploy.md](docs/deploy.md).

## Development (no full stack)

```bash
just setup
just up          # Postgres on 127.0.0.1:5432
just migrate
cd server && uv run pcs http    # 127.0.0.1:8080
cd web && npm run dev           # Vite, proxies /api
just check
```
