import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Requirement, RequirementComplianceRow as ComplianceRow } from "../api/types";
import { renderWithClient } from "../test/renderWithClient";
import { RequirementComplianceRow } from "./RequirementCompliance";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return { ...actual, getRequirementContract: vi.fn(), getRequirementEvidence: vi.fn() };
});

const client = await import("../api/client");
const getRequirementContract = vi.mocked(client.getRequirementContract);
const getRequirementEvidence = vi.mocked(client.getRequirementEvidence);

const requirement: Requirement = {
  req_key: "R-013", entry_id: "req-13", title: "Compliance dashboard",
  status: "done", lifecycle: "open", linked_files: [],
};

function row(overrides: Partial<ComplianceRow> = {}): ComplianceRow {
  return {
    requirement_id: "req-13", req_key: "R-013", status: "done",
    configured: true, verdict: "verified", ac_verified: 2, ac_total: 2,
    validation: "ok", review: "passed", exceptions: [], omitted_exceptions: 0,
    ...overrides,
  };
}

function renderRow(value: ComplianceRow): void {
  renderWithClient(<RequirementComplianceRow project="acme" requirement={requirement} row={value} statusControl={<span>Set status control</span>} />);
}

describe("requirement compliance row (T13)", () => {
  beforeEach(() => {
    getRequirementContract.mockReset();
    getRequirementEvidence.mockReset();
    getRequirementContract.mockResolvedValue({ requirement_id: "req-13", req_key: "R-013", headline: "Compliance dashboard", include: "both", invariants: [], criteria: [] });
    getRequirementEvidence.mockResolvedValue({
      requirement_id: "req-13", evidence: [], evidence_total: 0, evidence_omitted: 0, violations: [], violations_total: 0, violations_omitted: 0, limits: { evidence: 25, violations: 25 },
      close_gate: { requirement_id: "req-13", configured: true, passed: true, unmet: [], ac_verified: 2, ac_total: 2, missing: [], stale: [], blocking: [], validation: "ok", review: "passed" },
    });
  });

  it("separates implementation status from verification derived from exceptions", () => {
    renderRow(row({ verdict: "failed", exceptions: [{ kind: "missing", criterion_id: "ac-1", criterion_key: "AC-1", invariant_id: "inv-1", invariant_key: "INV-1", file_refs: [] }] }));
    expect(screen.getByText("Implementation")).toBeTruthy();
    expect(screen.getByText("Done")).toBeTruthy();
    expect(screen.getByText("Verification")).toBeTruthy();
    expect(screen.getByText("Missing")).toBeTruthy();
  });

  it("renders no criteria as explicit not configured rather than failure", () => {
    renderRow(row({ configured: false, verdict: "not-configured", ac_verified: 0, ac_total: 0, validation: "not-configured", review: "not-configured" }));
    expect(screen.getByText("Not configured")).toBeTruthy();
    expect(screen.queryByText("Failed")).toBeNull();
  });

  it("makes stale and blocking exceptions prominent", () => {
    renderRow(row({ verdict: "failed", validation: "stale", exceptions: [
      { kind: "stale", criterion_id: "ac-1", criterion_key: "AC-1", invariant_id: "inv-1", invariant_key: "INV-1", file_refs: ["tests/check.py"] },
      { kind: "blocking", violation_id: "v-1", invariant_id: "inv-1", invariant_key: "INV-1", file_refs: ["src/app.py"], summary: "Review unresolved" },
    ] }));
    expect(screen.getByText("Stale").className).toContain("text-fey-ember");
    expect(screen.getByText("1 blocking").className).toContain("text-fey-ember");
    expect(screen.getByRole("listitem").className).toContain("border-fey-ember");
  });

  it("surfaces omitted exceptions and retains lazy detail reads", async () => {
    renderRow(row({ ac_verified: 1, ac_total: 2, omitted_exceptions: 3 }));
    expect(screen.getByText("3 omitted")).toBeTruthy();
    expect(getRequirementContract).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "View compliance" }));
    expect(await screen.findByText("1/2 verified")).toBeTruthy();
    expect(screen.getByText("3 more exceptions require drill-down.")).toBeTruthy();
    expect(getRequirementContract).toHaveBeenCalledWith("acme", "req-13");
    expect(getRequirementEvidence).toHaveBeenCalledWith("acme", "req-13");
  });

  it("renders review exceptions as actionable independent-review work", async () => {
    renderRow(row({ verdict: "failed", review: "failed", exceptions: [{
      kind: "review-missing", criterion_id: "ac-review", criterion_key: "AC-REVIEW",
      invariant_id: "inv-review", invariant_key: "INV-REVIEW", file_refs: [],
    }] }));
    fireEvent.click(screen.getByRole("button", { name: "View compliance" }));
    expect(await screen.findByText("Independent review missing · AC-REVIEW")).toBeTruthy();
    expect(screen.getByText("Record passing review evidence from an independent reviewer.")).toBeTruthy();
    expect(screen.queryByText("Missing implementation evidence")).toBeNull();
  });

  it("never renders criterion prose or hostile raw log and diff content", async () => {
    const hostileContent = "RAW LOG: token=secret\n@@ -1 +1 @@\n-password\n+exfiltrated";
    getRequirementContract.mockResolvedValue({
      requirement_id: "req-13", req_key: "R-013", headline: "Compliance dashboard", include: "both", invariants: [],
      criteria: [{
        id: "ac-hostile-id", project_id: "project-id", invariant_id: "inv-hostile", key: "AC-HOSTILE",
        statement: hostileContent, evidence_kind: "test", required: true, independent_review: "required",
        sort_order: 1, status: "active", author: "auditor", created_at: "2026-01-01", updated_at: "2026-01-01",
      }],
    });
    getRequirementEvidence.mockResolvedValue({
      requirement_id: "req-13",
      close_gate: { requirement_id: "req-13", configured: true, passed: false, unmet: [hostileContent], ac_verified: 1, ac_total: 2, missing: [], stale: [], blocking: [], validation: "ok", review: "passed" },
      evidence: [], evidence_total: 0, evidence_omitted: 0,
      violations: [{ id: "violation-hostile", invariant_id: "inv-hostile", severity: "blocking", status: "open", summary: hostileContent, file_refs: ["audit/check.ts"] }],
      violations_total: 1, violations_omitted: 0, limits: { evidence: 25, violations: 25 },
    });
    renderRow(row({ verdict: "failed", exceptions: [{
      kind: "blocking", violation_id: "violation-hostile", invariant_id: "inv-hostile",
      invariant_key: "INV-HOSTILE", file_refs: ["audit/check.ts"], summary: hostileContent,
    }] }));

    fireEvent.click(screen.getByRole("button", { name: "View compliance" }));

    expect(await screen.findByText("AC-HOSTILE")).toBeTruthy();
    expect(screen.getByText(/ac-hostile-id · test evidence · review required/i)).toBeTruthy();
    expect(screen.getAllByText(/violation-hostile · inv-hostile/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/audit\/check\.ts/)).toBeTruthy();
    expect(screen.queryByText(hostileContent)).toBeNull();
    expect(document.body.textContent).not.toContain("RAW LOG");
    expect(document.body.textContent).not.toContain("@@ -1 +1 @@");
    expect(document.body.textContent).not.toContain("exfiltrated");
  });

  it("separates bounded warning details from blocking exception counts", async () => {
    getRequirementEvidence.mockResolvedValue({
      requirement_id: "req-13",
      close_gate: { requirement_id: "req-13", configured: true, passed: false, unmet: ["independent review missing for AC-REVIEW"], ac_verified: 2, ac_total: 2, missing: [], stale: [], blocking: [], validation: "ok", review: "failed" },
      evidence: [{ id: "e-1", criterion_id: "ac-review", contract_revision_id: "rev-1", kind: "test", result: "passed", source_commit: "0123456789012345678901234567890123456789", file_refs: ["tests/review.py"], seq: 9 }],
      evidence_total: 5,
      evidence_omitted: 4,
      violations: [{ id: "warning-1", invariant_id: "inv-1", severity: "warning", status: "open", summary: "Add boundary coverage", file_refs: ["src/app.py:12"] }],
      violations_total: 3,
      violations_omitted: 2,
      limits: { evidence: 25, violations: 25 },
    });
    renderRow(row());
    fireEvent.click(screen.getByRole("button", { name: "View compliance" }));
    expect(await screen.findByText(/Evidence summary · 1 shown of 5 · 4 omitted/)).toBeTruthy();
    expect(screen.getByText(/Warning violations · 1 shown open · 3 total · 2 violations omitted/)).toBeTruthy();
    expect(screen.getByText("Warning · warning-1 · inv-1")).toBeTruthy();
    expect(screen.queryByText("Add boundary coverage")).toBeNull();
    expect(screen.getByText("0 open blocking")).toBeTruthy();
  });

});
