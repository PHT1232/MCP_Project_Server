import { describe, expect, it } from "vitest";
import type { TokenSavingsOperationSummary } from "@workspace/api-client-react";
import {
  averageSavedPerCall,
  formatTokenCount,
  savingsPercent,
  sortByImpact,
} from "./tokenSavings";

function summary(partial: Partial<TokenSavingsOperationSummary> = {}): TokenSavingsOperationSummary {
  return {
    operation: "retrieve_context",
    call_count: 0,
    actual_tokens_total: 0,
    baseline_tokens_total: 0,
    saved_tokens_total: 0,
    ...partial,
  };
}

describe("savingsPercent", () => {
  it("computes a rounded percentage", () => {
    expect(savingsPercent(summary({ baseline_tokens_total: 1000, saved_tokens_total: 750 }))).toBe(75);
  });

  it("is 0 for a zero baseline rather than NaN or Infinity", () => {
    expect(savingsPercent(summary({ baseline_tokens_total: 0, saved_tokens_total: 0 }))).toBe(0);
  });

  it("clamps to 100 even if saved somehow exceeds baseline", () => {
    expect(savingsPercent(summary({ baseline_tokens_total: 10, saved_tokens_total: 50 }))).toBe(100);
  });

  it("clamps to 0 for a negative saved total (defensive)", () => {
    expect(savingsPercent(summary({ baseline_tokens_total: 100, saved_tokens_total: -10 }))).toBe(0);
  });
});

describe("averageSavedPerCall", () => {
  it("divides and floors", () => {
    expect(averageSavedPerCall(summary({ call_count: 3, saved_tokens_total: 10 }))).toBe(3);
  });

  it("is 0 when there were no calls, not a division error", () => {
    expect(averageSavedPerCall(summary({ call_count: 0, saved_tokens_total: 0 }))).toBe(0);
  });
});

describe("formatTokenCount", () => {
  it("passes small numbers through unchanged", () => {
    expect(formatTokenCount(0)).toBe("0");
    expect(formatTokenCount(999)).toBe("999");
    expect(formatTokenCount(-42)).toBe("-42");
  });

  it("formats thousands with one decimal, trimming a trailing .0", () => {
    expect(formatTokenCount(1000)).toBe("1k");
    expect(formatTokenCount(1234)).toBe("1.2k");
    expect(formatTokenCount(12345)).toBe("12.3k");
  });

  it("formats millions the same way", () => {
    expect(formatTokenCount(1_000_000)).toBe("1M");
    expect(formatTokenCount(2_500_000)).toBe("2.5M");
  });
});

describe("sortByImpact", () => {
  it("sorts descending by saved_tokens_total without mutating the input", () => {
    const input = [
      summary({ operation: "search_code", saved_tokens_total: 10 }),
      summary({ operation: "retrieve_context", saved_tokens_total: 500 }),
      summary({ operation: "prepare_task", saved_tokens_total: 100 }),
    ];
    const sorted = sortByImpact(input);
    expect(sorted.map((s) => s.operation)).toEqual(["retrieve_context", "prepare_task", "search_code"]);
    expect(input.map((s) => s.operation)).toEqual(["search_code", "retrieve_context", "prepare_task"]);
  });
});
