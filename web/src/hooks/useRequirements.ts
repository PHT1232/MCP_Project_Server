import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import {
  addEntry,
  listRequirements,
  syncRequirements,
  updateEntry,
} from "../api/client";
import { queryKeys } from "../api/queryKeys";
import type {
  EntryWriteResponse,
  RequirementStatus,
  RequirementsResponse,
  SyncReport,
} from "../api/types";

/** FR36a — the requirements list plus done/total counts. */
export function useRequirements(
  project: string | null,
): UseQueryResult<RequirementsResponse> {
  return useQuery({
    queryKey: queryKeys.requirements(project ?? ""),
    queryFn: () => listRequirements(project ?? ""),
    enabled: project !== null && project !== "",
  });
}

interface AddRequirementVars {
  title: string;
  status: RequirementStatus;
}
interface SetStatusVars {
  entryId: string;
  status: RequirementStatus;
}

export function useRequirementMutations(project: string): {
  add: UseMutationResult<EntryWriteResponse, Error, AddRequirementVars>;
  setStatus: UseMutationResult<EntryWriteResponse, Error, SetStatusVars>;
  sync: UseMutationResult<SyncReport, Error, void>;
} {
  const queryClient = useQueryClient();
  const invalidate = (): void => {
    void queryClient.invalidateQueries({
      queryKey: queryKeys.requirements(project),
    });
    void queryClient.invalidateQueries({
      queryKey: queryKeys.section(project, "requirements"),
    });
    void queryClient.invalidateQueries({ queryKey: queryKeys.briefing(project) });
  };

  const add = useMutation({
    mutationFn: (vars: AddRequirementVars) =>
      addEntry(project, {
        section: "requirements",
        headline: vars.title,
        status: vars.status,
      }),
    onSuccess: invalidate,
  });
  const setStatus = useMutation({
    mutationFn: (vars: SetStatusVars) =>
      updateEntry(project, vars.entryId, { status: vars.status }),
    onSuccess: invalidate,
  });
  const sync = useMutation({
    mutationFn: () => syncRequirements(project),
    onSuccess: invalidate,
  });

  return { add, setStatus, sync };
}
