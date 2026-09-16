import { describe, expect, it } from "vitest";
import type { PlanTask } from "@workspace/api-client-react";
import {
  filterReadyTasks,
  isLeaseExpired,
  isReclaimable,
  isTaskReady,
  layoutDag,
  leaseState,
} from "./planTasks";

const NOW = new Date("2026-06-01T12:00:00.000Z");

function task(partial: Partial<PlanTask> & Pick<PlanTask, "id" | "status">): PlanTask {
  return {
    plan_id: "plan-1",
    project_id: "proj-1",
    local_task_id: partial.id,
    title: `Task ${partial.id}`,
    objective: "Do the thing.",
    acceptance_criteria: [],
    linked_files: [],
    priority: 0,
    claimed_by: null,
    lease_expires_at: null,
    created_at: "2026-01-01T00:00:00.000Z",
    updated_at: "2026-01-01T00:00:00.000Z",
    dependencies: [],
    requirement_ids: [],
    ...partial,
  };
}

describe("isLeaseExpired", () => {
  it("is false when there is no lease", () => {
    expect(isLeaseExpired(null, NOW)).toBe(false);
  });

  it("is false while the lease is still in the future", () => {
    expect(isLeaseExpired("2026-06-01T12:00:01.000Z", NOW)).toBe(false);
  });

  it("is true exactly at the boundary (lease_expires_at == now())", () => {
    expect(isLeaseExpired("2026-06-01T12:00:00.000Z", NOW)).toBe(true);
  });

  it("is true once the lease is in the past", () => {
    expect(isLeaseExpired("2026-06-01T11:59:59.000Z", NOW)).toBe(true);
  });
});

describe("isReclaimable / leaseState", () => {
  it.each(["claimed", "in_progress", "in_review"] as const)(
    "%s with an expired lease is reclaimable and shows 'expired'",
    (status) => {
      const t = task({ id: "t1", status, lease_expires_at: "2026-06-01T12:00:00.000Z" });
      expect(isReclaimable(t, NOW)).toBe(true);
      expect(leaseState(t, NOW)).toBe("expired");
    },
  );

  it.each(["claimed", "in_progress", "in_review"] as const)(
    "%s with an unexpired lease is not reclaimable and shows 'active'",
    (status) => {
      const t = task({ id: "t1", status, lease_expires_at: "2026-06-01T13:00:00.000Z" });
      expect(isReclaimable(t, NOW)).toBe(false);
      expect(leaseState(t, NOW)).toBe("active");
    },
  );

  it("a ready task with no lease shows 'none' and is not reclaimable", () => {
    const t = task({ id: "t1", status: "ready" });
    expect(isReclaimable(t, NOW)).toBe(false);
    expect(leaseState(t, NOW)).toBe("none");
  });

  it("a completed task is never reclaimable even with a stale lease field", () => {
    const t = task({ id: "t1", status: "completed", lease_expires_at: "2020-01-01T00:00:00.000Z" });
    expect(isReclaimable(t, NOW)).toBe(false);
    expect(leaseState(t, NOW)).toBe("none");
  });
});

