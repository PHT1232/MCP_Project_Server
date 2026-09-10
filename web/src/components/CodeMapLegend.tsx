import type { ReactNode } from "react";

import type { BadgeTone } from "./StatusBadge";

/** FR33 — legend for the context overlay, ordered by the server's `overlay_legend`. */
const SECTION_TONE: Record<string, BadgeTone> = {
  focus: "growth",
  blockers: "ember",
  bugs: "ember",
  requirements: "mist",
};

const DOT_CLASS: Record<BadgeTone, string> = {
  growth: "bg-fey-growth",
  ember: "bg-fey-ember",
  mist: "bg-fey-white",
  graphite: "bg-fey-graphite",
};

export function CodeMapLegend({ legend }: { legend: readonly string[] }): ReactNode {
  return (
    <div className="flex flex-wrap items-center gap-16">
      {legend.map((section) => {
        const tone = SECTION_TONE[section] ?? "graphite";
        return (
          <span key={section} className="flex items-center gap-6">
            <span
              className={`inline-block h-8 w-8 rounded-full ${DOT_CLASS[tone]}`}
              aria-hidden
            />
            <span className="text-caption uppercase text-fey-graphite">{section}</span>
          </span>
        );
      })}
    </div>
  );
}
