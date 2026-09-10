import type { ReactNode } from "react";

import type { IndexStatus } from "../api/types";
import { Card } from "../components/Card";
import { Callout } from "../components/Callout";
import { PillButton } from "../components/PillButton";
import { StatusBadge } from "../components/StatusBadge";
import { SectionTitle } from "../components/Typography";
import { useIndexStatus, useReindex } from "../hooks/useIndexStatus";
import { errorText } from "../lib/errors";
import { semanticIndicator } from "../lib/semantic";

function when(iso: string | null): string {
  if (iso === null) {
    return "never";
  }
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString();
}

function Stat({ label, value }: { label: string; value: string }): ReactNode {
  return (
    <div className="flex flex-col gap-4 rounded-small border border-fey-smoke bg-fey-obsidian p-16">
      <span className="text-caption uppercase text-fey-graphite">{label}</span>
      <span className="text-heading-sm text-fey-white">{value}</span>
    </div>
  );
}

function SemanticIndicator({ status }: { status: IndexStatus }): ReactNode {
  const indicator = semanticIndicator(status);
  return (
    <div className="flex flex-col gap-8">
      <div className="flex items-center gap-10">
        <StatusBadge tone={indicator.available ? "growth" : "graphite"}>
          {indicator.available ? "Available" : "Unavailable"}
        </StatusBadge>
        <span className="text-body text-fey-white">{indicator.label}</span>
      </div>
      {indicator.note !== null && (
        <p className="text-body text-fey-graphite">{indicator.note}</p>
      )}
    </div>
  );
}

/** FR37 — index status panel + "reindex now" + semantic availability (AC21). */
export function IndexView({ project }: { project: string }): ReactNode {
  const query = useIndexStatus(project);
  const reindex = useReindex(project);
  const status = query.data;

  return (
    <div className="flex flex-col gap-24">
      <Card>
        <div className="flex flex-col gap-16">
          <div className="flex items-start justify-between gap-16">
            <SectionTitle>Code index</SectionTitle>
            <div className="flex gap-10">
              <PillButton
                size="sm"
                disabled={reindex.isPending}
                onClick={() => {
                  reindex.mutate({ incremental: true });
                }}
              >
                {reindex.isPending ? "Working…" : "Reindex now"}
              </PillButton>
              <PillButton
                size="sm"
                disabled={reindex.isPending}
                onClick={() => {
                  reindex.mutate({ incremental: false });
                }}
              >
                Full rebuild
              </PillButton>
            </div>
          </div>

          {reindex.isError && (
            <Callout tone="alert">{errorText(reindex.error)}</Callout>
          )}

          {query.isPending ? (
            <p className="text-body text-fey-graphite">Loading…</p>
          ) : query.isError || status === undefined ? (
            <Callout tone="alert">{errorText(query.error)}</Callout>
          ) : (
            <>
              <div className="grid gap-10 md:grid-cols-3">
                <Stat label="State" value={status.state} />
                <Stat label="Files" value={String(status.file_count)} />
                <Stat label="Chunks" value={String(status.chunk_count)} />
                <Stat label="Last full build" value={when(status.last_full_at)} />
                <Stat
                  label="Last incremental"
                  value={when(status.last_incremental_at)}
                />
                <Stat
                  label="Commit"
                  value={status.last_commit?.slice(0, 10) ?? "unknown"}
                />
              </div>

              <div className="flex flex-col gap-8">
                <SectionTitle>Semantic search</SectionTitle>
                <SemanticIndicator status={status} />
              </div>

              <div className="flex flex-col gap-8">
                <SectionTitle>
                  Skipped files ({status.skipped_count})
                </SectionTitle>
                {status.skipped.length === 0 ? (
                  <p className="text-body text-fey-graphite">
                    Nothing skipped.
                  </p>
                ) : (
                  <ul className="flex flex-col gap-4">
                    {status.skipped.map((item) => (
                      <li
                        key={item.path}
                        className="text-body text-fey-graphite"
                      >
                        <span className="text-fey-mist">{item.path}</span> —{" "}
                        {item.reason}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </>
          )}
        </div>
      </Card>
    </div>
  );
}
