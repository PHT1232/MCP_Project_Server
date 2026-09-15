import { useEffect, useRef, useState } from 'react';
import { Link } from 'wouter';
import { useCreatePlanWithTasks, useGeneratePlanDraft, type Plan, type PlanDraft } from '@workspace/api-client-react';
import { AlertCircle, Check, Loader2, Sparkles, X } from 'lucide-react';
import { Badge, Button, ErrorBanner, notify, notifyError } from '../../App';
import { DagView } from './DagView';
import { draftTasksToPlanTasks, draftToCreatePlanWithTasksInput } from '../../lib/planDraft';

const GOAL_MAX_CHARS = 4000;
const CONSTRAINTS_MAX_CHARS = 2000;
const MAX_TASKS_MIN = 1;
const MAX_TASKS_MAX = 30;
const MAX_TASKS_DEFAULT = 10;

export interface AiPlanDraftModalProps {
  project: string;
  onClose: () => void;
  onCreated: (plan: Plan) => void;
}

const FOCUSABLE_SELECTOR = 'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';

/**
 * T26's `generate_plan_draft` is strictly advisory and read-only (INV-PLAN-6)
 * — nothing here writes a row until "Review & Create" explicitly calls
 * `create_plan_with_tasks` (T23). Cancel/Discard/Escape/backdrop-click never
 * mutate anything.
 */
