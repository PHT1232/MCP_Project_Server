import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { getAiSettings } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import type { AiSettings } from "../api/types";

/** T20: redacted global settings contain no credentials. */
export function useAiSettings(): UseQueryResult<AiSettings> {
  return useQuery({ queryKey: queryKeys.aiSettings, queryFn: getAiSettings });
}
