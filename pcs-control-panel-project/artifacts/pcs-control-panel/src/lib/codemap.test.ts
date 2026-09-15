import { describe, expect, it } from "vitest";
import type { CodeMap, CodeMapEdge, CodeMapNode, Entry } from "@workspace/api-client-react";
import { edgeKey, emptyGraph, locateHit, mergeCodeMap, overlayTone, relatedEntries } from "./codemap";

function overlay(partial: Partial<CodeMapNode["overlay"]> = {}): CodeMapNode["overlay"] {
  return { focus: 0, blockers: 0, bugs: 0, requirements: 0, hot: false, ...partial };
}

function node(
  partial: Partial<CodeMapNode> & Pick<CodeMapNode, "id" | "kind" | "path">,
): CodeMapNode {
  return {
    label: partial.path.split("/").pop() || partial.path,
    language: null,
    loc: 0,
    size_bytes: 0,
    file_count: 0,
    symbol_count: 0,
    fan_in: 0,
    fan_out: 0,
    has_children: false,
    outside_scope: false,
    overlay: overlay(),
    ...partial,
  };
}

function edge(source: string, target: string, kind = "imports", weight = 1): CodeMapEdge {
  return { source, target, kind, weight };
}

function codeMap(
  partial: Partial<CodeMap> & Pick<CodeMap, "nodes" | "edges">,
): CodeMap {
  return {
    project: "p1",
    project_name: "Project One",
    scope: null,
    scope_kind: "directory",
    depth: 1,
    generated_from: { indexed: true },
    stats: { node_count: partial.nodes.length, edge_count: partial.edges.length, truncated: false },
    overlay_legend: [],
    ...partial,
  };
}

function entry(partial: Partial<Entry> & Pick<Entry, "id" | "section" | "headline">): Entry {
  return {
    project_id: "p1",
    detail: "",
    status: "open",
    priority: 0,
    author: "tester",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    requirement_status: null,
    linked_files: [],
    related_entry_id: null,
    req_key: null,
    ...partial,
  };
}

describe("emptyGraph", () => {
  it("returns empty, independent maps/sets", () => {
    const a = emptyGraph();
    const b = emptyGraph();
    expect(a.nodes.size).toBe(0);
    expect(a.edges.size).toBe(0);
    expect(a.loadedScopes.size).toBe(0);
    a.nodes.set("x", { ...node({ id: "x", kind: "file", path: "x" }), expanded: false });
    expect(b.nodes.size).toBe(0);
  });
});

describe("edgeKey", () => {
  it("joins source, target, and kind with spaces", () => {
    expect(edgeKey({ source: "a", target: "b", kind: "imports" })).toBe("a b imports");
  });
});

