import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import {
  getRequirementContract,
  getRequirementEvidence,
  reviewRequirementCompliance,
} from "../api/client";
import { queryKeys } from "../api/queryKeys";
import type {
  RequirementComplianceResponse,
  RequirementContract,
  RequirementEvidenceResponse,
} from "../api/types";

const COMPLIANCE_BATCH_SIZE = 25;

export interface RequirementComplianceAggregate extends RequirementComplianceResponse {
  errors: string[];
}

function chunksOf(ids: string[]): string[][] {
  const chunks: string[][] = [];
  for (let index = 0; index < ids.length; index += COMPLIANCE_BATCH_SIZE) {
    chunks.push(ids.slice(index, index + COMPLIANCE_BATCH_SIZE));
  }
  return chunks;
}

async function loadCompliance(
  project: string,
  requirementIds: string[],
): Promise<RequirementComplianceAggregate> {
  const results = await Promise.allSettled(
    chunksOf(requirementIds).map((ids) => reviewRequirementCompliance(project, ids)),
  );
  const successful = results.flatMap((result) =>
    result.status === "fulfilled" ? [result.value] : [],
  );
  const errors = results.flatMap((result, index) =>
    result.status === "rejected"
      ? [`Compliance batch ${String(index + 1)} could not be loaded.`]
      : [],
  );
  return {
    project_id: successful[0]?.project_id ?? "",
    requirements: successful.flatMap((result) => result.requirements),
    reviewed_count: successful.reduce((total, result) => total + result.reviewed_count, 0),
    omitted_requirements: successful.reduce(
      (total, result) => total + result.omitted_requirements,
      0,
    ),
    limits: successful[0]?.limits ?? {
      requirements: COMPLIANCE_BATCH_SIZE,
      exceptions_per_requirement: 0,
    },
    errors,
  };
}

/** T13 — bounded 25-ID reads aggregated without dropping requirement rows. */
export function useRequirementCompliance(
  project: string,
  requirementIds: string[],
): UseQueryResult<RequirementComplianceAggregate> {
  return useQuery({
    queryKey: queryKeys.requirementCompliance(project, requirementIds),
    queryFn: () => loadCompliance(project, requirementIds),
    enabled: project !== "" && requirementIds.length > 0,
  });
}

/** T13 — lazy drill-down reads, enabled only while a row is expanded. */
export function useRequirementComplianceDetail(
  project: string,
  requirementId: string,
  enabled: boolean,
): {
  contract: UseQueryResult<RequirementContract>;
  evidence: UseQueryResult<RequirementEvidenceResponse>;
} {
  const contract = useQuery({
    queryKey: queryKeys.requirementContract(project, requirementId),
    queryFn: () => getRequirementContract(project, requirementId),
    enabled,
  });
  const evidence = useQuery({
    queryKey: queryKeys.requirementEvidence(project, requirementId),
    queryFn: () => getRequirementEvidence(project, requirementId),
    enabled,
  });
  return { contract, evidence };
}
