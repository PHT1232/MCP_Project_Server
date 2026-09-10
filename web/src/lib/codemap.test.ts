import { describe, expect, it } from "vitest";

import type { CodeMap, CodeMapEdge, CodeMapNode, Entry } from "../api/types";
import {
  emptyGraph,
  locateHit,
  mergeCodeMap,
  overlayTone,
  relatedEntries,
  treeRows,
} from "./codemap";

function overlay(
  partial: Partial<CodeMapNode["overlay"]> = {},
): CodeMapNode["overlay"] {
  return { focus: 0, blockers: 0, bugs: 0, requirements: 0, hot: false, ...partial };
}

function node(id: string, over: Partial<CodeMapNode> = {}): CodeMapNode {
  const path = over.path ?? id.replace(/^(dir|file|sym):/, "");
  return {
    id,
    kind: id.startsWith("dir:") ? "directory" : "file",
    path,
    label: path.split("/").pop() ?? path,
    language: "python",
    loc: 10,
    size_bytes: 100,
    file_count: 1,
    symbol_count: 0,
    fan_in: 0,
    fan_out: 0,
    has_children: id.startsWith("dir:"),
    outside_scope: false,
    overlay: overlay(),
    ...over,
  };
}

function edge(source: string, target: string, weight = 1): CodeMapEdge {
  return { source, target, kind: "import", weight };
}

function map(
  scope: string | null,
  nodes: CodeMapNode[],
  edges: CodeMapEdge[],
  extra: Partial<CodeMap> = {},
): CodeMap {
  return {
    project: "p",
    project_name: "acme",
    scope,
    scope_kind: "directory",
    depth: 1,
    generated_from: { indexed: true },
    nodes,
    edges,
    stats: {
      node_count: nodes.length,
      edge_count: edges.length,
      truncated: false,
      total_files: 42,
    },
    overlay_legend: ["focus", "blockers", "bugs", "requirements"],
    ...extra,
  };
}

const ROOT = map(
  null,
  [node("dir:services"), node("dir:lib"), node("file:main.py", { path: "main.py" })],
  [edge("file:main.py", "dir:services"), edge("dir:services", "dir:lib")],
);

describe("mergeCodeMap", () => {
  it("seeds the graph from the top tier", () => {
    const graph = mergeCodeMap(emptyGraph(), ROOT);
    expect([...graph.nodes.keys()].sort()).toEqual([
      "dir:lib",
      "dir:services",
      "file:main.py",
    ]);
    expect(graph.edges.size).toBe(2);
    expect(graph.loadedScopes.has("")).toBe(true);
  });

  it("merges ONLY the expanded subtree — no sibling nodes appear (D9/AC20)", () => {
    const graph = mergeCodeMap(emptyGraph(), ROOT);
    const subtree = map(
      "services",
      [
        node("dir:services/billing", { path: "services/billing" }),
        node("dir:services/pricing", { path: "services/pricing" }),
        node("dir:lib", { path: "lib", outside_scope: true }),
      ],
      [
        edge("dir:services/billing", "dir:services/pricing", 2),
        edge("dir:services/billing", "dir:lib"),
      ],
    );
    const next = mergeCodeMap(graph, subtree);

    // the aggregate parent is gone, replaced by its children
    expect(next.nodes.has("dir:services")).toBe(false);
    expect(next.nodes.has("dir:services/billing")).toBe(true);
    expect(next.nodes.has("dir:services/pricing")).toBe(true);
    // a sibling that already existed as a real node is NOT overwritten by the stub
    expect(next.nodes.get("dir:lib")?.outside_scope).toBe(false);
    // main.py (never mentioned in the subtree response) is still there, untouched
    expect(next.nodes.has("file:main.py")).toBe(true);
    // no node from another subtree leaked in
    expect([...next.nodes.keys()].some((k) => k.startsWith("dir:services/api"))).toBe(
      false,
    );
    expect(next.loadedScopes.has("services")).toBe(true);
  });

  it("recomputes fan-in/out from the merged edge set", () => {
    const graph = mergeCodeMap(emptyGraph(), ROOT);
    expect(graph.nodes.get("dir:lib")?.fan_in).toBe(1);
    expect(graph.nodes.get("dir:services")?.fan_out).toBe(1);
    expect(graph.nodes.get("dir:services")?.fan_in).toBe(1);
  });

  it("ignores a file-scope payload (that feeds the inspector, not the graph)", () => {
    const graph = mergeCodeMap(emptyGraph(), ROOT);
    const fileScope = map("main.py", [], [], { scope_kind: "file" });
    expect(mergeCodeMap(graph, fileScope)).toBe(graph);
  });
});

