# Project Context MCP Server (`pcs`)

Shared, compact project briefing for AI agents, plus a searchable code index, a web UI with a level-of-detail code map, and multi-agent plan/task orchestration with atomic claim leases and AI-assisted (human-approved) plan drafting. Spec: [REQUIREMENTS.md](REQUIREMENTS.md). Contributor workflow: [AGENTS.md](AGENTS.md).

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

### VPS port and existing host Tailscale

To publish PCS on VPS loopback port `8989`, set these values in `.env`:

```dotenv
PCS_PORT=8989
PCS_BIND_MODE=localhost
PCS_BIND_ADDRESS=0.0.0.0
```

`PCS_PORT=8989` selects the **host** port. The Compose file must keep the server's internal environment and target port at `8080`:

```yaml
environment:
  PCS_PORT: "8080"
ports:
  - "127.0.0.1:${PCS_PORT:-8080}:8080"
```

After changing `.env`, recreate the base stack and verify it from the VPS:

```bash
docker compose -f deploy/docker-compose.yml up -d --build --force-recreate
curl http://127.0.0.1:8989/api/health
```

Expected Compose mapping: `127.0.0.1:8989->8080/tcp`. `PCS_BIND_ADDRESS=0.0.0.0` applies inside the container; Docker still publishes PCS only on VPS loopback.

If Tailscale is already installed on the VPS host, do **not** use `deploy/docker-compose.tailscale.yml` or configure `TS_AUTHKEY`. Publish the loopback service through the existing daemon:

```bash
tailscale status
sudo tailscale serve --bg http://127.0.0.1:8989
tailscale serve status
```

From another device on the same tailnet, open the HTTPS URL shown by `tailscale serve status`. Its endpoints are:

```text
https://<vps-name>.<tailnet>.ts.net/
https://<vps-name>.<tailnet>.ts.net/api/health
https://<vps-name>.<tailnet>.ts.net/mcp
```

Do not enable `tailscale funnel`; Funnel makes the service public. Remove the private proxy with `sudo tailscale serve reset`.

The optional Compose sidecar in `deploy/docker-compose.tailscale.yml` is only for hosts that need PCS to run as a separate Tailscale node.

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

## Plan & task orchestration

Break work into a plan with a task DAG, claim tasks with expiring leases, and let agents (or people) drive them to completion — via MCP tools, HTTP routes, or the Plans page in the web UI (`/projects/:project/plans`). Task completion never touches requirement status (D4): orchestration and requirement close-gate compliance stay independent.

```bash
PLAN=$(curl -s -X POST http://127.0.0.1:8080/api/projects/demo/plans/with-tasks \
  -H 'content-type: application/json' \
  -d '{"title":"Ship checkout","goal":"Migrate off the legacy gateway","tasks":[
        {"local_task_id":"t1","title":"Add pricing helper","objective":"Implement unit_price."}
      ]}')
PLAN_ID=$(echo "$PLAN" | jq -r .id)
curl -s -X POST http://127.0.0.1:8080/api/projects/demo/plans/$PLAN_ID/activate
curl -s http://127.0.0.1:8080/api/projects/demo/ready-tasks
```

An AI provider configured under [AI Settings](docs/http-api.md#global-ai-provider-settings-t20) can also propose a draft plan (`generate_plan_draft` / `POST .../plans/generate-draft`) — strictly advisory and read-only until a caller explicitly reviews and approves it via the same `create_plan_with_tasks` atomic path a manually authored plan uses. See [Architecture](docs/architecture.md#plan--task-orchestration) for the full lease lifecycle and DAG model, and the MCP/HTTP references below for every tool and route.

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
- [VPS troubleshooting runbook](docs/troubleshooting.md)
