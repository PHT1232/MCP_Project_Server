import type { ReactNode } from "react";

import { useLocation } from "../router/context";
import { Link } from "../router/router";

interface PillNavProps {
  children: ReactNode;
  className?: string;
}

/** DESIGN.md "Pill Navigation Button" container — a horizontal row of nav items. */
export function PillNav({ children, className = "" }: PillNavProps): ReactNode {
  return (
    <nav className={`flex flex-wrap items-center gap-16 ${className}`.trim()}>
      {children}
    </nav>
  );
}

interface PillNavLinkProps {
  to: string;
  children: ReactNode;
  /** Match if the current path starts with `to` (for section sub-routes). */
  prefix?: boolean;
}

/**
 * DESIGN.md "Pill Navigation Button": 99px shape, no fill, 12–14px Calibre 500.
 * Active = Fey Signal 1px bottom border + white text; inactive = Fey Graphite.
 * Signal is used here strictly as a *navigation* accent (never a status colour).
 */
export function PillNavLink({
  to,
  children,
  prefix = false,
}: PillNavLinkProps): ReactNode {
  const path = useLocation();
  const active = prefix ? path.startsWith(to) : path === to;
  const stateClass = active
    ? "border-fey-signal text-fey-white"
    : "border-transparent text-fey-graphite";
  return (
    <Link
      to={to}
      className={`rounded-buttons border-b px-14 py-6 text-body font-medium no-underline transition-colors ${stateClass}`}
      aria-current={active ? "page" : undefined}
    >
      {children}
    </Link>
  );
}
