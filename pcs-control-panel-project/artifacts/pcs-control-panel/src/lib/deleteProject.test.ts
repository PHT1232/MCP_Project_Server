import { describe, expect, it } from "vitest";
import { canConfirmProjectDelete } from "./deleteProject";

describe("canConfirmProjectDelete", () => {
  it("enables confirm only when the typed value matches the project name exactly after trim", () => {
    expect(canConfirmProjectDelete("northstar", "northstar")).toBe(true);
    expect(canConfirmProjectDelete("  northstar  ", "northstar")).toBe(true);
  });

  it("treats empty, partial, and mismatched names as cancelled / not ready", () => {
    expect(canConfirmProjectDelete("", "northstar")).toBe(false);
    expect(canConfirmProjectDelete("north", "northstar")).toBe(false);
    expect(canConfirmProjectDelete("Northstar", "northstar")).toBe(false);
  });
});
