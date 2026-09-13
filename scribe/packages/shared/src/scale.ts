import { z } from "zod";
import type { TextFragment } from "./schedule.js";
import type { DimChain } from "./dim-skeleton.js";
import { extractDimSkeleton } from "./dim-skeleton.js";

// ---------------------------------------------------------------------------
// Drawing scale (Stage V item 0 — v0-drawing-scale-plan.md §2).
// ---------------------------------------------------------------------------
// Scale is a property of the DRAWING, not the cabinet: one value per located
// region, in REAL inches per PDF point, from four sources reconciled in order
// of how directly they measure the drawing itself:
//   manual  — the reviewer dragged a known length (overrides everything)
//   chain   — consecutive printed dimension strings calibrate the sheet
//   note    — the printed scale note ("1/4\" = 1'-0\"") under the drawing
//   model   — the vision model's reported note (a vote, never sole truth)
// Pure + IO-free; callers supply text fragments and region rects.

export const PT_PER_IN = 72;

export const ScaleSourceKind = z.enum(["manual", "chain", "note", "model"]);
export type ScaleSourceKind = z.infer<typeof ScaleSourceKind>;

export const ScaleSource = z.object({
  kind: ScaleSourceKind,
  inPerPt: z.number().positive().nullable(),
  confidence: z.number().min(0).max(1),
  evidence: z.string().optional(),
  samples: z.number().int().nonnegative().optional(),
  spread: z.number().nonnegative().optional(),
  notToScale: z.boolean().optional(),
  sheetLevel: z.boolean().optional(),
});
export type ScaleSource = z.infer<typeof ScaleSource>;

export const DrawingScale = z.object({
  inPerPt: z.number().positive().nullable(),
  confidence: z.number().min(0).max(1),
  agreed: z.boolean(),
  notToScale: z.boolean(),
  unit: z.literal("in"),
  sources: z.array(ScaleSource),
  disagreement: z.string().optional(),
});
export type DrawingScale = z.infer<typeof DrawingScale>;

export interface RectPtLike {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

// ---- 1. Scale notes ----------------------------------------------------------

export interface ParsedScaleNote {
  // Real inches per paper inch (1/4" = 1'-0" → 48). Null when not to scale.
  ratio: number | null;
  inPerPt: number | null;
  notToScale: boolean;
}

const NTS_RE = /\b(?:n\.?\s*t\.?\s*s\.?|not\s+to\s+scale)\b/i;
// 1/4" = 1'-0"   3/8"=1'   1 1/2" = 1'-0"   1" = 1'-0"   (quotes optional/curly)
const ARCH_RE =
  /(?:^|[^\d/])((?:\d+\s+)?\d+(?:\/\d+)?)\s*["”]?\s*=\s*(\d+)\s*['’](?:\s*-?\s*(\d+)\s*["”]?)?/;
// SCALE 1:48
const RATIO_RE = /scale[^\d]*1\s*:\s*(\d{1,4})\b/i;

function mixedToNumber(s: string): number | null {
  const parts = s.trim().split(/\s+/);
  let v = 0;
  for (const p of parts) {
    const m = /^(\d+)(?:\/(\d+))?$/.exec(p);
    if (!m) return null;
    v += m[2] ? Number(m[1]) / Number(m[2]) : Number(m[1]);
  }
  return v > 0 ? v : null;
}

export function parseScaleNote(text: string): ParsedScaleNote | null {
  const s = text.replace(/[”“]/g, '"').replace(/[’‘]/g, "'").trim();
  if (NTS_RE.test(s)) return { ratio: null, inPerPt: null, notToScale: true };
  let m = ARCH_RE.exec(s);
  if (m) {
    const paperIn = mixedToNumber(m[1]);
    const realIn = Number(m[2]) * 12 + (m[3] ? Number(m[3]) : 0);
    if (paperIn && realIn > 0) {
      const ratio = realIn / paperIn;
      return { ratio, inPerPt: ratio / PT_PER_IN, notToScale: false };
    }
  }
  m = RATIO_RE.exec(s);
  if (m) {
    const ratio = Number(m[1]);
    if (ratio > 0) return { ratio, inPerPt: ratio / PT_PER_IN, notToScale: false };
  }
  return null;
}

export interface ScaleNote extends ParsedScaleNote {
  x: number;
  y: number;
  text: string;
}

export function findScaleNotes(fragments: TextFragment[]): ScaleNote[] {
  const out: ScaleNote[] = [];
  for (const f of fragments) {
    const parsed = parseScaleNote(f.text);
    if (parsed) out.push({ ...parsed, x: f.x, y: f.y, text: f.text.trim() });
  }
  return out;
}

