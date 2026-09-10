/**
 * Typed HTTP client for the `pcs` API. The only module that calls `fetch`;
 * components and hooks depend on these functions, never on `fetch` directly
 * (AGENTS.md frontend conventions). Every `/api` route the frontend consumes has
 * exactly one typed function here.
 */
import type {
  Briefing,
  Entry,
  EntryInput,
  EntryWriteResponse,
  Health,
  IndexStatus,
  Project,
  RegisterProjectInput,
  RequirementsResponse,
  SectionResponse,
  SyncReport,
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

export type { Entry };
