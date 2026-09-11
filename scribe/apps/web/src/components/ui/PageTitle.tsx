import type { ReactNode } from "react";

export function PageTitle({
  children,
  actions,
  eyebrow,
}: {
  children: ReactNode;
  actions?: ReactNode;
  eyebrow?: ReactNode;
}) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        {eyebrow && (
          <div className="mb-1 font-mono text-[11px] uppercase tracking-wider text-muted">
            {eyebrow}
          </div>
        )}
        <h1 className="wide font-display text-2xl font-semibold leading-tight text-ink">
          {children}
        </h1>
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}
