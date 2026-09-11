export interface Step {
  key: string;
  label: string;
  hint?: string;
}

// The job stepper from product-plan.md §2: done steps carry a green top rule,
// the current step the redline, upcoming steps a neutral one.
export function Stepper({
  steps,
  current,
  onSelect,
}: {
  steps: Step[];
  current: number;
  onSelect?: (index: number) => void;
}) {
  return (
    <ol className="flex overflow-x-auto" aria-label="Progress">
      {steps.map((s, i) => {
        const state = i < current ? "done" : i === current ? "now" : "next";
        const top =
          state === "done"
            ? "border-t-good"
            : state === "now"
              ? "border-t-accent"
              : "border-t-rule";
        const clickable = onSelect && i <= current;
        return (
          <li
            key={s.key}
            aria-current={state === "now" ? "step" : undefined}
            className={`min-w-28 flex-1 border border-r-0 border-rule border-t-[3px] bg-paper px-3 py-2 first:rounded-l-md last:rounded-r-md last:border-r ${top} ${
              clickable ? "cursor-pointer hover:bg-rule-soft" : ""
            }`}
            onClick={clickable ? () => onSelect(i) : undefined}
          >
            <div className="font-mono text-[10px] tracking-wider text-muted">
              {String(i + 1).padStart(2, "0")}
            </div>
            <div
              className={`wide font-display text-sm font-semibold ${
                state === "now" ? "text-accent" : "text-ink"
              }`}
            >
              {s.label}
            </div>
            {s.hint && (
              <div className="text-[11px] leading-snug text-muted">{s.hint}</div>
            )}
          </li>
        );
      })}
    </ol>
  );
}
