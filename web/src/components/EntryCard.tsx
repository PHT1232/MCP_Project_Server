import { useState, type ReactNode } from "react";

import type { Entry, EntryInput } from "../api/types";
import { EntryForm } from "./EntryForm";
import { PillButton } from "./PillButton";
import { StatusBadge } from "./StatusBadge";

interface EntryCardProps {
  entry: Entry;
  updating: boolean;
  resolving: boolean;
  onUpdate: (input: EntryInput) => void;
  onResolve: () => void;
}

function formatWhen(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString();
}

/** One context entry with inline edit + resolve (FR36). */
export function EntryCard({
  entry,
  updating,
  resolving,
  onUpdate,
  onResolve,
}: EntryCardProps): ReactNode {
  const [editing, setEditing] = useState(false);
  const resolved = entry.status !== "open";

  return (
    <div className="rounded-small border border-fey-smoke bg-fey-obsidian p-16">
      {editing ? (
        <EntryForm
          initialHeadline={entry.headline}
          initialDetail={entry.detail}
          submitLabel="Save changes"
          pending={updating}
          onSubmit={(input) => {
            onUpdate(input);
            setEditing(false);
          }}
          onCancel={() => {
            setEditing(false);
          }}
        />
      ) : (
        <div className="flex flex-col gap-8">
          <div className="flex items-start justify-between gap-16">
            <p className="text-body font-medium text-fey-white">{entry.headline}</p>
            {resolved && <StatusBadge tone="graphite">Resolved</StatusBadge>}
          </div>
          {entry.detail !== "" && entry.detail !== entry.headline && (
            <p className="whitespace-pre-wrap text-body text-fey-mist">
              {entry.detail}
            </p>
          )}
          {entry.linked_files.length > 0 && (
            <p className="text-caption text-fey-graphite">
              {entry.linked_files.join(" · ")}
            </p>
          )}
          <p className="text-caption uppercase text-fey-graphite">
            {entry.author} · {formatWhen(entry.updated_at)}
          </p>
          {!resolved && (
            <div className="flex gap-10">
              <PillButton
                size="sm"
                onClick={() => {
                  setEditing(true);
                }}
              >
                Edit
              </PillButton>
              <PillButton size="sm" onClick={onResolve} disabled={resolving}>
                {resolving ? "Resolving…" : "Resolve"}
              </PillButton>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
