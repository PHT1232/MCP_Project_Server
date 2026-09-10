import type { ReactNode } from "react";

interface CalloutProps {
  children: ReactNode;
  /**
   * `alert` uses Ember (DESIGN.md: orange-on-black reads as urgency); `muted`
   * is Graphite for neutral notices. No Signal blue — it is not a status colour.
   */
  tone?: "alert" | "muted";
  title?: string;
}

export function Callout({
  children,
  tone = "muted",
  title,
}: CalloutProps): ReactNode {
  const toneClass =
    tone === "alert"
      ? "border-fey-ember text-fey-ember"
      : "border-fey-smoke text-fey-graphite";
  return (
    <div
      className={`rounded-small border px-14 py-10 text-body ${toneClass}`}
      role={tone === "alert" ? "alert" : undefined}
    >
      {title !== undefined && (
        <p className="text-caption uppercase">{title}</p>
      )}
      {children}
    </div>
  );
}
