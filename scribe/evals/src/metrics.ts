import type { CabinetLineItem } from "@scribe/shared";

// Extraction quality metrics (PRD §10): line-item recall/precision and
// qty/dimension field accuracy on matched lines.

const DIM_TOLERANCE_IN = 0.51;

function dimsClose(a: number | null, b: number | null): boolean {
  if (a == null && b == null) return true;
  if (a == null || b == null) return false;
  return Math.abs(a - b) <= DIM_TOLERANCE_IN;
}

function normTag(tag: string | null): string | null {
  if (!tag) return null;
  return tag.toUpperCase().replace(/[\s-]/g, "");
}

function lineMatches(gold: CabinetLineItem, pred: CabinetLineItem): boolean {
  const gTag = normTag(gold.tag);
  const pTag = normTag(pred.tag);
  if (gTag && pTag) return gTag === pTag && gold.category === pred.category;
  return (
    gold.category === pred.category &&
    dimsClose(gold.width_in, pred.width_in) &&
    dimsClose(gold.height_in, pred.height_in)
  );
}

export interface SetMetrics {
  name: string;
  gold_lines: number;
  predicted_lines: number;
  matched: number;
  recall: number;
  precision: number;
  qty_accuracy: number;
  dim_accuracy: number;
}

export function scoreSet(
  name: string,
  gold: CabinetLineItem[],
  predicted: CabinetLineItem[]
): SetMetrics {
  const usedPred = new Set<number>();
  let matched = 0;
  let qtyCorrect = 0;
  let dimCorrect = 0;

  for (const g of gold) {
    let found = -1;
    for (const [i, p] of predicted.entries()) {
      if (usedPred.has(i)) continue;
      if (lineMatches(g, p)) {
        found = i;
        break;
      }
    }
    if (found === -1) continue;
    usedPred.add(found);
    matched++;
    const p = predicted[found];
    if (p.qty === g.qty) qtyCorrect++;
    if (
      dimsClose(g.width_in, p.width_in) &&
      dimsClose(g.height_in, p.height_in) &&
      dimsClose(g.depth_in, p.depth_in)
    ) {
      dimCorrect++;
    }
  }

  return {
    name,
    gold_lines: gold.length,
    predicted_lines: predicted.length,
    matched,
    recall: gold.length === 0 ? 1 : matched / gold.length,
    precision: predicted.length === 0 ? 1 : matched / predicted.length,
    qty_accuracy: matched === 0 ? 0 : qtyCorrect / matched,
    dim_accuracy: matched === 0 ? 0 : dimCorrect / matched,
  };
}

export interface AggregateMetrics {
  sets: SetMetrics[];
  recall: number;
  precision: number;
  qty_accuracy: number;
  dim_accuracy: number;
}

export function aggregate(sets: SetMetrics[]): AggregateMetrics {
  const totalGold = sets.reduce((s, m) => s + m.gold_lines, 0);
  const totalPred = sets.reduce((s, m) => s + m.predicted_lines, 0);
  const totalMatched = sets.reduce((s, m) => s + m.matched, 0);
  const qtyWeighted = sets.reduce((s, m) => s + m.qty_accuracy * m.matched, 0);
  const dimWeighted = sets.reduce((s, m) => s + m.dim_accuracy * m.matched, 0);
  return {
    sets,
    recall: totalGold === 0 ? 1 : totalMatched / totalGold,
    precision: totalPred === 0 ? 1 : totalMatched / totalPred,
    qty_accuracy: totalMatched === 0 ? 0 : qtyWeighted / totalMatched,
    dim_accuracy: totalMatched === 0 ? 0 : dimWeighted / totalMatched,
  };
}
