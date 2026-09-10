import type { ButtonHTMLAttributes, ReactNode } from "react";

interface PillButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  children: ReactNode;
}

/**
 * DESIGN.md "Primary Action Button": 99px radius, ghost (no chromatic fill),
 * white Calibre text, defined by shape + a soft white halo.
 */
export function PillButton({
  children,
  type = "button",
  disabled,
  ...rest
}: PillButtonProps): ReactNode {
  return (
    <button
      type={type}
      disabled={disabled}
      className="rounded-buttons border border-fey-smoke bg-fey-ink px-20 py-8 text-body font-medium text-fey-white shadow-md transition-opacity disabled:opacity-40"
      {...rest}
    >
      {children}
    </button>
  );
}
