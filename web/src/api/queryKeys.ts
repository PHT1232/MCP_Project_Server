/**
 * Central TanStack Query key registry. The manual-refresh control (FR38, D6)
 * invalidates by these keys, so every query the shell issues must be listed
 * here — nothing refetches on its own (no polling, no window-focus refetch).
 */

export const queryKeys = {
  projects: ["projects"] as const,
  briefing: (project: string) => ["briefing", project] as const,
  section: (project: string, section: string) =>
    ["section", project, section] as const,
  requirements: (project: string) => ["requirements", project] as const,
  indexStatus: (project: string) => ["index", project] as const,
  /**
   * FR32 — one tier of the code map. `scope === null` is the top tier; a subtree
   * path is a lazily-expanded slice. `isRefreshable` picks these up by `project`.
   */
  codeMap: (project: string, scope: string | null) =>
    ["code-map", project, scope ?? "__root__"] as const,
  /** FR34 — read-only source for the node inspector. */
  source: (project: string, path: string) => ["source", project, path] as const,
  /** FR35 — a search-panel query. */
  search: (project: string, query: string) => ["search", project, query] as const,
};

/**
 * True when a query key belongs to `project` (or is the shared project list).
 * The manual refresh (FR38) invalidates exactly this set — no more, no less.
 */
export function isRefreshable(key: readonly unknown[], project: string): boolean {
  if (key.length === 1 && key[0] === "projects") {
    return true;
  }
  return key.length >= 2 && key[1] === project;
}
