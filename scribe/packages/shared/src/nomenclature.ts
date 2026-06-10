import type { CabinetLineItem, LineCategory } from "./schemas.js";

// Deterministic parser for standard cabinet nomenclature (PRD §6.3).
// Encodes the same reference table the extraction prompt carries, and is used
// as a post-parser to validate/repair model output.

export interface ParsedTag {
  category: LineCategory;
  width_in: number | null;
  height_in: number | null;
  depth_in: number | null;
  modifier: string | null;
}

export const DEFAULT_DIMS = {
  base: { height_in: 34.5, depth_in: 24 },
  wall: { depth_in: 12 },
  tall: { height_in: 84, depth_in: 24 },
  vanity: { height_in: 32.5, depth_in: 21 },
} as const;

interface PrefixRule {
  category: LineCategory;
  kind: keyof typeof DEFAULT_DIMS;
}

// Longest-prefix-first. Covers the common KCD/Mozaik/2020 tag families.
const PREFIXES: [string, PrefixRule][] = [
  ["SB", { category: "casework_base", kind: "base" }], // sink base
  ["DB", { category: "casework_base", kind: "base" }], // drawer base
  ["BC", { category: "casework_base", kind: "base" }], // base corner
  ["BLS", { category: "casework_base", kind: "base" }], // base lazy susan
  ["VSB", { category: "vanity", kind: "vanity" }],
  ["VB", { category: "vanity", kind: "vanity" }],
  ["V", { category: "vanity", kind: "vanity" }],
  ["WC", { category: "casework_wall", kind: "wall" }], // wall corner
  ["WDC", { category: "casework_wall", kind: "wall" }],
  ["W", { category: "casework_wall", kind: "wall" }],
  ["TP", { category: "casework_tall", kind: "tall" }], // tall pantry
  ["U", { category: "casework_tall", kind: "tall" }], // utility
  ["T", { category: "casework_tall", kind: "tall" }],
  ["B", { category: "casework_base", kind: "base" }],
];

// Parses tags like "B24", "W3030", "SB36", "W302412", "B24FH", "TP8424".
// Digit groups: 2 digits = width only; 4 digits = width+height;
// 6 digits = width+height+depth. Trailing letters are kept as a modifier.
export function parseTag(rawTag: string): ParsedTag | null {
  const tag = rawTag.trim().toUpperCase().replace(/[\s-]/g, "");
  const m = tag.match(/^([A-Z]+)(\d+)([A-Z]*)$/);
  if (!m) return null;
  const [, prefix, digits, modifier] = m;

  const rule = PREFIXES.find(([p]) => p === prefix)?.[1];
  if (!rule) return null;
  if (digits.length % 2 !== 0 || digits.length > 6) return null;

  const pairs: number[] = [];
  for (let i = 0; i < digits.length; i += 2) {
    pairs.push(parseInt(digits.slice(i, i + 2), 10));
  }
  if (pairs.some((p) => p === 0)) return null;

  const defaults = DEFAULT_DIMS[rule.kind];
  const width_in = pairs[0] ?? null;
  let height_in: number | null =
    "height_in" in defaults ? defaults.height_in : null;
  let depth_in: number | null = defaults.depth_in;

  if (pairs.length >= 2) height_in = pairs[1];
  if (pairs.length >= 3) depth_in = pairs[2];

  return {
    category: rule.category,
    width_in,
    height_in,
    depth_in,
    modifier: modifier || null,
  };
}

// Validate/repair a model-extracted line against the deterministic parser:
// fill missing dims and category from the tag, and flag disagreements by
// lowering confidence (never silently overwrite model dims that disagree).
export function repairLine(line: CabinetLineItem): CabinetLineItem {
  if (!line.tag) return line;
  const parsed = parseTag(line.tag);
  if (!parsed) return line;

  const repaired = { ...line };

  if (repaired.category === "unknown") repaired.category = parsed.category;

  for (const dim of ["width_in", "height_in", "depth_in"] as const) {
    const fromTag = parsed[dim];
    if (fromTag == null) continue;
    if (repaired[dim] == null) {
      repaired[dim] = fromTag;
    } else if (dim === "width_in" && repaired[dim] !== fromTag) {
      // Width is always encoded in the tag; a mismatch means the model
      // misread either the tag or the dims column.
      repaired.confidence = Math.min(repaired.confidence, 0.5);
      repaired.notes = [
        repaired.notes,
        `tag/width mismatch: tag says ${fromTag}", extracted ${repaired[dim]}"`,
      ]
        .filter(Boolean)
        .join("; ");
    }
  }

  if (
    repaired.category !== parsed.category &&
    repaired.category !== "unknown" &&
    // vanity/base overlap is common and legitimate
    !(repaired.category === "vanity" && parsed.category === "casework_base")
  ) {
    repaired.confidence = Math.min(repaired.confidence, 0.6);
  }

  return repaired;
}
