import type { CabinetLineItem } from "./schemas.js";

// ---------------------------------------------------------------------------
// Reading-accuracy scoring (H2) — measure the READ, not the dollar total.
// ---------------------------------------------------------------------------
// The $-total is a lossy proxy: a read can match the dollar figure while listing
// the wrong cabinets (the Dean case). This scores the pipeline's predicted
// cabinets against per-line ground truth from the real quote packets:
//   recall    — of the real cabinets, how many did we find? (under-read)
//   precision — of the cabinets we listed, how many are real? (over-read/phantoms)
//   count/size error on the matched set.
// Matching is greedy at the UNIT level (qty expanded), same category + nearest
// size within tolerance, so a 15" base can't satisfy a 36" base.

const BOX_CATEGORIES = new Set([
  "casework_base",
  "casework_wall",
  "casework_tall",
  "vanity",
]);

export interface ScoredCabinet {
  category: string;
  w: number | null;
  h: number | null;
  qty?: number | null;
  tag?: string | null;
}

export interface ReadingScore {
  labelBoxes: number; // ground-truth cabinet units
  predictedBoxes: number; // predicted cabinet units
  matched: number;
  recall: number; // matched / labelBoxes
  precision: number; // matched / predictedBoxes
  f1: number;
  countErrorPct: number; // (predicted - label) / label * 100 (signed)
  meanSizeErrorIn: number; // mean(|Δw| + |Δh|) over matched units
}

// Per-unit alignment detail — which gold cabinet matched which prediction, which
// went MISSing, which predictions are PHANTOMs, and how many input rows the
// scorer silently dropped before matching (non-box category or null/zero dims).
// The aggregate score alone can't distinguish "wrong count" from "right count,
// wrong sizes", which is exactly the question on the worst quotes.
export interface AlignedUnit {
  category: string;
  w: number;
  h: number;
  tag: string | null;
}

export interface ReadingAlignment {
  gold: {
    unit: AlignedUnit;
    // null = MISS (no prediction matched this real cabinet)
    matchedPred: AlignedUnit | null;
    sizeErrIn: number | null; // |Δw|+|Δh| when matched
  }[];
  pred: {
    unit: AlignedUnit;
    matched: boolean; // false = PHANTOM (predicted, matched no real cabinet)
  }[];
  // Rows dropped by the unit filter, invisible to recall/precision.
  droppedPred: { nonBoxCategory: number; nullOrZeroDims: number };
  droppedGold: { nonBoxCategory: number; nullOrZeroDims: number };
}

export interface DetailedReadingScore extends ReadingScore {
  alignment: ReadingAlignment;
}

// Width/height tolerance for calling two cabinets "the same" (inches). A base's
// height varies little; widths must be close to count as a match.
const W_TOL = 3;
const H_TOL = 6;

interface Unit {
  category: string;
  w: number;
  h: number;
  tag: string | null;
  used: boolean;
}

interface UnitFilter {
  units: Unit[];
  droppedNonBox: number;
  droppedNullDims: number;
}

function toUnits(list: ScoredCabinet[]): UnitFilter {
  const units: Unit[] = [];
  let droppedNonBox = 0;
  let droppedNullDims = 0;
  for (const c of list) {
    if (!BOX_CATEGORIES.has(c.category)) {
      droppedNonBox++;
      continue;
    }
    if (c.w == null || c.h == null || c.w <= 0 || c.h <= 0) {
      droppedNullDims++;
      continue;
    }
    const qty = Math.max(1, Math.round(c.qty ?? 1));
    for (let i = 0; i < qty; i++)
      units.push({
        category: c.category,
        w: c.w,
        h: c.h,
        tag: c.tag ?? null,
        used: false,
      });
  }
  return { units, droppedNonBox, droppedNullDims };
}

function toAligned(u: Unit): AlignedUnit {
  return { category: u.category, w: u.w, h: u.h, tag: u.tag };
}

// Score predicted cabinets against ground-truth label cabinets, returning both
// the aggregate metrics and the full per-unit alignment. Faces (doors/
// drawer_fronts) and non-box categories are ignored on both sides.
export function scoreReadingDetailed(
  predicted: (CabinetLineItem | ScoredCabinet)[],
  labels: ScoredCabinet[]
): DetailedReadingScore {
  const predFilter = toUnits(predicted as ScoredCabinet[]);
  const goldFilter = toUnits(labels);
  const pred = predFilter.units;
  const gold = goldFilter.units;

  let matched = 0;
  let sizeErr = 0;
  const goldRows: ReadingAlignment["gold"] = [];
  // Greedy: for each ground-truth unit, take the closest unused prediction of
  // the same category within tolerance.
  for (const g of gold) {
    let best: Unit | null = null;
    let bestD = Infinity;
    for (const p of pred) {
      if (p.used || p.category !== g.category) continue;
      const dw = Math.abs(p.w - g.w);
      const dh = Math.abs(p.h - g.h);
      if (dw > W_TOL || dh > H_TOL) continue;
      const d = dw + dh;
      if (d < bestD) {
        bestD = d;
        best = p;
      }
    }
    if (best) {
      best.used = true;
      matched++;
      sizeErr += bestD;
      goldRows.push({ unit: toAligned(g), matchedPred: toAligned(best), sizeErrIn: bestD });
    } else {
      goldRows.push({ unit: toAligned(g), matchedPred: null, sizeErrIn: null });
    }
  }

  const labelBoxes = gold.length;
  const predictedBoxes = pred.length;
  const recall = labelBoxes ? matched / labelBoxes : 0;
  const precision = predictedBoxes ? matched / predictedBoxes : 0;
  const f1 = recall + precision > 0 ? (2 * recall * precision) / (recall + precision) : 0;
  return {
    labelBoxes,
    predictedBoxes,
    matched,
    recall,
    precision,
    f1,
    countErrorPct: labelBoxes ? ((predictedBoxes - labelBoxes) / labelBoxes) * 100 : 0,
    meanSizeErrorIn: matched ? sizeErr / matched : 0,
    alignment: {
      gold: goldRows,
      pred: pred.map((p) => ({ unit: toAligned(p), matched: p.used })),
      droppedPred: {
        nonBoxCategory: predFilter.droppedNonBox,
        nullOrZeroDims: predFilter.droppedNullDims,
      },
      droppedGold: {
        nonBoxCategory: goldFilter.droppedNonBox,
        nullOrZeroDims: goldFilter.droppedNullDims,
      },
    },
  };
}

export function scoreReading(
  predicted: (CabinetLineItem | ScoredCabinet)[],
  labels: ScoredCabinet[]
): ReadingScore {
  const { alignment: _alignment, ...score } = scoreReadingDetailed(predicted, labels);
  return score;
}
