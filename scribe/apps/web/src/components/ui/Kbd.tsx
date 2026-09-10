import type { ReactNode } from "react";

export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="inline-block rounded border border-rule bg-rule-soft px-1.5 py-0.5 font-mono text-[11px] leading-none text-muted">
      {children}
    </kbd>
  );
}
