import type { ButtonHTMLAttributes, ReactNode } from "react";

interface PillButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  children: ReactNode;
  size?: "sm" | "md";
}

/**
 * DESIGN.md "Primary Action Button": 99px radius, ghost (no chromatic fill),
 * white Calibre text, defined by shape + a soft white halo. Fey has no distinct
 * CTA fill colour — every action is ghost / text-style on the dark surface.
 */
export function PillButton({
  children,
  type = "button",
  disabled,
  size = "md",
  className = "",
  ...rest
}: PillButtonProps): ReactNode {
  const sizeClass = size === "sm" ? "px-14 py-6 text-caption" : "px-20 py-8 text-body";
  return (
    <button
      type={type}
      disabled={disabled}
      className={`rounded-buttons border border-fey-smoke bg-fey-ink ${sizeClass} font-medium text-fey-white shadow-md transition-opacity disabled:opacity-40 ${className}`.trim()}
      {...rest}
    >
      {children}
    </button>
  );
}
