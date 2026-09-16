/**
 * Pure, unit-tested planning-task helpers (T27): the ready-task predicate, the
 * lease-expiry boundary check, and DAG layering for the dependency visualizer.
 * Mirrors the `dependencies` field the server already returns on `PlanTask` —
 * the list of *prerequisite* task ids this task is blocked on (see
 * `pcs.planning.service.list_ready_tasks`'s canonical predicate) — so no
 * separate edge list needs to be fetched or reconstructed here.
 *
 * No React, no DOM — everything here is unit-tested in `planTasks.test.ts`.
 */
import type { Plan, PlanTask } from "@workspace/api-client-react";

/** Task statuses that hold an active claim lease and can go stale. */
export const RECLAIMABLE_STATUSES: ReadonlySet<PlanTask["status"]> = new Set([
  "claimed",
  "in_progress",
  "in_review",
]);

const NOT_READY_STATUSES: ReadonlySet<PlanTask["status"]> = new Set([
  "completed",
  "cancelled",
  "blocked",
]);

/**
 * `lease_expires_at <= now()` — inclusive of the exact boundary, matching the
 * server's canonical predicate (`pcs.planning.service.list_ready_tasks`).
 */
export function isLeaseExpired(leaseExpiresAt: string | null, now: Date = new Date()): boolean {
  if (!leaseExpiresAt) {
    return false;
  }
  return new Date(leaseExpiresAt).getTime() <= now.getTime();
}

/** True when a task's active lease has lapsed and it is available to reclaim. */
export function isReclaimable(
  task: Pick<PlanTask, "status" | "lease_expires_at">,
  now: Date = new Date(),
): boolean {
  return RECLAIMABLE_STATUSES.has(task.status) && isLeaseExpired(task.lease_expires_at, now);
}

export type LeaseState = "none" | "active" | "expired";

/** UI display state for a task's lease, independent of the ready predicate. */
export function leaseState(
  task: Pick<PlanTask, "status" | "lease_expires_at">,
  now: Date = new Date(),
): LeaseState {
  if (!RECLAIMABLE_STATUSES.has(task.status) || !task.lease_expires_at) {
    return "none";
  }
  return isLeaseExpired(task.lease_expires_at, now) ? "expired" : "active";
}

/**
 * Canonical ready-task predicate (FR46), mirrored client-side from
 * `pcs.planning.service.list_ready_tasks` so the "Ready tasks" filter toggle
 * can run against an already-fetched plan without a second round trip:
 *
 * 1. The task's plan is `active`.
 * 2. The task is not `completed`, `cancelled`, or `blocked`.
 * 3. Every prerequisite in `task.dependencies` is `completed`.
 * 4. The task's own status is `ready`, OR it holds an expired lease
 *    (`claimed` / `in_progress` / `in_review` with `lease_expires_at <= now()`).
 */
export function isTaskReady(
  task: PlanTask,
  tasksById: ReadonlyMap<string, PlanTask>,
  planStatus: Plan["status"],
  now: Date = new Date(),
): boolean {
  if (planStatus !== "active") {
    return false;
  }
  if (NOT_READY_STATUSES.has(task.status)) {
    return false;
  }
  const prereqsCompleted = task.dependencies.every(
    (depId) => tasksById.get(depId)?.status === "completed",
  );
  if (!prereqsCompleted) {
    return false;
  }
  return task.status === "ready" || isReclaimable(task, now);
}

/** Filters a plan's already-fetched task list down to ready tasks (FR46 toggle). */
export function filterReadyTasks(
  tasks: readonly PlanTask[],
  planStatus: Plan["status"],
  now: Date = new Date(),
): PlanTask[] {
  const byId = new Map(tasks.map((t) => [t.id, t] as const));
  return tasks.filter((task) => isTaskReady(task, byId, planStatus, now));
}

/**
 * Layers tasks by longest dependency-chain depth from any root (a task with
 * no in-plan prerequisites), for the DAG visualizer's left-to-right columns.
 * A dangling or cyclic reference (should never happen server-side — DAGs are
 * validated on write) is treated as depth 0 rather than thrown on, so the
 * view degrades instead of crashing.
 */
export function layoutDag(tasks: readonly PlanTask[]): PlanTask[][] {
  const byId = new Map(tasks.map((t) => [t.id, t] as const));
  const memo = new Map<string, number>();

  function depth(id: string, path: ReadonlySet<string>): number {
    const cached = memo.get(id);
    if (cached !== undefined) {
      return cached;
    }
    const task = byId.get(id);
    if (!task || task.dependencies.length === 0 || path.has(id)) {
      memo.set(id, 0);
      return 0;
    }
    const nextPath = new Set(path).add(id);
    const d =
      1 +
      Math.max(
        0,
        ...task.dependencies.map((depId) => (byId.has(depId) ? depth(depId, nextPath) : 0)),
      );
    memo.set(id, d);
    return d;
  }

  const layers: PlanTask[][] = [];
  for (const task of tasks) {
    const d = depth(task.id, new Set());
    (layers[d] ??= []).push(task);
  }
  return layers;
}
