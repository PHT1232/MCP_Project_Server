import type { ReactNode } from "react";

import type { CodeMap, SourceFile } from "../api/types";
import type { MergedNode, RelatedEntry } from "../lib/codemap";
import { errorText } from "../lib/errors";
import { Callout } from "./Callout";
import { Card } from "./Card";
import { SourceView } from "./SourceView";
import { StatusBadge, type BadgeTone } from "./StatusBadge";
import { Caption, SectionTitle } from "./Typography";

interface QueryLike<T> {
  data: T | undefined;
  isPending: boolean;
  isError: boolean;
  error: unknown;
}

interface NodeInspectorProps {
  node: MergedNode;
  fileScope: QueryLike<CodeMap>;
  source: QueryLike<SourceFile>;
  related: RelatedEntry[];
  onLocatePath: (path: string) => void;
}

const OVERLAY_TONE: Record<string, BadgeTone> = {
  focus: "growth",
  blockers: "ember",
  bugs: "ember",
  requirements: "mist",
};

function humanBytes(bytes: number): string {
  if (bytes < 1024) {
    return `${String(bytes)} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function Meta({ label, value }: { label: string; value: string }): ReactNode {
  return (
    <div className="flex flex-col gap-4">
      <span className="text-caption uppercase text-fey-graphite">{label}</span>
      <span className="text-body text-fey-white">{value}</span>
    </div>
  );
}

function PathList({
  title,
  paths,
  onLocatePath,
}: {
  title: string;
  paths: readonly string[];
  onLocatePath: (path: string) => void;
}): ReactNode {
  return (
    <div className="flex flex-col gap-6">
      <Caption>
        {title} ({paths.length})
      </Caption>
      {paths.length === 0 ? (
        <p className="text-body text-fey-graphite">None.</p>
      ) : (
        <ul className="flex flex-col gap-4">
          {paths.map((path) => (
            <li key={path}>
              <button
                type="button"
                className="text-left text-body text-fey-mist underline-offset-2 hover:text-fey-white hover:underline"
                onClick={() => {
                  onLocatePath(path);
                }}
              >
                {path}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/**
 * FR34 / AC13 — the node inspector: path, language, static size, dependencies /
 * dependents, related context entries, and the read-only source. No git
 * activity (D11).
 */
export function NodeInspector({
  node,
  fileScope,
  source,
  related,
  onLocatePath,
}: NodeInspectorProps): ReactNode {
  const isFile = node.kind === "file";
  const scope = fileScope.data;

  return (
    <Card surface="elevated">
      <div className="flex flex-col gap-16">
        <div className="flex flex-col gap-8">
          <div className="flex flex-wrap items-center gap-8">
            <SectionTitle>{node.label}</SectionTitle>
            <StatusBadge tone="graphite">{node.kind}</StatusBadge>
            {node.outside_scope && <StatusBadge tone="graphite">boundary</StatusBadge>}
            {node.overlay.hot && <StatusBadge tone="ember">hot spot</StatusBadge>}
            {(["focus", "blockers", "bugs", "requirements"] as const).map((key) =>
              node.overlay[key] > 0 ? (
                <StatusBadge key={key} tone={OVERLAY_TONE[key] ?? "graphite"}>
                  {key} {node.overlay[key]}
                </StatusBadge>
              ) : null,
            )}
          </div>
          <p className="text-body text-fey-graphite">{node.path || "(repository root)"}</p>
        </div>

        <div className="grid gap-10 md:grid-cols-3">
          <Meta label="Language" value={node.language ?? "—"} />
          <Meta label="Lines (LOC)" value={String(node.loc)} />
          <Meta label="Size" value={humanBytes(node.size_bytes)} />
          <Meta label="Fan-in / out" value={`${String(node.fan_in)} / ${String(node.fan_out)}`} />
          {node.kind === "directory" ? (
            <Meta label="Files" value={String(node.file_count)} />
          ) : (
            <Meta label="Symbols" value={String(node.symbol_count)} />
          )}
        </div>

        {isFile && (
          <div className="flex flex-col gap-16">
            {fileScope.isError && (
              <Callout tone="alert">{errorText(fileScope.error)}</Callout>
            )}
            {fileScope.isPending && (
              <p className="text-body text-fey-graphite">Loading dependencies…</p>
            )}
            {scope !== undefined && (
              <>
                <div className="grid gap-16 md:grid-cols-2">
                  <PathList
                    title="Depends on"
                    paths={scope.dependencies ?? []}
                    onLocatePath={onLocatePath}
                  />
                  <PathList
                    title="Depended on by"
                    paths={scope.dependents ?? []}
                    onLocatePath={onLocatePath}
                  />
                </div>
                {scope.nodes.length > 0 && (
                  <div className="flex flex-col gap-6">
                    <Caption>Symbols ({scope.nodes.length})</Caption>
                    <ul className="flex flex-col gap-4">
                      {scope.nodes.map((symbol) => (
                        <li key={symbol.id} className="text-body text-fey-mist">
                          <span className="text-fey-white">{symbol.label}</span>
                          {symbol.signature !== undefined && symbol.signature !== null
                            ? ` — ${symbol.signature}`
                            : ""}
                          {symbol.start_line !== undefined && (
                            <span className="text-caption text-fey-graphite">
                              {" "}
                              L{symbol.start_line}
                            </span>
                          )}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </>
            )}
          </div>
        )}

        <div className="flex flex-col gap-8">
          <Caption>Related context ({related.length})</Caption>
          {related.length === 0 ? (
            <p className="text-body text-fey-graphite">
              No context entries link to this path.
            </p>
          ) : (
            <ul className="flex flex-col gap-8">
              {related.map(({ section, entry }) => (
                <li
                  key={entry.id}
                  className="flex flex-col gap-4 rounded-small border border-fey-smoke bg-fey-ink p-14"
                >
                  <span className="flex items-center gap-8">
                    <StatusBadge tone="graphite">{section}</StatusBadge>
                    <span className="text-body text-fey-white">{entry.headline}</span>
                  </span>
                  {entry.detail !== "" && entry.detail !== entry.headline && (
                    <span className="whitespace-pre-wrap text-body text-fey-mist">
                      {entry.detail}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>

        {isFile && (
          <div className="flex flex-col gap-8">
            <Caption>Source</Caption>
            {source.isError && <Callout tone="alert">{errorText(source.error)}</Callout>}
            {source.isPending && (
              <p className="text-body text-fey-graphite">Loading source…</p>
            )}
            {source.data !== undefined && (
              <>
                {source.data.truncated && (
                  <Caption>Truncated to the first 512 KB.</Caption>
                )}
                <SourceView
                  source={source.data.content}
                  language={source.data.language}
                />
              </>
            )}
          </div>
        )}
      </div>
    </Card>
  );
}
