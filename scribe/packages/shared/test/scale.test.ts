import { describe, expect, it } from "vitest";
import {
  attachNotesToRegions,
  chainCalibration,
  extractDimSkeleton,
  findScaleNotes,
  parseScaleNote,
  reconcileScale,
  scaleForRegion,
  type DimChain,
  type ScaleSource,
} from "../src/index.js";

// Drawing scale (Stage V item 0): one scale per located drawing, from the
// title-block note, dimension-chain calibration, the model's reported note,
// or a manual calibration. Values are REAL inches per PDF point.

const PT_PER_IN = 72;

describe("parseScaleNote", () => {
  it.each([
    ['1/4" = 1\'-0"', 48],
    ['SCALE: 1/4"=1\'-0"', 48],
    ['1/8" = 1\'-0"', 96],
    ['3/8"=1\'', 32],
    ['3/16" = 1\'-0"', 64],
    ['1 1/2" = 1\'-0"', 8],
    ['1" = 1\'-0"', 12],
    ["Scale 1:48", 48],
    ['1/4” = 1’-0”', 48], // curly quotes
    ['1/2" = 1\'', 24],
  ])("parses %s → %d real inches per paper inch", (text, ratio) => {
    const r = parseScaleNote(text);
    expect(r).not.toBeNull();
    expect(r!.notToScale).toBe(false);
    expect(r!.ratio).toBeCloseTo(ratio, 6);
    expect(r!.inPerPt).toBeCloseTo(ratio / PT_PER_IN, 6);
  });

  it.each(["N.T.S.", "NTS", "NOT TO SCALE", "Scale: n.t.s."])(
    "recognises %s as not-to-scale",
    (text) => {
      const r = parseScaleNote(text);
      expect(r).not.toBeNull();
      expect(r!.notToScale).toBe(true);
      expect(r!.inPerPt).toBeNull();
    }
  );

  it.each(['1/4"', "24", "1:48 odds", "B24", "1/4 = 1", "SCALE"])(
    "rejects %s (a dimension, a tag, or prose)",
    (text) => {
      expect(parseScaleNote(text)).toBeNull();
    }
  );
});

describe("findScaleNotes", () => {
  it("returns every scale note on the page with its position", () => {
    const notes = findScaleNotes([
      { x: 100, y: 500, text: "KITCHEN ELEVATION" },
      { x: 100, y: 512, text: 'SCALE: 1/2" = 1\'-0"' },
      { x: 900, y: 780, text: 'SCALE: 1/4" = 1\'-0"' },
      { x: 400, y: 200, text: '36"' },
    ]);
    expect(notes.map((n) => [n.x, n.y, n.ratio])).toEqual([
      [100, 512, 24],
      [900, 780, 48],
    ]);
  });
});

// Chain of three cabinets 36 / 36 / 34.5 wide drawn at 1/4" = 1' (0.16667
// in/pt): 36" is 216 pt, 34.5" is 207 pt. Token centres sit at segment
// midpoints.
const SCALE = 12 / (0.25 * PT_PER_IN); // 0.6667 in per pt
const seg = (inches: number) => inches / SCALE;
function chainAt(y: number, inches: number[], x0 = 60): DimChain {
  let x = x0;
  const tokens = inches.map((v) => {
    const cx = x + seg(v) / 2;
    x += seg(v);
    return { x: Math.round(cx * 100) / 100, y, raw: `${v}"`, inches: v };
  });
  return { axis: "h", at: y, tokens };
}

