import { useEffect, useState } from "react";
import { Card } from "./ui";

// Mirrors @scribe/shared TakeoffProgress (kept local so the web app has no
// runtime dependency on the worker's zod schema).
export interface Progress {
  stage: string;
  done: number | null;
  total: number | null;
  message: string | null;
  started_at: string;
  updated_at: string;
}

interface StageDef {
  keys: string[];
  label: string;
  hint: string;
}

// The Reading screen's checklist. Two pipelines share it: PDFs go
// prepare → classify → (page pick) → locate → detect → measure → price;
// images and spreadsheets go read → price. A stage that never runs for the
// input is simply skipped.
const PDF_STAGES: StageDef[] = [
  { keys: ["prepare"], label: "Preparing pages", hint: "Rendering every page" },
  { keys: ["classify"], label: "Sorting page types", hint: "Plans, elevations, schedules" },
  { keys: ["locate"], label: "Finding the drawings", hint: "Each sheet's cabinet views" },
  { keys: ["detect"], label: "Finding cabinets", hint: "One pass per drawing" },
  { keys: ["measure"], label: "Measuring", hint: "Against the printed dimensions" },
  { keys: ["price"], label: "Pricing", hint: "Matching products, doors and hardware" },
];

const SIMPLE_STAGES: StageDef[] = [
  { keys: ["read"], label: "Reading", hint: "Extracting the cabinet list" },
  { keys: ["price"], label: "Pricing", hint: "Matching products, doors and hardware" },
];

// After the human's Mark → Find, a build is just measure → price.
const BUILD_STAGES: StageDef[] = [
  { keys: ["measure"], label: "Measuring", hint: "Every cabinet against the printed dimensions" },
  { keys: ["price"], label: "Pricing", hint: "Matching products, doors and hardware" },
];

// Before Mark, a PDF is only being rendered for the wizard.
const PREPARE_STAGES: StageDef[] = [
  { keys: ["prepare"], label: "Preparing pages", hint: "Rendering the pages you picked" },
  { keys: ["classify"], label: "Sorting page types", hint: "Plans, elevations, schedules" },
];

type Phase = "prepare" | "build" | "read";

function phaseOf(progress: Progress | null, sourceKind: string): Phase {
  if (sourceKind !== "pdf" || progress?.stage === "read") return "read";
  if (progress?.stage === "measure" || progress?.stage === "price") return "build";
  return "prepare";
}

function stagesFor(progress: Progress | null, sourceKind: string): StageDef[] {
  switch (phaseOf(progress, sourceKind)) {
    case "build":
      return BUILD_STAGES;
    case "prepare":
      return progress?.stage === "locate" || progress?.stage === "detect" ? PDF_STAGES : PREPARE_STAGES;
    default:
      return SIMPLE_STAGES;
  }
}

const PHASE_TITLE: Record<Phase, string> = {
  prepare: "Preparing your pages",
  build: "Building your takeoff",
  read: "Reading your drawings",
};

function elapsed(fromIso: string, now: number): string {
  const s = Math.max(0, Math.round((now - new Date(fromIso).getTime()) / 1000));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  return `${m}m ${String(s % 60).padStart(2, "0")}s`;
}

export function ReadingProgress({
  progress,
  sourceKind,
  pageCount,
  fallbackStartedAt,
  title,
}: {
  progress: Progress | null;
  sourceKind: string;
  pageCount: number | null;
  fallbackStartedAt: string;
  // Defaults to the phase the progress reports (preparing / building / reading).
  title?: string;
}) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(t);
  }, []);

  const stages = stagesFor(progress, sourceKind);
  const currentIdx = progress
    ? stages.findIndex((s) => s.keys.includes(progress.stage))
    : -1;
  const startedAt = progress?.started_at ?? fallbackStartedAt;

  return (
    <Card className="mx-auto max-w-xl">
      <div className="mb-4 flex items-baseline justify-between gap-3">
        <h2 className="wide font-display text-lg font-semibold text-ink">
          {title ?? PHASE_TITLE[phaseOf(progress, sourceKind)]}
        </h2>
        <span className="font-mono text-xs tabular-nums text-muted" aria-live="off">
          {elapsed(startedAt, now)}
        </span>
      </div>
      <ol className="space-y-1" aria-label="Reading progress">
        {stages.map((s, i) => {
          const state =
            currentIdx === -1 ? (i === 0 ? "now" : "next") : i < currentIdx ? "done" : i === currentIdx ? "now" : "next";
          const showCount =
            state === "now" && progress?.total != null && progress.total > 0;
          return (
            <li
              key={s.label}
              aria-current={state === "now" ? "step" : undefined}
              className={`flex items-start gap-3 rounded-md px-2 py-1.5 ${state === "now" ? "bg-accent-soft" : ""}`}
            >
              <span
                aria-hidden
                className={`mt-1 inline-flex size-4 shrink-0 items-center justify-center rounded-full border text-[10px] font-bold ${
                  state === "done"
                    ? "border-good bg-good text-white"
                    : state === "now"
                      ? "border-accent text-accent"
                      : "border-rule text-faint"
                }`}
              >
                {state === "done" ? "✓" : state === "now" ? <Spinner /> : ""}
              </span>
              <div className="min-w-0 flex-1">
                <div
                  className={`text-sm font-medium ${
                    state === "next" ? "text-muted" : "text-ink"
                  }`}
                >
                  {s.label}
                  {showCount && (
                    <span className="ml-2 font-mono text-xs tabular-nums text-muted">
                      {progress!.done ?? 0}/{progress!.total}
                    </span>
                  )}
                </div>
                <div className="text-xs text-muted">
                  {state === "now" && progress?.message ? progress.message : s.hint}
                </div>
              </div>
            </li>
          );
        })}
      </ol>
      <p className="mt-4 text-xs text-muted">
        {pageCount != null && sourceKind === "pdf"
          ? `${pageCount} page${pageCount === 1 ? "" : "s"} · `
          : ""}
        This page updates itself. Large plan sets take a few minutes.
      </p>
    </Card>
  );
}

function Spinner() {
  return (
    <span className="inline-block size-2 animate-pulse rounded-full bg-accent" />
  );
}
