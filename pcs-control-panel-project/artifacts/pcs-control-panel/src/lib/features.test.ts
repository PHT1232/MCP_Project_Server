import { describe, expect, it } from "vitest";
import type { Entry, Requirement } from "@workspace/api-client-react";
import { resolveFeatureRequirements } from "./features";

function feature(partial: Partial<Entry> & Pick<Entry, "id"> = { id: "f1" }): Entry {
  return {
    id: "f1",
    project_id: "p1",
    section: "features",
    headline: "Checkout",
    detail: "Takes a cart + payment method, returns an order confirmation.",
    status: "open",
    priority: 0,
    author: "agent",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    requirement_status: null,
    linked_files: [],
    related_entry_id: null,
    req_key: null,
    ...partial,
  };
}

function requirement(partial: Partial<Requirement> = {}): Requirement {
  return {
    req_key: "R-001",
    entry_id: "req1",
    title: "Checkout supports Apple Pay",
    status: "done",
    lifecycle: "open",
    linked_files: [],
    ...partial,
  };
}

describe("resolveFeatureRequirements", () => {
  it("pairs a feature with the requirement its related_entry_id points at", () => {
    const req = requirement({ entry_id: "req1" });
    const [resolved] = resolveFeatureRequirements(
      [feature({ id: "f1", related_entry_id: "req1" })],
      [req],
    );
    expect(resolved.requirement).toEqual(req);
  });

  it("resolves to undefined when related_entry_id is null", () => {
    const [resolved] = resolveFeatureRequirements(
      [feature({ id: "f1", related_entry_id: null })],
      [requirement({ entry_id: "req1" })],
    );
    expect(resolved.requirement).toBeUndefined();
  });

  it("resolves to undefined when related_entry_id points at no known requirement (e.g. archived)", () => {
    const [resolved] = resolveFeatureRequirements(
      [feature({ id: "f1", related_entry_id: "does-not-exist" })],
      [requirement({ entry_id: "req1" })],
    );
    expect(resolved.requirement).toBeUndefined();
  });

  it("returns an empty list for an empty feature list, not an error", () => {
    expect(resolveFeatureRequirements([], [requirement()])).toEqual([]);
  });

  it("preserves feature order and pairs multiple features independently", () => {
    const reqA = requirement({ entry_id: "req-a", title: "A" });
    const reqB = requirement({ entry_id: "req-b", title: "B" });
    const resolved = resolveFeatureRequirements(
      [
        feature({ id: "f1", related_entry_id: "req-b" }),
        feature({ id: "f2", related_entry_id: "req-a" }),
        feature({ id: "f3", related_entry_id: null }),
      ],
      [reqA, reqB],
    );
    expect(resolved.map((r) => r.feature.id)).toEqual(["f1", "f2", "f3"]);
    expect(resolved[0].requirement?.title).toBe("B");
    expect(resolved[1].requirement?.title).toBe("A");
    expect(resolved[2].requirement).toBeUndefined();
  });
});
