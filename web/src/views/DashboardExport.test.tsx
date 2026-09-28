import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ProjectContextExport } from "../api/client";
import { renderWithClient } from "../test/renderWithClient";
import { DashboardView } from "./DashboardView";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return {
    ...actual,
    getBriefing: vi.fn(),
    getSection: vi.fn(),
    exportProjectContext: vi.fn(),
  };
});

vi.mock("../lib/download", () => ({
  downloadFile: vi.fn(),
}));

const client = await import("../api/client");
const download = await import("../lib/download");
const getBriefing = vi.mocked(client.getBriefing);
const getSection = vi.mocked(client.getSection);
const exportProjectContext = vi.mocked(client.exportProjectContext);
const downloadFile = vi.mocked(download.downloadFile);

const ENVELOPE_MD: ProjectContextExport = {
  format: "markdown",
  filename: "acme-context.md",
  media_type: "text/markdown; charset=utf-8",
  content: "# acme — project context export\n\n## Overview\n",
  project: { id: "p1", name: "acme", root_path: "/repos/acme" },
  exported_at: "2026-09-28T00:00:00+00:00",
};

const ENVELOPE_JSON: ProjectContextExport = {
  ...ENVELOPE_MD,
  format: "json",
  filename: "acme-context.json",
  media_type: "application/json; charset=utf-8",
  content: '{\n  "project": { "name": "acme" }\n}\n',
};

describe("DashboardView export panel (T31)", () => {
  beforeEach(() => {
    getBriefing.mockReset();
    getSection.mockReset();
    exportProjectContext.mockReset();
    downloadFile.mockReset();
    getBriefing.mockResolvedValue({ project: "acme", briefing: "# briefing" });
    getSection.mockResolvedValue({ section: "blockers", entries: [] });
  });

  it("downloads Markdown and JSON with the server filename and content", async () => {
    exportProjectContext
      .mockResolvedValueOnce(ENVELOPE_MD)
      .mockResolvedValueOnce(ENVELOPE_JSON);

    renderWithClient(<DashboardView project="acme" />);

    await screen.findByRole("heading", { name: "Export project context" });

    fireEvent.click(screen.getByRole("button", { name: "Download Markdown" }));
    await waitFor(() => {
      expect(exportProjectContext).toHaveBeenCalledWith("acme", "markdown");
      expect(downloadFile).toHaveBeenCalledWith(
        "acme-context.md",
        ENVELOPE_MD.content,
        ENVELOPE_MD.media_type,
      );
    });

    fireEvent.click(screen.getByRole("button", { name: "Download JSON" }));
    await waitFor(() => {
      expect(exportProjectContext).toHaveBeenCalledWith("acme", "json");
      expect(downloadFile).toHaveBeenCalledWith(
        "acme-context.json",
        ENVELOPE_JSON.content,
        ENVELOPE_JSON.media_type,
      );
    });
  });

  it("surfaces export errors via the Callout pattern", async () => {
    exportProjectContext.mockRejectedValueOnce(new Error("export boom"));

    renderWithClient(<DashboardView project="acme" />);
    await screen.findByRole("heading", { name: "Export project context" });

    fireEvent.click(screen.getByRole("button", { name: "Download Markdown" }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("export boom");
    expect(downloadFile).not.toHaveBeenCalled();
  });
});
