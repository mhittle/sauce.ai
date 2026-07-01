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

// Width/height tolerance for calling two cabinets "the same" (inches). A base's
// height varies little; widths must be close to count as a match.
const W_TOL = 3;
const H_TOL = 6;

interface Unit {
  category: string;
  w: number;
  h: number;
  used: boolean;
}

function toUnits(list: ScoredCabinet[]): Unit[] {
  const units: Unit[] = [];
  for (const c of list) {
    if (!BOX_CATEGORIES.has(c.category)) continue;
    if (c.w == null || c.h == null || c.w <= 0 || c.h <= 0) continue;
    const qty = Math.max(1, Math.round(c.qty ?? 1));
    for (let i = 0; i < qty; i++)
      units.push({ category: c.category, w: c.w, h: c.h, used: false });
  }
  return units;
}

// Score predicted cabinets against ground-truth label cabinets. Faces (doors/
// drawer_fronts) and non-box categories are ignored on both sides.
export function scoreReading(
  predicted: (CabinetLineItem | ScoredCabinet)[],
  labels: ScoredCabinet[]
): ReadingScore {
  const pred = toUnits(predicted as ScoredCabinet[]);
  const gold = toUnits(labels);

  let matched = 0;
  let sizeErr = 0;
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
  };
}
