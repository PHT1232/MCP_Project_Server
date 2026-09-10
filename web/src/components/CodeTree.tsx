import type { ReactNode } from "react";

import {
  overlayTone,
  pathDepth,
  treeRows,
  type CodeGraph,
  type MergedNode,
} from "../lib/codemap";
import { PillButton } from "./PillButton";
import { StatusBadge } from "./StatusBadge";

export interface TreeFilter {
  path: string;
  language: string | null;
}

interface CodeTreeProps {
  graph: CodeGraph;
  filter: TreeFilter;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onExpand: (node: MergedNode) => void;
}

const OVERLAY_LABEL: Record<string, string> = {
  ember: "hot",
  growth: "focus",
  mist: "linked",
};

const KIND_LABEL: Record<MergedNode["kind"], string> = {
  directory: "dir",
  file: "file",
  external: "external",
  symbol: "symbol",
};

function metrics(node: MergedNode): string {
  if (node.kind === "external") {
    return "external module";
  }
  const parts: string[] = [];
  if (node.kind === "directory") {
    parts.push(`${String(node.file_count)} ${node.file_count === 1 ? "file" : "files"}`);
  }
  if (node.language !== null && node.language !== "") {
    parts.push(node.language);
  }
  if (node.loc > 0) {
    parts.push(`${String(node.loc)} LOC`);
  }
  if (node.fan_out > 0) {
    parts.push(`${String(node.fan_out)} out`);
  }
  if (node.fan_in > 0) {
    parts.push(`${String(node.fan_in)} in`);
  }
  return parts.join(" · ");
}

/** FR32–FR34 — the code map as a filterable, lazily-expanded file tree. */
export function CodeTree({
  graph,
  filter,
  selectedId,
  onSelect,
  onExpand,
}: CodeTreeProps): ReactNode {
  const rows = treeRows(graph, filter);
  if (rows.length === 0) {
    return (
      <p className="text-body text-fey-graphite">
        {graph.nodes.size === 0
          ? "No files in the map yet."
          : "No nodes match the current filter."}
      </p>
    );
  }

  return (
    <ul className="flex flex-col">
      {rows.map((node) => {
        const depth = pathDepth(node.path);
        const tone = overlayTone(node.overlay);
        const canExpand =
          node.kind === "directory" && node.has_children && !node.expanded;
        const isSelected = node.id === selectedId;
        return (
          <li key={node.id}>
            <div
              className={`flex items-center gap-10 border-l-2 py-6 pr-8 ${
                isSelected ? "border-fey-signal bg-fey-obsidian" : "border-transparent"
              }`}
              style={{ paddingInlineStart: `calc(var(--spacing-16) * ${String(depth)} + var(--spacing-8))` }}
            >
              <button
                type="button"
                onClick={() => {
                  onSelect(node.id);
                }}
                className="flex flex-1 flex-col items-start gap-2 text-left"
              >
                <span className="flex items-center gap-8 text-body">
                  <span className="text-caption uppercase text-fey-graphite">
                    {KIND_LABEL[node.kind]}
                  </span>
                  <span
                    className={
                      node.kind === "directory" ? "text-fey-white" : "text-fey-mist"
                    }
                  >
                    {node.label}
                    {node.outside_scope && (
                      <span className="text-fey-graphite"> · outside scope</span>
                    )}
                  </span>
                  {tone !== null && (
                    <StatusBadge tone={tone}>{OVERLAY_LABEL[tone]}</StatusBadge>
                  )}
                </span>
                <span className="text-caption text-fey-graphite">{metrics(node)}</span>
              </button>
              {canExpand && (
                <PillButton
                  size="sm"
                  onClick={() => {
                    onExpand(node);
                  }}
                >
                  Expand
                </PillButton>
              )}
            </div>
          </li>
        );
      })}
    </ul>
  );
}
