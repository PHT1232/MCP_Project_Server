import type { PlanTask, TaskStatus } from '@workspace/api-client-react';
import { Check, Clock, Copy, History, Link2, Loader2, PauseCircle, PlayCircle, RefreshCw, UserCircle2, XCircle } from 'lucide-react';
import { Badge, Button, type Tone } from '../../App';
import { RECLAIMABLE_STATUSES, isReclaimable, leaseState } from '../../lib/planTasks';

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

const STATUS_LABEL: Record<TaskStatus, string> = {
  pending: 'Pending',
  ready: 'Ready',
  claimed: 'Claimed',
  in_progress: 'In progress',
  blocked: 'Blocked',
  in_review: 'In review',
  completed: 'Completed',
  cancelled: 'Cancelled',
};

function formatCountdown(leaseExpiresAt: string, now: Date): string {
  const ms = new Date(leaseExpiresAt).getTime() - now.getTime();
  if (ms <= 0) {
    return 'Expired';
  }
  const totalMinutes = Math.floor(ms / 60000);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return hours > 0 ? `${hours}h ${minutes}m left` : `${minutes}m left`;
}

export interface TaskCardProps {
  task: PlanTask;
  hasToken: boolean;
  busy: boolean;
  now: Date;
  onClaim: () => void;
  onHeartbeat: () => void;
  onRelease: () => void;
  onSetStatus: (status: TaskStatus, reason?: string) => void;
  onComplete: () => void;
  onCopyPrompt: () => void;
  onViewHistory: () => void;
}

export function TaskCard({
  task,
  hasToken,
  busy,
  now,
  onClaim,
  onHeartbeat,
  onRelease,
  onSetStatus,
  onComplete,
  onCopyPrompt,
  onViewHistory,
}: TaskCardProps) {
  const lease = leaseState(task, now);
  const reclaimable = isReclaimable(task, now);
  const terminal = task.status === 'completed' || task.status === 'cancelled';
  const canClaimOrReclaim = task.status === 'ready' || reclaimable;
  // FR47: mutations on an active (unexpired) lease strictly require the local token.
  const managed = RECLAIMABLE_STATUSES.has(task.status) && lease === 'active';
  const canManage = managed && hasToken;
  const lockedNoToken = managed && !hasToken;
  const canComplete = !terminal && (canManage || lease !== 'active');

  const blockReason = () => {
    const reason = window.prompt('Reason for blocking this task (optional):');
    if (reason === null) return;
    onSetStatus('blocked', reason || undefined);
  };

  return (
    <div data-testid={`card-task-${task.id}`} className="rounded-lg border border-[#d8dcd5] bg-[#faf9f4] p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-[10px] uppercase tracking-wide text-[#8a969a]">{task.local_task_id}</span>
            <Badge testId={`badge-task-status-${task.id}`} tone={STATUS_TONE[task.status]} dot>{STATUS_LABEL[task.status]}</Badge>
            {lease === 'expired' && <Badge testId={`badge-task-lease-${task.id}`} tone="red">Expired - Reclaimable</Badge>}
            {lease === 'active' && task.lease_expires_at && (
              <Badge testId={`badge-task-lease-${task.id}`} tone="amber"><Clock size={11} />{formatCountdown(task.lease_expires_at, now)}</Badge>
            )}
          </div>
          <h4 className="mt-1.5 text-sm font-bold text-[#1e3036]">{task.title}</h4>
          <p className="mt-1 text-xs leading-5 text-[#69777c]">{task.objective}</p>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-[#7d898d]">
            {task.claimed_by && <span className="inline-flex items-center gap-1"><UserCircle2 size={12} />{task.claimed_by}</span>}
            {task.requirement_ids.map((id) => <Badge key={id} tone="blue">{id}</Badge>)}
            {task.dependencies.length > 0 && (
              <span className="inline-flex items-center gap-1 font-mono"><Link2 size={11} />depends on {task.dependencies.length}</span>
            )}
          </div>
        </div>
      </div>

      {lockedNoToken && (
        <p data-testid={`notice-task-locked-${task.id}`} className="mt-3 rounded-md border border-[#e9c1bc] bg-[#f7e1dd] px-2.5 py-1.5 text-[11px] text-[#97433d]">
          Active lease held by {task.claimed_by ?? 'another claimant'} — this browser has no valid claim token.
        </p>
      )}

      <div className="mt-3 flex flex-wrap gap-2">
        {canClaimOrReclaim && (
          <Button testId={`button-claim-${task.id}`} size="sm" variant="secondary" onClick={onClaim} disabled={busy}>
            {busy ? <Loader2 className="animate-spin" size={13} /> : <UserCircle2 size={13} />}
            {task.status === 'ready' ? 'Claim' : 'Reclaim'}
          </Button>
        )}
        {task.status === 'claimed' && canManage && (
          <Button testId={`button-start-${task.id}`} size="sm" variant="secondary" onClick={() => onSetStatus('in_progress')} disabled={busy}><PlayCircle size={13} />Start</Button>
        )}
        {task.status === 'in_progress' && canManage && (
          <Button testId={`button-send-to-review-${task.id}`} size="sm" variant="secondary" onClick={() => onSetStatus('in_review')} disabled={busy}><Check size={13} />Send to review</Button>
        )}
        {(task.status === 'claimed' || task.status === 'in_progress') && canManage && (
          <Button testId={`button-block-${task.id}`} size="sm" variant="quiet" onClick={blockReason} disabled={busy}><PauseCircle size={13} />Mark blocked</Button>
        )}
        {RECLAIMABLE_STATUSES.has(task.status) && canManage && (
          <Button testId={`button-heartbeat-${task.id}`} size="sm" variant="quiet" onClick={onHeartbeat} disabled={busy}><RefreshCw size={13} />Extend lease</Button>
        )}
        {RECLAIMABLE_STATUSES.has(task.status) && canManage && (
          <Button testId={`button-release-${task.id}`} size="sm" variant="quiet" onClick={onRelease} disabled={busy}><XCircle size={13} />Release</Button>
        )}
        {canComplete && (
          <Button testId={`button-complete-${task.id}`} size="sm" onClick={onComplete} disabled={busy}><Check size={13} />Complete</Button>
        )}
        <Button testId={`button-copy-prompt-${task.id}`} size="sm" variant="quiet" onClick={onCopyPrompt}><Copy size={13} />Copy agent prompt</Button>
        <Button testId={`button-history-${task.id}`} size="sm" variant="quiet" onClick={onViewHistory}><History size={13} />History</Button>
      </div>
    </div>
  );
}
