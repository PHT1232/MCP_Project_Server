import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import { addEntry, getSection, resolveEntry, updateEntry } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import type {
  EntryInput,
  EntryWriteResponse,
  SectionResponse,
} from "../api/types";

/** FR36 — one dashboard section's entries. */
export function useSection(
  project: string | null,
  section: string,
): UseQueryResult<SectionResponse> {
  return useQuery({
    queryKey: queryKeys.section(project ?? "", section),
    queryFn: () => getSection(project ?? "", section),
    enabled: project !== null && project !== "",
  });
}

interface AddEntryVars {
  section: string;
  input: EntryInput;
}
interface UpdateEntryVars {
  section: string;
  entryId: string;
  input: EntryInput;
}
interface ResolveEntryVars {
  section: string;
  entryId: string;
}

/**
 * FR36 create/update/resolve for a section's entries. Every success invalidates
 * that section plus the briefing, so a dashboard edit is reflected in the next
 * `get_project_briefing` and vice versa (AC14).
 */
export function useEntryMutations(project: string): {
  add: UseMutationResult<EntryWriteResponse, Error, AddEntryVars>;
  update: UseMutationResult<EntryWriteResponse, Error, UpdateEntryVars>;
  resolve: UseMutationResult<EntryWriteResponse, Error, ResolveEntryVars>;
} {
  const queryClient = useQueryClient();
  const invalidate = (section: string): void => {
    void queryClient.invalidateQueries({
      queryKey: queryKeys.section(project, section),
    });
    void queryClient.invalidateQueries({
      queryKey: queryKeys.briefing(project),
    });
    void queryClient.invalidateQueries({
      queryKey: queryKeys.requirements(project),
    });
  };

  const add = useMutation({
    mutationFn: (vars: AddEntryVars) => addEntry(project, vars.input),
    onSuccess: (_data, vars) => {
      invalidate(vars.section);
    },
  });
  const update = useMutation({
    mutationFn: (vars: UpdateEntryVars) =>
      updateEntry(project, vars.entryId, vars.input),
    onSuccess: (_data, vars) => {
      invalidate(vars.section);
    },
  });
  const resolve = useMutation({
    mutationFn: (vars: ResolveEntryVars) => resolveEntry(project, vars.entryId),
    onSuccess: (_data, vars) => {
      invalidate(vars.section);
    },
  });

  return { add, update, resolve };
}
