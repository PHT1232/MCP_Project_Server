/**
 * Pure code-map model: turn `get_code_map` responses (FR32/FR32a) into a merged
 * node/edge model, and the small algorithms the code-map view needs — lazy-expand
 * merge (D9/AC20: never re-fetch the whole graph), overlay tone (FR33),
 * search-hit → node location (FR35), and related-context matching (FR34). The
 * read-down document projection lives in `codemapDoc.ts`.
 *
 * No React, no DOM — everything here is unit-tested in `codemap.test.ts`.
 */
import type { CodeMap, CodeMapEdge, CodeMapNode, Entry } from "@workspace/api-client-react";

export interface MergedNode extends CodeMapNode {
  /** True once this node's own subtree has been merged in (FR32a lazy expand). */
  expanded: boolean;
}

export interface CodeGraph {
  nodes: Map<string, MergedNode>;
  edges: Map<string, CodeMapEdge>;
  /** Scope paths whose subtree is merged in. `""` = the top tier. */
  loadedScopes: Set<string>;
}

export function emptyGraph(): CodeGraph {
  return { nodes: new Map(), edges: new Map(), loadedScopes: new Set() };
}

export function edgeKey(edge: Pick<CodeMapEdge, "source" | "target" | "kind">): string {
  return `${edge.source} ${edge.target} ${edge.kind}`;
}

function getOrCreate<K, V>(map: Map<K, V>, key: K, make: () => V): V {
  const found = map.get(key);
  if (found !== undefined) {
    return found;
  }
  const created = make();
  map.set(key, created);
  return created;
}

function cloneGraph(graph: CodeGraph): CodeGraph {
  return {
    nodes: new Map(graph.nodes),
    edges: new Map(graph.edges),
    loadedScopes: new Set(graph.loadedScopes),
  };
}

/** Distinct in-/out-neighbour counts from the current edge set (D11 fan-in/out). */
function recomputeFans(graph: CodeGraph): void {
  const inN = new Map<string, Set<string>>();
  const outN = new Map<string, Set<string>>();
  for (const edge of graph.edges.values()) {
    if (edge.source === edge.target) {
      continue;
    }
    getOrCreate(outN, edge.source, () => new Set<string>()).add(edge.target);
    getOrCreate(inN, edge.target, () => new Set<string>()).add(edge.source);
  }
  for (const [id, node] of graph.nodes) {
    graph.nodes.set(id, {
      ...node,
      fan_in: inN.get(id)?.size ?? 0,
      fan_out: outN.get(id)?.size ?? 0,
    });
  }
}

/**
 * Merge one `get_code_map` tier into the graph and return a NEW graph.
 *
 * - Top tier (`map.scope` null): the graph is (re)seeded from this response.
 * - Subtree (`map.scope` a dir path): the server's response for a scope
 *   contains that directory's CHILDREN, never the scope node itself (AC20 —
 *   "the response only ever describes the requested tier"). So the scope
 *   node must be kept as-is (its own rollup stats stay valid regardless of
 *   how deep its subtree has been expanded) — only its now-stale aggregate-
 *   tier edges are dropped and replaced by the subtree's own, finer edges.
 *   Deleting the scope node itself here previously made the clicked
 *   directory vanish from the tree, since nothing in the response ever adds
 *   it back. Boundary stubs (`outside_scope`) never overwrite a real node
 *   already present.
 * - File scope (`map.scope_kind === "file"`) does not belong on the graph — the
 *   graph is returned unchanged (the caller uses that payload for the inspector).
 */
