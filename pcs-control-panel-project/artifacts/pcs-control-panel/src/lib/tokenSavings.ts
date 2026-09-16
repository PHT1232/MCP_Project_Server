/**
 * Pure formatting/derivation helpers for the token-savings log view — no
 * React, no DOM. Unit-tested in `tokenSavings.test.ts`, matching the
 * `lib/planTasks.ts` convention (T27).
 */
import type { TokenSavingsOperation, TokenSavingsOperationSummary } from '@workspace/api-client-react';

export const OPERATION_LABEL: Record<TokenSavingsOperation, string> = {
  retrieve_context: 'Retrieve context',
  search_code: 'Search code',
  prepare_task: 'Prepare task',
  get_project_briefing: 'Get briefing',
};

/** Percentage of baseline tokens saved, 0-100, rounded. NaN-safe for a zero baseline. */
export function savingsPercent(summary: Pick<TokenSavingsOperationSummary, 'baseline_tokens_total' | 'saved_tokens_total'>): number {
  if (summary.baseline_tokens_total <= 0) return 0;
  const pct = (summary.saved_tokens_total / summary.baseline_tokens_total) * 100;
  return Math.max(0, Math.min(100, Math.round(pct)));
}

/** Average tokens saved per call, rounded down. 0 when there were no calls. */
export function averageSavedPerCall(summary: Pick<TokenSavingsOperationSummary, 'call_count' | 'saved_tokens_total'>): number {
  if (summary.call_count <= 0) return 0;
  return Math.floor(summary.saved_tokens_total / summary.call_count);
}

/** Compact human count: 1234 -> "1.2k", 1234567 -> "1.2M". Small numbers pass through. */
export function formatTokenCount(value: number): string {
  const abs = Math.abs(value);
  if (abs < 1000) return String(value);
  if (abs < 1_000_000) return `${(value / 1000).toFixed(1).replace(/\.0$/, '')}k`;
  return `${(value / 1_000_000).toFixed(1).replace(/\.0$/, '')}M`;
}

/**
 * Sorts per-operation summaries by tokens saved, descending — the most
 * impactful operation first, for the breakdown list.
 */
export function sortByImpact(summaries: readonly TokenSavingsOperationSummary[]): TokenSavingsOperationSummary[] {
  return [...summaries].sort((a, b) => b.saved_tokens_total - a.saved_tokens_total);
}
