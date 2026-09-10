import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import type { CodeMapDoc } from "../lib/codemapDoc";
import { CodeMapDocument } from "./CodeMapDocument";

const DOC: CodeMapDoc = {
  projectName: "acme",
  totalFiles: 42,
  languages: ["python", "typescript"],
  lastCommit: "abcdef1234",
  overview: "A shared briefing for agents.",
  areas: [
    {
      path: "server",
      label: "server",
      kind: "directory",
      language: "python",
      fileCount: 30,
      loc: 6000,
      fanIn: 1,
      fanOut: 0,
      tone: "ember",
      badges: ["2 blockers", "current focus"],
      dependsOn: [],
      children: [
        { path: "server/src", label: "src", fileCount: 25, language: "python", tone: null },
      ],
      moreChildren: 2,
    },
    {
      path: "web",
      label: "web",
      kind: "directory",
      language: "typescript",
      fileCount: 20,
      loc: 3000,
      fanIn: 0,
      fanOut: 1,
      tone: null,
      badges: [],
      dependsOn: ["server"],
      children: [],
      moreChildren: 0,
    },
  ],
  connections: ["web → server"],
};

describe("CodeMapDocument", () => {
  it("renders the overview, areas, badges, children and connections", () => {
    render(
      <CodeMapDocument
        doc={DOC}
        hotSpots={[]}
        legend={["focus", "blockers"]}
        onSelectPath={vi.fn()}
      />,
    );
    expect(screen.getByText("A shared briefing for agents.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "server/" })).toBeTruthy();
    expect(screen.getByText("2 blockers")).toBeTruthy();
    expect(screen.getByText("current focus")).toBeTruthy();
    expect(screen.getByText("+2 more")).toBeTruthy();
    expect(screen.getByText("Depends on server")).toBeTruthy();
    expect(screen.getByText("web → server")).toBeTruthy();
  });

  it("calls onSelectPath with the full path when a path is clicked", () => {
    const onSelectPath = vi.fn();
    render(
      <CodeMapDocument
        doc={DOC}
        hotSpots={[{ path: "server/src/pcs/mcp/server.py", reasons: ["blocker: 421"] }]}
        legend={[]}
        onSelectPath={onSelectPath}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "src" }));
    expect(onSelectPath).toHaveBeenCalledWith("server/src");

    fireEvent.click(
      screen.getByRole("button", { name: "server/src/pcs/mcp/server.py" }),
    );
    expect(onSelectPath).toHaveBeenCalledWith("server/src/pcs/mcp/server.py");
  });

  it("shows a fallback when nothing connects", () => {
    render(
      <CodeMapDocument
        doc={{ ...DOC, connections: [] }}
        hotSpots={[]}
        legend={[]}
        onSelectPath={vi.fn()}
      />,
    );
    expect(
      screen.getByText("No cross-area dependencies were resolved in the index."),
    ).toBeTruthy();
  });
});
