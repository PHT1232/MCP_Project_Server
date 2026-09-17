import { useEffect, useMemo, useState } from 'react';
import { useParams } from 'wouter';
import {
  ApiError,
  useActivatePlan,
  useAddPlanTask,
  useAddTaskDependency,
  useArchivePlan,
  useClaimTask,
  useCompletePlan,
  useCompleteTask,
  useCreatePlan,
  useGetPlan,
  useHeartbeatTask,
  useListPlans,
  usePreparePlanTaskPrompt,
  useReleaseTask,
  useSetTaskStatus,
  useUpdatePlan,
  type Plan,
  type PlanStatus,
  type PlanTask,
  type TaskStatus,
} from '@workspace/api-client-react';
import { Archive, Check, GitBranch, ListTodo, Loader2, Play, Plus, Sparkles } from 'lucide-react';
import {
  Badge,
  Button,
  combineQueryErrors,
  cx,
  ErrorBanner,
  Field,
  notify,
  notifyError,
  PageHeader,
  ProjectTabs,
  queryClient,
  type Tone,
} from '../App';
import { AiPlanDraftModal } from '../components/plans/AiPlanDraftModal';
import { ClaimModal } from '../components/plans/ClaimModal';
import { DagView } from '../components/plans/DagView';
import { HistoryDrawer } from '../components/plans/HistoryDrawer';
import { TaskCard } from '../components/plans/TaskCard';
import { filterReadyTasks } from '../lib/planTasks';

const PLAN_STATUS_TONE: Record<PlanStatus, Tone> = {
  draft: 'ink',
  active: 'blue',
  completed: 'mint',
  archived: 'ink',
};

const CLAIM_TOKEN_PREFIX = 'pcs-claim-token:';

function tokenKey(taskId: string): string {
  return `${CLAIM_TOKEN_PREFIX}${taskId}`;
}

function getStoredToken(taskId: string): string | null {
  try {
    return localStorage.getItem(tokenKey(taskId));
  } catch {
    return null;
  }
}

function setStoredToken(taskId: string, token: string): void {
  try {
    localStorage.setItem(tokenKey(taskId), token);
  } catch {
    // localStorage unavailable — the claim still succeeded server-side, but
    // this browser won't be able to heartbeat/release/complete it directly.
  }
}

function clearStoredToken(taskId: string): void {
  try {
    localStorage.removeItem(tokenKey(taskId));
  } catch {
    // no-op
  }
}

/** Every planning query for this project, matched by URL prefix (INV-PLAN-7: no stale state after a mutation). */
function invalidatePlanningQueries(project: string): void {
  queryClient.invalidateQueries({
    predicate: (query) => {
      const key = query.queryKey[0];
      return (
        typeof key === 'string' &&
        (key === `/api/projects/${project}/ready-tasks` || key.startsWith(`/api/projects/${project}/plans`))
      );
    },
  });
}

/** 409s (stale token, claim conflict, plan not active) get a conflict banner; a stale local token is cleared. */
function handlePlanningError(action: string, err: unknown, taskId?: string): void {
  if (err instanceof ApiError && err.status === 409) {
    if (taskId) clearStoredToken(taskId);
    notifyError(`${action} — conflict`, err);
    return;
  }
  notifyError(action, err);
}

function progressLabel(plan: { tasks: PlanTask[] }): string {
  const completed = plan.tasks.filter((t) => t.status === 'completed').length;
  return `${completed} / ${plan.tasks.length}`;
}

const PLAN_STATUS_FILTERS: Array<{ id: PlanStatus | 'all'; label: string }> = [
  { id: 'all', label: 'All' },
  { id: 'active', label: 'Active' },
  { id: 'draft', label: 'Draft' },
  { id: 'completed', label: 'Completed' },
  { id: 'archived', label: 'Archived' },
];

