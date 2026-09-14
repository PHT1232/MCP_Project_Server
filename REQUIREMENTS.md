# Project Context MCP Server — Requirements

**Status:** Draft v0.6
**Last updated:** 2026-09-10
**Owner:** phattannnguyen@gmail.com

---

## 1. Summary

A [Model Context Protocol](https://modelcontextprotocol.io) (MCP) server that acts as
the single source of truth for **project working context** shared across every AI
coding agent involved in a project.

Instead of each agent (or each session) rediscovering the project by re-reading
`README.md`, scattered `.md` notes, and large portions of the codebase, agents
query this server and receive a compact, current briefing: what the project is,
what is being worked on, what is blocked, known bugs, and the coding conventions
to follow.

The server also maintains a **searchable index of the entire codebase** (keyword
+ semantic / RAG) so agents can locate relevant code without scanning files, and
ships a **web frontend** with an interactive **code map** so a human can
understand the project's structure, dependencies, and hot spots at a glance.

The system therefore has three parts:

1. **Context store** — curated operational context per project (§7.1–§7.5).
2. **Code intelligence** — full-codebase search + semantic retrieval (§7.6).
3. **Frontend** — code map and context dashboard (§7.7), styled per `DESIGN.md`.

**Companion documents:** `DESIGN.md` (frontend style reference — normative for
UI/UX, see FR39a).

---

## 1a. Architecture Decisions (v1)

These resolve the open questions from earlier drafts. Rationale and any residual
sub-questions are in §11.

| # | Decision |
|---|----------|
| D1 | **PostgreSQL** is the single datastore — context, per-entry history, code index, and vector embeddings (via `pgvector`). No file-based or SQLite store. |
| D2 | **Single-user, single-instance.** No team mode, no multi-tenant/hosted server, no app-level authentication. Reachable only from the user's own devices — localhost by default, or the user's private Tailscale tailnet (D16). Never bound to a public interface. |
| D3 | **Explicit project selection.** Every call names its project; there is no CWD-based or automatic project resolution. |
| D4 | **Fully agent-/human-driven context.** The server never infers blockers, bugs, or requirement status from tests, CI, or code. |
| D5 | **Full audit log.** Every entry change is an immutable revision; nothing is hard-deleted. |
| D6 | **Manual refresh** in the frontend. No live push (WebSocket/SSE) in v1. |
| D7 | **No bundled embedding model.** Semantic search is off until the user configures a backend; keyword/structural search always works. |
| D8 | **Reuse existing analysis tooling** (tree-sitter + a SCIP/LSP-style symbol layer). Symbol-level support limited to **7 language families**: TypeScript/JavaScript, Python, Java, Go, Rust, C#, C/C++. Others get keyword + plain-text chunking only. |
| D9 | **Server-side code-map aggregation.** The server serves the map with level-of-detail; the client only holds the visible subgraph. |
| D10 | **Task-prep call.** `search_code` and `retrieve_context` stay as primitives; a `prepare_task` convenience call returns briefing + relevant code in one budgeted response. |
| D11 | **Static structure only** in the code map — no churn or git-history overlays in v1. |
| D12 | **Requirements template file.** Requirements live in a structured, human-editable template file in the repo that the server keeps in two-way sync with the context store. |
| D13 | **Budget defaults.** Briefing 1,500 tokens; `prepare_task` 4,000 tokens with curated context capped at 50% and code floored at 30%; `headline` ≤ 120 chars; `detail` ≤ 8,000 chars. All configurable. (§7.2a) |
| D14 | **Code-analysis toolchain.** tree-sitter for parsing/chunking in all 7 families; a per-language SCIP indexer for symbols/xrefs, normalized to one SCIP model in PostgreSQL; tree-sitter `tags` queries as fallback. (FR23c) |
| D15 | **Requirements sync model.** File owns requirement existence + title/prose; store owns status + links + history. 3-way merge against a last-synced snapshot; on a status conflict the store wins and the file's status token is rewritten. Status is never inferred. (FR16a) |
| D16 | **Docker + Tailscale.** Ships as a Docker Compose stack (server + PostgreSQL). Access is localhost by default; optionally the stack joins the user's Tailscale tailnet and serves the frontend + HTTP MCP endpoint there, so the user reaches it from any of their own devices. Tailscale provides device identity/ACLs; no public exposure (no Funnel). (§7.8) |
| D17 | **Design language = `DESIGN.md`.** The frontend follows the "Fey" style reference in `DESIGN.md` — dark matte-black canvas, Calibre type, pill (99px) controls, 16px cards, single-black-halo depth, chromatic accents (Ember/Signal/Growth) only as meaning-carriers. Tokens are implemented verbatim from that file. (FR39a) |
| D18 | **Deterministic plan & task DAG.** Plans decompose work into tasks with explicit directed acyclic graph (DAG) dependencies. Cycles, self-dependencies, cross-plan, and cross-project links are rejected at creation and update by database and service constraints. (FR43–FR45) |
| D19 | **Requirement independence (Preserve D4).** Task completion and plan completion never mutate requirement status or close-gate state. Tasks track operational execution progress; requirements represent verified product contracts governed strictly by the evidence ledger and close gate. (FR53) |
| D20 | **Atomic exclusive leases & ephemeral tokens.** Claiming a task atomically grants a time-bounded lease with an expiring TTL and returns an ephemeral one-time secret token. Mutating a claimed task requires presenting the valid current token. Expired leases can be reclaimed safely by other workers without data loss. (FR47) |
| D21 | **Immutable task event audit trail.** Every plan task mutation (creation, claim, heartbeat, release, status change, completion) appends an immutable event row recording author, transition, and timestamp (mirroring D5). (FR48) |
| D22 | **Bounded role-neutral task handoff prompt.** `prepare_task(task_id=...)` returns a self-contained, token-budgeted Markdown prompt ready to paste into any implementation agent, incorporating task objective, acceptance criteria, dependency state, and linked requirement contracts without emitting secrets, tokens, or raw diffs. (FR49) |
| D23 | **Advisory AI plan generation with human approval.** AI plan drafting (`generate_plan_draft`) is an unprivileged, read-only advisory service utilizing validated T20 settings. It creates zero database records; persistence occurs only upon explicit human review and atomic creation (`create_plan_with_tasks`). (FR50–FR51) |
| D24 | **Milestone execution boundaries (Non-goals).** Agent process spawning/dispatch, local shell or container execution, Git worktree orchestration, GitHub issue/PR sync, and fine-grained authorization are non-goals for this milestone. PCS is the central context and orchestration ledger, not a runtime supervisor. (FR43–FR53) |

---

## 2. Problem Statement

When multiple agents — or the same agent across many sessions — work on one
project, their understanding of that project is **fragmented and repeatedly
rebuilt**:

- Each new session starts "cold" and burns tokens re-reading docs and code to
  reconstruct context that another session already had.
- Context lives in an agent's transient memory, so decisions, blockers, and
  conventions discovered by one agent are invisible to the next.
- Weaker / cheaper models perform poorly because they must infer project intent
  from raw source instead of being told it directly.
- Onboarding a fresh agent to a task requires a long human prompt or a large
  paste of background material.

---

## 3. Goals

- **G1** — Give any agent an accurate project briefing from a short prompt, with
  no need to pre-read docs or code.
- **G2** — Keep one shared, persistent context per project that all agents read
  from and write to.
- **G3** — Reduce token consumption per task by replacing exploratory
  file-reading with a single context query.
- **G4** — Improve the effective quality of weaker models by supplying explicit
  intent, constraints, and conventions.
- **G5** — Shorten debug and development cycles by surfacing current blockers and
  known bugs immediately.
- **G6** — Let agents find relevant code by intent, not just filename, through a
  full-codebase keyword + semantic (RAG) index.
- **G7** — Let a human understand an unfamiliar or evolving project quickly
  through a visual code map in a web frontend.

## 4. Non-Goals

- Not a replacement for version control, issue trackers, or full documentation.
- Not a long-term knowledge base or wiki; the curated context is intentionally
  small and operational ("what matters right now") — distinct from the code
  index, which is exhaustive and machine-generated.
- Not responsible for executing code, running builds, or editing project files.
- The frontend is for **understanding**, not a full IDE or code editor; no
  in-browser editing, refactoring, or terminal in v1.
- **Single-user, single-instance** (D2). No team mode, shared/hosted server,
  multi-tenant SaaS, authentication provider, or billing in v1. Reaching it from
  several of the user's *own* devices over a private Tailscale tailnet (D16) is
  in scope; anything multi-user or publicly exposed is not.
- The server does not infer context from tests, CI, or code (D4) — it only stores
  what an agent or human tells it.
- **Not an agent process supervisor or task execution worker (D24):** PCS manages plan state, DAG dependencies, leases, and handoff prompts; it does not spawn processes, manage terminal/shell sessions, or run agent commands.
- **Not a Git worktree or branch orchestrator (D24):** PCS does not create worktrees, switch branches, or automate git operations for tasks.
- **Not an external issue tracker sync (D24):** PCS does not sync bidirectional issues or pull requests with GitHub, Jira, or Linear in this milestone.
- **No fine-grained multi-user authorization (D2, D24):** Single-user model is preserved; no per-agent ACLs or role-based access control.

---

## 5. Business Requirements

| ID | Requirement | Success measure |
|----|-------------|-----------------|
| BR1 | Reduce fragmented context between agents working on the same project | A second agent picking up a task needs zero additional human context beyond the task itself |
| BR2 | Reduce time-to-first-useful-action for a new agent session | Agent produces a relevant change/plan without a preceding "exploration" phase |
| BR3 | Reduce token usage per task | Measurable drop in input tokens spent on file reads during the orientation phase vs. baseline |
| BR4 | Let weaker / cheaper models perform acceptably on project tasks | A smaller model, given server context, completes tasks that previously required a larger model |
| BR5 | Reduce debugging time | Known blockers and bugs are visible to the agent before it starts, avoiding rediscovery |
| BR6 | Cut time spent locating relevant code (human and agent) | A relevant-code lookup returns the right files/symbols in one query instead of a file-by-file search |
| BR7 | Speed up onboarding to an unfamiliar project | A developer can describe the project's architecture after a few minutes with the code map, without reading the source |

---

## 6. User Requirements

### Personas

- **Developer** — orchestrates one or more agents on a project; wants to prompt
  briefly and trust the agent has context.
- **Agent** — an MCP client (Claude Code, IDE assistant, custom orchestrator)
  that consumes and updates context.

### User stories

- **UR1** — As a developer, I can prompt any agent with a minimal instruction
  (e.g. "fix the failing auth test") and — given the project it is configured for
  — the agent understands what it does and the relevant constraints without me
  explaining them.
- **UR2** — As a developer, I do not have to keep re-pasting project background,
  conventions, or "gotchas" into each new agent or session.
- **UR3** — As an agent, at the start of a task I can retrieve the current
  project briefing in one call.
- **UR4** — As an agent, when I discover a new blocker, bug, decision, or
  convention, I can record it so the next agent sees it.
- **UR5** — As a developer, I can inspect and hand-edit the stored context for a
  project.
- **UR6** — As a developer working across several projects, each project's
  context is isolated and selected explicitly by name/ID on every call (D3).
- **UR7** — As an agent, I can search the codebase by natural-language intent
  (e.g. "where are auth tokens validated") and get back the specific files,
  symbols, and line ranges, ranked by relevance.
- **UR8** — As a developer, I can open a web frontend and see a code map of the
  project — modules, their relationships, size/complexity, and where the current
  focus, blockers, and bugs live — and drill from any node into the code and its
  context. I can also see the project's requirements and their status — what is
  done and what is not.

---

## 7. Functional Requirements

### 7.1 Project context store

- **FR1** — The server maintains a separate context record per project,
  identified by a stable project ID (and a human-readable name).
- **FR2** — Each project context contains at minimum:
  - **Overview** — what the project is and its purpose.
  - **Current focus** — the task(s) actively being worked on.
  - **Blockers** — things preventing progress, with status.
  - **Known bugs** — open defects with location/symptom notes.
  - **Coding conventions** — style, patterns, structure, do/don't rules.
  - **Key decisions** — architectural or process choices and their rationale.
  - **Requirements** — the project's requirements/deliverables, each with a
    status (`done` / `in progress` / `not started` / `blocked`), optional linked
    files, and optional linked blocker or bug. Backed by a template file in the
    repo (D12, FR16a).
  - **Glossary / domain terms** *(optional)* — project-specific vocabulary.
- **FR3** — Every context entry carries metadata: a stable ID, created/updated
  timestamp, author (agent or human), priority, and a "resolved" state.
- **FR3a** — Auto-expiry of stale entries is a **configurable per-project policy**
  (OQ3): default off (entries live until explicitly resolved); optionally
  age-based (resolve/hide entries older than N days). Explicit resolve is always
  available regardless of policy.
- **FR3b** — Every context entry has two content fields:
  - **`headline`** — one line (schema-enforced length limit); what the briefing
    shows.
  - **`detail`** — the full text (bounded, but generously); returned on
    drill-down.
  The writing agent supplies both while it still has full context; if only one is
  given the server derives the other by truncation, not by an LLM call.
- **FR4** — Context is persisted in **PostgreSQL** (D1) **verbatim** and survives
  server restarts. The stored copy is the source of truth and is never
  overwritten by a summarized form (see §7.2a).

### 7.2 Reading context (MCP surface)

- **FR5** — The server exposes an MCP **tool** to fetch a project briefing,
  returning a compact, formatted summary suitable for direct injection into an
  agent prompt.
- **FR6** — The briefing tool accepts optional parameters to scope the response
  (e.g. only blockers + bugs, or only conventions) so agents fetch only what they
  need.
- **FR7** — The server exposes MCP **resources** for each context section so
  clients that prefer resource subscriptions can read them individually.
- **FR8** — Every context call requires an explicit `project` (name or ID) (D3).
  There is no working-directory or automatic resolution. If `project` is missing
  or unknown, the server returns an error listing the registered projects so the
  caller can choose. Typically the MCP client is configured with its project once
  and passes it on every call.
- **FR9** — The briefing is token-bounded: the server enforces a configurable
  maximum size and applies the sizing strategy in §7.2a to fit it.

### 7.2a Context sizing strategy

The server owns compaction — it can do it once and cache it. Clients consume;
they are never expected to compress context themselves (that would cost tokens on
every call and fails on weak models). Compaction happens in layers, cheapest
first:

- **FR9a — Store verbatim.** Storage is always lossless (FR4). Every view is
  derived from the stored copy; a summary never replaces it.
- **FR9b — Compact at write time via schema.** Entries are kept small when
  created: the `headline` field is length-limited and `detail` is bounded
  (FR3b). This is the primary size control and uses no model.
- **FR9c — Deterministic assembly.** The briefing is built by selecting, ranking,
  truncating, and formatting `headline`s — no LLM. Default rank order: open
  blockers → current focus → open bugs → conventions linked to the current focus
  → recent decisions → requirement status summary. Items beyond the budget are
  collapsed to a count with a drill-down pointer (e.g. "+7 resolved bugs — call
  `get_section`").
- **FR9d — LLM summarization is opt-in and last resort.** Only used when a single
  entry's `detail` is inherently long (e.g. Overview, a large decision) or the
  budget is still exceeded after FR9c. Results are cached, keyed by the entry's
  content hash, and recomputed only on change. Uses the same backend config as
  the code index (NFR11).
- **FR9e — Graceful fallback.** With no LLM backend configured, FR9d degrades to
  deterministic truncation plus a drill-down pointer; the briefing is still
  produced.
- **FR9f — Drill-down always available.** Every item in a briefing carries its
  ID; `get_section` / `get_entry` and the `context://` resources return the
  verbatim `detail`. From the consumer's side, compaction is never lossy — the
  original is always one call away.
- **FR9g — Budget defaults (D13).** All limits are per-project configurable;
  defaults:
  - `headline` ≤ **120 characters** (hard reject above).
  - `detail` ≤ **8,000 characters** (~2k tokens) (hard reject above); no
    per-section exceptions.
  - Briefing budget: **1,500 tokens** (range 500–4,000).
  - `prepare_task` budget: **4,000 tokens** (range 1,000–16,000), split by
    FR22a.
  - LLM-summary cache entries never exceed the `detail` cap.

### 7.3 Writing context (MCP surface)

- **FR10** — The server exposes MCP tools to add, update, and resolve/close
  entries in each context section (focus, blocker, bug, convention, decision,
  requirement) — including setting a requirement's status. Context is only ever
  changed through these tools or the frontend — never inferred by the server
  (D4).
- **FR11** — **Full audit log (D5).** Every create, update, resolve, and delete
  is stored as an immutable revision with timestamp and author. Nothing is
  hard-deleted; "delete" and "resolve" are state transitions that keep the row
  and its history. The full history of any entry is retrievable
  (`get_entry_history`).
- **FR12** — The server exposes a tool to mark a blocker or bug as resolved,
  moving it out of the active briefing (its history is retained per FR11).
- **FR13** — Writes are validated against the section schema; malformed writes
  are rejected with an actionable error.

### 7.4 Project lifecycle

- **FR14** — The server exposes a tool to register a new project (ID, name, root
  path, initial overview).
- **FR15** — The server exposes a tool to list all registered projects with a
  one-line status each.
- **FR16** — A project's context can be bootstrapped from existing files in the
  repo (e.g. `README.md`, a conventions doc) as a one-time import, subject to
  human review.
- **FR16a** — **Requirements template file (D12).** The server maintains a
  structured, human-editable requirements file in the repo. Default path
  `.project-context/requirements.md` (configurable `requirements_file`). Created
  from a template on `register_project` if absent.

  **Format.** Markdown. Optional YAML frontmatter for file-level settings. One
  `###` heading per requirement, followed by a single managed metadata line, then
  free-form prose:

  ```
  ### R-001 — Persist context in PostgreSQL
  <!-- req status=in-progress files=src/db.ts,src/schema.sql blocker=B-004 -->
  All curated context, history, and the code index live in one PostgreSQL
  instance. ...
  ```

  - `status` ∈ `not-started` | `in-progress` | `blocked` | `done`. A missing
    metadata line means `not-started`.
  - IDs are server-assigned (`R-NNN`), stable, never reused. A human-added block
    with no ID gets one written back on the next sync.
  - The `<!-- req ... -->` line and the heading ID are **server-managed**; the
    title text and all prose are **human-owned** and never reflowed by the
    server.

  **System of record (D15).** The file owns requirement *existence* and
  *title/prose*; the store owns *status*, *links*, and *history*.

  **Sync (`sync_requirements`, also run on registration and frontend refresh).**
  A 3-way merge against a snapshot (file hash + parsed state) taken at the last
  successful sync:
  - block added in file → create in store;
  - block removed from file → `archived` in store (history kept per D5; never
    resurrected);
  - title/prose changed in file → update store;
  - status differs from store:
    - changed only in the file since last sync → file wins;
    - changed only in the store since last sync → store wins; server rewrites the
      file's `status=` token;
    - changed in both → **store wins**; server rewrites the file's token and logs
      a reconciliation note.
  - Writes to the file are atomic (temp + rename).
  - A block that fails to parse is skipped (its last-good state retained) and the
    error is returned by `sync_requirements` and shown in the frontend; a
    malformed file never partially applies.

### 7.5 Concurrency

- **FR17** — Multiple agents may read and write the same project context
  concurrently; writes are serialized and last-write-wins is avoided via
  append/merge semantics per entry.
- **FR18** — A read reflects all writes acknowledged before it started.

### 7.6 Code intelligence — search & RAG index

- **FR19** — The server indexes the full contents of a project's repository:
  source files, config, and docs, respecting `.gitignore` and a configurable
  ignore/allow list (vendored deps, build output, secrets excluded by default).
- **FR20** — The index supports two retrieval modes, combinable:
  - **Keyword / structural** — exact and fuzzy text, symbol names, definitions,
    references, file globs. Always available.
  - **Semantic (RAG)** — embedding-based retrieval over chunked code and docs for
    natural-language intent queries. Vectors are stored in PostgreSQL via
    `pgvector` (D1); available only once an embedding backend is configured (D7).
- **FR21** — Results return: file path, symbol name and kind (where applicable),
  line range, a snippet, a relevance score, and the retrieval mode that matched.
- **FR22** — Search is exposed as three MCP tools (D10):
  - `search_code` — hybrid keyword + semantic search, ranked results.
  - `retrieve_context` — token-bounded pack of the most relevant chunks for a
    task description, ready for prompt injection.
  - `prepare_task` — convenience call that returns a single budgeted response
    combining the project briefing (§7.2) and the relevant-code pack, so an agent
    can orient with one round trip. Built on top of the other two.
- **FR22a — `prepare_task` budget split (D13).** Total default 4,000 tokens
  (configurable). The server fills curated context first, capped at **50%** of
  the budget; the relevant-code pack takes the remainder. If context uses less
  than its cap, the slack goes to code. When any relevant chunks exist, code is
  guaranteed a **30%** floor (context is trimmed further if needed to honour it).
  The response reports the actual split.
- **FR23** — Chunking uses **tree-sitter** grammars (D8) to split on
  function/class/module boundaries for the supported languages, with a plain-text
  fallback for everything else.
- **FR23a** — **Supported languages (D8).** Symbol-level data (definitions,
  references, dependency edges, structural chunking) is provided for 7 language
  families: TypeScript/JavaScript, Python, Java, Go, Rust, C#, C/C++. Files in
  other languages are still indexed for keyword search and plain-text chunking
  but get no symbol table or dependency edges. The final list may shift with
  tree-sitter / SCIP-indexer maturity.
- **FR23b** — Symbol and cross-reference extraction reuses an existing toolchain
  rather than a custom parser per language (D8).
- **FR23c — Toolchain per language (D14).** Parsing/chunking is tree-sitter for
  all 7 families. Symbols and cross-references come from a per-language indexer,
  with output normalized to a single [SCIP](https://github.com/sourcegraph/scip)
  symbol model stored in PostgreSQL:

  | Family | Parse/chunk | Symbols & xrefs |
  |--------|-------------|-----------------|
  | TypeScript / JavaScript | tree-sitter | `scip-typescript` |
  | Python | tree-sitter | `scip-python` |
  | Java (+ JVM langs) | tree-sitter | `scip-java` |
  | Go | tree-sitter | `scip-go` |
  | Rust | tree-sitter | `rust-analyzer` (SCIP emit) |
  | C# | tree-sitter | `scip-dotnet` |
  | C / C++ | tree-sitter | `scip-clang` (needs `compile_commands.json`) |

  **Fallback:** when an indexer is unavailable, not installed, or fails, the
  server uses tree-sitter `tags` queries for definitions/references and
  import/include queries for dependency edges — lower fidelity, but the map and
  structural search still work. The index status (FR26) records which mode each
  language is running in.
- **FR24** — The index is built incrementally: on first registration it does a
  full pass; thereafter it updates only changed files, detected via file watch
  and/or git revision diff.
- **FR25** — Each indexed unit records the git commit/blob it came from so
  results can be flagged stale if the working tree has moved on.
- **FR26** — The server reports index status per project: last full build, last
  incremental update, file/chunk counts, and any files skipped with reason.
- **FR27** — Reindex can be triggered manually via an MCP tool and via the
  frontend.
- **FR28** — **No embedding backend is bundled (D7).** The user must configure
  one (a local model endpoint or an external API) for semantic search to work.
  Until then the server runs in keyword/structural-only mode and says so in
  results and in the frontend.
- **FR29** — A code search may be scoped: whole project, a subtree, a set of
  files, or "files related to the current focus".

### 7.7 Frontend — code map & context dashboard

- **FR30** — The server serves a web frontend (single-page app) over its HTTP
  transport; it is read-mostly and requires no separate deployment for local
  use.
- **FR31** — **Project picker** — the frontend lists all registered projects and
  their one-line status; selecting one loads its map and dashboard.
- **FR32** — **Code map view** — an interactive graph/diagram of the project
  structure:
  - Nodes represent modules/packages/directories and, on zoom, individual files
    and key symbols.
  - Edges represent dependencies (imports/calls) between nodes.
  - Node visual weight encodes size and structural complexity only — LOC,
    fan-in/fan-out (D11: no churn or git-history data in v1).
  - The map is pan/zoom, collapsible by hierarchy, and filterable by path or
    language.
- **FR32a** — **Server-side aggregation (D9).** The server computes the map and
  serves it with level-of-detail: top-level nodes and their aggregated edges by
  default; child nodes and finer edges are fetched on demand as the user expands
  or zooms. `get_code_map` takes a scope (subtree) and depth parameter. The
  client only ever holds the currently-visible subgraph, so the map scales to
  large repos.
- **FR33** — **Context overlay** — the map highlights where the **current
  focus**, **blockers**, and **known bugs** are located (by file/module), so a
  viewer sees hot spots in structural context.
- **FR34** — **Node inspector** — selecting a node shows: path, language, size,
  its dependencies and dependents, related context entries, and the source
  itself (read-only, syntax-highlighted). (Git activity/history is out of scope
  for v1 — D11.)
- **FR35** — **Search panel** — the same code search from §7.6 is available in
  the UI; results are selectable and focus/locate the corresponding node on the
  map.
- **FR36** — **Context dashboard** — a non-graph view listing the full project
  briefing (overview, focus, blockers, bugs, conventions, decisions) with the
  ability for a developer to edit entries (create, update, resolve) — the same
  operations as the MCP write tools.
- **FR36a** — **Requirements view** — a list of the project's requirements with
  their status (done / in progress / not started / blocked) and a completion
  summary (e.g. "12 of 20 done"). A developer can add requirements and change
  their status; agents can update status via the MCP write tools. Edits flow
  through the store and back into the requirements template file (FR16a). Where a
  requirement links to files, those nodes are indicated on the code map.
- **FR37** — **Index status panel** — shows indexing state from FR26 and offers a
  "reindex now" action.
- **FR38** — **Manual refresh (D6).** The frontend shows data as of the last
  load; a visible "refresh" control re-fetches context, requirements, index
  status, and the map. No live push (WebSocket/SSE) in v1.
- **FR39** — The code map is generated from the same analysis that feeds the
  index (dependency graph, symbol table); no separate manual diagramming.
- **FR39a** — **Design language (D17).** The frontend's visual and interaction
  design conforms to `DESIGN.md` (the "Fey" style reference):
  - Its color, typography, spacing, radius, shadow, and surface tokens are
    implemented verbatim (the CSS custom properties / Tailwind v4 `@theme` block
    in that file's Quick Start) and used everywhere — no ad-hoc values.
  - Dark theme only; Fey Ink (`#0b0b0b`) canvas with Fey Charcoal / Fey Obsidian
    for nested depth; never flat `#000000` as page background.
  - Calibre (with the documented fallback stack) is the sole typeface across all
    sizes; display headings use the −0.08em tracking.
  - All interactive controls use the 99px pill radius; content cards use 16px;
    depth is a single black halo, not stacked shadows.
  - Chromatic accents (Ember, Signal, Growth) appear only as meaning-carriers —
    status pills, highlighted words, code-map hot spots, diff/direction — never
    as decorative fills; at most one accent per card/headline. In particular,
    Signal blue is a navigation accent, not a status color.
  - The map, dashboards, and panels are treated as the "data-dense product
    surfaces" the reference describes: white type for primary values, Fey
    Graphite for secondary, monoline icons.
  - The "Do's and Don'ts" section of `DESIGN.md` is normative. Where this
    document and `DESIGN.md` disagree on visuals, `DESIGN.md` wins; where a UI
    element has no precedent there, it is derived from the nearest documented
    component.

### 7.8 Deployment & access

- **FR40** — **Docker (D16).** The whole system runs from a Docker Compose stack:
  the server container plus a PostgreSQL container (with `pgvector`). `docker
  compose up` starts a working instance with no further build steps.
  - Named volumes persist the PostgreSQL data and the code index.
  - Project repositories are mounted into the server container — read-only for
    code indexing, read-write for the requirements template file (FR16a) only.
  - All configuration is via environment variables / a mounted config file
    (database URL, project list and mount paths, embedding backend, bind mode,
    Tailscale settings). No secrets are baked into the image.
  - A prebuilt image is published; the stack also builds from source in-repo.
- **FR41** — **Tailscale access (D16).** The stack can join the user's Tailscale
  tailnet so the frontend and the HTTP MCP endpoint are reachable from any of the
  user's own devices without a VPN or port-forwarding.
  - Enabled by config (a Tailscale auth key); disabled by default.
  - When disabled, the server binds to `127.0.0.1` only.
  - When enabled, it binds to the Tailscale interface (and optionally still
    localhost); it is **never** bound to a public/LAN interface, and Tailscale
    **Funnel (public exposure) is not used**.
  - Access control is delegated to Tailscale — device authorization, and
    optionally tailnet ACLs / `tailscale serve` for HTTPS on the tailnet. There
    is no app-level login (D2).
  - MCP over stdio remains the path for a co-located agent; the HTTP/SSE MCP
    transport over the tailnet is what remote agents (e.g. an agent on the user's
    laptop, server on a home box) use.
- **FR42** — **Local agents keep working** whichever access mode is active: an
  agent running in the same environment as the server always has a stdio MCP path
  that needs no network.

### 7.9 Plan and task orchestration

- **FR43** — **Plan management** — The server supports creating, listing, reading,
  updating, archiving, and activating named plans per project. A plan defines a high-level
  goal/milestone with lifecycle state (`draft`, `active`, `completed`, `archived`) and
  strict project isolation.
- **FR44** — **Plan task model** — Each plan contains structured tasks with title,
  objective, acceptance criteria, optional linked files, normalized requirement links
  via `plan_task_requirements` with composite foreign keys, priority, and lifecycle
  status (`pending`, `ready`, `claimed`, `in_progress`, `blocked`, `in_review`,
  `completed`, `cancelled`).
- **FR45** — **DAG dependencies** — Tasks declare prerequisite task dependencies within
  the same plan. The service rejects self-dependencies, dependency cycles, cross-plan, and
  cross-project references. Completing a prerequisite unlocks dependent tasks whose
  prerequisites are fully met.
- **FR46** — **Ready-task discovery** — The server exposes operations to query ready
  tasks across a plan or project whose prerequisites are all completed and that currently
  have no active unexpired claim lease.
- **FR47** — **Atomic claim and lease heartbeat** — Workers claim ready tasks via atomic
  leases with a random one-time claim token and expiring TTL. A worker heartbeats the
  lease to extend expiration, or releases it explicitly. Expired in-progress tasks can be
  reclaimed. Stale or invalid claim tokens cannot mutate claimed tasks.
- **FR48** — **Task audit history** — Every plan task mutation appends an immutable event
  row recording author, event type, prior state, new state, timestamp, and structured
  payload.
- **FR49** — **Planned task handoff prompt** — `prepare_task(task_id=...)` builds a
  role-neutral, token-budgeted Markdown prompt containing task objective, acceptance
  criteria, dependency state, relevant requirement contract, and guidelines without
  exposing secrets, tokens, or raw diffs.
- **FR50** — **Advisory AI plan draft generation** — `generate_plan_draft` uses secure
  T20 AI settings to produce structured candidate task DAGs; generation is strictly
  read-only and creates zero database entities.
- **FR51** — **Explicit draft approval and atomic creation** — Persisting an AI plan
  draft requires explicit caller approval via `create_plan_with_tasks`, executing in a
  single atomic database transaction.
- **FR52** — **Plans web interface** — The frontend provides a `/projects/:project/plans`
  route and nav item to browse plans, inspect task DAG status, filter ready tasks,
  manage claims/leases, view task history, and review/create AI plan drafts using
  `DESIGN.md` tokens.
- **FR53** — **Requirement status independence (D4)** — Task and plan completion never
  mutate requirement status or bypass evidence close gates.

---

## 8. Non-Functional Requirements

- **NFR1 — Latency:** A briefing fetch returns in < 200 ms for a typical project
  (local PostgreSQL).
- **NFR2 — Compactness:** Default briefing fits within a configurable budget
  (default 1,500 tokens — D13) while remaining self-contained.
- **NFR3 — Deployment:** Primary distribution is a **Docker Compose stack**
  (server + PostgreSQL with `pgvector`) — see §7.8. MCP is served over stdio
  and, when remote access is enabled, over HTTP/SSE on the tailnet; the frontend
  over HTTP. Running the server directly against a user-provided PostgreSQL is
  also supported. No external services beyond PostgreSQL and (optionally)
  Tailscale + a configured embedding backend.
- **NFR4 — Durability:** All state lives in PostgreSQL with a defined schema.
  Standard `pg_dump` logical backup/restore is supported. The requirements
  template file (FR16a) remains a human-readable, git-diffable copy of that
  section in the repo.
- **NFR5 — Safety:** The server only reads/writes its own context store and
  explicitly configured repo paths; it never executes project code.
- **NFR6 — Observability:** All tool calls are logged with project ID, caller,
  and outcome for debugging and token-savings measurement.
- **NFR7 — Compatibility:** Conforms to the current MCP specification; works with
  any compliant MCP client without client-side custom code.
- **NFR8 — Graceful degradation:** If the store is unavailable, reads fail with a
  clear message rather than returning stale or empty context silently. If the
  embedding backend is unavailable, code search falls back to keyword mode and
  says so.
- **NFR9 — Index freshness:** After a file changes, incremental reindex of that
  file completes within seconds; a stale result is always marked, never served
  as current.
- **NFR10 — Index build cost:** Full index of a medium repo (≈100k LOC) completes
  in minutes on a developer laptop; embedding calls are batched and cached by
  content hash so unchanged code is never re-embedded.
- **NFR11 — Privacy:** Code, context, and embeddings leave the host only over (a)
  an explicitly configured external embedding/LLM backend, or (b) the user's own
  Tailscale tailnet (WireGuard-encrypted, the user's devices only). Never to any
  other destination. The configured backend and the current access mode are shown
  in the frontend and logs.
- **NFR12 — Storage:** The code index and `pgvector` embeddings live in the same
  PostgreSQL instance as the context store (D1), in separate schemas/tables, and
  are safe to drop and rebuild without touching curated context.
- **NFR13 — Frontend footprint:** The frontend is served by the same process,
  needs no build step to run, and works in a current desktop browser. Because the
  map is aggregated server-side (FR32a), the client stays responsive regardless
  of repo size.
- **NFR14 — Access surface:** Binds to `127.0.0.1` by default. The only optional
  wider exposure is the user's private Tailscale tailnet (FR41) — never a public
  or LAN interface, and no Tailscale Funnel. Access control on the tailnet is
  Tailscale's (device auth, ACLs); there is no app-level auth in v1 (D2). All
  traffic on the tailnet is encrypted by Tailscale (WireGuard); `tailscale serve`
  may be used for HTTPS.
- **NFR15 — Design fidelity:** The frontend ships a single stylesheet/theme
  layer generated from `DESIGN.md`'s token block (D17); components reference
  tokens, not literals. Accessibility target: AAA text contrast on the dark
  canvas, as the reference intends. A visual review against `DESIGN.md`'s
  component specs and Do's/Don'ts is part of frontend acceptance.

---

## 9. Proposed MCP Interface (indicative, subject to design)

### Tools

| Tool | Purpose |
|------|---------|
| `get_project_briefing` | Return compact context summary; params: `project?`, `sections?`, `max_tokens?` |
| `get_section` | Return all entries of one section verbatim (`headline` + `detail`); params: `project?`, `section`, `include_resolved?` |
| `get_entry` | Return one entry's verbatim `detail` by ID |
| `get_entry_history` | Return the full revision history of one entry (D5) |
| `prepare_task` | One budgeted response: project briefing + relevant-code pack for a task description (D10) |
| `list_projects` | List registered projects with status |
| `register_project` | Create a new project context |
| `set_current_focus` | Replace/append the active task description |
| `add_blocker` / `resolve_blocker` | Manage blockers |
| `add_bug` / `resolve_bug` | Manage known bugs |
| `add_convention` | Record a coding convention |
| `add_decision` | Record a key decision + rationale |
| `add_requirement` / `set_requirement_status` | Manage requirements and their done/not-done status; changes sync to the template file (D12) |
| `sync_requirements` | Re-parse the requirements template file into the store / reconcile (FR16a) |
| `import_from_repo` | One-time bootstrap from existing docs (review required) |
| `search_code` | Hybrid keyword + semantic search; params: `query`, `project?`, `scope?`, `mode?`, `max_results?` |
| `retrieve_context` | Token-bounded pack of most relevant code/doc chunks for a task description |
| `get_index_status` | Index build/update state, counts, skipped files |
| `reindex` | Trigger full or incremental reindex |
| `get_code_map` | Return the dependency/structure graph (nodes, edges, metrics) as data |

### Resources

- `context://{project}/overview`
- `context://{project}/focus`
- `context://{project}/blockers`
- `context://{project}/bugs`
- `context://{project}/conventions`
- `context://{project}/decisions`
- `context://{project}/requirements` — requirements with status
- `context://{project}/history/{entry-id}` — revision history of an entry
- `context://{project}/code-map` — dependency/structure graph (aggregated; params for scope/depth)
- `context://{project}/index-status`

---

## 10. Acceptance Criteria

- **AC1** — Given a registered project, an agent calls `get_project_briefing`
  and receives overview, current focus, open blockers, open bugs, and
  conventions in one response under the token budget.
- **AC2** — A developer prompts a fresh agent session with only a task sentence;
  the agent, using only the briefing, identifies the correct files/area to work
  on without reading unrelated files.
- **AC3** — Agent A adds a blocker; Agent B's next briefing (new session)
  includes that blocker without any human relay.
- **AC4** — Resolving a bug removes it from subsequent briefings but keeps it in
  the archive.
- **AC4a** — When entries exceed the token budget, the briefing shows headlines
  plus collapsed counts with drill-down pointers; calling `get_entry` with an
  item's ID returns its verbatim `detail`. Stored content is unchanged by
  briefing generation.
- **AC5** — Two projects registered simultaneously return isolated, correct
  context; the wrong project's data never leaks into a briefing.
- **AC6** — Server restart preserves all context.
- **AC7** — A measured task run shows fewer orientation-phase input tokens with
  the server than a baseline run without it.
- **AC8** — A natural-language query ("where is X handled") via `search_code`
  returns the correct file and symbol in the top results for a project the model
  has not previously seen.
- **AC9** — Editing a source file and re-querying within seconds returns the
  updated content; a query against code that changed since indexing flags the
  result as stale.
- **AC10** — With no embedding backend configured, `search_code` still returns
  keyword results and the response indicates semantic search is unavailable.
- **AC11** — Opening the frontend for a project renders a code map whose top-level
  nodes match the project's actual module structure, with dependency edges
  between them.
- **AC12** — An open blocker or bug tied to a file is visibly marked on the
  corresponding node in the code map.
- **AC13** — Selecting a node in the map opens the node inspector with the file's
  source, its dependencies/dependents, and any related context entries.
- **AC14** — A context entry edited in the frontend dashboard is reflected in the
  next `get_project_briefing` call, and vice versa.
- **AC14a** — The frontend requirements view lists every requirement with its
  status and an accurate done/total count; an agent marking a requirement `done`
  via MCP updates that view, and a status changed in the frontend is visible to
  the next agent query.
- **AC15** — Dropping the code-index tables/schema in PostgreSQL and restarting
  triggers a clean rebuild with no loss of curated context.
- **AC16** — A call with a missing or unknown `project` returns an error that
  lists the registered projects; it does not guess (D3).
- **AC17** — Editing an entry twice produces two retrievable revisions via
  `get_entry_history`; a "deleted" entry is absent from normal reads but its
  history is still retrievable (D5).
- **AC18** — Adding a requirement in the frontend writes a matching block into the
  requirements template file; editing a status marker in the file and calling
  `sync_requirements` updates the store and the frontend view (D12).
- **AC19** — `prepare_task` returns briefing + relevant code in one response
  within the combined token budget; the split adapts when one side is large (D10).
- **AC20** — `get_code_map` at default depth returns only top-level nodes and
  aggregated edges; expanding a node fetches its children without re-sending the
  whole graph (D9).
- **AC21** — With no embedding backend configured, the frontend and
  `get_index_status` both clearly show semantic search as unavailable (D7).
- **AC22** — When a requirement's status is changed both in the file and via MCP
  since the last sync, `sync_requirements` keeps the store's status, rewrites the
  file's `status=` token to match, and reports the reconciliation; a block
  deleted from the file becomes `archived` (still in history), not removed (D15).
- **AC23** — For a repo in a supported language with no SCIP indexer installed,
  the map and structural search still build via the tree-sitter `tags` fallback,
  and `get_index_status` reports that language as running in fallback mode (D14).
- **AC24** — `prepare_task` reports the actual context/code token split, and when
  curated context is small the code pack expands to use the freed budget (D13).
- **AC25** — `docker compose up` from a clean checkout brings up the server and
  PostgreSQL, and an agent can register a project and fetch a briefing with no
  additional setup beyond configuring project mount paths (D16).
- **AC26** — With Tailscale enabled, the frontend and the HTTP MCP endpoint are
  reachable from another of the user's tailnet devices by its Tailscale name, and
  are not reachable from a non-tailnet host on the same LAN or from the public
  internet. With Tailscale disabled, both bind to localhost only (D16).
- **AC27** — The frontend renders on the Fey Ink canvas with Calibre type and
  99px/16px radii; its computed colors, fonts, spacing, and shadows resolve to
  `DESIGN.md` token values, not literals; and a review finds no violations of
  that file's "Don't" list (e.g. filled chromatic buttons, a second typeface,
  blue used as a status color) (D17).
- **AC28** — `create_plan_with_tasks` atomically creates a plan, tasks, dependencies,
  normalized requirement links via `plan_task_requirements`, and initial history events
  in a single transaction; duplicate keys, cycles, cross-plan references, and cross-project
  requirement IDs are rejected (D18, FR43–FR45).
- **AC29** — `claim_task` atomically issues an expiring lease and unique ephemeral token;
  two concurrent claim attempts for the same task result in exactly one success; operations
  with an expired or incorrect token are rejected (D20, FR47).
- **AC30** — Completing a prerequisite task automatically unlocks dependent tasks to ready
  state; `complete_task` appends an immutable event with structured payload diff and never
  alters requirement status (D4, D19, FR48, FR53).
- **AC31** — `prepare_task(task_id=...)` outputs a role-neutral Markdown prompt containing
  task objective, acceptance criteria, dependency state, and linked requirement invariants
  within the token budget, free of claim tokens, provider keys, or raw diffs (D22, FR49).
- **AC32** — `generate_plan_draft` validates candidate task schemas locally and persists
  zero database records until explicit human approval invokes `create_plan_with_tasks` (D23, FR50, FR51).
- **AC33** — The Plans frontend displays plan DAGs, tracks lease states with feedback,
  allows manual and approved AI plan creation, and contains zero literal hex/px/shadow
  values in violation of `DESIGN.md` (D17, D23, FR52).

---

## 11. Resolved Questions & Residual Sub-Questions

All original open questions are decided (§1a). What remains under each is a
narrower tuning/design detail, not a blocker.

- **OQ1 — Store.** *Decided (D1):* PostgreSQL for everything, `pgvector` for
  embeddings. *Residual:* schema design; whether to use JSONB for entry bodies
  vs. typed columns.
- **OQ2 — Project resolution.** *Decided (D3):* explicit `project` on every call;
  no CWD or auto-resolution. *Residual:* none.
- **OQ3 — Stale entries.** *Decided (D5-adjacent, FR3-expiry):* configurable
  per-project policy, default off. *Residual:* which policies to offer beyond
  "off" and "age-based" (e.g. archive-on-focus-change).
- **OQ4 — Team mode.** *Decided (D2):* out of scope; single-user, single-instance,
  localhost by default with optional private-tailnet access (D16). *Residual:*
  none for v1.
- **OQ5 — Summarization.** *Decided (§7.2a):* server stores verbatim and owns
  compaction; clients never compress. Budgets/limits set in FR9g / D13 (briefing
  1,500 tok, `headline` 120 ch, `detail` 8,000 ch), all configurable. *Residual:*
  none — tune the defaults against real projects post-v1.
- **OQ6 — Auto-updating context.** *Decided (D4):* fully agent-/human-driven; no
  test/CI watching. *Residual:* none. (Code-index file-watching for freshness is
  separate and still in scope — FR24.)
- **OQ7 — History.** *Decided (D5, FR11):* full immutable audit log per entry;
  nothing hard-deleted. *Residual:* retention/compaction policy for very long
  histories.
- **OQ8 — Frontend updates.** *Decided (D6, FR38):* manual refresh; no live push
  in v1. *Residual:* none.
- **OQ9 — Embedding backend.** *Decided (D7, FR28):* none bundled; user
  configures one; keyword-only until then. *Residual:* which backends to document
  first (local runner vs. which hosted APIs).
- **OQ10 — Code-map analysis.** *Decided (D8/D14, FR23a–FR23c):* tree-sitter for
  parse/chunk; per-language SCIP indexer (`scip-typescript`, `scip-python`,
  `scip-java`, `scip-go`, `rust-analyzer`, `scip-dotnet`, `scip-clang`) normalized
  to one SCIP model in PostgreSQL; tree-sitter `tags` fallback. *Residual:* none —
  swap an indexer only if it proves unmaintained during build.
- **OQ11 — Vector store.** *Decided (D1):* `pgvector`. *Residual:* index type
  (HNSW vs. IVFFlat) and embedding dimension, once a backend is chosen.
- **OQ12 — Map scale.** *Decided (D9, FR32a):* server-side aggregation from the
  start; client holds only the visible subgraph. *Residual:* aggregation
  granularity and default depth.
- **OQ13 — Task-prep call.** *Decided (D10/D13, FR22/FR22a):* keep `search_code`
  and `retrieve_context` as primitives; add `prepare_task` — total 4,000 tokens,
  curated context capped at 50%, code floored at 30% when chunks exist, slack
  flows to code, actual split reported. *Residual:* none.
- **OQ14 — Map history data.** *Decided (D11):* static structure only in v1; no
  churn/git overlays. *Residual:* none (revisit as a backlog item).
- **OQ15 — Requirements source.** *Decided (D12/D15, FR16a):* Markdown template
  at `.project-context/requirements.md` (configurable); `### R-NNN — title` +
  a managed `<!-- req status=… files=… -->` line + human prose. File owns
  existence/prose, store owns status/links/history; 3-way merge on
  `sync_requirements`, store wins status conflicts and rewrites the file token;
  removed blocks are archived not deleted; malformed blocks are skipped with an
  error, never partially applied. Status is always explicit, never inferred.
  *Residual:* none.
- **OQ16 — Tailscale integration.** *Decided (D16, §7.8):* optional, off by
  default, tailnet-only (no Funnel), Tailscale owns access control. *Residual:*
  Tailscale as a sidecar container vs. embedded `tsnet` in the server process,
  and whether to default-enable `tailscale serve` for HTTPS on the tailnet.

---

## 12. Out of Scope for v1 (Backlog)

- Automatic bug detection from test/CI output.
- Cross-project knowledge linking / search across multiple repos at once.
- Fine-grained per-agent permissions.
- In-browser code editing, refactoring, or running commands from the frontend.
- Semantic search over git history / past versions (index tracks current tree
  only).
- Real-time collaborative editing of context, and live push / WebSocket updates,
  in the frontend (D6).
- Hosted / team-shared multi-user deployment with accounts (D2).
- Churn and git-history overlays on the code map; node inspector git activity
  (D11).
- Symbol-level support for languages outside the 7 supported families (D8).
- Server-inferred context from tests/CI (D4).
- Agent process supervisor, runner, or automated agent dispatch (D24).
- Shell execution, terminal sessions, script runners, or automated execution of commands (D24).
- Git worktree automation, branch creation, or repository lifecycle management (D24).
- External issue tracker / project management two-way sync (GitHub, Jira, Linear) (D24).
- Fine-grained per-agent authorization or multi-user access control (D2, D24).
