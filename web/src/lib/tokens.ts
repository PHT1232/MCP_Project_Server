/**
 * DESIGN.md tokens for the Sigma canvas (NFR15 / AC27).
 *
 * The code map renders to WebGL/canvas through Sigma, which cannot consume
 * Tailwind utility classes — it needs concrete colour strings. So the palette is
 * read from the `tokens.css` custom properties at runtime via `getComputedStyle`
 * (the single source of truth). `FALLBACK` mirrors `tokens.css` verbatim and is
 * only used where no computed style exists (jsdom under vitest); the real app
 * always resolves the live token values.
 */

const FALLBACK: Readonly<Record<string, string>> = {
  "--color-fey-white": "#ffffff",
  "--color-fey-ink": "#0b0b0b",
  "--color-fey-charcoal": "#191919",
  "--color-fey-obsidian": "#131313",
  "--color-fey-graphite": "#868f97",
  "--color-fey-mist": "#cccccc",
  "--color-fey-smoke": "#525252",
  "--color-fey-ember": "#ffa16c",
  "--color-fey-signal": "#479ffa",
  "--color-fey-growth": "#4ebe96",
};

export function readToken(name: string): string {
  if (typeof document !== "undefined" && typeof getComputedStyle === "function") {
    const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    if (value !== "") {
      return value;
    }
  }
  return FALLBACK[name] ?? FALLBACK["--color-fey-graphite"] ?? "#868f97";
}

export interface CodeMapPalette {
  canvas: string;
  label: string;
  edge: string;
  /** Base node fills by kind. */
  directory: string;
  file: string;
  external: string;
  stub: string;
  /** Overlay tones (FR33) — mirror the StatusBadge tones; never Signal blue. */
  hot: string;
  focus: string;
  requirement: string;
  /** Selection ring — Signal is allowed here purely as a navigation accent. */
  selected: string;
}

export function codeMapPalette(): CodeMapPalette {
  return {
    canvas: readToken("--color-fey-ink"),
    label: readToken("--color-fey-mist"),
    edge: readToken("--color-fey-smoke"),
    directory: readToken("--color-fey-mist"),
    file: readToken("--color-fey-graphite"),
    external: readToken("--color-fey-smoke"),
    stub: readToken("--color-fey-smoke"),
    hot: readToken("--color-fey-ember"),
    focus: readToken("--color-fey-growth"),
    requirement: readToken("--color-fey-white"),
    selected: readToken("--color-fey-signal"),
  };
}
