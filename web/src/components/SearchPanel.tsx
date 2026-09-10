import { useState, type ReactNode } from "react";

import type { SearchHit } from "../api/types";
import { useCodeSearch } from "../hooks/useCodeMap";
import { errorText } from "../lib/errors";
import { Callout } from "./Callout";
import { Field, TextInput } from "./fields";
import { PillButton } from "./PillButton";
import { StatusBadge } from "./StatusBadge";
import { Caption } from "./Typography";

interface SearchPanelProps {
  project: string;
  onLocateHit: (hit: SearchHit) => void;
}

/** FR35 — the code-search panel. A hit selects + locates its node on the map. */
export function SearchPanel({ project, onLocateHit }: SearchPanelProps): ReactNode {
  const [draft, setDraft] = useState("");
  const [query, setQuery] = useState("");
  const search = useCodeSearch(project, query);

  return (
    <div className="flex flex-col gap-14">
      <form
        className="flex items-end gap-10"
        onSubmit={(event) => {
          event.preventDefault();
          setQuery(draft.trim());
        }}
      >
        <div className="grow">
          <Field label="Search code">
            <TextInput
              value={draft}
              placeholder="function name, phrase, path…"
              onChange={(event) => {
                setDraft(event.target.value);
              }}
            />
          </Field>
        </div>
        <PillButton type="submit" disabled={draft.trim() === ""}>
          Search
        </PillButton>
      </form>

      {query !== "" && search.isPending && (
        <p className="text-body text-fey-graphite">Searching…</p>
      )}
      {search.isError && <Callout tone="alert">{errorText(search.error)}</Callout>}

      {search.data && (
        <div className="flex flex-col gap-10">
          {search.data.note !== undefined && search.data.note !== null && (
            <Caption>{search.data.note}</Caption>
          )}
          {search.data.hits.length === 0 ? (
            <p className="text-body text-fey-graphite">No matches.</p>
          ) : (
            <ul className="flex flex-col gap-8">
              {search.data.hits.map((hit, index) => (
                <li key={`${hit.path}:${String(hit.start_line)}:${String(index)}`}>
                  <button
                    type="button"
                    onClick={() => {
                      onLocateHit(hit);
                    }}
                    className="flex w-full flex-col gap-6 rounded-small border border-fey-smoke bg-fey-obsidian p-14 text-left transition-colors hover:border-fey-mist"
                  >
                    <span className="flex flex-wrap items-center gap-8">
                      <span className="text-body text-fey-white">{hit.path}</span>
                      <span className="text-caption text-fey-graphite">
                        L{hit.start_line}–{hit.end_line}
                      </span>
                      <StatusBadge tone="graphite">{hit.matched_mode}</StatusBadge>
                      {hit.stale && <StatusBadge tone="ember">stale</StatusBadge>}
                      <span className="text-caption text-fey-graphite">
                        score {hit.score.toFixed(2)}
                      </span>
                    </span>
                    {hit.snippet !== "" && (
                      <span className="block max-h-[8rem] overflow-hidden whitespace-pre-wrap text-caption text-fey-mist">
                        {hit.snippet}
                      </span>
                    )}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
