import type { CabinetLineItem, LineCategory } from "./schemas.js";

// ---------------------------------------------------------------------------
// Text-layer cabinet-schedule extraction (Class 1 — "the input already lists
// the cabinets").
// ---------------------------------------------------------------------------
// Many quote/spec PDFs (CabinetNow spec sheets, competitor quotes, cut lists)
// carry the cabinet schedule as a real text-layer TABLE, e.g.
//     R1C1  Vanity Sink Base  15  34 1/2  24  Vanity Sink Base
// Reading that verbatim is exact and free — no vision, no zero-shot counting
// ceiling. mupdf reports the cells as individually-positioned fragments (a flat
// text dump collapses the columns), so we regroup fragments into visual rows by
// y, order cells by x, then parse each row into a cabinet line item. Pure + IO-
// free: the worker supplies the fragments (pdf.ts pageTextFragments).

export interface TextFragment {
  x: number;
  y: number;
  text: string;
}

// Group positioned fragments into visual rows (fragments within `yTol` points
// vertically belong to the same row), order each row's cells left-to-right, and
// join with a double space so a downstream /\s{2,}/ split recovers the columns.
export function reconstructRows(
  fragments: TextFragment[],
  yTol = 4
): string[] {
  const sorted = [...fragments].sort((a, b) => a.y - b.y || a.x - b.x);
  const rows: { y: number; cells: TextFragment[] }[] = [];
  for (const f of sorted) {
    const cur = rows[rows.length - 1];
    if (cur && Math.abs(f.y - cur.y) <= yTol) cur.cells.push(f);
    else rows.push({ y: f.y, cells: [f] });
  }
  return rows.map((r) =>
    r.cells
      .sort((a, b) => a.x - b.x)
      .map((c) => c.text.trim())
      .join("  ")
  );
}

// Parse a decimal-inch dimension from one table cell: "24" -> 24, "34 1/2" ->
// 34.5, "1/2" -> 0.5, `30"` -> 30. Returns null if the cell isn't a dimension.
export function parseDimCell(cell: string): number | null {
  const s = cell.trim().replace(/["”'’]|(?:\bin\b)/gi, "").trim();
  let m = /^(\d+)\s+(\d+)\/(\d+)$/.exec(s); // "34 1/2"
  if (m) return Number(m[1]) + Number(m[2]) / Number(m[3]);
  m = /^(\d+)\/(\d+)$/.exec(s); // "1/2"
  if (m) return Number(m[1]) / Number(m[2]);
  m = /^(\d+(?:\.\d+)?)$/.exec(s); // "24" / "24.5"
  if (m) return Number(m[1]);
  return null;
}

// A cabinet description must name a real casework noun — this keeps prose on
// elevation sheets ("WALL A — BACK WALL | 72" FACE") from parsing as a row.
const CABINET_NOUN =
  /\b(vanity|sink base|base|wall|tall|pantry|linen|utility|drawer base|oven base|trash|corner|filler|panel|cabinet)\b/i;

function categoryFor(desc: string): { category: LineCategory; filler: boolean } {
  const d = desc.toLowerCase();
  if (/\bvanity\b/.test(d)) return { category: "vanity", filler: false };
  if (/\bfiller\b|\bpanel\b|\bend\b|\bbf\b|\bscribe\b|toe|crown|mould?ing|\breturn\b/.test(d))
    return { category: "casework_base", filler: true };
  if (/\btall\b|\bpantry\b|\blinen\b|\butility\b/.test(d))
    return { category: "casework_tall", filler: false };
  if (/\bwall\b|\bupper\b/.test(d)) return { category: "casework_wall", filler: false };
  return { category: "casework_base", filler: false }; // base / sink base / default
}

// A short leading alnum code like "R1C1", "B12", "A3" is a tag column, not the
// description.
const TAG_CODE = /^[A-Za-z]?\d+[A-Za-z]?\d*$|^R\d+[CN]\d+$/;

function parseRow(row: string): CabinetLineItem | null {
  const cells = row
    .split(/\s{2,}/)
    .map((c) => c.trim())
    .filter(Boolean);
  if (cells.length < 3) return null;

  const dimAt = cells.map((c) => parseDimCell(c));
  const dims = dimAt.filter((v): v is number => v != null);
  if (dims.length < 2) return null; // need at least width + height

  const desc = cells.find(
    (c, i) => dimAt[i] == null && CABINET_NOUN.test(c) && !TAG_CODE.test(c)
  );
  if (!desc) return null;

  const [w, h, d] = dims;
  // Plausibility gate — real cabinet box dimensions, in inches.
  if (!(w > 2 && w <= 64 && h > 2 && h <= 120)) return null;

  const { category, filler } = categoryFor(desc);
  const depth =
    d != null && d > 3 && d <= 36 ? d : category === "casework_wall" ? 12 : 24;
  const tag = `${desc} ${w % 1 === 0 ? w : w.toFixed(3).replace(/0+$/, "")}`
    .replace(/\s+/g, " ")
    .trim();

  return {
    source_page: null,
    tag: filler ? `${tag} Filler` : tag,
    room: null,
    qty: 1,
    category,
    width_in: w,
    height_in: h,
    depth_in: depth,
    door_style: null,
    material: null,
    finish: null,
    assembled: null,
    // Read from an explicit schedule table, not estimated from geometry.
    notes: `schedule: ${row}`,
    confidence: 0.9,
    estimated: false,
  };
}

export interface SchedulePageInput {
  page: number;
  fragments: TextFragment[];
}

export interface ScheduleExtraction {
  lines: CabinetLineItem[];
  // Pages that yielded a contiguous cabinet table (>= MIN_ROWS parsed rows).
  schedulePages: number[];
}

// A real table is a CLUSTER of rows on one page — require at least this many
// parsed cabinet rows on a page before trusting it as a schedule (one stray
// dimension line on a drawing must not trigger the extraction path).
export const MIN_SCHEDULE_ROWS = 3;

// Extract cabinet line items from the text-layer schedule table(s) in a document.
// Returns the parsed lines (with source_page set) and which pages were schedules.
// An empty result means no confident table was found → caller falls back to vision.
export function extractCabinetSchedule(
  pages: SchedulePageInput[]
): ScheduleExtraction {
  const lines: CabinetLineItem[] = [];
  const schedulePages: number[] = [];
  for (const { page, fragments } of pages) {
    const rows = reconstructRows(fragments);
    const parsed = rows
      .map(parseRow)
      .filter((l): l is CabinetLineItem => l != null)
      .map((l) => ({ ...l, source_page: page }));
    if (parsed.length >= MIN_SCHEDULE_ROWS) {
      schedulePages.push(page);
      lines.push(...parsed);
    }
  }
  return { lines, schedulePages };
}
