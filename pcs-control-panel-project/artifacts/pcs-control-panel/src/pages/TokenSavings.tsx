import { useState } from 'react';
import { useParams } from 'wouter';
import {
  useGetTokenSavingsLog,
  useGetTokenSavingsSummary,
  type TokenSavingsOperation,
} from '@workspace/api-client-react';
import { Activity, Database, Loader2, Sparkles, Zap } from 'lucide-react';
import { Badge, combineQueryErrors, cx, ErrorBanner, PageHeader, ProjectTabs, type Tone } from '../App';
import { averageSavedPerCall, formatTokenCount, OPERATION_LABEL, savingsPercent, sortByImpact } from '../lib/tokenSavings';

const OPERATION_TONE: Record<TokenSavingsOperation, Tone> = {
  retrieve_context: 'blue',
  search_code: 'mint',
  prepare_task: 'amber',
  get_project_briefing: 'ink',
};

const OPERATION_FILTERS: Array<{ id: TokenSavingsOperation | 'all'; label: string }> = [
  { id: 'all', label: 'All' },
  { id: 'retrieve_context', label: OPERATION_LABEL.retrieve_context },
  { id: 'search_code', label: OPERATION_LABEL.search_code },
  { id: 'prepare_task', label: OPERATION_LABEL.prepare_task },
  { id: 'get_project_briefing', label: OPERATION_LABEL.get_project_briefing },
];

