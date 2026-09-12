/**
 * Typed HTTP client for the `pcs` API. The only module that calls `fetch`;
 * components and hooks depend on these functions, never on `fetch` directly
 * (AGENTS.md frontend conventions). Every `/api` route the frontend consumes has
 * exactly one typed function here.
 */
import type {
  AcceptanceCriterion,
  Briefing,
  CodeMap,
  Entry,
  EntryInput,
  EntryWriteResponse,
  Health,
  IndexStatus,
  Project,
  RegisterProjectInput,
  CreateCriterionInput,
  CreateInvariantInput,
  RequirementComplianceResponse,
  RequirementContract,
  RequirementEvidenceResponse,
  RequirementInvariant,
  RequirementsResponse,
  SearchResponse,
  SectionResponse,
  SourceFile,
  SyncReport,
  UpdateCriterionInput,
  UpdateInvariantInput,
} from "./types";

const BASE_URL: string = import.meta.env.VITE_API_BASE ?? "";

export class ApiError extends Error {
  readonly status: number;
  readonly available: string[] | undefined;

  constructor(status: number, message: string, available?: string[]) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.available = available;
  }
}

interface ApiErrorBody {
  error?: string;
  available?: string[];
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (!headers.has("accept")) {
    headers.set("accept", "application/json");
  }
  const response = await fetch(`${BASE_URL}${path}`, { ...init, headers });

  if (!response.ok) {
    const body: ApiErrorBody = await response
      .json()
      .then((value: unknown) => (value ?? {}) as ApiErrorBody)
      .catch(() => ({}));
    throw new ApiError(
      response.status,
      body.error ?? `${String(response.status)} ${response.statusText}`,
      body.available,
    );
  }

  return (await response.json()) as T;
}

function jsonBody(payload: unknown): RequestInit {
  return {
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  };
}

function projectPath(project: string, suffix = ""): string {
  return `/api/projects/${encodeURIComponent(project)}${suffix}`;
}

export function getHealth(): Promise<Health> {
  return request<Health>("/api/health");
}

/** FR31 — every registered project with its one-line status. */
export function listProjects(): Promise<Project[]> {
  return request<Project[]>("/api/projects");
}

export function registerProject(input: RegisterProjectInput): Promise<Project> {
  return request<Project>("/api/projects", {
    method: "POST",
    ...jsonBody(input),
  });
}

export function getBriefing(project: string): Promise<Briefing> {
  return request<Briefing>(projectPath(project, "/briefing"));
}

/** FR36 — one dashboard section with its entries. */
export function getSection(
  project: string,
  section: string,
  includeResolved = false,
): Promise<SectionResponse> {
  const query = includeResolved ? "?include_resolved=true" : "";
  return request<SectionResponse>(
    projectPath(project, `/sections/${encodeURIComponent(section)}${query}`),
  );
}

/** FR36 — create an entry (mirrors the `add_*` MCP write tools). */
export function addEntry(
  project: string,
  input: EntryInput,
): Promise<EntryWriteResponse> {
  return request<EntryWriteResponse>(projectPath(project, "/entries"), {
    method: "POST",
    ...jsonBody(input),
  });
}

/** FR36 — merge fields onto an entry (mirrors the `update_*` MCP write tools). */
export function updateEntry(
  project: string,
  entryId: string,
  input: EntryInput,
): Promise<EntryWriteResponse> {
  return request<EntryWriteResponse>(
    projectPath(project, `/entries/${encodeURIComponent(entryId)}`),
    { method: "PATCH", ...jsonBody(input) },
  );
}

/** FR36 — resolve an entry (mirrors the `resolve_*` MCP write tools). */
export function resolveEntry(
  project: string,
  entryId: string,
): Promise<EntryWriteResponse> {
  return request<EntryWriteResponse>(
    projectPath(project, `/entries/${encodeURIComponent(entryId)}/resolve`),
    { method: "POST" },
  );
}

/**
 * FR36 — replace the current focus (S-T06: `set_current_focus` replace-semantics;
 * the generic `add_focus` CRUD is deliberately not surfaced).
 */
export function setFocus(project: string, text: string): Promise<Project> {
  return request<Project>(projectPath(project, "/focus"), {
    method: "PUT",
    ...jsonBody({ text }),
  });
}

/** FR36a — the requirements list with an accurate done/total count. */
export function listRequirements(
  project: string,
): Promise<RequirementsResponse> {
  return request<RequirementsResponse>(projectPath(project, "/requirements"));
}

/** T13 — verbatim contract drill-down; no evidence bodies are included. */
export function getRequirementContract(
  project: string,
  requirementId: string,
): Promise<RequirementContract> {
  return request<RequirementContract>(
    projectPath(
      project,
      `/requirements/${encodeURIComponent(requirementId)}/contract`,
    ),
  );
}

/** T14 — create an invariant; omitted optional fields are allocated by the service. */
export function createRequirementInvariant(
  project: string,
  requirementId: string,
  input: CreateInvariantInput,
): Promise<RequirementInvariant> {
  return request<RequirementInvariant>(
    projectPath(
      project,
      `/requirements/${encodeURIComponent(requirementId)}/invariants`,
    ),
    { method: "POST", ...jsonBody(input) },
  );
}

