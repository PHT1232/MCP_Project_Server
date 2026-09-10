# VPS troubleshooting runbook

This runbook records the fixes used for a Docker Compose deployment on a VPS where Tailscale is already installed on the host.

## 1. Recommended directory layout

Keep PCS and indexed repositories in separate directories:

```text
/root/MCP_Project_Server/       # PCS checkout
/root/pcs-repos/                # repositories PCS indexes
/root/pcs-repos/my-project/     # one indexed repository
/root/pcs-repos/.project-context/
```

Create the directories and clone a project on the VPS host:

```bash
mkdir -p /root/pcs-repos/.project-context
git clone YOUR_GIT_REPOSITORY_URL /root/pcs-repos/my-project
ls -la /root/pcs-repos/my-project
```

PCS does not clone repositories. The repository must already exist in the host directory mounted into the server container.

## 2. Configure the repository mount

Set these values in `/root/MCP_Project_Server/.env`:

```dotenv
PCS_REPOS_DIR=/root/pcs-repos
PCS_REQUIREMENTS_DIR=/root/pcs-repos/.project-context
```

The Compose file maps them as follows:

```text
VPS host                              Server container
/root/pcs-repos                       /repos
/root/pcs-repos/my-project            /repos/my-project
/root/pcs-repos/.project-context      /repos/.project-context
```

The dashboard **Root path** must use the container path:

```text
/repos/my-project
```

Do not enter either of these:

```text
pcs-repos/my-project
/root/pcs-repos/my-project
```

### Apply a changed mount

Changing `.env` does not modify an existing container. Recreate it:

```bash
cd /root/MCP_Project_Server
docker compose --env-file .env -f deploy/docker-compose.yml \
  up -d --build --force-recreate server
```

Inspect the actual running mounts:

```bash
docker inspect "$(docker compose -f deploy/docker-compose.yml ps -q server)" \
  --format '{{range .Mounts}}{{println .Source "->" .Destination}}{{end}}'
```

Expected:

```text
/root/pcs-repos -> /repos
/root/pcs-repos/.project-context -> /repos/.project-context
```

Confirm the project is visible inside the container:

```bash
docker compose -f deploy/docker-compose.yml exec server ls -la /repos
docker compose -f deploy/docker-compose.yml exec server ls -la /repos/my-project
```

If Compose still renders an old source path, check for a shell variable overriding `.env`:

```bash
printenv PCS_REPOS_DIR
unset PCS_REPOS_DIR
```

Then recreate the server again with `--env-file .env`.

## 3. Fix a reset connection on a custom port

For VPS loopback port `8989`, `.env` contains:

```dotenv
PCS_PORT=8989
PCS_BIND_MODE=localhost
PCS_BIND_ADDRESS=0.0.0.0
```

The host port and container port are different. In `deploy/docker-compose.yml`, the server must still listen internally on `8080`:

```yaml
services:
  server:
    environment:
      PCS_BIND_MODE: ${PCS_BIND_MODE:-localhost}
      PCS_BIND_ADDRESS: ${PCS_BIND_ADDRESS:-0.0.0.0}
      PCS_PORT: "8080"
    ports:
      - "127.0.0.1:${PCS_PORT:-8080}:8080"
```

Correct mapping:

```text
VPS 127.0.0.1:8989 -> container 0.0.0.0:8080
```

A connection reset occurs when both values are `8989` in the container environment while Docker still targets container port `8080`.

Inspect the rendered configuration:

```bash
docker compose --env-file .env -f deploy/docker-compose.yml config \
  | sed -n '/server:/,/^[^ ]/p'
```

It must show:

```yaml
PCS_PORT: "8080"
```

and a port mapping with:

```yaml
host_ip: 127.0.0.1
published: "8989"
target: 8080
```

Recreate and test:

```bash
docker compose --env-file .env -f deploy/docker-compose.yml \
  up -d --build --force-recreate server
curl -v --max-time 10 http://127.0.0.1:8989/api/health
```

If it still fails:

```bash
docker compose -f deploy/docker-compose.yml ps
docker compose -f deploy/docker-compose.yml logs --tail=200 server
docker compose -f deploy/docker-compose.yml exec server python -m pcs.healthcheck
```

## 4. Use Tailscale already installed on the VPS

Do not start `deploy/docker-compose.tailscale.yml` when using the VPS host's existing Tailscale daemon. That overlay creates a separate Tailscale sidecar node.

First verify PCS locally:

```bash
curl http://127.0.0.1:8989/api/health
```

Then publish the loopback service privately:

```bash
tailscale status
sudo tailscale serve --bg http://127.0.0.1:8989
tailscale serve status
```

From another device on the same tailnet, use the HTTPS hostname printed by `tailscale serve status`:

```text
https://<vps-name>.<tailnet>.ts.net/
https://<vps-name>.<tailnet>.ts.net/api/health
https://<vps-name>.<tailnet>.ts.net/mcp
```

Do not enable `tailscale funnel`; Funnel makes the service public.

Remove the proxy with:

```bash
sudo tailscale serve reset
```

