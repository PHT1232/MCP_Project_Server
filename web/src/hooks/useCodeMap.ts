import {
  useQuery,
  useQueryClient,
  type QueryClient,
  type UseQueryResult,
} from "@tanstack/react-query";

import { getCodeMap, getSource, searchCode } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import type { CodeMap, SearchResponse, SourceFile } from "../api/types";

/**
 * FR32 — the top tier of the code map. Subtree expansions are fetched
 * imperatively (see `fetchCodeMapScope`) and merged client-side so a refresh
 * (FR38) only ever re-pulls this one query, then the view re-seeds from it.
 */
export function useCodeMap(project: string | null): UseQueryResult<CodeMap> {
  return useQuery({
    queryKey: queryKeys.codeMap(project ?? "", null),
    queryFn: () => getCodeMap(project ?? ""),
    enabled: project !== null && project !== "",
  });
}

/**
 * FR32 — one level below the top tier (`depth=2`), for the read-down document's
 * per-area child list. Separate from `useCodeMap` so a refresh (FR38) re-pulls
 * both tiers and nothing else.
 */
export function useCodeMapDoc(project: string | null): UseQueryResult<CodeMap> {
  return useQuery({
    queryKey: queryKeys.codeMapDoc(project ?? ""),
    queryFn: () => getCodeMap(project ?? "", undefined, 2),
    enabled: project !== null && project !== "",
  });
}

/** FR32a — fetch one subtree / file scope on demand, cached under its own key. */
export function fetchCodeMapScope(
  queryClient: QueryClient,
  project: string,
  scope: string,
  depth?: number,
): Promise<CodeMap> {
  return queryClient.query({
    queryKey: queryKeys.codeMap(project, scope),
    queryFn: () => getCodeMap(project, scope, depth),
    // Serve a cached tier if we already have it; only fetch a scope once.
    staleTime: "static",
  });
}

/** FR34 — a file's symbol / dependency view for the inspector (`scope=<file>`). */
export function useFileScope(
  project: string | null,
  path: string | null,
): UseQueryResult<CodeMap> {
  return useQuery({
    queryKey: queryKeys.codeMap(project ?? "", path),
    queryFn: () => getCodeMap(project ?? "", path ?? ""),
    enabled: project !== null && project !== "" && path !== null && path !== "",
  });
}

/** FR34 — read-only source for the inspected file. */
export function useSource(
  project: string | null,
  path: string | null,
): UseQueryResult<SourceFile> {
  return useQuery({
    queryKey: queryKeys.source(project ?? "", path ?? ""),
    queryFn: () => getSource(project ?? "", path ?? ""),
    enabled: project !== null && project !== "" && path !== null && path !== "",
  });
}

/** FR35 — a submitted search-panel query (empty query = idle). */
export function useCodeSearch(
  project: string | null,
  query: string,
): UseQueryResult<SearchResponse> {
  return useQuery({
    queryKey: queryKeys.search(project ?? "", query),
    queryFn: () => searchCode(project ?? "", query, { limit: 30 }),
    enabled: project !== null && project !== "" && query !== "",
  });
}

export function useCodeMapClient(): QueryClient {
  return useQueryClient();
}
