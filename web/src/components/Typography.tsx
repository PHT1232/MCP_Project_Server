import type { ReactNode } from "react";

interface HeadlineProps {
  children: ReactNode;
  /** `display` (48px) for page headers, `heading` (24px) for section headers. */
  size?: "display" | "heading";
  className?: string;
}

/**
 * DESIGN.md "Section Headline": Calibre 700, white, the signature negative
 * tracking (carried by the `text-display` / `text-heading` tokens). A trailing
 * period on a short statement is deliberate punctuation.
 */
export function Headline({
  children,
  size = "display",
  className = "",
}: HeadlineProps): ReactNode {
  const sizeClass = size === "display" ? "text-display" : "text-heading";
  return (
    <h1 className={`${sizeClass} font-bold text-fey-white ${className}`.trim()}>
      {children}
    </h1>
  );
}

interface HighlightProps {
  children: ReactNode;
  /** DESIGN.md "Highlighted Word": one accent word per headline, maximum. */
  tone?: "ember" | "signal";
}

export function Highlight({ children, tone = "ember" }: HighlightProps): ReactNode {
  const toneClass = tone === "signal" ? "text-fey-signal" : "text-fey-ember";
  return <span className={toneClass}>{children}</span>;
}

interface SectionTitleProps {
  children: ReactNode;
  className?: string;
}

/** A card / panel heading — `heading-sm`, white, no chromatic accent. */
export function SectionTitle({
  children,
  className = "",
}: SectionTitleProps): ReactNode {
  return (
    <h2 className={`text-heading-sm font-medium text-fey-white ${className}`.trim()}>
      {children}
    </h2>
  );
}

interface CaptionProps {
  children: ReactNode;
  className?: string;
}

/** DESIGN.md caption: 10px Calibre, Fey Graphite, often uppercase. */
export function Caption({ children, className = "" }: CaptionProps): ReactNode {
  return (
    <p
      className={`text-caption uppercase text-fey-graphite ${className}`.trim()}
    >
      {children}
    </p>
  );
}
