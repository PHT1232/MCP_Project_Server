/** Shapes returned by the `pcs` HTTP API (mirrors pcs.web_api.routes). */

/** One registered project plus its one-line status (FR31). */
export interface Project {
  id: string;
  name: string;
  root_path: string;
  status_line: string;
  briefing_token_budget: number;
  prepare_task_token_budget: number;
  headline_max_chars: number;
  detail_max_chars: number;
  expiry_policy: string;
  expiry_days: number | null;
}

export interface Briefing {
  project: string;
  briefing: string;
}

export interface RegisterProjectInput {
  name: string;
  root_path: string;
  overview: string;
}

export interface Health {
  status: string;
  bind_mode: string;
  bind_host: string;
}

/** Context-dashboard sections that carry editable entries (FR36). */
export type DashboardSection =
  | "overview"
  | "focus"
  | "blockers"
  | "bugs"
  | "conventions"
  | "decisions";

/** Store-side lifecycle of an entry (open until resolved/deleted/archived). */
export type EntryLifecycle = "open" | "resolved" | "deleted" | "archived";

/** Requirement status vocabulary shared by store and file (FR16a). */
export type RequirementStatus =
  | "not-started"
  | "in-progress"
  | "blocked"
  | "done";

/** One context entry (pcs.context.types.EntryView.as_dict). */
export interface Entry {
  id: string;
  project_id: string;
  section: string;
  headline: string;
  detail: string;
  status: EntryLifecycle;
  priority: number;
  author: string;
  created_at: string;
  updated_at: string;
  requirement_status: RequirementStatus | null;
  linked_files: string[];
  related_entry_id: string | null;
  req_key: string | null;
}

export interface SectionResponse {
  section: string;
  entries: Entry[];
}

export interface EntryInput {
  section?: string;
  headline?: string;
  detail?: string;
  priority?: number;
  status?: RequirementStatus;
  linked_files?: string[];
}

/** A reconciliation note surfaced from a requirements write (AC14a, AC22). */
export interface ReconciliationNote {
  req_key: string;
  message: string;
}

/**
 * Present on entry / requirement write responses whenever the change touched the
 * `requirements` section — its `errors` and `reconciliations` must be surfaced
 * to the user (AC14a).
 */
export interface RequirementsFileSync {
  path: string;
  written: boolean;
  errors: string[];
  reconciliations: ReconciliationNote[];
}

/** An entry write response: the entry, plus an optional file-sync report. */
export type EntryWriteResponse = Entry & {
  requirements_file?: RequirementsFileSync;
};

/** One requirement's synced state (pcs.requirements.types.RequirementView). */
export interface Requirement {
  req_key: string;
  entry_id: string;
  title: string;
  status: RequirementStatus;
  lifecycle: string;
  linked_files: string[];
}

export interface RequirementsResponse {
  requirements: Requirement[];
  done_count: number;
  total_count: number;
}

/** pcs.requirements.types.SyncReport.as_dict — the manual "sync" report (AC18). */
export interface SyncReport {
  project_id: string;
  project_name: string;
  file_path: string;
  ok: boolean;
  file_existed: boolean;
  file_written: boolean;
  created: string[];
  updated: string[];
  archived: string[];
  written_back: string[];
  reconciliations: ReconciliationNote[];
  errors: string[];
  requirements: Requirement[];
  done_count: number;
  total_count: number;
}

export interface SkippedFile {
  path: string;
  reason: string;
}

/* --------------------------------------------------------------------------
 * Code map (FR32–FR34) — mirrors pcs.codemap.service.get_code_map.
 * ------------------------------------------------------------------------ */

/** Per-node context overlay counts (FR33). `hot = blockers + bugs > 0`. */
export interface CodeMapOverlay {
  focus: number;
  blockers: number;
  bugs: number;
  requirements: number;
  hot: boolean;
}

export type CodeMapNodeKind = "directory" | "file" | "symbol" | "external";

/** One node of a code-map tier (directory / file) or a file's symbol. */
export interface CodeMapNode {
  id: string;
  kind: CodeMapNodeKind;
  path: string;
  label: string;
  language: string | null;
  loc: number;
  size_bytes: number;
  file_count: number;
  symbol_count: number;
  fan_in: number;
  fan_out: number;
  has_children: boolean;
  outside_scope: boolean;
  overlay: CodeMapOverlay;
  /** Present only on `kind: "symbol"` nodes (file scope). */
  symbol_kind?: string;
  start_line?: number;
  end_line?: number;
  signature?: string | null;
}

export interface CodeMapEdge {
  source: string;
  target: string;
  kind: string;
  weight: number;
}

export interface CodeMapProvenance {
  indexed: boolean;
  last_full_at?: string | null;
  last_incremental_at?: string | null;
  last_commit?: string | null;
  symbol_modes?: Record<string, string>;
}

export interface CodeMapStats {
  total_files?: number;
  total_resolved_edges?: number;
  node_count: number;
  edge_count: number;
  truncated: boolean;
}

export interface CodeMap {
  project: string;
  project_name: string;
  scope: string | null;
  scope_kind: "directory" | "file";
  depth: number;
  generated_from: CodeMapProvenance;
  nodes: CodeMapNode[];
  edges: CodeMapEdge[];
  /** File scope only (FR34): resolved file-level deps / dependents. */
  dependencies?: string[];
  dependents?: string[];
  stats: CodeMapStats;
  overlay_legend: string[];
}

/** FR34 — read-only file source for the inspector. */
export interface SourceFile {
  path: string;
  language: string | null;
  content: string;
  truncated: boolean;
}

/* --------------------------------------------------------------------------
 * Code search (FR35) — mirrors pcs.index.service.search_code.
 * ------------------------------------------------------------------------ */

export interface SearchHit {
  path: string;
  start_line: number;
  end_line: number;
  snippet: string;
  score: number;
  matched_mode: string;
  retrieval_modes?: string[];
  stale: boolean;
  symbol: string | null;
  kind: string;
  language: string | null;
}

export interface SearchResponse {
  hits: SearchHit[];
  semantic_available: boolean;
  mode: string;
  note?: string | null;
}

/**
 * pcs.index.service.IndexStatusView.as_dict (FR26). `semantic_available` is
 * always present; `semantic_note` arrives once T04 lands the embedding backend
 * (AC21) — treat it as optional.
 */
export interface IndexStatus {
  project_id: string;
  project_name: string;
  state: string;
  last_full_at: string | null;
  last_incremental_at: string | null;
  last_commit: string | null;
  file_count: number;
  chunk_count: number;
  skipped_count: number;
  skipped: SkippedFile[];
  semantic_available: boolean;
  semantic_note?: string | null;
}
