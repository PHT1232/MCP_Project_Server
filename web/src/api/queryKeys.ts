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
