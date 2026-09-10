import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import { getBriefing, listProjects, registerProject } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import type { Briefing, Project, RegisterProjectInput } from "../api/types";

export function useProjects(): UseQueryResult<Project[]> {
  return useQuery({ queryKey: queryKeys.projects, queryFn: listProjects });
}

/** The single project matching `name` (by name), derived from the list query. */
export function useProject(name: string | null): Project | undefined {
  const projects = useProjects();
  if (name === null) {
    return undefined;
  }
  return projects.data?.find((p) => p.name === name);
}

export function useBriefing(project: string | null): UseQueryResult<Briefing> {
  return useQuery({
    queryKey: queryKeys.briefing(project ?? ""),
    queryFn: () => getBriefing(project ?? ""),
    enabled: project !== null && project !== "",
  });
}

export function useRegisterProject(): UseMutationResult<
  Project,
  Error,
  RegisterProjectInput
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: registerProject,
    onSuccess: (created: Project) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.projects });
      queryClient.setQueryData<Project[]>(queryKeys.projects, (current) =>
        current ? [...current, created] : [created],
      );
    },
  });
}
