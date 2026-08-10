import type {
  PageClass,
  PageClassification,
  SelectedPage,
} from "./schemas.js";
import { RELEVANT_PAGE_CLASSES } from "./schemas.js";

// ---------------------------------------------------------------------------
// Page-selection gate (2026-08 two-stage human review).
//
// The autonomous flow read every page the classifier deemed relevant. With the
// page-picker gate, the HUMAN decides which pages are read, and can override
// the classifier's type per page (diagnosis showed the plan-vs-elevation call
// decides reading accuracy, so the tag override is high-leverage). This module
// is pure: it merges the user's selection into the classifier output and
// applies the same relevance filter + read-order sort the worker always used.
// ---------------------------------------------------------------------------

// Read order: schedules first, then finish schedules, elevations, floor plans
// last (least precise source — PRD §6.3).
function rank(c: PageClassification): number {
  return c.class === "cabinet_schedule_table"
    ? 0
    : c.class === "finish_schedule"
      ? 1
      : c.class === "floor_plan"
        ? 3
        : 2;
}

export interface RelevantPageSelection {
  // No schedule table among the (selected) pages → estimation mode: floor
  // plans become a relevant source and every line is flagged estimated.
  estimationMode: boolean;
  // Pages to read, in read order, with user tag overrides applied.
  relevant: PageClassification[];
}

// Merge a human page selection into the classifier's output and filter to the
// pages worth reading. `selected == null` reproduces the autonomous flow
// (every page considered). A user tag override replaces the classifier's class
// for that page (confidence 1 — a human said so); a selected page the
// classifier never saw is admitted with its override class (or "other").
// Selected pages whose effective class is not a readable type are excluded —
// the tag tells the reader HOW to read a page, and "other"/cover pages have
// no read path.
export function selectRelevantPages(
  classified: PageClassification[],
  selected: SelectedPage[] | null | undefined
): RelevantPageSelection {
  let effective: PageClassification[];
  if (selected == null) {
    effective = classified;
  } else {
    const byPage = new Map(classified.map((c) => [c.page, c]));
    effective = selected.map((s) => {
      const base = byPage.get(s.page);
      const cls: PageClass = s.class ?? base?.class ?? "other";
      return s.class != null || base == null
        ? { page: s.page, class: cls, confidence: 1 }
        : base;
    });
  }

  const estimationMode = !effective.some(
    (c) => c.class === "cabinet_schedule_table"
  );
  const relevantClasses: PageClass[] = estimationMode
    ? [...RELEVANT_PAGE_CLASSES, "floor_plan"]
    : RELEVANT_PAGE_CLASSES;

  const relevant = effective
    .filter((c) => relevantClasses.includes(c.class))
    .sort((a, b) => rank(a) - rank(b));

  return { estimationMode, relevant };
}
