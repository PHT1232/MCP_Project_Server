import type { IndexStatus } from "../api/types";

export interface SemanticIndicator {
  available: boolean;
  label: string;
  note: string | null;
}

const DEFAULT_UNAVAILABLE_NOTE =
  "No embedding backend is configured — keyword and structural search only (AC21).";

/**
 * AC21 / D7 — derive the semantic-search availability indicator from an index
 * status payload. When unavailable we always show a reason: the server's
 * `semantic_note` if present, otherwise a default explanation.
 */
export function semanticIndicator(status: IndexStatus): SemanticIndicator {
  const note =
    typeof status.semantic_note === "string" && status.semantic_note.trim() !== ""
      ? status.semantic_note.trim()
      : null;

  if (status.semantic_available) {
    return {
      available: true,
      label: "Semantic search available",
      note,
    };
  }
  return {
    available: false,
    label: "Semantic search unavailable",
    note: note ?? DEFAULT_UNAVAILABLE_NOTE,
  };
}