describe("mergeCodeMap", () => {
  it("seeds the graph from the top tier and marks nodes unexpanded", () => {
    const top = codeMap({
      scope: null,
      nodes: [
        node({ id: "dir:src", kind: "directory", path: "src", has_children: true }),
        node({ id: "file:readme.md", kind: "file", path: "readme.md" }),
      ],
      edges: [],
    });

    const graph = mergeCodeMap(emptyGraph(), top);

    expect(graph.loadedScopes.has("")).toBe(true);
    expect(graph.nodes.get("dir:src")?.expanded).toBe(false);
    expect(graph.nodes.size).toBe(2);
  });

  it("recomputes fan-in/fan-out from the current edge set, ignoring self-loops", () => {
    const top = codeMap({
      nodes: [
        node({ id: "file:a.ts", kind: "file", path: "a.ts" }),
        node({ id: "file:b.ts", kind: "file", path: "b.ts" }),
        node({ id: "file:c.ts", kind: "file", path: "c.ts" }),
      ],
      edges: [
        edge("file:a.ts", "file:b.ts"),
        edge("file:a.ts", "file:c.ts"),
        edge("file:a.ts", "file:a.ts"), // self-loop must not count
      ],
    });

    const graph = mergeCodeMap(emptyGraph(), top);

    expect(graph.nodes.get("file:a.ts")?.fan_out).toBe(2);
    expect(graph.nodes.get("file:a.ts")?.fan_in).toBe(0);
    expect(graph.nodes.get("file:b.ts")?.fan_in).toBe(1);
    expect(graph.nodes.get("file:c.ts")?.fan_in).toBe(1);
  });

  it("a second top-tier merge fully reseeds the graph (does not accumulate)", () => {
    const first = codeMap({
      nodes: [node({ id: "file:old.ts", kind: "file", path: "old.ts" })],
      edges: [],
    });
    const second = codeMap({
      nodes: [node({ id: "file:new.ts", kind: "file", path: "new.ts" })],
      edges: [],
    });

    const graph = mergeCodeMap(mergeCodeMap(emptyGraph(), first), second);

    expect(graph.nodes.has("file:old.ts")).toBe(false);
    expect(graph.nodes.has("file:new.ts")).toBe(true);
  });

  it("returns the graph unchanged for a file-scope response", () => {
    const original = mergeCodeMap(
      emptyGraph(),
      codeMap({ nodes: [node({ id: "file:a.ts", kind: "file", path: "a.ts" })], edges: [] }),
    );
    const fileScope = codeMap({
      scope: "a.ts",
      scope_kind: "file",
      nodes: [node({ id: "file:a.ts", kind: "file", path: "a.ts", loc: 999 })],
      edges: [],
    });

    const result = mergeCodeMap(original, fileScope);

    expect(result).toBe(original);
    expect(result.nodes.get("file:a.ts")?.loc).toBe(0);
  });

  it("subtree merge drops the aggregate dir node, replaces its tier edges, and marks the ancestor expanded", () => {
    const top = mergeCodeMap(
      emptyGraph(),
      codeMap({
        nodes: [node({ id: "dir:src", kind: "directory", path: "src", has_children: true })],
        edges: [edge("dir:src", "dir:other", "contains")],
      }),
    );

    const subtree = codeMap({
      scope: "src",
      nodes: [
        node({ id: "dir:src", kind: "directory", path: "src", has_children: true }),
        node({ id: "file:src/a.ts", kind: "file", path: "src/a.ts" }),
      ],
      edges: [edge("dir:src", "file:src/a.ts", "contains")],
    });

    const graph = mergeCodeMap(top, subtree);

    // The old aggregate-tier edge to dir:other is gone.
    expect(graph.edges.has(edgeKey({ source: "dir:src", target: "dir:other", kind: "contains" }))).toBe(
      false,
    );
    expect(graph.edges.has(edgeKey({ source: "dir:src", target: "file:src/a.ts", kind: "contains" }))).toBe(
      true,
    );
    expect(graph.nodes.has("file:src/a.ts")).toBe(true);
    expect(graph.nodes.get("dir:src")?.expanded).toBe(true);
    expect(graph.loadedScopes.has("src")).toBe(true);
  });

  it("never lets an outside_scope boundary stub overwrite an already-loaded real node", () => {
    const withRealNode = mergeCodeMap(
      emptyGraph(),
      codeMap({
        scope: "src",
        nodes: [node({ id: "file:src/b.ts", kind: "file", path: "src/b.ts", loc: 42, outside_scope: false })],
        edges: [],
      }),
    );

    const otherTier = codeMap({
      scope: "lib",
      nodes: [
        node({ id: "file:src/b.ts", kind: "file", path: "src/b.ts", loc: 0, outside_scope: true }),
      ],
      edges: [],
    });

    const graph = mergeCodeMap(withRealNode, otherTier);

    const kept = graph.nodes.get("file:src/b.ts");
    expect(kept?.outside_scope).toBe(false);
    expect(kept?.loc).toBe(42);
  });

  it("preserves the expanded flag of a node that was already expanded before a re-merge", () => {
    const top = mergeCodeMap(
      emptyGraph(),
      codeMap({
        nodes: [node({ id: "dir:src", kind: "directory", path: "src", has_children: true })],
        edges: [],
      }),
    );
    const expandedOnce = mergeCodeMap(
      top,
      codeMap({
        scope: "src",
        nodes: [
          node({ id: "dir:src", kind: "directory", path: "src", has_children: true }),
          node({ id: "dir:src/nested", kind: "directory", path: "src/nested", has_children: true }),
        ],
        edges: [],
      }),
    );
    expect(expandedOnce.nodes.get("dir:src/nested")?.expanded).toBe(false);

    const nestedExpanded = mergeCodeMap(
      expandedOnce,
      codeMap({
        scope: "src/nested",
        nodes: [
          node({ id: "dir:src/nested", kind: "directory", path: "src/nested", has_children: true }),
          node({ id: "file:src/nested/x.ts", kind: "file", path: "src/nested/x.ts" }),
        ],
        edges: [],
      }),
    );
    expect(nestedExpanded.nodes.get("dir:src/nested")?.expanded).toBe(true);
    // A merge scoped to the child must not un-expand the already-expanded parent.
    expect(nestedExpanded.nodes.get("dir:src")?.expanded).toBe(true);
  });
});