describe("isTaskReady / filterReadyTasks", () => {
  it("a 'ready' task in an active plan with no dependencies is ready", () => {
    const t = task({ id: "t1", status: "ready" });
    expect(isTaskReady(t, new Map([["t1", t]]), "active", NOW)).toBe(true);
  });

  it("is not ready when the plan is not active", () => {
    const t = task({ id: "t1", status: "ready" });
    expect(isTaskReady(t, new Map([["t1", t]]), "draft", NOW)).toBe(false);
  });

  it.each(["completed", "cancelled", "blocked"] as const)(
    "a %s task is never ready",
    (status) => {
      const t = task({ id: "t1", status });
      expect(isTaskReady(t, new Map([["t1", t]]), "active", NOW)).toBe(false);
    },
  );

  it("is not ready when a prerequisite is not completed", () => {
    const prereq = task({ id: "p1", status: "in_progress" });
    const t = task({ id: "t1", status: "ready", dependencies: ["p1"] });
    const byId = new Map([
      ["p1", prereq],
      ["t1", t],
    ]);
    expect(isTaskReady(t, byId, "active", NOW)).toBe(false);
  });

  it("is ready once every prerequisite is completed", () => {
    const prereq = task({ id: "p1", status: "completed" });
    const t = task({ id: "t1", status: "ready", dependencies: ["p1"] });
    const byId = new Map([
      ["p1", prereq],
      ["t1", t],
    ]);
    expect(isTaskReady(t, byId, "active", NOW)).toBe(true);
  });

  it("an in_review task with an expired lease is ready (reclaimable), including the exact boundary", () => {
    const t = task({ id: "t1", status: "in_review", lease_expires_at: "2026-06-01T12:00:00.000Z" });
    expect(isTaskReady(t, new Map([["t1", t]]), "active", NOW)).toBe(true);
  });

  it("a claimed task with an unexpired lease is not ready", () => {
    const t = task({ id: "t1", status: "claimed", lease_expires_at: "2026-06-01T13:00:00.000Z" });
    expect(isTaskReady(t, new Map([["t1", t]]), "active", NOW)).toBe(false);
  });

  it("filterReadyTasks returns only the ready subset, preserving task identity", () => {
    const ready = task({ id: "t1", status: "ready" });
    const blocked = task({ id: "t2", status: "blocked" });
    const expiredInReview = task({
      id: "t3",
      status: "in_review",
      lease_expires_at: "2026-06-01T12:00:00.000Z",
    });
    const staleClaim = task({ id: "t4", status: "claimed", lease_expires_at: "2026-06-01T13:00:00.000Z" });
    const result = filterReadyTasks([ready, blocked, expiredInReview, staleClaim], "active", NOW);
    expect(result.map((t) => t.id)).toEqual(["t1", "t3"]);
  });
});

describe("layoutDag", () => {
  it("puts tasks with no dependencies at layer 0", () => {
    const a = task({ id: "a", status: "ready" });
    const b = task({ id: "b", status: "ready" });
    const layers = layoutDag([a, b]);
    expect(layers).toHaveLength(1);
    expect(layers[0].map((t) => t.id).sort()).toEqual(["a", "b"]);
  });

  it("layers a linear chain a -> b -> c by dependency depth", () => {
    const a = task({ id: "a", status: "completed" });
    const b = task({ id: "b", status: "completed", dependencies: ["a"] });
    const c = task({ id: "c", status: "ready", dependencies: ["b"] });
    const layers = layoutDag([a, b, c]);
    expect(layers.map((layer) => layer.map((t) => t.id))).toEqual([["a"], ["b"], ["c"]]);
  });

  it("layers a diamond (a <- b, a <- c, b&c <- d) by longest path", () => {
    const a = task({ id: "a", status: "completed" });
    const b = task({ id: "b", status: "completed", dependencies: ["a"] });
    const c = task({ id: "c", status: "completed", dependencies: ["a"] });
    const d = task({ id: "d", status: "ready", dependencies: ["b", "c"] });
    const layers = layoutDag([a, b, c, d]);
    expect(layers[0].map((t) => t.id)).toEqual(["a"]);
    expect(layers[1].map((t) => t.id).sort()).toEqual(["b", "c"]);
    expect(layers[2].map((t) => t.id)).toEqual(["d"]);
  });

  it("treats a dangling dependency reference as an unresolved (depth-0) prerequisite rather than throwing", () => {
    const a = task({ id: "a", status: "ready", dependencies: ["ghost"] });
    expect(() => layoutDag([a])).not.toThrow();
    const layers = layoutDag([a]);
    expect(layers.flat().map((t) => t.id)).toEqual(["a"]);
  });

  it("does not infinite-loop on a cyclic reference (defensive — server rejects cycles on write)", () => {
    const a = task({ id: "a", status: "ready", dependencies: ["b"] });
    const b = task({ id: "b", status: "ready", dependencies: ["a"] });
    expect(() => layoutDag([a, b])).not.toThrow();
  });
});
