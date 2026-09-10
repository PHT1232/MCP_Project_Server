import type { ReactNode } from "react";

import type { RequirementStatus } from "../api/types";
import { requirementStatusLabel } from "../lib/requirements";

/**
 * DESIGN.md "Status Badge": small 99px pill, minimal padding, 10–11px Calibre
 * uppercase. One chromatic accent per badge, maximum — and never Signal blue
 * (that is a navigation accent, not a status colour). Green = done (Growth),
 * Ember = attention (blocked), neutrals carry the rest.
 */
export type BadgeTone = "growth" | "ember" | "mist" | "graphite";

interface StatusBadgeProps {
  tone: BadgeTone;
  children: ReactNode;
}

const TONE_CLASS: Record<BadgeTone, string> = {
  growth: "border-fey-growth text-fey-growth",
  ember: "border-fey-ember text-fey-ember",
  mist: "border-fey-mist text-fey-mist",
  graphite: "border-fey-smoke text-fey-graphite",
};

export function StatusBadge({ tone, children }: StatusBadgeProps): ReactNode {
  return (
    <span
      className={`inline-flex items-center rounded-buttons border px-8 py-4 text-caption uppercase ${TONE_CLASS[tone]}`}
    >
      {children}
    </span>
  );
}

const REQUIREMENT_TONE: Record<RequirementStatus, BadgeTone> = {
  done: "growth",
  blocked: "ember",
  "in-progress": "mist",
  "not-started": "graphite",
};

export function RequirementStatusBadge({
  status,
}: {
  status: RequirementStatus;
}): ReactNode {
  return (
    <StatusBadge tone={REQUIREMENT_TONE[status]}>
      {requirementStatusLabel(status)}
    </StatusBadge>
  );
}