export default function TokenSavings() {
  const project = decodeURIComponent(useParams<{ project: string }>().project ?? '');
  const [operationFilter, setOperationFilter] = useState<TokenSavingsOperation | 'all'>('all');

  const summaryQuery = useGetTokenSavingsSummary(project);
  const logQuery = useGetTokenSavingsLog(project, {
    operation: operationFilter === 'all' ? undefined : operationFilter,
    limit: 100,
  });

  const summary = summaryQuery.data;
  const entries = logQuery.data ?? [];
  const byOperation = sortByImpact(summary?.by_operation ?? []);
  const loadError = combineQueryErrors(summaryQuery, logQuery);

  return (
    <>
      <PageHeader
        eyebrow="atlas-console / token savings"
        title="Token Savings"
        description="How many tokens retrieve_context, search_code, prepare_task, and get_project_briefing actually returned, versus what returning the full untruncated content would have cost."
        actions={
          summary ? (
            <Badge tone="mint" dot testId="status-token-savings">
              {formatTokenCount(summary.overall.saved_tokens_total)} tokens saved
            </Badge>
          ) : undefined
        }
      />
      <ProjectTabs active="token-savings" />
      {loadError.isError && <ErrorBanner testId="banner-token-savings-error" message={loadError.message} onRetry={loadError.retry} />}

      {summaryQuery.isLoading && <div className="py-10 text-center"><Loader2 className="animate-spin mx-auto text-[#3155d8]" /></div>}

      {summary && (
        <>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <div data-testid="stat-tokens-saved" className="rounded-lg border border-[#d9dcd5] bg-[#faf9f4] p-4 shadow-[0_1px_0_rgba(31,43,45,.04)]">
              <div className="flex items-start justify-between">
                <p className="text-[11px] font-semibold uppercase tracking-[.12em] text-[#758188]">Tokens saved</p>
                <span className="rounded p-1.5 bg-[#dcefe7] text-[#246a5a]"><Sparkles size={14} /></span>
              </div>
              <div className="mt-2 flex items-baseline gap-2">
                <strong className="font-mono text-2xl font-medium tracking-tight text-[#1e3036]">{formatTokenCount(summary.overall.saved_tokens_total)}</strong>
                <span className="text-xs text-[#78868b]">of {formatTokenCount(summary.overall.baseline_tokens_total)} baseline</span>
              </div>
            </div>
            <div data-testid="stat-savings-percent" className="rounded-lg border border-[#d9dcd5] bg-[#faf9f4] p-4 shadow-[0_1px_0_rgba(31,43,45,.04)]">
              <div className="flex items-start justify-between">
                <p className="text-[11px] font-semibold uppercase tracking-[.12em] text-[#758188]">Savings rate</p>
                <span className="rounded p-1.5 bg-[#e5e9ff] text-[#3047a8]"><Zap size={14} /></span>
              </div>
              <div className="mt-2 flex items-baseline gap-2">
                <strong className="font-mono text-2xl font-medium tracking-tight text-[#1e3036]">{savingsPercent(summary.overall)}%</strong>
                <span className="text-xs text-[#78868b]">vs. full content</span>
              </div>
            </div>
            <div data-testid="stat-calls-logged" className="rounded-lg border border-[#d9dcd5] bg-[#faf9f4] p-4 shadow-[0_1px_0_rgba(31,43,45,.04)]">
              <div className="flex items-start justify-between">
                <p className="text-[11px] font-semibold uppercase tracking-[.12em] text-[#758188]">Calls logged</p>
                <span className="rounded p-1.5 bg-[#f8edcf] text-[#856115]"><Activity size={14} /></span>
              </div>
              <div className="mt-2 flex items-baseline gap-2">
                <strong className="font-mono text-2xl font-medium tracking-tight text-[#1e3036]">{summary.overall.call_count}</strong>
              </div>
            </div>
            <div data-testid="stat-avg-saved" className="rounded-lg border border-[#d9dcd5] bg-[#faf9f4] p-4 shadow-[0_1px_0_rgba(31,43,45,.04)]">
              <div className="flex items-start justify-between">
                <p className="text-[11px] font-semibold uppercase tracking-[.12em] text-[#758188]">Avg saved / call</p>
                <span className="rounded p-1.5 bg-[#e3e7e8] text-[#33454b]"><Database size={14} /></span>
              </div>
              <div className="mt-2 flex items-baseline gap-2">
                <strong className="font-mono text-2xl font-medium tracking-tight text-[#1e3036]">{formatTokenCount(averageSavedPerCall(summary.overall))}</strong>
              </div>
            </div>
          </div>

          {byOperation.length > 0 && (
            <section className="mt-5 rounded-lg border border-[#d8dcd5] bg-[#faf9f4]">
              <div className="border-b border-[#e4e6df] px-5 py-4">
                <p className="font-mono text-[10px] uppercase tracking-[.16em] text-[#7d898d]">Breakdown</p>
                <h2 className="mt-1 text-base font-bold">Savings by operation</h2>
              </div>
              <div className="space-y-3 p-5">
                {byOperation.map((op) => {
                  const key = op.operation as TokenSavingsOperation;
                  const pct = savingsPercent(op);
                  return (
                    <div key={op.operation ?? 'unknown'} data-testid={`row-operation-${op.operation}`}>
                      <div className="flex items-center justify-between text-xs">
                        <span className="flex items-center gap-2 font-semibold text-[#1e3036]">
                          <Badge tone={OPERATION_TONE[key]} dot>{OPERATION_LABEL[key] ?? op.operation}</Badge>
                          <span className="text-[#7d898d]">{op.call_count} call{op.call_count === 1 ? '' : 's'}</span>
                        </span>
                        <span className="font-mono text-[#53646a]">{formatTokenCount(op.saved_tokens_total)} saved · {pct}%</span>
                      </div>
                      <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-[#e3e6df]">
                        <div className="h-full rounded-full bg-[#3155d8]" style={{ width: `${pct}%` }} />
                      </div>
                    </div>
                  );
                })}
              </div>
            </section>
          )}
        </>
      )}

      <section className="mt-5 rounded-lg border border-[#d8dcd5] bg-[#faf9f4]">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#e4e6df] px-5 py-4">
          <div>
            <p className="font-mono text-[10px] uppercase tracking-[.16em] text-[#7d898d]">Log</p>
            <h2 className="mt-1 text-base font-bold">Recent calls</h2>
          </div>
        </div>
        <div className="flex items-center gap-1 overflow-x-auto border-b border-[#e4e6df] px-3 py-2">
          {OPERATION_FILTERS.map(({ id, label }) => (
            <button
              key={id}
              data-testid={`filter-operation-${id}`}
              onClick={() => setOperationFilter(id)}
              className={cx(
                'flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-md px-2.5 py-1.5 text-xs font-semibold transition-colors',
                operationFilter === id ? 'bg-[#e5e9ff] text-[#3047a8]' : 'text-[#758187] hover:bg-[#eef0ea] hover:text-[#34464c]',
              )}
            >
              {label}
            </button>
          ))}
        </div>
        {logQuery.isLoading && <div className="py-10 text-center"><Loader2 className="animate-spin mx-auto text-[#3155d8]" /></div>}
        {!logQuery.isLoading && entries.length === 0 && (
          <p className="p-5 text-sm text-[#7d898d]">No calls logged yet for this filter. Entries appear here after retrieve_context, search_code, prepare_task, or get_project_briefing is called by an agent or the UI.</p>
        )}
        {entries.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-[#e4e6df] text-[10px] uppercase tracking-wide text-[#7d898d]">
                  <th className="px-5 py-2 font-semibold">Operation</th>
                  <th className="px-3 py-2 font-semibold">Caller</th>
                  <th className="px-3 py-2 font-semibold text-right">Actual</th>
                  <th className="px-3 py-2 font-semibold text-right">Baseline</th>
                  <th className="px-3 py-2 font-semibold text-right">Saved</th>
                  <th className="px-5 py-2 font-semibold text-right">When</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#e4e6df]">
                {entries.map((entry) => (
                  <tr key={entry.id} data-testid={`row-log-entry-${entry.id}`}>
                    <td className="px-5 py-2.5">
                      <Badge tone={OPERATION_TONE[entry.operation]} dot>{OPERATION_LABEL[entry.operation] ?? entry.operation}</Badge>
                    </td>
                    <td className="px-3 py-2.5 font-mono text-[#53646a]">{entry.caller}</td>
                    <td className="px-3 py-2.5 text-right font-mono text-[#53646a]">{formatTokenCount(entry.actual_tokens)}</td>
                    <td className="px-3 py-2.5 text-right font-mono text-[#53646a]">{formatTokenCount(entry.baseline_tokens)}</td>
                    <td className="px-3 py-2.5 text-right font-mono font-semibold text-[#246a5a]">{formatTokenCount(entry.saved_tokens)}</td>
                    <td className="px-5 py-2.5 text-right font-mono text-[10px] text-[#8a969a]">{new Date(entry.created_at).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}
