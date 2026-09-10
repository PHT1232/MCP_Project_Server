# Project Context MCP Server (`pcs`)

Shared, compact project briefing for AI agents, plus a searchable code index and a web UI with a level-of-detail code map. Spec: [REQUIREMENTS.md](REQUIREMENTS.md). Contributor workflow: [AGENTS.md](AGENTS.md).

## Quick start with Docker

From a clean checkout with Docker Compose v2:

```bash
cp .env.example .env
docker compose -f deploy/docker-compose.yml up --build --wait
```

The API, streamable HTTP MCP transport, and UI are available on `http://127.0.0.1:8080` only. PostgreSQL is published on host loopback at port `5432`.

Register a project and fetch its briefing. The container sees `PCS_REPOS_DIR` at `/repos`; the default host directory is this repository's `repos/` placeholder.

```bash
curl -s http://127.0.0.1:8080/api/health
curl -s -X POST http://127.0.0.1:8080/api/projects \
  -H 'content-type: application/json' \
  -d '{"name":"demo","root_path":"/repos","overview":"Local demo project."}'
curl -s http://127.0.0.1:8080/api/projects/demo/briefing
```

Set `PCS_REPOS_DIR` to the host directory containing projects and register `/repos/<subdir>` when serving more than one repository. Semantic search is disabled by default; keyword and structural search remain available.

## MCP clients

For a co-located client, configure stdio with the `server` directory as the working directory:

```json
{
  "command": "uv",
  "args": ["run", "pcs", "stdio"],
  "cwd": "/absolute/path/to/mcp_server/server"
}
```

For a streamable HTTP client, use:

```text
http://127.0.0.1:8080/mcp
```

MCP calls identify projects by exact name or ID. The JSON frontend API is separate under `/api`.

## Development

Install dependencies and start PostgreSQL:

```bash
just setup
just up
just migrate
```

Run the servers in separate terminals from the repository root:

```bash
# Terminal 1
(cd server && uv run pcs http)

# Terminal 2
(cd web && npm run dev)
```

Vite proxies `/api` to `http://127.0.0.1:8080` by default. Run the full project gate with:

```bash
just check
```

## Documentation

- [Architecture](docs/architecture.md)
- [Configuration reference](docs/configuration.md)
- [MCP tools and resources](docs/mcp-reference.md)
- [HTTP API](docs/http-api.md)
- [Deployment, persistence, and Tailscale](docs/deploy.md)
