import {
  useMutation,
  useQueryClient,
  type UseMutationResult,
} from "@tanstack/react-query";

import { setFocus } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import type { Project } from "../api/types";

/**
 * FR36 / S-T06 — replace the current focus (`set_current_focus` semantics). The
 * generic `add_focus` / `update_focus` / `resolve_focus` CRUD is intentionally
 * not surfaced in the dashboard.
 */
export function useSetFocus(
  project: string,
): UseMutationResult<Project, Error, string> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (text: string) => setFocus(project, text),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.section(project, "focus"),
      });
      void queryClient.invalidateQueries({ queryKey: queryKeys.projects });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.briefing(project),
      });
    },
  });
}