export default function Plans() {
  const project = decodeURIComponent(useParams<{ project: string }>().project ?? '');
  const [statusFilter, setStatusFilter] = useState<PlanStatus | 'all'>('active');
  const plansQuery = useListPlans(project, statusFilter === 'all' ? undefined : { status: statusFilter });
  const plans = useMemo(() => plansQuery.data ?? [], [plansQuery.data]);

  const [selectedPlanId, setSelectedPlanId] = useState<string | null>(null);
  useEffect(() => {
    if (!selectedPlanId && plans.length > 0) setSelectedPlanId(plans[0].id);
  }, [plans, selectedPlanId]);

  const planQuery = useGetPlan(project, selectedPlanId ?? '', { query: { enabled: !!selectedPlanId } as any });
  const plan = planQuery.data ?? null;

  const [newPlanOpen, setNewPlanOpen] = useState(false);
  const [newTitle, setNewTitle] = useState('');
  const [newGoal, setNewGoal] = useState('');
  const createPlanMutation = useCreatePlan();
  const createPlan = () => {
    if (!newTitle.trim() || !newGoal.trim()) {
      notifyError('Create plan', new Error('Title and goal are both required.'));
      return;
    }
    createPlanMutation.mutate(
      { project, data: { title: newTitle.trim(), goal: newGoal.trim() } },
      {
        onSuccess: (created) => {
          invalidatePlanningQueries(project);
          setSelectedPlanId(created.id);
          setNewTitle('');
          setNewGoal('');
          setNewPlanOpen(false);
          notify('Plan created', created.title);
        },
        onError: (err) => notifyError('Create plan', err),
      },
    );
  };

  const [aiDraftOpen, setAiDraftOpen] = useState(false);

  const loadError = combineQueryErrors(plansQuery);

  return (
    <>
      <PageHeader
        eyebrow="atlas-console / plans"
        title="Plans"
        description="Break work into orchestrated, lease-claimable tasks for agents and operators to pick up."
        actions={<>
          <Button testId="button-generate-with-ai" variant="secondary" size="sm" onClick={() => setAiDraftOpen(true)}><Sparkles size={14} />Generate with AI</Button>
          <Button testId="button-new-plan" size="sm" onClick={() => setNewPlanOpen((v) => !v)}><Plus size={14} />New plan</Button>
        </>}
      />
      <ProjectTabs active="plans" />
      {loadError.isError && <ErrorBanner testId="banner-plans-error" message={loadError.message} onRetry={loadError.retry} />}

      {newPlanOpen && (
        <div className="mb-5 grid min-w-0 grid-cols-1 gap-3 rounded-lg border border-[#cbd7f4] bg-[#faf9f4] p-4 md:grid-cols-[1fr_1.6fr_auto] md:items-end">
          <Field testId="input-new-plan-title" label="Title" value={newTitle} onChange={setNewTitle} placeholder="e.g. Checkout migration" />
          <Field testId="input-new-plan-goal" label="Goal" value={newGoal} onChange={setNewGoal} placeholder="What does 'done' look like?" />
          <Button testId="button-submit-new-plan" onClick={createPlan} disabled={createPlanMutation.isPending}>
            {createPlanMutation.isPending ? <Loader2 className="animate-spin" size={14} /> : <Check size={14} />}
            Create
          </Button>
        </div>
      )}

      <div className="mb-4 flex items-center gap-1 overflow-x-auto rounded-lg border border-[#d7dbd4] bg-[#e7e9e2] p-1">
        {PLAN_STATUS_FILTERS.map(({ id, label }) => (
          <button
            key={id}
            data-testid={`filter-plan-status-${id}`}
            onClick={() => setStatusFilter(id)}
            className={cx(
              'whitespace-nowrap rounded-md px-3 py-2 text-xs font-semibold transition-colors md:px-4',
              statusFilter === id ? 'bg-[#faf9f4] text-[#1e3036] shadow-[0_1px_2px_rgba(31,43,45,.08)]' : 'text-[#758187] hover:text-[#34464c]',
            )}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="grid min-w-0 grid-cols-1 gap-5 xl:grid-cols-[320px_1fr]">
        <section className="min-w-0 space-y-2">
          {plansQuery.isLoading && <div className="py-10 text-center"><Loader2 className="animate-spin mx-auto text-[#3155d8]" /></div>}
          {!plansQuery.isLoading && plans.length === 0 && (
            <p className="rounded-lg border border-dashed border-[#c7d0cb] bg-[#faf9f4] p-5 text-center text-xs text-[#7b888c]">No plans match this filter.</p>
          )}
          {plans.map((p) => (
            <button
              key={p.id}
              type="button"
              data-testid={`card-plan-${p.id}`}
              onClick={() => setSelectedPlanId(p.id)}
              className={cx(
                'block w-full rounded-lg border p-4 text-left transition-colors',
                selectedPlanId === p.id ? 'border-[#3155d8] bg-[#e8edff]' : 'border-[#d8dcd5] bg-[#faf9f4] hover:border-[#b7c2c6]',
              )}
            >
              <div className="flex items-center justify-between gap-2">
                <h3 className="min-w-0 flex-1 truncate text-sm font-bold text-[#1e3036]">{p.title}</h3>
                <Badge tone={PLAN_STATUS_TONE[p.status]} dot>{p.status}</Badge>
              </div>
              <p className="mt-1 line-clamp-2 text-xs leading-5 text-[#69777c]">{p.goal}</p>
              <div className="mt-2 flex items-center justify-between font-mono text-[10px] text-[#8a969a]">
                <span>{progressLabel(p)} tasks</span>
                <span>{new Date(p.created_at).toLocaleDateString()}</span>
              </div>
            </button>
          ))}
        </section>

        <section>
          {!selectedPlanId && <p className="rounded-lg border border-dashed border-[#c7d0cb] bg-[#faf9f4] p-10 text-center text-sm text-[#7b888c]">Select a plan to see its tasks.</p>}
          {selectedPlanId && planQuery.isLoading && <div className="py-10 text-center"><Loader2 className="animate-spin mx-auto text-[#3155d8]" /></div>}
          {selectedPlanId && planQuery.isError && (
            <ErrorBanner testId="banner-plan-detail-error" message={planQuery.error instanceof Error ? planQuery.error.message : 'Failed to load this plan.'} onRetry={() => planQuery.refetch()} />
          )}
          {plan && <PlanDetail project={project} plan={plan} />}
        </section>
      </div>

      {aiDraftOpen && (
        <AiPlanDraftModal
          project={project}
          onClose={() => setAiDraftOpen(false)}
          onCreated={(created) => {
            invalidatePlanningQueries(project);
            setSelectedPlanId(created.id);
            setAiDraftOpen(false);
          }}
        />
      )}
    </>
  );
}

function PlanDetail({ project, plan }: { project: string; plan: Plan }) {
  const [editing, setEditing] = useState(false);
  const [draftTitle, setDraftTitle] = useState(plan.title);
  const [draftGoal, setDraftGoal] = useState(plan.goal);
  useEffect(() => {
    setDraftTitle(plan.title);
    setDraftGoal(plan.goal);
  }, [plan.id, plan.title, plan.goal]);

  const updatePlanMutation = useUpdatePlan();
  const archivePlanMutation = useArchivePlan();
  const activatePlanMutation = useActivatePlan();
  const completePlanMutation = useCompletePlan();

  const saveEdit = () => {
    const kwargs: { title?: string; goal?: string } = {};
    if (draftTitle.trim() && draftTitle !== plan.title) kwargs.title = draftTitle.trim();
    if (draftGoal.trim() && draftGoal !== plan.goal) kwargs.goal = draftGoal.trim();
    if (Object.keys(kwargs).length === 0) {
      setEditing(false);
      return;
    }
    updatePlanMutation.mutate(
      { project, planId: plan.id, data: kwargs },
      {
        onSuccess: () => {
          invalidatePlanningQueries(project);
          setEditing(false);
          notify('Plan updated');
        },
        onError: (err) => notifyError('Update plan', err),
      },
    );
  };

  const runLifecycle = (
    mutation: typeof archivePlanMutation | typeof activatePlanMutation | typeof completePlanMutation,
    label: string,
  ) => {
    mutation.mutate(
      { project, planId: plan.id },
      {
        onSuccess: () => {
          invalidatePlanningQueries(project);
          notify(label);
        },
        onError: (err) => notifyError(label, err),
      },
    );
  };

  const [readyOnly, setReadyOnly] = useState(false);
  const now = useMemo(() => new Date(), [plan.updated_at]);
  const visibleTasks = readyOnly ? filterReadyTasks(plan.tasks, plan.status, now) : plan.tasks;

  const [addTaskOpen, setAddTaskOpen] = useState(false);
  const [taskLocalId, setTaskLocalId] = useState('');
  const [taskTitle, setTaskTitle] = useState('');
  const [taskObjective, setTaskObjective] = useState('');
  const addTaskMutation = useAddPlanTask();
  const addTask = () => {
    if (!taskLocalId.trim() || !taskTitle.trim() || !taskObjective.trim()) {
      notifyError('Add task', new Error('Local id, title, and objective are all required.'));
      return;
    }
    addTaskMutation.mutate(
      { project, planId: plan.id, data: { local_task_id: taskLocalId.trim(), title: taskTitle.trim(), objective: taskObjective.trim() } },
      {
        onSuccess: () => {
          invalidatePlanningQueries(project);
          setTaskLocalId('');
          setTaskTitle('');
          setTaskObjective('');
          setAddTaskOpen(false);
          notify('Task added');
        },
        onError: (err) => notifyError('Add task', err),
      },
    );
  };

  const [depFrom, setDepFrom] = useState('');
  const [depOn, setDepOn] = useState('');
  const addDepMutation = useAddTaskDependency();
  const addDependency = () => {
    if (!depFrom || !depOn) {
      notifyError('Add dependency', new Error('Choose both tasks.'));
      return;
    }
    if (depFrom === depOn) {
      notifyError('Add dependency', new Error('A task cannot depend on itself.'));
      return;
    }
    addDepMutation.mutate(
      { project, planId: plan.id, data: { task_id: depFrom, depends_on_task_id: depOn } },
      {
        onSuccess: () => {
          invalidatePlanningQueries(project);
          setDepFrom('');
          setDepOn('');
          notify('Dependency added');
        },
        onError: (err) => notifyError('Add dependency', err),
      },
    );
  };

  const claimMutation = useClaimTask();
  const heartbeatMutation = useHeartbeatTask();
  const releaseMutation = useReleaseTask();
  const statusMutation = useSetTaskStatus();
  const completeMutation = useCompleteTask();
  const prepareMutation = usePreparePlanTaskPrompt();

  const [claimTarget, setClaimTarget] = useState<PlanTask | null>(null);
  const [historyTarget, setHistoryTarget] = useState<PlanTask | null>(null);
  const [busyTaskId, setBusyTaskId] = useState<string | null>(null);
  const [tokenVersion, setTokenVersion] = useState(0); // bumps to re-read localStorage after claim/release/409

  const submitClaim = (claimedBy: string, leaseSeconds: number) => {
    if (!claimTarget) return;
    const taskId = claimTarget.id;
    setBusyTaskId(taskId);
    claimMutation.mutate(
      { project, planId: plan.id, taskId, data: { claimed_by: claimedBy, lease_seconds: leaseSeconds } },
      {
        onSuccess: (result) => {
          setStoredToken(taskId, result.claim_token);
          setTokenVersion((v) => v + 1);
          invalidatePlanningQueries(project);
          setClaimTarget(null);
          setBusyTaskId(null);
          notify('Task claimed', `Lease held by ${claimedBy}.`);
        },
        onError: (err) => {
          setBusyTaskId(null);
          handlePlanningError('Claim task', err, taskId);
        },
      },
    );
  };

  const withToken = (taskId: string, action: string, run: (token: string) => void) => {
    const token = getStoredToken(taskId);
    if (!token) {
      notifyError(action, new Error('No local claim token for this task — claim or reclaim it first.'));
      return;
    }
    run(token);
  };

  const heartbeat = (task: PlanTask) => {
    withToken(task.id, 'Extend lease', (token) => {
      setBusyTaskId(task.id);
      heartbeatMutation.mutate(
        { project, planId: plan.id, taskId: task.id, data: { claim_token: token } },
        {
          onSuccess: () => {
            invalidatePlanningQueries(project);
            setBusyTaskId(null);
            notify('Lease extended');
          },
          onError: (err) => {
            setBusyTaskId(null);
            handlePlanningError('Extend lease', err, task.id);
            setTokenVersion((v) => v + 1);
          },
        },
      );
    });
  };

  const release = (task: PlanTask) => {
    withToken(task.id, 'Release task', (token) => {
      setBusyTaskId(task.id);
      releaseMutation.mutate(
        { project, planId: plan.id, taskId: task.id, data: { claim_token: token } },
        {
          onSuccess: () => {
            clearStoredToken(task.id);
            setTokenVersion((v) => v + 1);
            invalidatePlanningQueries(project);
            setBusyTaskId(null);
            notify('Task released');
          },
          onError: (err) => {
            setBusyTaskId(null);
            handlePlanningError('Release task', err, task.id);
            setTokenVersion((v) => v + 1);
          },
        },
      );
    });
  };

  const setStatus = (task: PlanTask, status: TaskStatus, reason?: string) => {
    withToken(task.id, 'Update task status', (token) => {
      setBusyTaskId(task.id);
      statusMutation.mutate(
        { project, planId: plan.id, taskId: task.id, data: { status, claim_token: token, reason } },
        {
          onSuccess: () => {
            invalidatePlanningQueries(project);
            setBusyTaskId(null);
            notify('Task status updated', status);
          },
          onError: (err) => {
            setBusyTaskId(null);
            handlePlanningError('Update task status', err, task.id);
            setTokenVersion((v) => v + 1);
          },
        },
      );
    });
  };

  const complete = (task: PlanTask) => {
    const token = getStoredToken(task.id) ?? undefined;
    setBusyTaskId(task.id);
    completeMutation.mutate(
      { project, planId: plan.id, taskId: task.id, data: { claim_token: token } },
      {
        onSuccess: () => {
          clearStoredToken(task.id);
          setTokenVersion((v) => v + 1);
          invalidatePlanningQueries(project);
          setBusyTaskId(null);
          notify('Task completed');
        },
        onError: (err) => {
          setBusyTaskId(null);
          handlePlanningError('Complete task', err, task.id);
          setTokenVersion((v) => v + 1);
        },
      },
    );
  };

  const copyPrompt = async (task: PlanTask) => {
    setBusyTaskId(task.id);
    prepareMutation.mutate(
      { project, data: { task_id: task.id } },
      {
        onSuccess: async (result) => {
          try {
            await navigator.clipboard.writeText(result.prompt);
            notify('Copied', `Agent handoff prompt for ${task.local_task_id} copied to clipboard.`);
          } catch (err) {
            notifyError('Copy agent prompt', err);
          } finally {
            setBusyTaskId(null);
          }
        },
        onError: (err) => {
          setBusyTaskId(null);
          notifyError('Prepare agent prompt', err);
        },
      },
    );
  };

  const progress = plan.tasks.length > 0 ? Math.round((plan.tasks.filter((t) => t.status === 'completed').length / plan.tasks.length) * 100) : 0;

  return (
    <div className="space-y-5">
      <section className="rounded-lg border border-[#d8dcd5] bg-[#faf9f4] p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            {editing ? (
              <div className="space-y-2">
                <Field testId="input-edit-plan-title" label="Title" value={draftTitle} onChange={setDraftTitle} />
                <Field testId="input-edit-plan-goal" label="Goal" value={draftGoal} onChange={setDraftGoal} />
              </div>
            ) : (
              <>
                <div className="flex flex-wrap items-center gap-2">
                  <h2 data-testid="text-plan-title" className="text-xl font-bold text-[#1e3036]">{plan.title}</h2>
                  <Badge tone={PLAN_STATUS_TONE[plan.status]} dot testId="badge-plan-status">{plan.status}</Badge>
                </div>
                <p className="mt-1 text-sm leading-6 text-[#69777c]">{plan.goal}</p>
              </>
            )}
          </div>
          <div className="flex flex-wrap gap-2">
            {editing ? (
              <>
                <Button testId="button-cancel-edit-plan" variant="quiet" size="sm" onClick={() => setEditing(false)}>Cancel</Button>
                <Button testId="button-save-edit-plan" size="sm" onClick={saveEdit} disabled={updatePlanMutation.isPending}>
                  {updatePlanMutation.isPending ? <Loader2 className="animate-spin" size={13} /> : <Check size={13} />}Save
                </Button>
              </>
            ) : (
              <Button testId="button-edit-plan" variant="secondary" size="sm" onClick={() => setEditing(true)}>Edit</Button>
            )}
            {plan.status === 'draft' && (
              <Button testId="button-activate-plan" variant="secondary" size="sm" onClick={() => runLifecycle(activatePlanMutation, 'Plan activated')} disabled={activatePlanMutation.isPending}><Play size={13} />Activate</Button>
            )}
            {plan.status === 'active' && (
              <Button testId="button-complete-plan" variant="secondary" size="sm" onClick={() => runLifecycle(completePlanMutation, 'Plan completed')} disabled={completePlanMutation.isPending}><Check size={13} />Complete</Button>
            )}
            {plan.status !== 'archived' && (
              <Button testId="button-archive-plan" variant="danger" size="sm" onClick={() => runLifecycle(archivePlanMutation, 'Plan archived')} disabled={archivePlanMutation.isPending}><Archive size={13} />Archive</Button>
            )}
          </div>
        </div>
        <div className="mt-4 h-2 overflow-hidden rounded-full bg-[#e3e6df]"><div className="h-full rounded-full bg-[#3155d8]" style={{ width: `${progress}%` }} /></div>
        <p className="mt-2 font-mono text-[11px] text-[#7d898d]">{progressLabel(plan)} tasks complete</p>
      </section>

      <section className="rounded-lg border border-[#d8dcd5] bg-[#faf9f4]">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#e4e6df] px-5 py-4">
          <div className="flex items-center gap-2"><ListTodo size={15} className="text-[#3155d8]" /><h3 className="text-sm font-bold">Tasks</h3></div>
          <div className="flex flex-wrap items-center gap-2">
            <label className="flex items-center gap-1.5 text-xs text-[#53646a]">
              <input data-testid="toggle-ready-tasks" type="checkbox" checked={readyOnly} onChange={(e) => setReadyOnly(e.target.checked)} />
              Ready tasks only
            </label>
            <Button testId="button-toggle-add-task" size="sm" variant="secondary" onClick={() => setAddTaskOpen((v) => !v)}><Plus size={13} />Add task</Button>
          </div>
        </div>

        {addTaskOpen && (
          <div className="grid min-w-0 grid-cols-1 gap-3 border-b border-[#e4e6df] p-4 md:grid-cols-[.6fr_1fr_1.4fr_auto] md:items-end">
            <Field testId="input-task-local-id" label="Local id" value={taskLocalId} onChange={setTaskLocalId} placeholder="t1" />
            <Field testId="input-task-title" label="Title" value={taskTitle} onChange={setTaskTitle} placeholder="Add pricing helper" />
            <Field testId="input-task-objective" label="Objective" value={taskObjective} onChange={setTaskObjective} placeholder="What must be true when this is done?" />
            <Button testId="button-submit-add-task" onClick={addTask} disabled={addTaskMutation.isPending}>{addTaskMutation.isPending ? <Loader2 className="animate-spin" size={13} /> : <Plus size={13} />}Add</Button>
          </div>
        )}

        <div className="space-y-3 p-4">
          {visibleTasks.length === 0 && <p className="text-xs italic text-[#7d898d]">{plan.tasks.length === 0 ? 'No tasks yet.' : 'No ready tasks right now.'}</p>}
          {visibleTasks.map((task) => (
            <TaskCard
              key={`${task.id}-${tokenVersion}`}
              task={task}
              hasToken={!!getStoredToken(task.id)}
              busy={busyTaskId === task.id}
              now={now}
              onClaim={() => setClaimTarget(task)}
              onHeartbeat={() => heartbeat(task)}
              onRelease={() => release(task)}
              onSetStatus={(status, reason) => setStatus(task, status, reason)}
              onComplete={() => complete(task)}
              onCopyPrompt={() => copyPrompt(task)}
              onViewHistory={() => setHistoryTarget(task)}
            />
          ))}
        </div>
      </section>

      <section className="rounded-lg border border-[#d8dcd5] bg-[#faf9f4]">
        <div className="flex items-center justify-between border-b border-[#e4e6df] px-5 py-4">
          <div className="flex items-center gap-2"><GitBranch size={15} className="text-[#3155d8]" /><h3 className="text-sm font-bold">Dependencies</h3></div>
        </div>
        {plan.tasks.length >= 2 && (
          <div className="flex flex-wrap items-end gap-3 border-b border-[#e4e6df] p-4">
            <label className="min-w-0 max-w-full flex-1 text-xs font-semibold text-[#53646a]">Task
              <select data-testid="select-dependency-task" value={depFrom} onChange={(e) => setDepFrom(e.target.value)} className="mt-1.5 h-10 w-full max-w-full rounded-md border border-[#ccd4d1] bg-[#f1efe8] px-2 text-sm outline-none">
                <option value="">Choose…</option>
                {plan.tasks.map((t) => <option key={t.id} value={t.id}>{t.local_task_id} — {t.title}</option>)}
              </select>
            </label>
            <label className="min-w-0 max-w-full flex-1 text-xs font-semibold text-[#53646a]">Depends on
              <select data-testid="select-dependency-depends-on" value={depOn} onChange={(e) => setDepOn(e.target.value)} className="mt-1.5 h-10 w-full max-w-full rounded-md border border-[#ccd4d1] bg-[#f1efe8] px-2 text-sm outline-none">
                <option value="">Choose…</option>
                {plan.tasks.map((t) => <option key={t.id} value={t.id}>{t.local_task_id} — {t.title}</option>)}
              </select>
            </label>
            <Button testId="button-add-dependency" size="sm" onClick={addDependency} disabled={addDepMutation.isPending}>{addDepMutation.isPending ? <Loader2 className="animate-spin" size={13} /> : <Plus size={13} />}Add dependency</Button>
          </div>
        )}
        <DagView tasks={plan.tasks} selectedTaskId={historyTarget?.id ?? null} onSelect={(taskId) => setHistoryTarget(plan.tasks.find((t) => t.id === taskId) ?? null)} />
      </section>

      {claimTarget && (
        <ClaimModal
          taskLabel={`${claimTarget.local_task_id} — ${claimTarget.title}`}
          reclaim={claimTarget.status !== 'ready'}
          pending={claimMutation.isPending}
          onSubmit={submitClaim}
          onClose={() => setClaimTarget(null)}
        />
      )}
      {historyTarget && (
        <HistoryDrawer
          project={project}
          planId={plan.id}
          taskId={historyTarget.id}
          taskLabel={`${historyTarget.local_task_id} — ${historyTarget.title}`}
          onClose={() => setHistoryTarget(null)}
        />
      )}
    </div>
  );
}