/** T14 — merge-update an invariant; omitted fields keep stored values. */
export function updateRequirementInvariant(
  project: string,
  invariantId: string,
  input: UpdateInvariantInput,
): Promise<RequirementInvariant> {
  return request<RequirementInvariant>(
    projectPath(
      project,
      `/requirements/invariants/${encodeURIComponent(invariantId)}`,
    ),
    { method: "PATCH", ...jsonBody(input) },
  );
}

/** T14 — soft-delete an invariant (cascades open criteria). */
export function deleteRequirementInvariant(
  project: string,
  invariantId: string,
): Promise<RequirementInvariant> {
  return request<RequirementInvariant>(
    projectPath(
      project,
      `/requirements/invariants/${encodeURIComponent(invariantId)}`,
    ),
    { method: "DELETE" },
  );
}

/** T14 — create an acceptance criterion under one invariant. */
export function createAcceptanceCriterion(
  project: string,
  invariantId: string,
  input: CreateCriterionInput,
): Promise<AcceptanceCriterion> {
  return request<AcceptanceCriterion>(
    projectPath(
      project,
      `/requirements/invariants/${encodeURIComponent(invariantId)}/criteria`,
    ),
    { method: "POST", ...jsonBody(input) },
  );
}

/** T14 — merge-update a criterion; omitted fields keep stored values. */
export function updateAcceptanceCriterion(
  project: string,
  criterionId: string,
  input: UpdateCriterionInput,
): Promise<AcceptanceCriterion> {
  return request<AcceptanceCriterion>(
    projectPath(
      project,
      `/requirements/criteria/${encodeURIComponent(criterionId)}`,
    ),
    { method: "PATCH", ...jsonBody(input) },
  );
}

/** T14 — soft-delete a criterion; revision history is kept. */
export function deleteAcceptanceCriterion(
  project: string,
  criterionId: string,
): Promise<AcceptanceCriterion> {
  return request<AcceptanceCriterion>(
    projectPath(
      project,
      `/requirements/criteria/${encodeURIComponent(criterionId)}`,
    ),
    { method: "DELETE" },
  );
}

/** T13 — compact evidence references and violations; never raw logs or diffs. */
export function getRequirementEvidence(
  project: string,
  requirementId: string,
): Promise<RequirementEvidenceResponse> {
  return request<RequirementEvidenceResponse>(
    projectPath(
      project,
      `/requirements/${encodeURIComponent(requirementId)}/evidence`,
    ),
  );
}

/** T13 — deterministic exception-only compliance review. */
export function reviewRequirementCompliance(
  project: string,
  requirementIds: string[],
): Promise<RequirementComplianceResponse> {
  const params = new URLSearchParams();
  for (const requirementId of requirementIds) {
    params.append("requirement_id", requirementId);
  }
  return request<RequirementComplianceResponse>(
    projectPath(project, `/requirements/compliance?${params.toString()}`),
  );
}

/** FR36a — re-parse the requirements file and reconcile with the store (AC18). */
export function syncRequirements(project: string): Promise<SyncReport> {
  return request<SyncReport>(projectPath(project, "/requirements/sync"), {
    method: "POST",
  });
}

/** FR37 — index counts, timestamps, skipped-with-reason, semantic availability. */
export function getIndexStatus(project: string): Promise<IndexStatus> {
  return request<IndexStatus>(projectPath(project, "/index"));
}

/** FR37 — trigger an index rebuild. */
export function reindex(
  project: string,
  incremental = true,
): Promise<IndexStatus> {
  return request<IndexStatus>(projectPath(project, "/reindex"), {
    method: "POST",
    ...jsonBody({ incremental }),
  });
}

/**
 * FR32 / FR32a — one tier of the code map. `scope` omitted = the top directory
 * tier; a subtree path returns only that slice; an indexed file path returns its
 * symbol / dependency view (FR34). The client never asks for the whole graph.
 */
export function getCodeMap(
  project: string,
  scope?: string,
  depth?: number,
): Promise<CodeMap> {
  const params = new URLSearchParams();
  if (scope !== undefined && scope !== "") {
    params.set("scope", scope);
  }
  if (depth !== undefined) {
    params.set("depth", String(depth));
  }
  const query = params.toString();
  return request<CodeMap>(
    projectPath(project, `/code-map${query === "" ? "" : `?${query}`}`),
  );
}

/** FR34 — the read-only source of one indexed file for the node inspector. */
export function getSource(project: string, path: string): Promise<SourceFile> {
  const params = new URLSearchParams({ path });
  return request<SourceFile>(
    projectPath(project, `/source?${params.toString()}`),
  );
}

export interface SearchOptions {
  scope?: "project" | "subtree" | "files" | "focus";
  subtree?: string;
  limit?: number;
}

/** FR35 — hybrid keyword + semantic code search for the search panel. */
export function searchCode(
  project: string,
  query: string,
  options: SearchOptions = {},
): Promise<SearchResponse> {
  const params = new URLSearchParams({ q: query });
  if (options.scope !== undefined) {
    params.set("scope", options.scope);
  }
  if (options.subtree !== undefined) {
    params.set("subtree", options.subtree);
  }
  if (options.limit !== undefined) {
    params.set("limit", String(options.limit));
  }
  return request<SearchResponse>(
    projectPath(project, `/search?${params.toString()}`),
  );
}

export type { Entry };
