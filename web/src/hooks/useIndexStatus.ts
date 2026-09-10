import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import { getIndexStatus, reindex } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import type { IndexStatus } from "../api/types";

/** FR37 — index counts, timestamps, skipped files, semantic availability. */
export function useIndexStatus(
  project: string | null,
): UseQueryResult<IndexStatus> {
  return useQuery({
    queryKey: queryKeys.indexStatus(project ?? ""),
    queryFn: () => getIndexStatus(project ?? ""),
    enabled: project !== null && project !== "",
  });
}

/** FR37 — "reindex now". */
export function useReindex(
  project: string,
): UseMutationResult<IndexStatus, Error, { incremental: boolean }> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (vars: { incremental: boolean }) =>
      reindex(project, vars.incremental),
    onSuccess: (data) => {
      queryClient.setQueryData<IndexStatus>(queryKeys.indexStatus(project), data);
      void queryClient.invalidateQueries({
        queryKey: queryKeys.indexStatus(project),
      });
    },
  });
}
