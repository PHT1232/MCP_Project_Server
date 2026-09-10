# T08 — Deployment: Docker + Tailscale

**Branch:** `task/T08-deploy`  ·  **Depends on:** T00 (develop early, finalize last)

> Stub — flesh out after T00; final pass once server + frontend are real.

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
- [ ] `docker compose up` from clean checkout → server + PG healthy; register a project + fetch a briefing with only mount-path config (AC25)
- [ ] Tailscale on → reachable from another tailnet device by name; NOT reachable from a non-tailnet LAN host or public internet (AC26)
- [ ] Tailscale off → localhost only (AC26)
- [ ] No secrets baked into images; `.env.example` complete
- [ ] `just check` green; compose config linted
- [ ] Handoff written

## Handoff
_(fill in)_