export function mergeCodeMap(graph: CodeGraph, map: CodeMap): CodeGraph {
  if (map.scope_kind === "file") {
    return graph;
  }
  const scope = map.scope ?? "";

  if (scope === "") {
    const next = emptyGraph();
    for (const node of map.nodes) {
      next.nodes.set(node.id, { ...node, expanded: false });
    }
    for (const edge of map.edges) {
      next.edges.set(edgeKey(edge), edge);
    }
    next.loadedScopes.add("");
    recomputeFans(next);
    return next;
  }

  const next = cloneGraph(graph);
  const aggregateId = `dir:${scope}`;
  for (const key of [...next.edges.keys()]) {
    const edge = next.edges.get(key);
    if (edge && (edge.source === aggregateId || edge.target === aggregateId)) {
      next.edges.delete(key);
    }
  }

  for (const node of map.nodes) {
    const existing = next.nodes.get(node.id);
    if (node.outside_scope && existing && !existing.outside_scope) {
      continue; // keep the real node, not the stub
    }
    next.nodes.set(node.id, { ...node, expanded: existing?.expanded ?? false });
  }
  for (const edge of map.edges) {
    next.edges.set(edgeKey(edge), edge);
  }

  // Mark the nearest ancestor that is still a node as expanded.
  for (const [id, node] of next.nodes) {
    if (node.path === scope || scope.startsWith(node.path + "/")) {
      if (node.kind === "directory") {
        next.nodes.set(id, { ...node, expanded: true });
      }
    }
  }
  next.loadedScopes.add(scope);
  recomputeFans(next);
  return next;
}

export type OverlayTone = "ember" | "growth" | "mist";

/**
 * FR33 / AC12 — the single StatusBadge tone a node's overlay earns. Ember for a
 * hot spot (blocker/bug), Growth for the current focus, Mist for a
 * requirement-linked file. Never Signal blue (DESIGN.md: not a status colour).
 */
export function overlayTone(overlay: CodeMapNode["overlay"]): OverlayTone | null {
  if (overlay.hot || overlay.blockers > 0 || overlay.bugs > 0) {
    return "ember";
  }
  if (overlay.focus > 0) {
    return "growth";
  }
  if (overlay.requirements > 0) {
    return "mist";
  }
  return null;
}

function topSegment(path: string): string {
  if (path === "") {
    return "";
  }
  return path.split("/")[0] ?? path;
}

export type LocateResult =
  | { kind: "node"; nodeId: string }
  | { kind: "expand"; scope: string }
  | { kind: "unreachable" };

function isAncestorPath(ancestor: string, path: string): boolean {
  return ancestor !== "" && (ancestor === path || path.startsWith(ancestor + "/"));
}

/**
 * FR35 — where a search hit's file lands on the current graph. Either it is an
 * existing node, or the caller must expand a scope and try again, or it cannot
 * be revealed (not indexed in this map).
 */
export function locateHit(graph: CodeGraph, filePath: string): LocateResult {
  const fileNode = graph.nodes.get(`file:${filePath}`);
  if (fileNode) {
    return { kind: "node", nodeId: fileNode.id };
  }

  let best: MergedNode | null = null;
  for (const node of graph.nodes.values()) {
    if (isAncestorPath(node.path, filePath)) {
      if (best === null || node.path.length > best.path.length) {
        best = node;
      }
    }
  }
  if (best) {
    if (best.kind === "directory" && best.has_children && !best.expanded) {
      return { kind: "expand", scope: best.path };
    }
    if (best.path !== filePath) {
      // The map is expanded here but has no finer node — settle on the closest.
      return { kind: "node", nodeId: best.id };
    }
    return { kind: "node", nodeId: best.id };
  }

  const seg = topSegment(filePath);
  if (seg !== "" && seg !== filePath) {
    return { kind: "expand", scope: seg };
  }
  return { kind: "unreachable" };
}

export interface RelatedEntry {
  section: string;
  entry: Entry;
}

function pathTouches(linked: string, target: string): boolean {
  const p = linked.trim().replace(/^\/+|\/+$/g, "");
  if (p === "" || target === "") {
    return false;
  }
  return p === target || target.startsWith(p + "/") || p.startsWith(target + "/");
}

/**
 * FR34 — context entries whose `linked_files` touch a path (same match rule the
 * server's overlay uses: exact, inside, or an ancestor dir).
 */
export function relatedEntries(
  entriesBySection: Readonly<Record<string, readonly Entry[]>>,
  path: string,
): RelatedEntry[] {
  const out: RelatedEntry[] = [];
  for (const [section, entries] of Object.entries(entriesBySection)) {
    for (const entry of entries) {
      if (entry.linked_files.some((f) => pathTouches(f, path))) {
        out.push({ section, entry });
      }
    }
  }
  return out;
}
