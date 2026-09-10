import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import type { CodeMap, CodeMapNode } from "../api/types";
import { emptyGraph, mergeCodeMap } from "../lib/codemap";
import { CodeTree } from "./CodeTree";

function node(id: string, over: Partial<CodeMapNode> = {}): CodeMapNode {
  const path = over.path ?? id.replace(/^(dir|file):/, "");
  return {
    id,
    kind: id.startsWith("dir:") ? "directory" : "file",
    path,
    label: path.split("/").pop() ?? path,
    language: "python",
    loc: 12,
    size_bytes: 100,
    file_count: 3,
    symbol_count: 0,
    fan_in: 0,
    fan_out: 2,
    has_children: id.startsWith("dir:"),
    outside_scope: false,
    overlay: { focus: 0, blockers: 1, bugs: 0, requirements: 0, hot: true },
    ...over,
  };
}

const MAP: CodeMap = {
  project: "p",
  project_name: "acme",
  scope: null,
  scope_kind: "directory",
  depth: 1,
  generated_from: { indexed: true },
  nodes: [
    node("dir:services"),
    node("file:main.py", {
      path: "main.py",
      overlay: { focus: 0, blockers: 0, bugs: 0, requirements: 0, hot: false },
    }),
  ],
  edges: [],
  stats: { node_count: 2, edge_count: 0, truncated: false, total_files: 10 },
  overlay_legend: ["focus", "blockers", "bugs", "requirements"],
};

describe("CodeTree", () => {
  const graph = mergeCodeMap(emptyGraph(), MAP);

  it("renders a row per node with an Expand button on unexpanded directories", () => {
    render(
      <CodeTree
        graph={graph}
        filter={{ path: "", language: null }}
        selectedId={null}
        onSelect={vi.fn()}
        onExpand={vi.fn()}
      />,
    );
    expect(screen.getByText("services")).toBeTruthy();
    expect(screen.getByText("main.py")).toBeTruthy();
    // one Expand button — only the directory can expand
    expect(screen.getAllByRole("button", { name: "Expand" })).toHaveLength(1);
    // the hot directory shows its overlay badge
    expect(screen.getByText("hot")).toBeTruthy();
  });

  it("selects on row click and expands on the Expand button", () => {
    const onSelect = vi.fn();
    const onExpand = vi.fn();
    render(
      <CodeTree
        graph={graph}
        filter={{ path: "", language: null }}
        selectedId={null}
        onSelect={onSelect}
        onExpand={onExpand}
      />,
    );
    fireEvent.click(screen.getByText("main.py"));
    expect(onSelect).toHaveBeenCalledWith("file:main.py");

    fireEvent.click(screen.getByRole("button", { name: "Expand" }));
    expect(onExpand).toHaveBeenCalledOnce();
    expect((onExpand.mock.calls[0]?.[0] as CodeMapNode).id).toBe("dir:services");
  });

  it("applies the path filter", () => {
    render(
      <CodeTree
        graph={graph}
        filter={{ path: "services", language: null }}
        selectedId={null}
        onSelect={vi.fn()}
        onExpand={vi.fn()}
      />,
    );
    expect(screen.getByText("services")).toBeTruthy();
    expect(screen.queryByText("main.py")).toBeNull();
  });
});
