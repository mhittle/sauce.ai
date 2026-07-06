import { describe, expect, it } from "vitest";
import {
  buildDimGrounding,
  extractDimSkeleton,
  parseDimInches,
  type TextFragment,
} from "../src/index.js";

describe("parseDimInches", () => {
  it("parses plain inches, quoted inches, fractions, decimals", () => {
    expect(parseDimInches("24")).toBe(24);
    expect(parseDimInches('124"')).toBe(124);
    expect(parseDimInches("34 1/2")).toBe(34.5);
    expect(parseDimInches('1 1/2"')).toBe(1.5);
    expect(parseDimInches("25.625")).toBe(25.625);
    expect(parseDimInches('1/2"')).toBe(0.5);
  });

  it("parses feet-inches forms", () => {
    expect(parseDimInches(`1'-6"`)).toBe(18);
    expect(parseDimInches(`6' - 0"`)).toBe(72);
    expect(parseDimInches(`3'-2 1/2"`)).toBe(38.5);
  });

  it("rejects prose and codes", () => {
    expect(parseDimInches("KITCHEN")).toBeNull();
    expect(parseDimInches("A1.00")).toBeNull();
    expect(parseDimInches("")).toBeNull();
  });
});

// The Q7 island: elevation chain `6 | 27 | 24 | 24 | 27 | 6` plus the sheet's
// grid ruler `1 2 3 … 8` (which must be suppressed) and a KITCHEN label.
function islandFragments(): TextFragment[] {
  const frags: TextFragment[] = [];
  const chain = ["6", "27", "24", "24", "27", "6"];
  chain.forEach((t, i) => frags.push({ x: 1142 + i * 60, y: 280, text: t }));
  for (let i = 0; i < 8; i++)
    frags.push({ x: 78 + i * 72, y: 23, text: String(i + 1) });
  frags.push({ x: 1562, y: 813, text: "KITCHEN" });
  frags.push({ x: 1894, y: 716, text: '124"' });
  frags.push({ x: 1938, y: 716, text: "4" });
  return frags;
}

describe("extractDimSkeleton", () => {
  const skel = extractDimSkeleton(islandFragments());

  it("clusters collinear dims into a chain, in x order", () => {
    const island = skel.chains.find((c) => c.at === 280);
    expect(island).toBeDefined();
    expect(island!.tokens.map((t) => t.inches)).toEqual([6, 27, 24, 24, 27, 6]);
  });

  it("suppresses the sheet grid ruler (consecutive integers)", () => {
    expect(skel.chains.find((c) => c.at === 23)).toBeUndefined();
  });

  it("keeps room/fixture labels with positions", () => {
    expect(skel.labels).toContainEqual({ x: 1562, y: 813, text: "KITCHEN" });
  });
});

describe("buildDimGrounding", () => {
  it("renders chains and the count-once rule into the prompt block", () => {
    const g = buildDimGrounding(islandFragments());
    expect(g).toBeDefined();
    expect(g).toContain("6 | 27 | 24 | 24 | 27 | 6");
    expect(g).toMatch(/count them ONCE/i);
    expect(g).toContain("KITCHEN(1562,813)");
  });

  it("returns undefined when the page has no printed structure", () => {
    expect(
      buildDimGrounding([{ x: 10, y: 10, text: "GENERAL NOTES" }])
    ).toBeUndefined();
  });
});