// A note belongs to the drawing it sits under: inside the region's x-range,
// within 15% of the region's height below its bottom edge (titles and scale
// notes print under the drawing). Nearest such note wins. Drawings with no
// note of their own take the sheet note (a note that attaches to nothing —
// typically the title block), marked sheetLevel.
export function attachNotesToRegions<R extends { id: string; rect: RectPtLike }>(
  regions: R[],
  notes: ScaleNote[]
): Map<string, ScaleNote & { sheetLevel: boolean }> {
  const out = new Map<string, ScaleNote & { sheetLevel: boolean }>();
  const used = new Set<ScaleNote>();
  for (const r of regions) {
    const h = r.rect.y1 - r.rect.y0;
    let best: { n: ScaleNote; d: number } | null = null;
    for (const n of notes) {
      const insideX = n.x >= r.rect.x0 - 10 && n.x <= r.rect.x1;
      const below = n.y >= r.rect.y0 && n.y <= r.rect.y1 + h * 0.15;
      if (!insideX || !below) continue;
      const d = Math.abs(n.y - r.rect.y1);
      if (!best || d < best.d) best = { n, d };
    }
    if (best) {
      out.set(r.id, { ...best.n, sheetLevel: false });
      used.add(best.n);
    }
  }
  const sheet = notes.find((n) => !used.has(n));
  if (sheet) {
    for (const r of regions) {
      if (!out.has(r.id)) out.set(r.id, { ...sheet, sheetLevel: true });
    }
  }
  return out;
}

// ---- 2. Dimension-chain calibration ----------------------------------------

export interface ChainCalibration {
  inPerPt: number | null;
  // Size of the densest agreeing cluster (not the raw pair count).
  samples: number;
  // Relative half-range of that cluster (0 = perfect agreement).
  spread: number;
  accepted: boolean;
}

const MIN_CLUSTER = 3;
const CLUSTER_TOL = 0.1;
const MIN_GAP_PT = 8;
// Reveal/filler labels (1 1/2", 2") and cabinet numbers ("1", "3") parse as
// inches but don't sit on a dimension chain's midpoints; skip pairs that
// involve them. Real cabinet dimensions start around a filler's 3".
const MIN_TOKEN_IN = 3;

function median(xs: number[]): number {
  const s = [...xs].sort((a, b) => a - b);
  const mid = Math.floor(s.length / 2);
  return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
}

// Consecutive tokens on a chain sit at the midpoints of adjacent segments, so
// the distance between two token centres is (in_i + in_{i+1}) / 2 real
// inches. Each adjacent pair is one sample of inches-per-point.
//
// Real sheets contaminate the samples (a chain at one y can run across two
// neighbouring drawings; a reveal label sits beside a chain; a cabinet number
// parses as inches), so the estimate is the DENSEST CLUSTER of samples, not
// their median: for every sample, count the samples within ±10% of it; the
// best-supported sample's cluster is the calibration. `spread` is the
// cluster's relative half-range and `samples` its size.
export function chainCalibration(
  chains: DimChain[],
  rect?: RectPtLike,
  slackPt = 0
): ChainCalibration {
  const samples: number[] = [];
  for (const chain of chains) {
    const tokens = rect
      ? chain.tokens.filter(
          (t) =>
            t.x >= rect.x0 - slackPt &&
            t.x <= rect.x1 + slackPt &&
            t.y >= rect.y0 - slackPt &&
            t.y <= rect.y1 + slackPt
        )
      : chain.tokens;
    for (let i = 1; i < tokens.length; i++) {
      const a = tokens[i - 1];
      const b = tokens[i];
      if (a.inches < MIN_TOKEN_IN || b.inches < MIN_TOKEN_IN) continue;
      const gap = chain.axis === "h" ? Math.abs(b.x - a.x) : Math.abs(b.y - a.y);
      if (gap < MIN_GAP_PT) continue;
      samples.push((a.inches + b.inches) / 2 / gap);
    }
  }
  if (samples.length === 0) return { inPerPt: null, samples: 0, spread: 0, accepted: false };
  let best: number[] = [];
  for (const c of samples) {
    const cluster = samples.filter((v) => Math.abs(v - c) / c <= CLUSTER_TOL);
    if (cluster.length > best.length) best = cluster;
  }
  const est = median(best);
  const spread = best.length > 1 ? (Math.max(...best) - Math.min(...best)) / est / 2 : 0;
  return {
    inPerPt: est,
    samples: best.length,
    spread,
    accepted: best.length >= MIN_CLUSTER,
  };
}

// ---- 3. Reconcile ------------------------------------------------------------

const KIND_CONFIDENCE: Record<ScaleSourceKind, number> = {
  manual: 1,
  chain: 0.9,
  note: 0.8,
  model: 0.6,
};
const RANK: Record<ScaleSourceKind, number> = { manual: 0, chain: 1, note: 2, model: 3 };
const AGREE_TOL = 0.08;
const DISAGREE_PENALTY = 0.2;

