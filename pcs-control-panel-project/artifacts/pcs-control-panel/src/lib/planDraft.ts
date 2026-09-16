/**
 * Pure shaping of an unpersisted AI `PlanDraft` (T26/T28) into inputs for
 * T27's already-built, tested components — no DOM, no network, no server
 * mutation. Two responsibilities:
 *
 * - `draftTasksToPlanTasks` maps `PlanDraftTask`/`PlanDraftDependency` (keyed
 *   by `local_task_id`, no server id yet) into the shape `DagView` already
 *   consumes (`PlanTask`), so the dependency visualizer built for T27 can be
 *   reused as-is for a draft instead of a second bespoke renderer. Since
 *   nothing here is persisted, `id` is set to `local_task_id` itself (unique
 *   within one draft — `pcs.planning.schemas.parse_plan_draft` rejects
 *   duplicates server-side) and every lease/plan field is a stable placeholder.
 * - `draftToCreatePlanWithTasksInput` maps the same draft into the exact body
 *   shape `POST /plans/with-tasks` (`create_plan_with_tasks`, T23) expects,
 *   for the "Review & Create" approval action (AC-PLAN-10, INV-PLAN-6).
 */
import type {
  CreatePlanWithTasksInput,
  PlanDraft,
  PlanTask,
} from '@workspace/api-client-react';

const DRAFT_PLACEHOLDER_TIMESTAMP = new Date(0).toISOString();

export function draftTasksToPlanTasks(
  draft: Pick<PlanDraft, 'tasks' | 'dependencies'>,
): PlanTask[] {
  return draft.tasks.map((task) => ({
    id: task.local_task_id,
    plan_id: '',
    project_id: '',
    local_task_id: task.local_task_id,
    title: task.title,
    objective: task.objective,
    acceptance_criteria: task.acceptance_criteria,
    linked_files: task.linked_files,
    priority: 0,
    status: 'pending',
    claimed_by: null,
    lease_expires_at: null,
    created_at: DRAFT_PLACEHOLDER_TIMESTAMP,
    updated_at: DRAFT_PLACEHOLDER_TIMESTAMP,
    dependencies: draft.dependencies
      .filter((dep) => dep.task_local_id === task.local_task_id)
      .map((dep) => dep.depends_on_local_id),
    requirement_ids: task.requirement_ids,
  }));
}

export function draftToCreatePlanWithTasksInput(
  draft: Pick<PlanDraft, 'title' | 'goal' | 'tasks' | 'dependencies'>,
): CreatePlanWithTasksInput {
  return {
    title: draft.title,
    goal: draft.goal,
    tasks: draft.tasks.map((task) => ({
      local_task_id: task.local_task_id,
      title: task.title,
      objective: task.objective,
      acceptance_criteria: task.acceptance_criteria,
      linked_files: task.linked_files,
      requirement_ids: task.requirement_ids,
    })),
    dependencies: draft.dependencies.map((dep) => ({
      task_local_id: dep.task_local_id,
      depends_on_local_id: dep.depends_on_local_id,
    })),
  };
}
