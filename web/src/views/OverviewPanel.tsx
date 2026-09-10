import { useState, type ReactNode } from "react";

import { Card } from "../components/Card";
import { Callout } from "../components/Callout";
import { EntryForm } from "../components/EntryForm";
import { PillButton } from "../components/PillButton";
import { SectionTitle } from "../components/Typography";
import { useEntryMutations, useSection } from "../hooks/useSections";
import { errorText } from "../lib/errors";

/**
 * FR36 — the project overview. There is exactly one overview entry (created at
 * registration); the dashboard edits it in place (no add / resolve).
 */
export function OverviewPanel({ project }: { project: string }): ReactNode {
  const [editing, setEditing] = useState(false);
  const query = useSection(project, "overview");
  const { update } = useEntryMutations(project);

  const entry = query.data?.entries.find((item) => item.status === "open");

  return (
    <Card>
      <div className="flex flex-col gap-16">
        <div className="flex items-start justify-between gap-16">
          <SectionTitle>Overview</SectionTitle>
          {entry !== undefined && !editing && (
            <PillButton
              size="sm"
              onClick={() => {
                setEditing(true);
              }}
            >
              Edit
            </PillButton>
          )}
        </div>

        {query.isPending ? (
          <p className="text-body text-fey-graphite">Loading…</p>
        ) : query.isError ? (
          <Callout tone="alert">{errorText(query.error)}</Callout>
        ) : entry === undefined ? (
          <p className="text-body text-fey-graphite">
            No overview recorded. Agents set this via `update_overview`.
          </p>
        ) : editing ? (
          <EntryForm
            initialHeadline={entry.headline}
            initialDetail={entry.detail}
            submitLabel="Save overview"
            pending={update.isPending}
            onSubmit={(input) => {
              update.mutate(
                { section: "overview", entryId: entry.id, input },
                { onSuccess: () => { setEditing(false); } },
              );
            }}
            onCancel={() => { setEditing(false); }}
          />
        ) : (
          <div className="flex flex-col gap-8">
            <p className="text-body font-medium text-fey-white">
              {entry.headline}
            </p>
            {entry.detail !== "" && entry.detail !== entry.headline && (
              <p className="whitespace-pre-wrap text-body text-fey-mist">
                {entry.detail}
              </p>
            )}
          </div>
        )}

        {update.isError && (
          <Callout tone="alert">{errorText(update.error)}</Callout>
        )}
      </div>
    </Card>
  );
}
