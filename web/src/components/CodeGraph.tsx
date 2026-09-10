import { useEffect, useRef, type ReactNode } from "react";
import Graph from "graphology";
import Sigma from "sigma";

import {
  layout,
  nodeMatchesFilter,
  nodeWeight,
  overlayTone,
  type CodeGraph as CodeGraphModel,
  type MergedNode,
} from "../lib/codemap";
import { codeMapPalette, type CodeMapPalette } from "../lib/tokens";

export interface GraphFilter {
  path: string;
  language: string | null;
}

interface CodeGraphProps {
  graph: CodeGraphModel;
  filter: GraphFilter;
  selectedId: string | null;
  onSelectNode: (id: string) => void;
  onExpandNode: (node: MergedNode) => void;
}

const MIN_NODE = 4;
const MAX_NODE = 26;

function fillFor(node: MergedNode, palette: CodeMapPalette): string {
  const tone = overlayTone(node.overlay);
  if (tone === "ember") {
    return palette.hot;
  }
  if (tone === "growth") {
    return palette.focus;
  }
  if (tone === "mist") {
    return palette.requirement;
  }
  if (node.outside_scope) {
    return palette.stub;
  }
  if (node.kind === "directory") {
    return palette.directory;
  }
  if (node.kind === "external") {
    return palette.external;
  }
  return palette.file;
}

/**
 * FR32 — the interactive Sigma / graphology canvas. Pan/zoom is Sigma's default;
 * node size is the static structural weight (D11); edge thickness is the
 * aggregated `weight`; overlay tones colour hot spots (FR33). Click selects a
 * node (opens the inspector); double-click expands a `has_children` node
 * (FR32a — the parent lazily loads its own subtree, never the whole graph).
 */
export function CodeGraph({
  graph,
  filter,
  selectedId,
  onSelectNode,
  onExpandNode,
}: CodeGraphProps): ReactNode {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const sigmaRef = useRef<Sigma | null>(null);
  const dataRef = useRef<Graph | null>(null);
  const modelsRef = useRef<Map<string, MergedNode>>(new Map());
  const handlersRef = useRef({ onSelectNode, onExpandNode });
  handlersRef.current = { onSelectNode, onExpandNode };

  useEffect(() => {
    const container = containerRef.current;
    if (container === null) {
      return;
    }
    const data = new Graph({ type: "directed", multi: false, allowSelfLoops: false });
    const palette = codeMapPalette();
    const sigma = new Sigma(data, container, {
      renderLabels: true,
      labelColor: { color: palette.label },
      labelFont: "Calibre, ui-sans-serif, system-ui, sans-serif",
      defaultEdgeColor: palette.edge,
      defaultNodeColor: palette.file,
      minEdgeThickness: 1,
    });
    sigma.on("clickNode", ({ node }) => {
      handlersRef.current.onSelectNode(node);
    });
    sigma.on("doubleClickNode", ({ node }) => {
      const model = modelsRef.current.get(node);
      if (model !== undefined) {
        handlersRef.current.onExpandNode(model);
      }
    });
    sigmaRef.current = sigma;
    dataRef.current = data;
    return () => {
      sigma.kill();
      sigmaRef.current = null;
      dataRef.current = null;
    };
  }, []);

  useEffect(() => {
    const data = dataRef.current;
    const sigma = sigmaRef.current;
    if (data === null || sigma === null) {
      return;
    }
    const palette = codeMapPalette();

    const visible: MergedNode[] = [];
    for (const node of graph.nodes.values()) {
      if (nodeMatchesFilter(node, filter)) {
        visible.push(node);
      }
    }
    const positions = layout(visible);
    const weights = visible.map((node) => nodeWeight(node));
    const maxWeight = Math.max(1, ...weights);

    data.clear();
    const models = new Map<string, MergedNode>();
    visible.forEach((node, index) => {
      const pos = positions.get(node.id) ?? { x: index, y: 0 };
      const base =
        MIN_NODE + ((weights[index] ?? 1) / maxWeight) * (MAX_NODE - MIN_NODE);
      data.addNode(node.id, {
        x: pos.x,
        y: pos.y,
        size: node.id === selectedId ? base + 3 : base,
        label: node.label,
        color: node.id === selectedId ? palette.selected : fillFor(node, palette),
      });
      models.set(node.id, node);
    });
    modelsRef.current = models;

    for (const edge of graph.edges.values()) {
      if (!data.hasNode(edge.source) || !data.hasNode(edge.target)) {
        continue;
      }
      data.mergeDirectedEdge(edge.source, edge.target, {
        size: Math.min(6, 1 + Math.log2(edge.weight + 1)),
        color: palette.edge,
        type: "arrow",
      });
    }
    sigma.refresh();
  }, [graph, filter, selectedId]);

  return (
    <div
      ref={containerRef}
      className="relative h-[70vh] min-h-[28rem] w-full rounded-small border border-fey-smoke bg-fey-ink"
    />
  );
}
