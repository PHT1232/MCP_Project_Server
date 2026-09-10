import { useEffect, useState, type ReactNode } from "react";

import { Card } from "../components/Card";
import { Callout } from "../components/Callout";
import { PillButton } from "../components/PillButton";
import { SectionTitle } from "../components/Typography";
import { TextArea } from "../components/fields";
import { useSetFocus } from "../hooks/useFocus";
import { useSection } from "../hooks/useSections";
import { errorText } from "../lib/errors";

/**
 * FR36 / S-T06 — the current focus, edited with `set_current_focus`
 * replace-semantics: saving supersedes the prior focus rather than appending.
 */
export function FocusPanel({ project }: { project: string }): ReactNode {
  const query = useSection(project, "focus");
  const setFocus = useSetFocus(project);

  const current = query.data?.entries.find((entry) => entry.status === "open");
  const currentText = current?.detail ?? "";
  const [draft, setDraft] = useState(currentText);

  useEffect(() => {
    setDraft(currentText);
  }, [currentText]);

  const dirty = draft.trim() !== currentText.trim();

  return (
    <Card>
      <div className="flex flex-col gap-16">
        <div className="flex flex-col gap-4">
          <SectionTitle>Current focus</SectionTitle>
          <p className="text-body text-fey-graphite">
            One active focus per project. Saving replaces the previous focus.
          </p>
        </div>

        {query.isError ? (
          <Callout tone="alert">{errorText(query.error)}</Callout>
        ) : (
          <form
            className="flex flex-col gap-14"
            onSubmit={(event) => {
              event.preventDefault();
              if (!dirty || setFocus.isPending) {
                return;
              }
              setFocus.mutate(draft.trim());
            }}
          >
            <TextArea
              value={draft}
              rows={3}
              placeholder="What the team is working on right now"
              onChange={(event) => {
                setDraft(event.target.value);
              }}
            />
            <div className="flex items-center gap-10">
              <PillButton
                type="submit"
                size="sm"
                disabled={!dirty || setFocus.isPending}
              >
                {setFocus.isPending ? "Saving…" : "Set focus"}
              </PillButton>
              {current !== undefined && (
                <span className="text-caption uppercase text-fey-graphite">
                  updated {new Date(current.updated_at).toLocaleString()}
                </span>
              )}
            </div>
            {setFocus.isError && (
              <Callout tone="alert">{errorText(setFocus.error)}</Callout>
            )}
          </form>
        )}
      </div>
    </Card>
  );
}
