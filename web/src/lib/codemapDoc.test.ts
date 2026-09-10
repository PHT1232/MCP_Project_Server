import { describe, expect, it } from "vitest";

import type { CodeMap, CodeMapEdge, CodeMapNode, Entry } from "../api/types";
import { buildCodeMapDoc, hotSpotsFromEntries } from "./codemapDoc";

function overlay(
  partial: Partial<CodeMapNode["overlay"]> = {},
): CodeMapNode["overlay"] {
  return { focus: 0, blockers: 0, bugs: 0, requirements: 0, hot: false, ...partial };
}

function node(id: string, over: Partial<CodeMapNode> = {}): CodeMapNode {
  const path = over.path ?? id.replace(/^(dir|file):/, "");
  return {
    id,
    kind: id.startsWith("dir:") ? "directory" : "file",
    path,
    label: path.split("/").pop() ?? path,
    language: "python",
    loc: 100,
    size_bytes: 1000,
    file_count: 5,
    symbol_count: 0,
    fan_in: 0,
    fan_out: 0,
    has_children: id.startsWith("dir:"),
    outside_scope: false,
    overlay: overlay(),
    ...over,
  };
}

function edge(source: string, target: string): CodeMapEdge {
  return { source, target, kind: "import", weight: 1 };
}

function map(
  nodes: CodeMapNode[],
  edges: CodeMapEdge[],
  extra: Partial<CodeMap> = {},
): CodeMap {
  return {
    project: "p",
    project_name: "acme",
    scope: null,
    scope_kind: "directory",
    depth: 1,
    generated_from: { indexed: true, last_commit: "abcdef1234567890" },
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

const TOP = map(
  [
    node("dir:web", { path: "web", file_count: 20, fan_out: 1, language: "typescript" }),
    node("dir:server", {
      path: "server",
      file_count: 30,
      fan_in: 1,
      overlay: overlay({ blockers: 2, focus: 1, hot: true }),
    }),
    node("file:justfile", { path: "justfile", file_count: 1, language: null }),
  ],
  [edge("dir:web", "dir:server")],
);

const DETAIL = map(
  [
    node("dir:server/src", { path: "server/src", file_count: 25 }),
    node("dir:server/tests", { path: "server/tests", file_count: 5 }),
    node("dir:web/src", { path: "web/src", file_count: 20, language: "typescript" }),
    node("dir:server", { path: "server", file_count: 30 }),
  ],
  [],
);

describe("buildCodeMapDoc (FR32)", () => {
  it("orders areas by file count and carries metrics + overview", () => {
    const doc = buildCodeMapDoc(TOP, DETAIL, { overview: "A shared brief." });
    expect(doc.areas.map((a) => a.label)).toEqual(["server", "web", "justfile"]);
    expect(doc.overview).toBe("A shared brief.");
    expect(doc.totalFiles).toBe(42);
    expect(doc.languages).toEqual(["python", "typescript"]);
    expect(doc.lastCommit).toBe("abcdef1234567890");
  });

  it("turns the overlay into human badges and a tone", () => {
    const [server] = buildCodeMapDoc(TOP, DETAIL).areas;
    expect(server?.tone).toBe("ember");
    expect(server?.badges).toEqual(["2 blockers", "current focus"]);
  });

  it("lists each area's children from the deeper tier, sorted by size", () => {
    const server = buildCodeMapDoc(TOP, DETAIL).areas.find((a) => a.label === "server");
    expect(server?.children.map((c) => c.label)).toEqual(["src", "tests"]);
    expect(server?.moreChildren).toBe(0);
  });

  it("renders inter-area dependencies as sentences and per-area 'depends on'", () => {
    const doc = buildCodeMapDoc(TOP, DETAIL);
    expect(doc.connections).toEqual(["web → server"]);
    expect(doc.areas.find((a) => a.label === "web")?.dependsOn).toEqual(["server"]);
    expect(doc.areas.find((a) => a.label === "server")?.dependsOn).toEqual([]);
  });

  it("works without the deeper tier", () => {
    const doc = buildCodeMapDoc(TOP, undefined);
    expect(doc.areas).toHaveLength(3);
    expect(doc.areas.every((area) => area.children.length === 0)).toBe(true);
  });

  it("caps the child list and reports the overflow", () => {
    const kids = Array.from({ length: 9 }, (_, i) =>
      node(`dir:server/p${String(i)}`, { path: `server/p${String(i)}`, file_count: i }),
    );
    const doc = buildCodeMapDoc(TOP, map([...kids], []));
    const server = doc.areas.find((a) => a.label === "server");
    expect(server?.children).toHaveLength(6);
    expect(server?.moreChildren).toBe(3);
  });
});

describe("hotSpotsFromEntries (FR33)", () => {
  const entry = (id: string, headline: string, linked: string[]): Entry => ({
    id,
    project_id: "p",
    section: "blockers",
    headline,
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

  it("collects linked files with their reason, most-referenced first", () => {
    const spots = hotSpotsFromEntries(
      [
        entry("1", "421 on remote", ["server/src/pcs/mcp/server.py"]),
        entry("2", "read-only sync", ["server/src/pcs/mcp/server.py", "deploy/x.yml"]),
      ],
      [entry("3", "flaky test", ["server/tests/test_x.py"])],
    );
    expect(spots[0]).toEqual({
      path: "server/src/pcs/mcp/server.py",
      reasons: ["blocker: 421 on remote", "blocker: read-only sync"],
    });
    expect(spots.map((s) => s.path)).toContain("server/tests/test_x.py");
    expect(spots.find((s) => s.path === "server/tests/test_x.py")?.reasons).toEqual([
      "bug: flaky test",
    ]);
  });

  it("ignores blank links", () => {
    expect(hotSpotsFromEntries([], [])).toEqual([]);
  });
});
