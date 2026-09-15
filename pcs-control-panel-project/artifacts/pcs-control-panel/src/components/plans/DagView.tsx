import type { PlanTask, TaskStatus } from '@workspace/api-client-react';
import { ArrowRight } from 'lucide-react';
import { Badge, cx, type Tone } from '../../App';
import { layoutDag } from '../../lib/planTasks';

const STATUS_TONE: Record<TaskStatus, Tone> = {
  pending: 'ink',
  ready: 'blue',
  claimed: 'amber',
  in_progress: 'amber',
  blocked: 'red',
  in_review: 'blue',
  completed: 'mint',
  cancelled: 'ink',
};

export interface DagViewProps {
  tasks: readonly PlanTask[];
  selectedTaskId: string | null;
  onSelect: (taskId: string) => void;
}

/**
 * FR44/FR45 dependency visualizer — tasks laid out in left-to-right columns by
 * longest prerequisite-chain depth (`lib/planTasks.ts#layoutDag`), each chip
 * naming the local ids it is blocked on so prerequisite chains and blocking
 * relationships are legible without a graph-drawing library (out of scope).
 */
export function DagView({ tasks, selectedTaskId, onSelect }: DagViewProps) {
  if (tasks.length === 0) {
    return <p className="p-4 text-xs italic text-[#7d898d]">No tasks in this plan yet.</p>;
  }

  const layers = layoutDag(tasks);
  const byId = new Map(tasks.map((t) => [t.id, t] as const));

  return (
    <div data-testid="dag-view" className="flex gap-4 overflow-x-auto p-4">
      {layers.map((layer, layerIndex) => (
        <div key={layerIndex} className="flex min-w-[200px] shrink-0 flex-col gap-2">
          <p className="font-mono text-[10px] uppercase tracking-wide text-[#8a969a]">
            {layerIndex === 0 ? 'No prerequisites' : `Depth ${layerIndex}`}
          </p>
          {layer.map((task) => (
            <button
              key={task.id}
              type="button"
              data-testid={`dag-node-${task.id}`}
              onClick={() => onSelect(task.id)}
              className={cx(
                'rounded-md border px-2.5 py-2 text-left text-xs transition-colors',
                selectedTaskId === task.id ? 'border-[#3155d8] bg-[#e8edff]' : 'border-[#dfe3dc] bg-[#eef0ea] hover:border-[#b7c2c6]',
              )}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono text-[10px] text-[#7d898d]">{task.local_task_id}</span>
                <Badge tone={STATUS_TONE[task.status]}>{task.status}</Badge>
              </div>
              <p className="mt-1 truncate font-semibold text-[#1e3036]">{task.title}</p>
              {task.dependencies.length > 0 && (
                <p className="mt-1 flex flex-wrap items-center gap-1 font-mono text-[10px] text-[#8a969a]">
                  <ArrowRight size={10} />
                  {task.dependencies.map((depId) => byId.get(depId)?.local_task_id ?? depId).join(', ')}
                  {task.dependencies.some((depId) => byId.get(depId)?.status !== 'completed') && (
                    <span className="text-[#97433d]">(blocked)</span>
                  )}
                </p>
              )}
            </button>
          ))}
        </div>
      ))}
    </div>
  );
}
