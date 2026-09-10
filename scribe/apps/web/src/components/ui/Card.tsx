import type { ReactNode } from "react";

export function Card({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={`rounded-lg border border-rule bg-paper p-4 ${className}`}>
      {children}
    </div>
  );
}

// Section label inside a card or above a table.
export function SectionLabel({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <h2
      className={`mb-2 font-mono text-[11px] font-medium uppercase tracking-wider text-muted ${className}`}
    >
      {children}
    </h2>
  );
}
