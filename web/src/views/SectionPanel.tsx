import { useState, type ReactNode } from "react";

import type { DashboardSection } from "../api/types";
import { Card } from "../components/Card";
import { EntryCard } from "../components/EntryCard";
import { EntryForm } from "../components/EntryForm";
import { Callout } from "../components/Callout";
import { PillButton } from "../components/PillButton";
import { SectionTitle } from "../components/Typography";
import { useEntryMutations, useSection } from "../hooks/useSections";
import { errorText } from "../lib/errors";

interface SectionPanelProps {
  project: string;
  section: DashboardSection;
  title: string;
  description: string;
}

/**
 * FR36 — a briefing section (blockers / bugs / conventions / decisions) with
 * create / update / resolve. Mirrors the MCP `add_* / update_* / resolve_*`
 * write tools, so an edit here is reflected in the next briefing (AC14).
 */
export function SectionPanel({
  project,
  section,
  title,
  description,
}: SectionPanelProps): ReactNode {
  const [adding, setAdding] = useState(false);
  const query = useSection(project, section);
  const { add, update, resolve } = useEntryMutations(project);

  const entries = query.data?.entries ?? [];

  return (
    <Card>
      <div className="flex flex-col gap-16">
        <div className="flex items-start justify-between gap-16">
          <div className="flex flex-col gap-4">
            <SectionTitle>{title}</SectionTitle>
            <p className="text-body text-fey-graphite">{description}</p>
          </div>
          <PillButton
            size="sm"
            onClick={() => {
              setAdding((value) => !value);
            }}
          >
            {adding ? "Close" : "Add"}
          </PillButton>
        </div>

        {adding && (
          <div className="rounded-small border border-fey-smoke bg-fey-obsidian p-16">
            <EntryForm
              submitLabel="Add entry"
              pending={add.isPending}
              onSubmit={(input) => {
                add.mutate(
                  { section, input: { ...input, section } },
                  { onSuccess: () => { setAdding(false); } },
                );
              }}
              onCancel={() => { setAdding(false); }}
            />
          </div>
        )}

        {add.isError && <Callout tone="alert">{errorText(add.error)}</Callout>}
        {update.isError && (
          <Callout tone="alert">{errorText(update.error)}</Callout>
        )}
        {resolve.isError && (
          <Callout tone="alert">{errorText(resolve.error)}</Callout>
        )}

        {query.isPending ? (
          <p className="text-body text-fey-graphite">Loading…</p>
        ) : query.isError ? (
          <Callout tone="alert">{errorText(query.error)}</Callout>
        ) : entries.length === 0 ? (
          <p className="text-body text-fey-graphite">Nothing recorded yet.</p>
        ) : (
          <ul className="flex flex-col gap-10">
            {entries.map((entry) => (
              <li key={entry.id}>
                <EntryCard
                  entry={entry}
                  updating={update.isPending}
                  resolving={resolve.isPending}
                  onUpdate={(input) => {
                    update.mutate({ section, entryId: entry.id, input });
                  }}
                  onResolve={() => {
                    resolve.mutate({ section, entryId: entry.id });
                  }}
                />
              </li>
            ))}
          </ul>
        )}
      </div>
    </Card>
  );
}