## 5. Enable semantic search

Keyword and structural search work without embeddings. Semantic search requires an embedding backend followed by a full reindex.

The embedding values belong under `services.server.environment` in `deploy/docker-compose.yml`:

```yaml
PCS_EMBEDDING_BACKEND: ${PCS_EMBEDDING_BACKEND:-}
PCS_EMBEDDING_BASE_URL: ${PCS_EMBEDDING_BASE_URL:-}
PCS_EMBEDDING_API_KEY: ${PCS_EMBEDDING_API_KEY:-}
PCS_EMBEDDING_MODEL: ${PCS_EMBEDDING_MODEL:-text-embedding-3-small}
PCS_EMBEDDING_DIMENSIONS: ${PCS_EMBEDDING_DIMENSIONS:-1536}
PCS_EMBEDDING_BATCH_SIZE: ${PCS_EMBEDDING_BATCH_SIZE:-64}
PCS_EMBEDDING_TIMEOUT_SECONDS: ${PCS_EMBEDDING_TIMEOUT_SECONDS:-30}
```

### Local hashing backend

This backend is free, offline, and keeps code on the VPS, but offers lower-quality matching than a learned model:

```dotenv
PCS_EMBEDDING_BACKEND=hashing
PCS_EMBEDDING_BASE_URL=
PCS_EMBEDDING_API_KEY=
PCS_EMBEDDING_MODEL=hashing
PCS_EMBEDDING_DIMENSIONS=512
PCS_EMBEDDING_BATCH_SIZE=64
PCS_EMBEDDING_TIMEOUT_SECONDS=30
```

### OpenAI backend

OpenAI API billing is separate from a ChatGPT Pro subscription:

```dotenv
PCS_EMBEDDING_BACKEND=openai
PCS_EMBEDDING_BASE_URL=https://api.openai.com/v1
PCS_EMBEDDING_API_KEY=YOUR_API_KEY
PCS_EMBEDDING_MODEL=text-embedding-3-small
PCS_EMBEDDING_DIMENSIONS=1536
PCS_EMBEDDING_BATCH_SIZE=64
PCS_EMBEDDING_TIMEOUT_SECONDS=30
```

Project code chunks are sent to the configured OpenAI-compatible endpoint. Do not commit `.env` or display the API key in logs or support messages.

Recreate the server after changing these values:

```bash
docker compose --env-file .env -f deploy/docker-compose.yml \
  up -d --build --force-recreate server
```

Verify settings without printing the key:

```bash
docker compose --env-file .env -f deploy/docker-compose.yml exec server sh -c '
env | grep -E "^PCS_EMBEDDING_(BACKEND|BASE_URL|MODEL|DIMENSIONS|BATCH_SIZE|TIMEOUT_SECONDS)="
if [ -n "$PCS_EMBEDDING_API_KEY" ]; then
  echo "PCS_EMBEDDING_API_KEY=set"
else
  echo "PCS_EMBEDDING_API_KEY=missing"
fi
'
```

## 6. Run the required full reindex

Existing chunks are not automatically embedded after enabling a backend. Run a full reindex, not an incremental one.

For a project named `PhanMemBaoGia 2`, URL-encode the space:

```bash
curl -sS -X POST \
  'http://127.0.0.1:8989/api/projects/PhanMemBaoGia%202/reindex' \
  -H 'content-type: application/json' \
  -d '{"incremental":false}'
```

Check status:

```bash
curl -sS \
  'http://127.0.0.1:8989/api/projects/PhanMemBaoGia%202/index'
```

Successful semantic indexing reports:

```json
{
  "semantic_available": true,
  "semantic_model": "text-embedding-3-small",
  "embedded_chunk_count": 663
}
```

The exact chunk count depends on the repository.

## 7. Fix OpenAI HTTP 429 errors

This log means PCS is configured correctly but the provider rejected the request:

```text
embedding_failed: 429 Too Many Requests
```

Common causes:

- OpenAI API billing is not enabled.
- The API project budget is zero or exhausted.
- The account or project rate limit was reached.
- The key belongs to a project without available API quota.

A ChatGPT Pro subscription does not include OpenAI API credit. Check:

- <https://platform.openai.com/usage>
- <https://platform.openai.com/settings/organization/billing/overview>
- <https://platform.openai.com/settings/organization/limits>
- <https://platform.openai.com/api-keys>

After fixing billing or limits, run another full reindex. Alternatively, switch to the local `hashing` backend and full-reindex without API cost.

## 8. Routine diagnostics

```bash
# Container status
docker compose -f deploy/docker-compose.yml ps

# Recent server logs
docker compose -f deploy/docker-compose.yml logs --tail=200 server

# Follow logs during reindex
docker compose -f deploy/docker-compose.yml logs -f server

# Local health
curl -sS http://127.0.0.1:8989/api/health

# Actual mounts
docker inspect "$(docker compose -f deploy/docker-compose.yml ps -q server)" \
  --format '{{range .Mounts}}{{println .Source "->" .Destination}}{{end}}'
```