describe("chainCalibration", () => {
  it("recovers inches-per-point from consecutive dimension tokens", () => {
    const r = chainCalibration([chainAt(40, [36, 36, 34.5]), chainAt(60, [24, 18, 30])]);
    expect(r.inPerPt).not.toBeNull();
    expect(r.inPerPt!).toBeCloseTo(SCALE, 3);
    expect(r.samples).toBe(4);
    expect(r.spread).toBeLessThan(0.02);
    expect(r.accepted).toBe(true);
  });

  it("uses only the tokens inside the region rect", () => {
    const inside = chainAt(40, [36, 36, 34.5]); // spans 60..~219 pt
    const elsewhere = chainAt(400, [12, 12, 12], 900); // a different drawing at another scale
    elsewhere.tokens.forEach((t) => (t.inches = 6)); // would give half the scale
    const r = chainCalibration([inside, elsewhere], { x0: 0, y0: 0, x1: 400, y1: 300 });
    expect(r.samples).toBe(2);
    expect(r.inPerPt!).toBeCloseTo(SCALE, 3);
  });

  it("is not accepted with fewer than three agreeing samples", () => {
    const r = chainCalibration([chainAt(40, [36, 36])]);
    expect(r.samples).toBe(1);
    expect(r.accepted).toBe(false);
    expect(r.inPerPt).not.toBeNull(); // still reported, just not trusted alone
  });

  it("is not accepted when no three samples agree", () => {
    const bad = chainAt(40, [36, 36, 36, 36]);
    bad.tokens[1].x += 60; // two tokens dragged off their midpoints
    bad.tokens[2].x -= 40;
    const r = chainCalibration([bad]);
    expect(r.accepted).toBe(false);
    expect(r.samples).toBeLessThan(3);
  });

  it("finds the true scale as the densest cluster on a contaminated sheet", () => {
    // Mirrors what real kits show: a good chain, a reveal label pair (1 1/2"),
    // a cabinet-number pair, and a chain that jumps to the next drawing.
    const good = chainAt(40, [24, 36, 36, 24, 30]);
    const reveals: DimChain = { axis: "h", at: 60, tokens: [
      { x: 100, y: 60, raw: '1 1/2"', inches: 1.5 }, { x: 140, y: 60, raw: '1 1/2"', inches: 1.5 }, { x: 330, y: 60, raw: '2"', inches: 2 } ] };
    const numbers: DimChain = { axis: "h", at: 80, tokens: [
      { x: 100, y: 80, raw: "1", inches: 1 }, { x: 190, y: 80, raw: "3", inches: 3 }, { x: 400, y: 80, raw: "1", inches: 1 } ] };
    const jump: DimChain = { axis: "h", at: 100, tokens: [
      { x: 60, y: 100, raw: '36"', inches: 36 }, { x: 60 + seg(36), y: 100, raw: '36"', inches: 36 }, { x: 900, y: 100, raw: '36"', inches: 36 } ] };
    const r = chainCalibration([good, reveals, numbers, jump]);
    expect(r.inPerPt!).toBeCloseTo(SCALE, 3);
    expect(r.accepted).toBe(true);
    expect(r.samples).toBe(5); // 4 from the good chain + the one true pair on the jump chain
  });

  it("ignores the sheet grid ruler via the skeleton", () => {
    // extractDimSkeleton already drops consecutive-integer rulers; a page with
    // only a ruler calibrates to nothing.
    const frags = Array.from({ length: 12 }, (_, i) => ({ x: 50 + i * 100, y: 20, text: String(i + 1) }));
    const skel = extractDimSkeleton(frags);
    const r = chainCalibration(skel.chains);
    expect(r.samples).toBe(0);
    expect(r.inPerPt).toBeNull();
  });

  it("uses token centres when fragments carry widths", () => {
    // Top-left positions would skew every sample by half a token width; with
    // w present the skeleton centres them.
    const frags = [36, 36, 34.5].map((v, i) => ({
      x: 60 + [0, seg(36), seg(72)][i] + seg(v) / 2 - 10,
      y: 40,
      w: 20,
      h: 8,
      text: `${v}"`,
    }));
    const skel = extractDimSkeleton(frags);
    const r = chainCalibration(skel.chains);
    expect(r.inPerPt!).toBeCloseTo(SCALE, 3);
  });
});

describe("attachNotesToRegions", () => {
  const regions = [
    { id: "a", rect: { x0: 50, y0: 50, x1: 600, y1: 500 } },
    { id: "b", rect: { x0: 700, y0: 50, x1: 1200, y1: 500 } },
  ];
  it("gives each drawing the note printed under it", () => {
    const notes = [
      { x: 80, y: 520, text: '1/2" = 1\'-0"', ratio: 24, inPerPt: 24 / 72, notToScale: false },
      { x: 720, y: 530, text: '1/4" = 1\'-0"', ratio: 48, inPerPt: 48 / 72, notToScale: false },
    ];
    const out = attachNotesToRegions(regions, notes);
    expect(out.get("a")?.ratio).toBe(24);
    expect(out.get("b")?.ratio).toBe(48);
  });
  it("falls back to the sheet note for drawings without their own", () => {
    const notes = [
      { x: 1500, y: 1100, text: 'SCALE: 1/4" = 1\'-0"', ratio: 48, inPerPt: 48 / 72, notToScale: false },
    ];
    const out = attachNotesToRegions(regions, notes);
    expect(out.get("a")?.ratio).toBe(48);
    expect(out.get("a")?.sheetLevel).toBe(true);
  });
});

