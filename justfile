# Project Context MCP Server — task runner.
# `just check` is the single gate every task must keep green.

set shell := ["bash", "-euo", "pipefail", "-c"]

server_dir := "server"
web_dir := "web"
compose := "docker compose -f deploy/docker-compose.yml"

# List recipes.
default:
    @just --list

# Install all dependencies (server + web).
setup:
    cd {{server_dir}} && uv sync
    cd {{web_dir}} && npm ci || (cd {{web_dir}} && npm install)

# Auto-format and apply safe lint fixes.
fmt:
    cd {{server_dir}} && uv run ruff format . && uv run ruff check --fix .
    cd {{web_dir}} && npm run fmt

# Lint + format check (no writes).
lint:
    cd {{server_dir}} && uv run ruff format --check . && uv run ruff check .
    cd {{web_dir}} && npm run lint

# Static type checks (mypy --strict + tsc --noEmit).
typecheck:
    cd {{server_dir}} && uv run mypy
    cd {{web_dir}} && npm run typecheck

# Tests (pytest + vitest).
test:
    cd {{server_dir}} && uv run pytest
    cd {{web_dir}} && npm run test

# Validate compose files (compose CLI; does not start containers).
compose-lint:
    docker compose -f deploy/docker-compose.yml config -q
    docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.tailscale.yml config -q

# Full gate: format check, lint, types, tests, production web build, compose files.
check: lint typecheck test compose-lint
    cd {{web_dir}} && npm run build

# Apply database migrations from empty to head.
migrate:
    cd {{server_dir}} && uv run alembic upgrade head

# Start the PostgreSQL container and wait for it to be healthy.
# Full stack (server + PG): docker compose -f deploy/docker-compose.yml up --wait
up:
    {{compose}} up -d --wait postgres

# Stop compose services (keeps named volumes).
down:
    {{compose}} down

# Run a task's acceptance suite. No-op stub until T09 wires real acceptance.
accept task:
    @echo "[accept] stub for {{task}} — real acceptance wiring lands with T09"
