import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Requirement, RequirementComplianceResponse } from "../api/types";
import { renderWithClient } from "../test/renderWithClient";
import { RequirementsView } from "./RequirementsView";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return {
    ...actual,
    listRequirements: vi.fn(),
    reviewRequirementCompliance: vi.fn(),
    addEntry: vi.fn(),
    updateEntry: vi.fn(),
    syncRequirements: vi.fn(),
  };
});

const client = await import("../api/client");
const listRequirements = vi.mocked(client.listRequirements);
const reviewRequirementCompliance = vi.mocked(client.reviewRequirementCompliance);

function requirement(index: number): Requirement {
  return {
    req_key: `R-${String(index).padStart(3, "0")}`,
    entry_id: `req-${String(index)}`,
    title: `Requirement ${String(index)}`,
    status: "in-progress",
    lifecycle: "open",
    linked_files: [],
  };
}

describe("RequirementsView compliance batching (T13)", () => {
  beforeEach(() => {
    listRequirements.mockReset();
    reviewRequirementCompliance.mockReset();
  });

  it("keeps every row usable and marks only a failed compliance batch unavailable", async () => {
    const requirements = Array.from({ length: 26 }, (_, index) => requirement(index + 1));
    listRequirements.mockResolvedValue({ requirements, done_count: 0, total_count: 26 });
    reviewRequirementCompliance.mockImplementation(
      (_project, ids): Promise<RequirementComplianceResponse> => {
        if (ids.includes("req-26")) return Promise.reject(new Error("hostile internal batch trace"));
        return Promise.resolve({
          project_id: "project-id",
          requirements: ids.map((id) => {
            const source = requirements.find((item) => item.entry_id === id);
            if (source === undefined) throw new Error("unknown fixture id");
            return {
              requirement_id: id,
              req_key: source.req_key,
              status: source.status,
              configured: true,
              verdict: "verified",
              ac_verified: 1,
              ac_total: 1,
              validation: "ok",
              review: "passed",
              exceptions: [],
              omitted_exceptions: 0,
            };
          }),
          reviewed_count: ids.length,
          omitted_requirements: 0,
          limits: { requirements: 25, exceptions_per_requirement: 8 },
        });
      },
    );

    renderWithClient(<RequirementsView project="acme" />);

    expect(await screen.findAllByText("Current")).toHaveLength(25);
    expect(screen.getByText("Compliance batch 2 could not be loaded.")).toBeTruthy();
    expect(screen.getByText("Compliance unavailable for this requirement.")).toBeTruthy();
    expect(screen.getByText("R-026 · Requirement 26")).toBeTruthy();
    expect(screen.queryByText("hostile internal batch trace")).toBeNull();
    expect(screen.queryByText("Loading compliance…")).toBeNull();
    expect(screen.getAllByLabelText("Set status")).toHaveLength(26);
    expect(screen.getAllByRole("button", { name: "View compliance" })).toHaveLength(25);

    const failedBatchStatus = screen.getAllByLabelText("Set status")[25];
    if (failedBatchStatus === undefined) throw new Error("missing failed-batch status control");
    fireEvent.change(failedBatchStatus, { target: { value: "done" } });
    await waitFor(() => {
      expect(client.updateEntry).toHaveBeenCalledWith("acme", "req-26", { status: "done" });
    });

    expect(reviewRequirementCompliance).toHaveBeenCalledTimes(2);
    expect(reviewRequirementCompliance.mock.calls[0]?.[1]).toHaveLength(25);
    expect(reviewRequirementCompliance.mock.calls[1]?.[1]).toEqual(["req-26"]);
  });
});