export function reconcileScale(sources: ScaleSource[]): DrawingScale {
  const empty: DrawingScale = {
    inPerPt: null,
    confidence: 0,
    agreed: true,
    notToScale: false,
    unit: "in",
    sources: [],
  };
  if (sources.length === 0) return empty;
  const manual = sources.find((s) => s.kind === "manual" && s.inPerPt != null);
  const nts = sources.find((s) => s.notToScale);
  if (nts && !manual) {
    return { ...empty, notToScale: true, confidence: nts.confidence, sources };
  }
  // A chain only outranks the note when it earned it (accepted = confidence
  // at its full kind value).
  const usable = sources.filter(
    (s) => s.inPerPt != null && !(s.kind === "chain" && s.confidence < KIND_CONFIDENCE.chain)
  );
  const ranked = (usable.length > 0 ? usable : sources.filter((s) => s.inPerPt != null)).sort(
    (a, b) => RANK[a.kind] - RANK[b.kind]
  );
  const chosen = ranked[0];
  if (!chosen || chosen.inPerPt == null) return { ...empty, sources };
  // Only sources that earned their say vote on agreement: an unaccepted chain
  // (one or two stray samples) must not flag a good note as a disagreement.
  const others = sources.filter(
    (s) => s !== chosen && s.inPerPt != null && s.confidence >= 0.5
  );
  const off = others.filter(
    (s) => Math.abs(s.inPerPt! - chosen.inPerPt!) / chosen.inPerPt! > AGREE_TOL
  );
  const agreed = off.length === 0;
  const confidence =
    chosen.kind === "manual"
      ? 1
      : Math.max(0, Math.min(1, chosen.confidence - (agreed ? 0 : DISAGREE_PENALTY)));
  return {
    inPerPt: chosen.inPerPt,
    confidence,
    agreed,
    notToScale: false,
    unit: "in",
    sources,
    ...(agreed
      ? {}
      : {
          disagreement: off
            .map((s) => `${s.kind} says ${s.inPerPt!.toFixed(4)} in/pt vs ${chosen.kind} ${chosen.inPerPt!.toFixed(4)}`)
            .join("; "),
        }),
  };
}

// ---- 4. One call per region --------------------------------------------------

export function scaleForRegion(opts: {
  fragments: TextFragment[];
  rect: RectPtLike;
  // The model's reported scale note for this region/page, if any.
  modelNote?: string | null;
  // A note already attached to this region (from attachNotesToRegions); when
  // absent the nearest note under the rect is used, else any sheet note.
  note?: (ScaleNote & { sheetLevel?: boolean }) | null;
  // Reviewer calibration: real inches per point.
  manualInPerPt?: number | null;
}): DrawingScale {
  const sources: ScaleSource[] = [];

  const skel = extractDimSkeleton(opts.fragments);
  const cal = chainCalibration(skel.chains, opts.rect, 12);
  if (cal.inPerPt != null) {
    sources.push({
      kind: "chain",
      inPerPt: cal.inPerPt,
      confidence: cal.accepted ? KIND_CONFIDENCE.chain : 0.4,
      samples: cal.samples,
      spread: Math.round(cal.spread * 1000) / 1000,
    });
  }

  let note = opts.note ?? null;
  if (note === null && opts.note === undefined) {
    const attached = attachNotesToRegions(
      [{ id: "r", rect: opts.rect }],
      findScaleNotes(opts.fragments)
    ).get("r");
    note = attached ?? null;
  }
  if (note) {
    sources.push({
      kind: "note",
      inPerPt: note.inPerPt,
      confidence: note.sheetLevel ? 0.7 : KIND_CONFIDENCE.note,
      evidence: note.text,
      notToScale: note.notToScale,
      sheetLevel: note.sheetLevel ?? false,
    });
  }

  if (opts.modelNote) {
    const parsed = parseScaleNote(opts.modelNote);
    if (parsed) {
      sources.push({
        kind: "model",
        inPerPt: parsed.inPerPt,
        confidence: KIND_CONFIDENCE.model,
        evidence: opts.modelNote,
        notToScale: parsed.notToScale,
      });
    }
  }

  if (opts.manualInPerPt != null && opts.manualInPerPt > 0) {
    sources.push({ kind: "manual", inPerPt: opts.manualInPerPt, confidence: 1 });
  }

  return reconcileScale(sources);
}

// Convert a reconciled scale to inches per pixel of a render at `dpi`.
export function inPerPx(scale: DrawingScale, dpi: number): number | null {
  return scale.inPerPt == null ? null : (scale.inPerPt * PT_PER_IN) / dpi;
}
