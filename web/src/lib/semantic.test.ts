import { describe, expect, it } from "vitest";

import type { IndexStatus } from "../api/types";
import { semanticIndicator } from "./semantic";

function status(overrides: Partial<IndexStatus>): IndexStatus {
  return {
    project_id: "p",
    project_name: "p",
    state: "ready",
    last_full_at: null,
    last_incremental_at: null,
    last_commit: null,
    file_count: 0,
    chunk_count: 0,
    skipped_count: 0,
    skipped: [],
    semantic_available: false,
    ...overrides,
  };
}

describe("semanticIndicator (AC21 / D7)", () => {
  it("reports unavailable with a default reason when no backend is configured", () => {
    const indicator = semanticIndicator(status({ semantic_available: false }));
    expect(indicator.available).toBe(false);
    expect(indicator.label).toBe("Semantic search unavailable");
    expect(indicator.note).toContain("No embedding backend");
  });

  it("prefers the server's semantic_note when present", () => {
    const indicator = semanticIndicator(
      status({ semantic_available: false, semantic_note: "OPENAI_API_KEY unset" }),
    );
    expect(indicator.available).toBe(false);
    expect(indicator.note).toBe("OPENAI_API_KEY unset");
  });

  it("reports available once a backend is configured", () => {
    const indicator = semanticIndicator(
      status({ semantic_available: true, semantic_note: null }),
    );
    expect(indicator.available).toBe(true);
    expect(indicator.label).toBe("Semantic search available");
    expect(indicator.note).toBeNull();
  });

  it("ignores a blank semantic_note", () => {
    const indicator = semanticIndicator(
      status({ semantic_available: false, semantic_note: "   " }),
    );
    expect(indicator.note).toContain("No embedding backend");
  });
});
