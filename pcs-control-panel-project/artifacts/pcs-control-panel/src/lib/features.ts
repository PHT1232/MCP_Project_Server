/**
 * Pure derivation helpers for the Features view — no React, no DOM. Unit-
 * tested in `features.test.ts`, matching the `lib/tokenSavings.ts` convention.
 */
import type { Entry, Requirement } from '@workspace/api-client-react';

export interface ResolvedFeature {
  feature: Entry;
  requirement: Requirement | undefined;
}

/**
 * Pairs each feature entry with the requirement its `related_entry_id`
 * points at, if any. A feature with no `related_entry_id`, or one that
 * points at a requirement id not present in `requirements` (e.g. the
 * requirement was archived), resolves to `undefined` rather than throwing.
 */
export function resolveFeatureRequirements(
  features: readonly Entry[],
  requirements: readonly Requirement[],
): ResolvedFeature[] {
  const byId = new Map(requirements.map((req) => [req.entry_id, req]));
  return features.map((feature) => ({
    feature,
    requirement: feature.related_entry_id ? byId.get(feature.related_entry_id) : undefined,
  }));
}