describe("reconcileScale", () => {
  const chain: ScaleSource = { kind: "chain", inPerPt: 0.66, confidence: 0.9, samples: 6, spread: 0.02 };
  const note: ScaleSource = { kind: "note", inPerPt: 0.6667, confidence: 0.8, evidence: '1/4" = 1\'-0"' };
  const model: ScaleSource = { kind: "model", inPerPt: 0.6667, confidence: 0.6, evidence: '1/4"=1\'' };

  it("prefers the chain, then the note, then the model", () => {
    expect(reconcileScale([model, note, chain]).inPerPt).toBe(0.66);
    expect(reconcileScale([model, note]).inPerPt).toBeCloseTo(0.6667, 4);
    expect(reconcileScale([model]).inPerPt).toBeCloseTo(0.6667, 4);
    expect(reconcileScale([model]).confidence).toBe(0.6);
  });

  it("a manual calibration overrides everything", () => {
    const manual: ScaleSource = { kind: "manual", inPerPt: 0.5, confidence: 1 };
    const r = reconcileScale([chain, note, manual]);
    expect(r.inPerPt).toBe(0.5);
    expect(r.confidence).toBe(1);
  });

  it("flags disagreement beyond 8% and lowers confidence", () => {
    const off: ScaleSource = { kind: "note", inPerPt: 0.5, confidence: 0.8, evidence: '3/8" = 1\'' };
    const r = reconcileScale([chain, off]);
    expect(r.inPerPt).toBe(0.66);
    expect(r.agreed).toBe(false);
    expect(r.confidence).toBeCloseTo(0.7, 6);
    expect(r.disagreement).toMatch(/note/);
  });

  it("an unaccepted chain neither outranks the note nor flags a disagreement", () => {
    const weak: ScaleSource = { kind: "chain", inPerPt: 0.013, confidence: 0.4, samples: 1, spread: 0 };
    const r = reconcileScale([weak, note]);
    expect(r.inPerPt).toBeCloseTo(0.6667, 4);
    expect(r.agreed).toBe(true);
    expect(r.confidence).toBe(0.8);
  });

  it("not-to-scale wins over everything but manual", () => {
    const nts: ScaleSource = { kind: "note", inPerPt: null, confidence: 0.8, notToScale: true, evidence: "N.T.S." };
    const r = reconcileScale([chain, nts]);
    expect(r.notToScale).toBe(true);
    expect(r.inPerPt).toBeNull();
    const manual: ScaleSource = { kind: "manual", inPerPt: 0.5, confidence: 1 };
    expect(reconcileScale([nts, manual]).inPerPt).toBe(0.5);
  });

  it("returns an empty scale when there are no sources", () => {
    const r = reconcileScale([]);
    expect(r.inPerPt).toBeNull();
    expect(r.confidence).toBe(0);
    expect(r.sources).toEqual([]);
  });
});

describe("scaleForRegion", () => {
  it("combines the page's text layer and a model note into one scale", () => {
    const frags = [
      // Four tokens = three calibration samples, the minimum for an accepted chain.
      ...[36, 36, 34.5, 24].map((v, i) => ({ x: 60 + [0, seg(36), seg(72), seg(106.5)][i] + seg(v) / 2, y: 40, text: `${v}"` })),
      { x: 70, y: 520, text: 'SCALE: 1/4" = 1\'-0"' },
    ];
    const r = scaleForRegion({
      fragments: frags,
      rect: { x0: 0, y0: 0, x1: 600, y1: 500 },
      modelNote: '1/4" = 1\'-0"',
    });
    expect(r.inPerPt!).toBeCloseTo(SCALE, 3);
    expect(r.agreed).toBe(true);
    expect(r.sources.map((s) => s.kind).sort()).toEqual(["chain", "model", "note"]);
    expect(r.confidence).toBe(0.9);
  });

  it("reports the chain as unaccepted and falls back to the note on a sparse sheet", () => {
    const frags = [
      { x: 168, y: 40, text: '36"' },
      { x: 384, y: 40, text: '36"' },
      { x: 70, y: 520, text: 'SCALE: 1/4" = 1\'-0"' },
    ];
    const r = scaleForRegion({ fragments: frags, rect: { x0: 0, y0: 0, x1: 600, y1: 500 } });
    expect(r.inPerPt!).toBeCloseTo(SCALE, 3);
    expect(r.sources.find((s) => s.kind === "chain")?.confidence).toBeLessThan(0.5);
  });
});
