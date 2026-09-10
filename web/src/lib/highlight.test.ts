import { describe, expect, it } from "vitest";

import { highlight } from "./highlight";

function kindsFor(source: string, lang: string | null): Set<string> {
  return new Set(highlight(source, lang).map((token) => token.kind));
}

describe("highlight", () => {
  it("tags keywords, strings and numbers in a code line", () => {
    const tokens = highlight('const total = 42 + "usd";', "typescript");
    const byKind = (k: string): string =>
      tokens
        .filter((t) => t.kind === k)
        .map((t) => t.text)
        .join("");
    expect(byKind("keyword")).toContain("const");
    expect(byKind("number")).toBe("42");
    expect(byKind("string")).toBe('"usd"');
  });

  it("treats # as a comment only for hash-comment languages", () => {
    expect(kindsFor("# a note\nx = 1", "python").has("comment")).toBe(true);
    expect(kindsFor("const x = obj.#priv;", "typescript").has("comment")).toBe(false);
  });

  it("round-trips the source text exactly", () => {
    const source = "def f(x):\n    return x  # done\n";
    expect(highlight(source, "python").map((t) => t.text).join("")).toBe(source);
  });

  it("handles an unterminated string without looping", () => {
    expect(highlight('x = "oops', "python").map((t) => t.text).join("")).toBe('x = "oops');
  });
});