export function AiPlanDraftModal({ project, onClose, onCreated }: AiPlanDraftModalProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const previouslyFocused = useRef<Element | null>(null);

  useEffect(() => {
    previouslyFocused.current = document.activeElement;
    dialogRef.current?.focus();
    return () => {
      if (previouslyFocused.current instanceof HTMLElement) previouslyFocused.current.focus();
    };
  }, []);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key === 'Tab' && dialogRef.current) {
        const focusable = dialogRef.current.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR);
        if (focusable.length === 0) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [onClose]);

  const [step, setStep] = useState<'input' | 'preview'>('input');
  const [goal, setGoal] = useState('');
  const [constraints, setConstraints] = useState('');
  const [maxTasks, setMaxTasks] = useState(String(MAX_TASKS_DEFAULT));
  const [warning, setWarning] = useState<string | null>(null);
  const [draft, setDraft] = useState<PlanDraft | null>(null);
  const [provider, setProvider] = useState('');
  const [model, setModel] = useState('');

  const generateMutation = useGeneratePlanDraft();
  const createMutation = useCreatePlanWithTasks();

  // generator.py's unconfigured/unreachable-provider warnings both point the
  // caller at AI Settings; a malformed-draft warning does not.
  const showSettingsLink = warning?.includes('AI Settings') ?? false;

  const generate = () => {
    const trimmedGoal = goal.trim();
    if (!trimmedGoal) {
      notifyError('Generate plan draft', new Error('Goal is required.'));
      return;
    }
    const tasks = Number(maxTasks);
    if (!Number.isFinite(tasks) || tasks < MAX_TASKS_MIN || tasks > MAX_TASKS_MAX) {
      notifyError('Generate plan draft', new Error(`Max tasks must be between ${MAX_TASKS_MIN} and ${MAX_TASKS_MAX}.`));
      return;
    }
    setWarning(null);
    generateMutation.mutate(
      { project, data: { goal: trimmedGoal, constraints: constraints.trim() || undefined, max_tasks: tasks } },
      {
        onSuccess: (result) => {
          if (result.ok && result.draft) {
            setDraft(result.draft);
            setProvider(result.provider);
            setModel(result.model);
            setStep('preview');
          } else {
            setWarning(result.warning ?? 'The AI provider did not return a usable draft.');
          }
        },
        onError: (err) => notifyError('Generate plan draft', err),
      },
    );
  };

  const approve = () => {
    if (!draft) return;
    createMutation.mutate(
      { project, data: draftToCreatePlanWithTasksInput(draft) },
      {
        onSuccess: (plan) => {
          notify('Plan created', `${plan.title} — ${plan.tasks.length} task(s).`);
          onCreated(plan);
        },
        onError: (err) => notifyError('Create plan', err),
      },
    );
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#17292f]/40 p-4" onClick={onClose}>
      <div
        ref={dialogRef}
        data-testid="modal-ai-plan-draft"
        role="dialog"
        aria-modal="true"
        aria-labelledby="ai-draft-modal-title"
        tabIndex={-1}
        className="flex max-h-[90vh] w-full max-w-2xl flex-col overflow-hidden rounded-lg border border-[#d8dcd5] bg-[#faf9f4] shadow-xl outline-none"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-[#e4e6df] px-5 py-4">
          <div className="flex items-center gap-2">
            <Sparkles size={16} className="text-[#3155d8]" />
            <h2 id="ai-draft-modal-title" className="text-base font-bold">Generate plan with AI</h2>
          </div>
          <button data-testid="button-close-ai-draft-modal" onClick={onClose} className="rounded p-1.5 text-[#879397] hover:bg-[#e8edff]"><X size={16} /></button>
        </div>

        <div className="overflow-y-auto p-5">
          {step === 'input' && (
            <div className="space-y-4">
              <div>
                <label className="text-xs font-semibold text-[#53646a]" htmlFor="ai-draft-goal">Goal</label>
                <textarea
                  id="ai-draft-goal"
                  data-testid="textarea-ai-draft-goal"
                  value={goal}
                  onChange={(event) => setGoal(event.target.value.slice(0, GOAL_MAX_CHARS))}
                  placeholder="What should this plan accomplish?"
                  rows={4}
                  className="mt-1.5 w-full resize-y rounded-md border border-[#ccd4d1] bg-[#f1efe8] p-3 text-sm outline-none focus:border-[#3155d8]"
                />
                <p className="mt-1 text-right font-mono text-[10px] text-[#8a969a]">{goal.length} / {GOAL_MAX_CHARS}</p>
              </div>
              <div>
                <label className="text-xs font-semibold text-[#53646a]" htmlFor="ai-draft-constraints">Guidance / constraints (optional)</label>
                <textarea
                  id="ai-draft-constraints"
                  data-testid="textarea-ai-draft-constraints"
                  value={constraints}
                  onChange={(event) => setConstraints(event.target.value.slice(0, CONSTRAINTS_MAX_CHARS))}
                  placeholder="Anything the AI should keep in mind — existing conventions, files to avoid, sequencing preferences…"
                  rows={3}
                  className="mt-1.5 w-full resize-y rounded-md border border-[#ccd4d1] bg-[#f1efe8] p-3 text-sm outline-none focus:border-[#3155d8]"
                />
              </div>
              <label className="block text-xs font-semibold text-[#53646a]" htmlFor="ai-draft-max-tasks">
                Max tasks ({MAX_TASKS_MIN}–{MAX_TASKS_MAX})
                <div className="mt-1.5 flex items-center gap-3">
                  <input
                    id="ai-draft-max-tasks"
                    data-testid="slider-ai-draft-max-tasks"
                    type="range"
                    min={MAX_TASKS_MIN}
                    max={MAX_TASKS_MAX}
                    value={maxTasks}
                    onChange={(event) => setMaxTasks(event.target.value)}
                    className="flex-1"
                  />
                  <span className="w-8 text-right font-mono text-sm">{maxTasks}</span>
                </div>
              </label>

              {warning && (
                <div data-testid="banner-ai-draft-warning" className="flex items-start gap-3 rounded-md border border-[#e9c1bc] bg-[#f7e1dd] px-4 py-3 text-sm text-[#97433d]">
                  <AlertCircle size={17} className="mt-0.5 shrink-0" />
                  <div>
                    <p>{warning}</p>
                    {showSettingsLink && (
                      <Link href="/settings/ai" data-testid="link-ai-draft-settings" className="mt-1 inline-block font-semibold underline underline-offset-2">Open AI settings</Link>
                    )}
                  </div>
                </div>
              )}

              <div className="flex justify-end gap-2 border-t border-[#e4e6df] pt-4">
                <Button testId="button-cancel-ai-draft" variant="quiet" size="sm" onClick={onClose}>Cancel</Button>
                <Button testId="button-generate-ai-draft" size="sm" onClick={generate} disabled={generateMutation.isPending}>
                  {generateMutation.isPending ? <Loader2 className="animate-spin" size={14} /> : <Sparkles size={14} />}
                  {generateMutation.isPending ? 'Generating…' : 'Generate draft'}
                </Button>
              </div>
            </div>
          )}

          {step === 'preview' && draft && (
            <div className="space-y-4">
              <div data-testid="banner-ai-draft-advisory" className="flex items-start gap-3 rounded-md border border-[#cbd7f4] bg-[#e8edff] px-4 py-3 text-sm text-[#3047a8]">
                <Sparkles size={17} className="mt-0.5 shrink-0" />
                <div>
                  <p className="font-semibold">Unpersisted proposal — nothing has been saved yet.</p>
                  <p className="mt-1 text-xs text-[#4b5b96]">Generated by {provider} · {model}. Review below, then create the plan or discard it.</p>
                </div>
              </div>

              <div>
                <h3 data-testid="text-ai-draft-title" className="text-lg font-bold text-[#1e3036]">{draft.title}</h3>
                <p className="mt-1 text-sm leading-6 text-[#69777c]">{draft.goal}</p>
                {draft.notes && <p className="mt-2 rounded-md bg-[#eef0ea] p-2.5 text-xs italic text-[#69777c]">{draft.notes}</p>}
              </div>

              <div className="rounded-lg border border-[#d8dcd5]">
                <p className="border-b border-[#e4e6df] px-3 py-2 font-mono text-[10px] uppercase tracking-wide text-[#7d898d]">Proposed tasks ({draft.tasks.length})</p>
                <div className="divide-y divide-[#e4e6df]">
                  {draft.tasks.map((task) => (
                    <div key={task.local_task_id} data-testid={`row-ai-draft-task-${task.local_task_id}`} className="p-3">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-mono text-[10px] uppercase text-[#8a969a]">{task.local_task_id}</span>
                        <h4 className="text-sm font-bold text-[#1e3036]">{task.title}</h4>
                      </div>
                      <p className="mt-1 text-xs leading-5 text-[#69777c]">{task.objective}</p>
                      {task.acceptance_criteria.length > 0 && (
                        <ul className="mt-1.5 list-disc space-y-0.5 pl-4 text-xs text-[#53646a]">
                          {task.acceptance_criteria.map((criterion, index) => <li key={index}>{criterion}</li>)}
                        </ul>
                      )}
                      {(task.linked_files.length > 0 || task.requirement_ids.length > 0) && (
                        <div className="mt-1.5 flex flex-wrap gap-1.5">
                          {task.linked_files.map((file) => <Badge key={file} tone="ink">{file}</Badge>)}
                          {task.requirement_ids.map((id) => <Badge key={id} tone="blue">{id}</Badge>)}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>

              {draft.dependencies.length > 0 && (
                <div className="rounded-lg border border-[#d8dcd5]">
                  <p className="border-b border-[#e4e6df] px-3 py-2 font-mono text-[10px] uppercase tracking-wide text-[#7d898d]">Dependencies</p>
                  <DagView tasks={draftTasksToPlanTasks(draft)} selectedTaskId={null} onSelect={() => {}} />
                </div>
              )}

              {createMutation.isError && (
                <ErrorBanner
                  testId="banner-ai-draft-create-error"
                  message={createMutation.error instanceof Error ? createMutation.error.message : 'Failed to create the plan.'}
                  onRetry={approve}
                />
              )}

              <div className="flex justify-between gap-2 border-t border-[#e4e6df] pt-4">
                <Button testId="button-back-ai-draft" variant="quiet" size="sm" onClick={() => { setStep('input'); setDraft(null); }}>Back</Button>
                <div className="flex gap-2">
                  <Button testId="button-discard-ai-draft" variant="quiet" size="sm" onClick={onClose}>Discard</Button>
                  <Button testId="button-approve-ai-draft" size="sm" onClick={approve} disabled={createMutation.isPending}>
                    {createMutation.isPending ? <Loader2 className="animate-spin" size={14} /> : <Check size={14} />}
                    {createMutation.isPending ? 'Creating…' : 'Review & Create'}
                  </Button>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
