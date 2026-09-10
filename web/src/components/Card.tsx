import type { ReactNode } from "react";

interface CardProps {
  children: ReactNode;
  /**
   * Surface level (DESIGN.md "Surfaces"): `card` = Fey Charcoal for top-level
   * panels, `elevated` = Fey Obsidian for nested wells / rows.
   */
  surface?: "card" | "elevated";
  /** DESIGN.md "always pair a dark surface with a heavy black halo". */
  halo?: boolean;
  className?: string;
}

/**
 * DESIGN.md "Product Showcase Card": 16px radius, a Fey dark surface, and a
 * single heavy black halo for floating-in-space depth (never stacked shadows).
 */
export function Card({
  children,
  surface = "card",
  halo = true,
  className = "",
}: CardProps): ReactNode {
  const surfaceClass = surface === "elevated" ? "bg-fey-obsidian" : "bg-fey-charcoal";
  const haloClass = halo ? "shadow-xl" : "";
  return (
    <section
      className={`rounded-cards ${surfaceClass} ${haloClass} p-24 ${className}`.trim()}
    >
      {children}
    </section>
  );
}
