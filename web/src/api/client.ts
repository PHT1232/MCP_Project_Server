/**
 * Typed HTTP client for the `pcs` API. The only module that calls `fetch`;
 * components and hooks depend on these functions, never on `fetch` directly
 * (AGENTS.md frontend conventions).
 */
import type {
  Briefing,
  Health,
  Project,
  RegisterProjectInput,
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

export function getHealth(): Promise<Health> {
  return request<Health>("/api/health");
}

export function listProjects(): Promise<Project[]> {
  return request<Project[]>("/api/projects");
}

export function registerProject(input: RegisterProjectInput): Promise<Project> {
  return request<Project>("/api/projects", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(input),
  });
}

export function getBriefing(project: string): Promise<Briefing> {
  return request<Briefing>(
    `/api/projects/${encodeURIComponent(project)}/briefing`,
  );
}
