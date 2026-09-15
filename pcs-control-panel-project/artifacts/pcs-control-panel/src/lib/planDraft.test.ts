import { describe, expect, it } from "vitest";
import type { PlanDraft } from "@workspace/api-client-react";
import { layoutDag } from "./planTasks";
import { draftTasksToPlanTasks, draftToCreatePlanWithTasksInput } from "./planDraft";

function draft(partial: Partial<PlanDraft> = {}): PlanDraft {
  return {
    title: "Ship pricing",
    goal: "Add unit pricing end to end",
    tasks: [
      {
        local_task_id: "t1",
        title: "Add pricing helper",
        objective: "Implement unit_price.",
        acceptance_criteria: ["unit_price returns item.price * item.quantity"],
        linked_files: ["shop/pricing.py"],
        requirement_ids: [],
      },
      {
        local_task_id: "t2",
        title: "Wire pricing into cart total",
        objective: "Use unit_price inside cart_total.",
        acceptance_criteria: ["cart_total sums unit_price(item)"],
        linked_files: ["shop/cart.py"],
        requirement_ids: ["R-1"],
      },
    ],
    dependencies: [{ task_local_id: "t2", depends_on_local_id: "t1" }],
    notes: "Keep pricing pure.",
    ...partial,
  };
}

describe("draftTasksToPlanTasks", () => {
  it("maps every draft task into a PlanTask-shaped placeholder keyed by local_task_id", () => {
    const tasks = draftTasksToPlanTasks(draft());
    expect(tasks).toHaveLength(2);
    expect(tasks[0]).toMatchObject({
      id: "t1",
      local_task_id: "t1",
      title: "Add pricing helper",
      status: "pending",
      claimed_by: null,
      lease_expires_at: null,
      dependencies: [],
      requirement_ids: [],
    });
    expect(tasks[1]).toMatchObject({
      id: "t2",
      local_task_id: "t2",
      dependencies: ["t1"],
      requirement_ids: ["R-1"],
    });
  });

  it("carries acceptance criteria and linked files through unchanged", () => {
    const tasks = draftTasksToPlanTasks(draft());
    expect(tasks[0].acceptance_criteria).toEqual(["unit_price returns item.price * item.quantity"]);
    expect(tasks[0].linked_files).toEqual(["shop/pricing.py"]);
  });

  it("produces output layoutDag (T27) can layer directly, since dependencies reference local ids as-is", () => {
    const layers = layoutDag(draftTasksToPlanTasks(draft()));
    expect(layers.map((layer) => layer.map((t) => t.local_task_id))).toEqual([["t1"], ["t2"]]);
  });

  it("handles a task with no dependencies pointing at it", () => {
    const tasks = draftTasksToPlanTasks(draft({ dependencies: [] }));
    expect(tasks.every((t) => t.dependencies.length === 0)).toBe(true);
  });
});

describe("draftToCreatePlanWithTasksInput", () => {
  it("maps the draft 1:1 into the create_plan_with_tasks body shape", () => {
    const input = draftToCreatePlanWithTasksInput(draft());
    expect(input).toEqual({
      title: "Ship pricing",
      goal: "Add unit pricing end to end",
      tasks: [
        {
          local_task_id: "t1",
          title: "Add pricing helper",
          objective: "Implement unit_price.",
          acceptance_criteria: ["unit_price returns item.price * item.quantity"],
          linked_files: ["shop/pricing.py"],
          requirement_ids: [],
        },
        {
          local_task_id: "t2",
          title: "Wire pricing into cart total",
          objective: "Use unit_price inside cart_total.",
          acceptance_criteria: ["cart_total sums unit_price(item)"],
          linked_files: ["shop/cart.py"],
          requirement_ids: ["R-1"],
        },
      ],
      dependencies: [{ task_local_id: "t2", depends_on_local_id: "t1" }],
    });
  });

  it("drops the advisory 'notes' field — it has no home in create_plan_with_tasks", () => {
    const input = draftToCreatePlanWithTasksInput(draft());
    expect(input).not.toHaveProperty("notes");
  });

  it("passes an empty dependencies array through as-is for a draft with no edges", () => {
    const input = draftToCreatePlanWithTasksInput(draft({ dependencies: [] }));
    expect(input.dependencies).toEqual([]);
  });
});
