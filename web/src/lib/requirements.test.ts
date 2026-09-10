import { describe, expect, it } from "vitest";

import { doneFraction, doneSummary, requirementStatusLabel } from "./requirements";

describe("doneSummary (FR36a 'N of M done')", () => {
  it("formats the count", () => {
    expect(doneSummary(12, 20)).toBe("12 of 20 done");
  });

  it("handles an empty requirement set", () => {
    expect(doneSummary(0, 0)).toBe("0 of 0 done");
  });

  it("clamps a stale done count to the total", () => {
    expect(doneSummary(25, 20)).toBe("20 of 20 done");
  });

  it("floors fractional / negative inputs", () => {
    expect(doneSummary(-3, 10.9)).toBe("0 of 10 done");
  });
});

describe("doneFraction", () => {
  it("is zero when there are no requirements", () => {
    expect(doneFraction(0, 0)).toBe(0);
  });

  it("is the completed ratio", () => {
    expect(doneFraction(3, 12)).toBe(0.25);
  });

  it("never exceeds 1", () => {
    expect(doneFraction(99, 10)).toBe(1);
  });
});

describe("requirementStatusLabel", () => {
  it("maps every token to a readable label", () => {
    expect(requirementStatusLabel("not-started")).toBe("Not started");
    expect(requirementStatusLabel("in-progress")).toBe("In progress");
    expect(requirementStatusLabel("blocked")).toBe("Blocked");
    expect(requirementStatusLabel("done")).toBe("Done");
  });
});
