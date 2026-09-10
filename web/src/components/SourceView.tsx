import { useMemo, type ReactNode } from "react";

import { highlight, type TokenKind } from "../lib/highlight";

/** Token kind → DESIGN.md token colour (one chromatic accent: Ember keywords). */
const KIND_CLASS: Record<TokenKind, string> = {
  keyword: "text-fey-ember",
  string: "text-fey-mist",
  comment: "text-fey-graphite",
  number: "text-fey-mist",
  text: "text-fey-pale",
};

interface Piece {
  text: string;
  kind: TokenKind;
}

function toLines(source: string, language: string | null): Piece[][] {
  const lines: Piece[][] = [[]];
  for (const token of highlight(source, language)) {
    const parts = token.text.split("\n");
    parts.forEach((part, index) => {
      if (index > 0) {
        lines.push([]);
      }
      if (part !== "") {
        lines[lines.length - 1]?.push({ text: part, kind: token.kind });
      }
    });
  }
  return lines;
}

/**
 * FR34 / AC13 — read-only, syntax-highlighted source with a line-number gutter.
 * The highlighter is the tiny in-repo `lib/highlight` pass (NFR13).
 */
export function SourceView({
  source,
  language,
}: {
  source: string;
  language: string | null;
}): ReactNode {
  const lines = useMemo(() => toLines(source, language), [source, language]);

  return (
    <div className="max-h-[60vh] overflow-auto rounded-small border border-fey-smoke bg-fey-ink">
      <pre className="min-w-full text-caption">
        <code className="block">
          {lines.map((pieces, index) => (
            <span key={index} className="flex gap-14">
              <span className="sticky left-0 select-none bg-fey-ink pr-8 text-right text-fey-smoke tabular-nums">
                {index + 1}
              </span>
              <span className="whitespace-pre text-fey-pale">
                {pieces.map((piece, pieceIndex) => (
                  <span key={pieceIndex} className={KIND_CLASS[piece.kind]}>
                    {piece.text}
                  </span>
                ))}
              </span>
            </span>
          ))}
        </code>
      </pre>
    </div>
  );
}
