import { useGetTaskHistory, type TaskEventType } from '@workspace/api-client-react';
import { Loader2, X } from 'lucide-react';
import { Badge, ErrorBanner, type Tone } from '../../App';

const EVENT_TONE: Record<TaskEventType, Tone> = {
  created: 'blue',
  updated: 'ink',
  dependency_added: 'ink',
  claimed: 'amber',
  reclaimed: 'amber',
  heartbeat: 'ink',
  released: 'ink',
  status_changed: 'blue',
  completed: 'mint',
  cancelled: 'red',
};

export interface HistoryDrawerProps {
  project: string;
  planId: string;
  taskId: string;
  taskLabel: string;
  onClose: () => void;
}

/** FR48/D21/INV-PLAN-4 — append-only task audit history, chronologically ordered. */
export function HistoryDrawer({ project, planId, taskId, taskLabel, onClose }: HistoryDrawerProps) {
  const historyQuery = useGetTaskHistory(project, planId, taskId);
  const events = historyQuery.data ?? [];

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-[#17292f]/40" onClick={onClose}>
      <div
        data-testid="drawer-task-history"
        className="flex h-full w-full max-w-md flex-col overflow-hidden border-l border-[#d8dcd5] bg-[#faf9f4] shadow-xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-[#e4e6df] px-5 py-4">
          <div>
            <p className="font-mono text-[10px] uppercase tracking-[.16em] text-[#7d898d]">Task history</p>
            <h2 className="mt-1 text-sm font-bold">{taskLabel}</h2>
          </div>
          <button data-testid="button-close-history" onClick={onClose} className="rounded p-1.5 text-[#879397] hover:bg-[#e8edff]"><X size={16} /></button>
        </div>
        <div className="flex-1 overflow-y-auto p-4">
          {historyQuery.isLoading && <div className="py-10 text-center"><Loader2 className="animate-spin mx-auto text-[#3155d8]" /></div>}
          {historyQuery.isError && (
            <ErrorBanner
              testId="banner-history-error"
              message={historyQuery.error instanceof Error ? historyQuery.error.message : 'Failed to load task history.'}
              onRetry={() => historyQuery.refetch()}
            />
          )}
          {!historyQuery.isLoading && events.length === 0 && <p className="text-xs italic text-[#7d898d]">No events recorded yet.</p>}
          <ol className="space-y-3">
            {events.map((event) => (
              <li key={event.id} data-testid={`history-event-${event.id}`} className="rounded-md border border-[#e4e6df] bg-[#eef0ea] p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone={EVENT_TONE[event.event_type]}>{event.event_type.replace(/_/g, ' ')}</Badge>
                  <span className="font-mono text-[10px] text-[#8a969a]">{new Date(event.created_at).toLocaleString()}</span>
                </div>
                <p className="mt-1.5 text-xs text-[#53646a]">
                  {event.actor}
                  {event.old_status && event.new_status && <span className="font-mono"> · {event.old_status} → {event.new_status}</span>}
                </p>
                {Object.keys(event.payload).length > 0 && (
                  <pre className="mt-2 overflow-auto rounded bg-[#f1efe8] p-2 font-mono text-[10px] leading-5 text-[#53646a] whitespace-pre-wrap">
                    {JSON.stringify(event.payload, null, 2)}
                  </pre>
                )}
              </li>
            ))}
          </ol>
        </div>
      </div>
    </div>
  );
}
