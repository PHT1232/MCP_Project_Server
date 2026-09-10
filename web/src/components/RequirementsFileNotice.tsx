import type { ReactNode } from "react";

import type { RequirementsFileSync } from "../api/types";
import { Callout } from "./Callout";

/**
 * AC14a — surface the `requirements_file` object returned by requirement writes:
 * any file `errors`, and any `reconciliations` the store applied.
 */
export function RequirementsFileNotice({
  sync,
}: {
  sync: RequirementsFileSync | undefined;
}): ReactNode {
  if (sync === undefined) {
    return null;
  }
  const hasErrors = sync.errors.length > 0;
  const hasNotes = sync.reconciliations.length > 0;
  if (!hasErrors && !hasNotes) {
    return null;
  }
  return (
    <div className="flex flex-col gap-8">
      {hasErrors && (
        <Callout tone="alert" title="Requirements file errors">
          <ul className="flex flex-col gap-4">
            {sync.errors.map((err) => (
              <li key={err}>{err}</li>
            ))}
          </ul>
        </Callout>
      )}
      {hasNotes && (
        <Callout tone="muted" title="Reconciled with the file">
          <ul className="flex flex-col gap-4">
            {sync.reconciliations.map((note) => (
              <li key={`${note.req_key}:${note.message}`}>
                <span className="text-fey-mist">{note.req_key}</span> — {note.message}
              </li>
            ))}
          </ul>
        </Callout>
      )}
    </div>
  );
}
