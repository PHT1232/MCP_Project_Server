import type { RequirementStatus } from "../api/types";

/**
 * The FR36a completion summary — "N of M done". `done` is clamped into
 * `[0, total]` so a stale count never renders something nonsensical.
 */
export function doneSummary(done: number, total: number): string {
  const safeTotal = Math.max(0, Math.trunc(total));
  const safeDone = Math.min(Math.max(0, Math.trunc(done)), safeTotal);
  return `${String(safeDone)} of ${String(safeTotal)} done`;
}

/** Fraction complete in `[0, 1]`; `0` when there are no requirements. */
export function doneFraction(done: number, total: number): number {
  const safeTotal = Math.max(0, Math.trunc(total));
  if (safeTotal === 0) {
    return 0;
  }
  const safeDone = Math.min(Math.max(0, Math.trunc(done)), safeTotal);
  return safeDone / safeTotal;
}

export const REQUIREMENT_STATUSES: readonly RequirementStatus[] = [
  "not-started",
  "in-progress",
  "blocked",
  "done",
];

const STATUS_LABELS: Record<RequirementStatus, string> = {
  "not-started": "Not started",
  "in-progress": "In progress",
  blocked: "Blocked",
  done: "Done",
};

export function requirementStatusLabel(status: RequirementStatus): string {
  return STATUS_LABELS[status];
}
