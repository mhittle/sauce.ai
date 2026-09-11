import type { ReactNode } from "react";

export function EmptyState({
  title,
  description,
  action,
  className = "",
}: {
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-rule px-6 py-10 text-center ${className}`}
    >
      <div className="wide font-display text-base font-semibold text-ink">
        {title}
      </div>
      {description && (
        <p className="max-w-md text-sm text-muted">{description}</p>
      )}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}
