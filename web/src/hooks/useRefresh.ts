import { useCallback, useState } from "react";
import { useIsFetching, useQueryClient } from "@tanstack/react-query";

import { isRefreshable } from "../api/queryKeys";

interface RefreshControl {
  /** Re-fetch context, requirements and index status for the project (FR38). */
  refresh: () => void;
  /** True while any of those re-fetches is in flight. */
  isRefreshing: boolean;
  /** ISO timestamp of the last manual refresh, or `null` before the first. */
  lastRefreshedAt: string | null;
}

/**
 * FR38 / D6 — the manual refresh. Nothing in the shell polls or subscribes; the
 * only way fresh data enters the UI is this control (or an edit the user makes).
 */
export function useRefreshAll(
  project: string | null,
  includeGlobal = false,
): RefreshControl {
  const queryClient = useQueryClient();
  const [lastRefreshedAt, setLastRefreshedAt] = useState<string | null>(null);
  const inFlight = useIsFetching({
    predicate: (query) => isRefreshable(query.queryKey, project, includeGlobal),
  });

  const refresh = useCallback(() => {
    if (project === null && !includeGlobal) {
      return;
    }
    setLastRefreshedAt(new Date().toISOString());
    void queryClient.invalidateQueries({
      predicate: (query) => isRefreshable(query.queryKey, project, includeGlobal),
    });
  }, [includeGlobal, project, queryClient]);

  return { refresh, isRefreshing: inFlight > 0, lastRefreshedAt };
}