describe("overlayTone (FR33 / AC12)", () => {
  it("is ember for a hot spot", () => {
    expect(overlayTone(overlay({ hot: true, blockers: 1 }))).toBe("ember");
    expect(overlayTone(overlay({ bugs: 2 }))).toBe("ember");
  });
  it("is growth for the current focus, mist for requirements, null otherwise", () => {
    expect(overlayTone(overlay({ focus: 1 }))).toBe("growth");
    expect(overlayTone(overlay({ requirements: 1 }))).toBe("mist");
    expect(overlayTone(overlay())).toBeNull();
  });
});

describe("treeRows (FR32)", () => {
  it("returns loaded nodes path-sorted", () => {
    const graph = mergeCodeMap(emptyGraph(), ROOT);
    const rows = treeRows(graph, { path: "", language: null });
    expect(rows.map((r) => r.id)).toEqual(["dir:lib", "file:main.py", "dir:services"]);
  });

  it("puts a directory before a file that shares its path prefix, then by id", () => {
    const graph = mergeCodeMap(
      emptyGraph(),
      map(
        null,
        [
          node("file:pkg", { path: "pkg", kind: "file", has_children: false }),
          node("dir:pkg", { path: "pkg", kind: "directory", has_children: true }),
        ],
        [],
      ),
    );
    expect(treeRows(graph, { path: "", language: null }).map((r) => r.id)).toEqual([
      "dir:pkg",
      "file:pkg",
    ]);
  });

  it("narrows by the path and language filters", () => {
    const graph = mergeCodeMap(
      emptyGraph(),
      map(
        null,
        [
          node("file:api.go", { path: "api.go", language: "go" }),
          node("file:lib/util.py", { path: "lib/util.py" }),
        ],
        [],
      ),
    );
    expect(treeRows(graph, { path: "lib", language: null }).map((r) => r.id)).toEqual([
      "file:lib/util.py",
    ]);
    expect(treeRows(graph, { path: "", language: "go" }).map((r) => r.id)).toEqual([
      "file:api.go",
    ]);
  });
});

describe("locateHit (FR35)", () => {
  const graph = mergeCodeMap(emptyGraph(), ROOT);

  it("returns the exact file node when present", () => {
    expect(locateHit(graph, "main.py")).toEqual({ kind: "node", nodeId: "file:main.py" });
  });

  it("asks the caller to expand the closest collapsed ancestor", () => {
    expect(locateHit(graph, "services/billing/invoice.py")).toEqual({
      kind: "expand",
      scope: "services",
    });
  });

  it("settles on the closest node once the map is expanded there", () => {
    const expanded = mergeCodeMap(
      graph,
      map(
        "services",
        [node("dir:services/billing", { path: "services/billing", has_children: false })],
        [],
      ),
    );
    expect(locateHit(expanded, "services/billing/deep/x.py")).toEqual({
      kind: "node",
      nodeId: "dir:services/billing",
    });
  });

  it("is unreachable for a root-level file that is not in the map", () => {
    expect(locateHit(graph, "ghost.py")).toEqual({ kind: "unreachable" });
  });
});

describe("relatedEntries (FR34)", () => {
  const entry = (id: string, linked: string[]): Entry => ({
    id,
    project_id: "p",
    section: "blockers",
    headline: `h-${id}`,
    detail: "",
    status: "open",
    priority: 0,
    author: "a",
    created_at: "",
    updated_at: "",
    requirement_status: null,
    linked_files: linked,
    related_entry_id: null,
    req_key: null,
  });

  it("matches exact, inside, and ancestor-dir links", () => {
    const bySection = {
      blockers: [entry("1", ["services/billing/invoice.py"])],
      bugs: [entry("2", ["services/billing"])],
      decisions: [entry("3", ["lib/money.py"])],
    };
    const hits = relatedEntries(bySection, "services/billing/invoice.py");
    expect(hits.map((h) => h.entry.id).sort()).toEqual(["1", "2"]);
    expect(hits.find((h) => h.entry.id === "2")?.section).toBe("bugs");
  });
});

