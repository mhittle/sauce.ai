import { useEffect, useLayoutEffect, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Button } from "./Button";

// A small callout pinned to an element tagged data-tour="<anchor>". It never
// blocks input: the page stays usable while the mark points. Re-measures on
// resize/scroll; returns null when the anchor is not on the page.
export function Coachmark({
  anchor,
  title,
  children,
  step,
  total,
  onNext,
  onSkip,
  last,
}: {
  anchor: string;
  title: string;
  children: ReactNode;
  step: number;
  total: number;
  onNext: () => void;
  onSkip: () => void;
  last: boolean;
}) {
  const [box, setBox] = useState<{ top: number; left: number; below: boolean } | null>(null);

  useLayoutEffect(() => {
    function measure() {
      const el = document.querySelector<HTMLElement>(`[data-tour="${anchor}"]`);
      if (!el) {
        setBox(null);
        return;
      }
      const r = el.getBoundingClientRect();
      const below = r.bottom + 160 < window.innerHeight;
      setBox({
        top: below ? r.bottom + 8 : r.top - 8,
        left: Math.min(Math.max(r.left, 12), window.innerWidth - 300),
        below,
      });
    }
    measure();
    const id = window.setTimeout(measure, 250);
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    return () => {
      window.clearTimeout(id);
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
    };
  }, [anchor]);

  useEffect(() => {
    const el = document.querySelector<HTMLElement>(`[data-tour="${anchor}"]`);
    el?.classList.add("tour-target");
    return () => el?.classList.remove("tour-target");
  }, [anchor]);

  if (!box) return null;
  return createPortal(
    <div
      role="dialog"
      aria-label={title}
      className="fixed z-50 w-72 rounded-lg border border-accent bg-paper p-3 text-ink shadow-lg"
      style={{
        top: box.below ? box.top : undefined,
        bottom: box.below ? undefined : window.innerHeight - box.top,
        left: box.left,
      }}
    >
      <div className="mb-1 flex items-baseline justify-between gap-2">
        <div className="text-sm font-semibold">{title}</div>
        <div className="font-mono text-[10px] text-faint">
          {step}/{total}
        </div>
      </div>
      <div className="text-sm text-muted">{children}</div>
      <div className="mt-3 flex items-center justify-between">
        <button type="button" className="text-xs text-faint hover:text-ink hover:underline" onClick={onSkip}>
          Skip tour
        </button>
        <Button size="sm" variant="primary" onClick={onNext}>
          {last ? "Got it" : "Next"}
        </Button>
      </div>
    </div>,
    document.body
  );
}
