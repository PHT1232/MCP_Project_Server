import { useCallback, useEffect, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";

import type { Entry, SearchHit } from "../api/types";
import { Callout } from "../components/Callout";
import { Card } from "../components/Card";
import { CodeGraph, type GraphFilter } from "../components/CodeGraph";
import { CodeMapLegend } from "../components/CodeMapLegend";
import { NodeInspector } from "../components/NodeInspector";
import { Field, Select, TextInput } from "../components/fields";
import { PillButton } from "../components/PillButton";
import { SearchPanel } from "../components/SearchPanel";
import { Caption, SectionTitle } from "../components/Typography";
import { useSection } from "../hooks/useSections";
import {
  fetchCodeMapScope,
  useCodeMap,
  useFileScope,
  useSource,
} from "../hooks/useCodeMap";
import {
  emptyGraph,
  graphLanguages,
  locateHit,
  mergeCodeMap,
  relatedEntries,
  type CodeGraph as CodeGraphModel,
  type MergedNode,
} from "../lib/codemap";
import { errorText } from "../lib/errors";
import { projectRoute } from "../routes";
import { Link } from "../router/router";

const SUBTREE_DEPTH = 2;

/** FR32–FR35 — the interactive code map, node inspector and search panel. */
export function CodeMapView({ project }: { project: string }): ReactNode {
  const queryClient = useQueryClient();
  const root = useCodeMap(project);
  const [graph, setGraph] = useState<CodeGraphModel>(() => emptyGraph());
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [pathFilter, setPathFilter] = useState("");
  const [language, setLanguage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [expandError, setExpandError] = useState<string | null>(null);

  // Re-seed from the (single) top-tier query. A manual refresh (FR38) re-pulls
  // only this query; expansions are re-opened by the user.
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

  // Reuse T06's section data for the inspector's "related context" (FR34).
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

  const expand = useCallback(
    async (scope: string): Promise<CodeGraphModel> => {
      const map = await fetchCodeMapScope(queryClient, project, scope, SUBTREE_DEPTH);
      const next = mergeCodeMap(graph, map);
      setGraph(next);
      return next;
    },
    [graph, project, queryClient],
  );

  const onExpandNode = useCallback(
    (node: MergedNode) => {
      if (!node.has_children || node.kind !== "directory") {
        setSelectedId(node.id);
        return;
      }
      setBusy(true);
      setExpandError(null);
      void expand(node.path)
        .catch((error: unknown) => {
          setExpandError(errorText(error));
        })
        .finally(() => {
          setBusy(false);
        });
    },
    [expand],
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

  const onLocateHit = useCallback(
    (hit: SearchHit) => {
      setBusy(true);
      setExpandError(null);
      void locate(hit.path)
        .catch((error: unknown) => {
          setExpandError(errorText(error));
        })
        .finally(() => {
          setBusy(false);
        });
    },
    [locate],
  );

  const filter: GraphFilter = { path: pathFilter, language };
  const languages = graphLanguages(graph);

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
          <div className="flex flex-wrap items-start justify-between gap-16">
            <div className="flex flex-col gap-4">
              <SectionTitle>Code map</SectionTitle>
              <Caption>
                {String(graph.nodes.size)} nodes shown ·{" "}
                {root.data.stats.total_files ?? 0} files indexed
                {provenance.last_commit !== undefined && provenance.last_commit !== null
                  ? ` · @ ${provenance.last_commit.slice(0, 10)}`
                  : ""}
              </Caption>
            </div>
            <div className="flex flex-wrap items-end gap-10">
              <div className="w-[14rem]">
                <Field label="Filter by path">
                  <TextInput
                    value={pathFilter}
                    placeholder="services/billing"
                    onChange={(event) => {
                      setPathFilter(event.target.value);
                    }}
                  />
                </Field>
              </div>
              <Field label="Language">
                <Select
                  value={language ?? ""}
                  onChange={(event) => {
                    setLanguage(event.target.value === "" ? null : event.target.value);
                  }}
                >
                  <option value="">All</option>
                  {languages.map((lang) => (
                    <option key={lang} value={lang}>
                      {lang}
                    </option>
                  ))}
                </Select>
              </Field>
              <PillButton
                size="sm"
                onClick={() => {
                  setGraph(mergeCodeMap(emptyGraph(), root.data));
                  setSelectedId(null);
                  setExpandError(null);
                }}
              >
                Reset view
              </PillButton>
            </div>
          </div>

          <CodeMapLegend legend={root.data.overlay_legend} />
          {busy && <Caption>Loading…</Caption>}
          {expandError !== null && <Callout tone="alert">{expandError}</Callout>}
          <p className="text-caption text-fey-graphite">
            Click a node to inspect it · double-click a directory to expand it.
          </p>

          <CodeGraph
            graph={graph}
            filter={filter}
            selectedId={selectedId}
            onSelectNode={setSelectedId}
            onExpandNode={onExpandNode}
          />
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
