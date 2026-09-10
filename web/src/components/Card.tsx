import type { ReactNode } from "react";

interface CardProps {
  children: ReactNode;
}

/**
 * DESIGN.md "Product Showcase Card": 16px radius, Fey Charcoal surface, a single
 * heavy black halo for floating-in-space depth (no stacked elevation).
 */
export function Card({ children }: CardProps): ReactNode {
  return (
    <section className="rounded-cards bg-fey-charcoal p-24 shadow-xl">
      {children}
    </section>
  );
}
