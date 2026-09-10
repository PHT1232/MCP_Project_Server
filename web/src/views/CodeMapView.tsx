import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";

import type { Entry, SearchHit } from "../api/types";
import { Callout } from "../components/Callout";
import { Card } from "../components/Card";
import { CodeMapDocument } from "../components/CodeMapDocument";
import { NodeInspector } from "../components/NodeInspector";
import { SearchPanel } from "../components/SearchPanel";
import { Caption, SectionTitle } from "../components/Typography";
import { useSection } from "../hooks/useSections";
import {
  fetchCodeMapScope,
  useCodeMap,
  useCodeMapDoc,
  useFileScope,
  useSource,
} from "../hooks/useCodeMap";
import {
  emptyGraph,
  locateHit,
  mergeCodeMap,
  relatedEntries,
  type CodeGraph as CodeGraphModel,
  type MergedNode,
} from "../lib/codemap";
import { buildCodeMapDoc, hotSpotsFromEntries } from "../lib/codemapDoc";
import { errorText } from "../lib/errors";
import { projectRoute } from "../routes";
import { Link } from "../router/router";

const SUBTREE_DEPTH = 2;

/** FR32–FR35 — the code map as a read-down document, plus inspector and search. */
export function CodeMapView({ project }: { project: string }): ReactNode {
  const queryClient = useQueryClient();
  const root = useCodeMap(project);
  const detail = useCodeMapDoc(project);
  const [graph, setGraph] = useState<CodeGraphModel>(() => emptyGraph());
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [expandError, setExpandError] = useState<string | null>(null);

  // Re-seed from the (single) top-tier query. A manual refresh (FR38) re-pulls
  // only this query; expansions are re-opened as the user clicks paths.
  useEffect(() => {
    if (root.data !== undefined) {
      setGraph(mergeCodeMap(emptyGraph(), root.data));
    }
  }, [root.data]);

  const selectedNode: MergedNode | undefined =
    selectedId === null ? undefined : graph.nodes.get(selectedId);
  const selectedPath = selectedNode?.kind === "file" ? selectedNode.path : null;

  const fileScope = useFileScope(project, selectedPath);
  const source = useSource(project, selectedPath);

  // Reuse T06's section data for the document + the inspector's related context.
  const overviewSection = useSection(project, "overview");
  const focusSection = useSection(project, "focus");
  const blockersSection = useSection(project, "blockers");
  const bugsSection = useSection(project, "bugs");
  const conventionsSection = useSection(project, "conventions");
  const decisionsSection = useSection(project, "decisions");
  const entriesBySection: Record<string, Entry[]> = {
    focus: focusSection.data?.entries ?? [],
    blockers: blockersSection.data?.entries ?? [],
    bugs: bugsSection.data?.entries ?? [],
    conventions: conventionsSection.data?.entries ?? [],
    decisions: decisionsSection.data?.entries ?? [],
  };
  const related =
    selectedNode === undefined
      ? []
      : relatedEntries(entriesBySection, selectedNode.path);

  const overviewEntry = overviewSection.data?.entries.find(
    (item) => item.status === "open",
  );
  const overviewText =
    overviewEntry === undefined
      ? null
      : overviewEntry.detail !== "" && overviewEntry.detail !== overviewEntry.headline
        ? `${overviewEntry.headline}\n\n${overviewEntry.detail}`
        : overviewEntry.headline;
  const doc = useMemo(
    () =>
      root.data === undefined
        ? null
        : buildCodeMapDoc(root.data, detail.data, { overview: overviewText }),
    [root.data, detail.data, overviewText],
  );
  const hotSpots = useMemo(
    () =>
      hotSpotsFromEntries(
        blockersSection.data?.entries ?? [],
        bugsSection.data?.entries ?? [],
      ),
    [blockersSection.data, bugsSection.data],
  );

  const locate = useCallback(
    async (filePath: string): Promise<void> => {
      let current = graph;
      for (let step = 0; step < 5; step += 1) {
        const result = locateHit(current, filePath);
        if (result.kind === "node") {
          setSelectedId(result.nodeId);
          return;
        }
        if (result.kind === "unreachable") {
          setExpandError(`"${filePath}" is not in the current map.`);
          return;
        }
        const map = await fetchCodeMapScope(
          queryClient,
          project,
          result.scope,
          SUBTREE_DEPTH,
        );
        current = mergeCodeMap(current, map);
        setGraph(current);
      }
    },
    [graph, project, queryClient],
  );

  const onSelectPath = useCallback(
    (path: string) => {
      setBusy(true);
      setExpandError(null);
      void locate(path)
        .catch((error: unknown) => {
          setExpandError(errorText(error));
        })
        .finally(() => {
          setBusy(false);
        });
    },
    [locate],
  );

  const onLocateHit = useCallback(
    (hit: SearchHit) => {
      onSelectPath(hit.path);
    },
    [onSelectPath],
  );

  if (root.isPending) {
    return (
      <Card>
        <p className="text-body text-fey-graphite">Loading the code map…</p>
      </Card>
    );
  }
  if (!root.isSuccess) {
    return (
      <Card>
        <Callout tone="alert">{errorText(root.error)}</Callout>
      </Card>
    );
  }
  if (!root.data.generated_from.indexed) {
    return (
      <Card>
        <div className="flex flex-col gap-16">
          <SectionTitle>Code map</SectionTitle>
          <Callout tone="muted" title="Not indexed yet">
            This project has no code index, so there is nothing to map. Build one
            from the{" "}
            <Link
              to={projectRoute(project, "index")}
              className="text-fey-mist underline underline-offset-2"
            >
              Index
            </Link>{" "}
            view, then refresh.
          </Callout>
        </div>
      </Card>
    );
  }

  const provenance = root.data.generated_from;

  return (
    <div className="flex flex-col gap-24">
      <Card>
        <div className="flex flex-col gap-16">
          <div className="flex flex-col gap-4">
            <SectionTitle>Code map</SectionTitle>
            <Caption>
              {String(doc?.totalFiles ?? root.data.stats.total_files ?? 0)} files
              {doc !== null && doc.languages.length > 0
                ? ` · ${doc.languages.join(", ")}`
                : ""}
              {provenance.last_commit !== undefined && provenance.last_commit !== null
                ? ` · @ ${provenance.last_commit.slice(0, 10)}`
                : ""}
            </Caption>
            <p className="text-caption text-fey-graphite">
              A low-resolution written map of the codebase. Click any path to open
              it in the inspector below.
            </p>
          </div>

          {(busy || detail.isPending) && <Caption>Loading…</Caption>}
          {expandError !== null && <Callout tone="alert">{expandError}</Callout>}

          {doc !== null && (
            <CodeMapDocument
              doc={doc}
              hotSpots={hotSpots}
              legend={root.data.overlay_legend}
              onSelectPath={onSelectPath}
            />
          )}
        </div>
      </Card>

      {selectedNode !== undefined && (
        <NodeInspector
          node={selectedNode}
          fileScope={fileScope}
          source={source}
          related={related}
          onLocatePath={(path) => {
            void locate(path);
          }}
        />
      )}

      <Card>
        <div className="flex flex-col gap-16">
          <SectionTitle>Search</SectionTitle>
          <SearchPanel project={project} onLocateHit={onLocateHit} />
        </div>
      </Card>
    </div>
  );
}