describe("overlayTone", () => {
  it("is ember when hot", () => {
    expect(overlayTone(overlay({ hot: true }))).toBe("ember");
  });

  it("is ember when there are blockers, even without hot", () => {
    expect(overlayTone(overlay({ blockers: 1 }))).toBe("ember");
  });

  it("is ember when there are bugs", () => {
    expect(overlayTone(overlay({ bugs: 2 }))).toBe("ember");
  });

  it("ember takes priority over focus and requirements", () => {
    expect(overlayTone(overlay({ hot: true, focus: 3, requirements: 4 }))).toBe("ember");
  });

  it("is growth when focused and not a hot spot", () => {
    expect(overlayTone(overlay({ focus: 1 }))).toBe("growth");
  });

  it("growth takes priority over requirements", () => {
    expect(overlayTone(overlay({ focus: 1, requirements: 5 }))).toBe("growth");
  });

  it("is mist when only requirement-linked", () => {
    expect(overlayTone(overlay({ requirements: 1 }))).toBe("mist");
  });

  it("is null when nothing is set", () => {
    expect(overlayTone(overlay())).toBeNull();
  });
});

describe("locateHit", () => {
  it("finds an exact file node", () => {
    const graph = mergeCodeMap(
      emptyGraph(),
      codeMap({ nodes: [node({ id: "file:src/a.ts", kind: "file", path: "src/a.ts" })], edges: [] }),
    );
    expect(locateHit(graph, "src/a.ts")).toEqual({ kind: "node", nodeId: "file:src/a.ts" });
  });

  it("asks the caller to expand an unexpanded ancestor directory", () => {
    const graph = mergeCodeMap(
      emptyGraph(),
      codeMap({
        nodes: [node({ id: "dir:src", kind: "directory", path: "src", has_children: true })],
        edges: [],
      }),
    );
    expect(locateHit(graph, "src/deep/file.ts")).toEqual({ kind: "expand", scope: "src" });
  });

  it("settles on the closest loaded ancestor when the map has no finer node", () => {
    // A directory only becomes "expanded" once its own scope has been merged
    // in (mergeCodeMap forces expanded:false on every top-tier seed), so build
    // this up the same way the UI does: seed, then merge that dir's subtree.
    const top = mergeCodeMap(
      emptyGraph(),
      codeMap({
        nodes: [node({ id: "dir:src", kind: "directory", path: "src", has_children: true })],
        edges: [],
      }),
    );
    const expandedGraph = mergeCodeMap(
      top,
      codeMap({
        scope: "src",
        nodes: [node({ id: "dir:src", kind: "directory", path: "src", has_children: true })],
        edges: [],
      }),
    );
    expect(expandedGraph.nodes.get("dir:src")?.expanded).toBe(true);
    expect(locateHit(expandedGraph, "src/unindexed.ts")).toEqual({ kind: "node", nodeId: "dir:src" });
  });

  it("asks the caller to expand the top-level segment when nothing is loaded yet", () => {
    expect(locateHit(emptyGraph(), "src/a.ts")).toEqual({ kind: "expand", scope: "src" });
  });

  it("is unreachable for a bare top-level path with nothing loaded", () => {
    expect(locateHit(emptyGraph(), "README.md")).toEqual({ kind: "unreachable" });
  });
});

describe("relatedEntries", () => {
  const sections = {
    blockers: [entry({ id: "b1", section: "blockers", headline: "Blocked", linked_files: ["src/a.ts"] })],
    bugs: [entry({ id: "bug1", section: "bugs", headline: "Bug in dir", linked_files: ["src"] })],
    decisions: [
      entry({ id: "d1", section: "decisions", headline: "Decision on subtree", linked_files: ["src/a.ts/nested"] }),
    ],
    conventions: [
      entry({ id: "c1", section: "conventions", headline: "Unrelated", linked_files: ["other/file.ts"] }),
    ],
  };

  it("matches an entry linked to the exact path", () => {
    const result = relatedEntries(sections, "src/a.ts");
    expect(result.map((r) => r.entry.id)).toContain("b1");
  });

  it("matches an entry linked to an ancestor directory of the path", () => {
    const result = relatedEntries(sections, "src/a.ts");
    expect(result.map((r) => r.entry.id)).toContain("bug1");
  });

  it("matches an entry linked to a path inside the target directory", () => {
    const result = relatedEntries(sections, "src");
    expect(result.map((r) => r.entry.id)).toContain("d1");
  });

  it("excludes entries with unrelated linked files", () => {
    const result = relatedEntries(sections, "src/a.ts");
    expect(result.map((r) => r.entry.id)).not.toContain("c1");
  });

  it("preserves the originating section name", () => {
    const result = relatedEntries(sections, "src/a.ts");
    const blocker = result.find((r) => r.entry.id === "b1");
    expect(blocker?.section).toBe("blockers");
  });

  it("returns nothing for an empty path", () => {
    expect(relatedEntries(sections, "")).toEqual([]);
  });
});
