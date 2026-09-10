import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import {
  getBriefing,
  listProjects,
  registerProject,
} from "../api/client";
import type { Briefing, Project, RegisterProjectInput } from "../api/types";

const PROJECTS_KEY = ["projects"] as const;

export function useProjects(): UseQueryResult<Project[]> {
  return useQuery({ queryKey: PROJECTS_KEY, queryFn: listProjects });
}

export function useBriefing(project: string | null): UseQueryResult<Briefing> {
  return useQuery({
    queryKey: ["briefing", project] as const,
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
      void queryClient.invalidateQueries({ queryKey: PROJECTS_KEY });
      queryClient.setQueryData<Project[]>(PROJECTS_KEY, (current) =>
        current ? [...current, created] : [created],
      );
    },
  });
}
