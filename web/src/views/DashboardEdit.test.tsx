import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";

import type { Entry, SectionResponse } from "../api/types";
import { renderWithClient } from "../test/renderWithClient";
import { SectionPanel } from "./SectionPanel";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return {
    ...actual,
    getSection: vi.fn(),
    addEntry: vi.fn(),
    updateEntry: vi.fn(),
    resolveEntry: vi.fn(),
  };
});

const client = await import("../api/client");
const getSection = vi.mocked(client.getSection);
const addEntry = vi.mocked(client.addEntry);

function entry(overrides: Partial<Entry>): Entry {
  return {
    id: "e1",
    project_id: "p",
    section: "blockers",
    headline: "old blocker",
    detail: "still stuck",
    status: "open",
    priority: 0,
    author: "tester",
    created_at: "2026-09-10T00:00:00Z",
    updated_at: "2026-09-10T00:00:00Z",
    requirement_status: null,
    linked_files: [],
    related_entry_id: null,
    req_key: null,
    ...overrides,
  };
}

function section(entries: Entry[]): SectionResponse {
  return { section: "blockers", entries };
}

describe("dashboard edit → refetch (AC14, D6)", () => {
  beforeEach(() => {
    getSection.mockReset();
    addEntry.mockReset();
  });

  it("re-fetches the section after a create so the new entry appears", async () => {
    getSection.mockResolvedValueOnce(section([entry({ id: "e1" })]));
    addEntry.mockResolvedValueOnce(entry({ id: "e2", headline: "new blocker" }));
    getSection.mockResolvedValueOnce(
      section([entry({ id: "e1" }), entry({ id: "e2", headline: "new blocker" })]),
    );

    renderWithClient(
      <SectionPanel
        project="p"
        section="blockers"
        title="Blockers"
        description="test"
      />,
    );

    await screen.findByText("old blocker");
    expect(getSection).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    fireEvent.change(screen.getByLabelText("Headline"), {
      target: { value: "new blocker" },
    });
    fireEvent.change(screen.getByLabelText("Detail"), {
      target: { value: "a fresh problem" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add entry" }));

    await waitFor(() => {
      expect(addEntry).toHaveBeenCalledWith("p", {
        section: "blockers",
        headline: "new blocker",
        detail: "a fresh problem",
      });
    });

    // The mutation invalidates the section query → a second fetch (D6: only an
    // edit or the manual refresh brings in new data).
    await waitFor(() => {
      expect(getSection).toHaveBeenCalledTimes(2);
    });
    await screen.findByText("new blocker");
  });
});
