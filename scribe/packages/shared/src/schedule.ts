import type { CabinetLineItem, LineCategory } from "./schemas.js";
import { isNonBoxCasework } from "./regions.js";

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
    bbox_2d: null,
  };
}

// ---------------------------------------------------------------------------
// Header-driven table parsing. Many packets (CabinetNow "CABINET BOXES",
// designer schedules) carry an explicit header row — `Name/STYLE | WIDTH |
// HEIGHT | DEPTH | Qty | UNIT #` — whose cell x-positions define the columns.
// Mapping data cells to columns by x fixes formats the positional heuristic
// mis-reads (a leading "Cab#" column parsed as the width), recovers the Qty
// column, and lets wrapped names (a description spanning 2-3 visual rows) be
// reassembled. Falls back to the legacy row heuristic when no header exists.
// ---------------------------------------------------------------------------

interface RowCells {
  y: number;
  cells: { x: number; text: string }[];
}

// Like reconstructRows, but keeps each cell's x so callers can map cells to
// header columns; rows are y-sorted, cells x-sorted.
export function reconstructRowCells(
  fragments: TextFragment[],
  yTol = 4
): RowCells[] {
  const sorted = [...fragments].sort((a, b) => a.y - b.y || a.x - b.x);
  const rows: RowCells[] = [];
  for (const f of sorted) {
    const text = f.text.trim();
    if (!text) continue;
    const cur = rows[rows.length - 1];
    if (cur && Math.abs(f.y - cur.y) <= yTol) cur.cells.push({ x: f.x, text });
    else rows.push({ y: f.y, cells: [{ x: f.x, text }] });
  }
  for (const r of rows) r.cells.sort((a, b) => a.x - b.x);
  return rows;
}

type ColRole = "name" | "width" | "height" | "depth" | "qty" | "unit" | "ignore";

interface HeaderCols {
  y: number;
  // Column boundaries: every header cell, x-sorted, with its role. A data cell
  // belongs to the LAST boundary at or left of it (numeric cells are typically
  // right-aligned, so nearest-header matching mis-buckets them; range
  // membership doesn't care about alignment).
  bounds: { x: number; role: ColRole }[];
}

// A money-ish header cell means the table is a PRICED component list (the
// packet's "DOOR & DRAWER LIST" carries $/sqft + subtotal columns) — those rows
// are doors/fronts, not cabinet boxes, so the whole table is skipped.
const MONEY_HEADER = /\$|sub-?total|price|total/i;
const NAME_HEADER = /^(?:.*\bstyle\b.*|name|description|item)$/i;

function headerRole(text: string): ColRole | null {
  const t = text.trim();
  if (/^width$/i.test(t)) return "width";
  if (/^height$/i.test(t)) return "height";
  if (/^depth$/i.test(t)) return "depth";
  if (/^qty\.?$/i.test(t)) return "qty";
  if (/^(?:unit\s*#?|cab#.*)$/i.test(t)) return "unit";
  if (NAME_HEADER.test(t) && !/material|room/i.test(t)) return "name";
  return null;
}

// Returns the parsed header, the sentinel "money" for a priced component-list
// header (doors/fronts — a table boundary that must also CLOSE any carried
// header so its rows aren't parsed as cabinets), or null for a non-header row.
function findHeader(row: RowCells): HeaderCols | "money" | null {
  const bounds: { x: number; role: ColRole }[] = [];
  const seen = new Set<ColRole>();
  let money = false;
  for (const c of row.cells) {
    if (MONEY_HEADER.test(c.text)) money = true;
    const role = headerRole(c.text);
    // First cell of each role wins; every other header cell still becomes an
    // "ignore" boundary so its data (room names, notes) can't bleed into a
    // neighboring column.
    if (role && !seen.has(role)) {
      seen.add(role);
      bounds.push({ x: c.x, role });
    } else {
      bounds.push({ x: c.x, role: "ignore" });
    }
  }
  const isTableHeader = seen.has("width") && seen.has("height");
  if (money) return isTableHeader ? "money" : null;
  if (!seen.has("name") || !isTableHeader) return null;
  bounds.sort((a, b) => a.x - b.x);
  return { y: row.y, bounds };
}

// Range membership: the cell belongs to the rightmost column whose x (minus a
// small pad for slightly-outdented data) is ≤ the cell's x. Anything left of
// the first boundary belongs to the first column — data in the leftmost column
// often outdents past its own header ("CABINET BOX STYLE" at x82, names at x52).
const COL_PAD = 12; // pt
function columnFor(hdr: HeaderCols, x: number): ColRole | null {
  let role: ColRole = hdr.bounds[0].role;
  for (const b of hdr.bounds) {
    if (x >= b.x - COL_PAD) role = b.role;
    else break;
  }
  return role === "ignore" ? null : role;
}

interface PendingRecord {
  nameParts: { y: number; text: string }[];
  w: number | null;
  h: number | null;
  d: number | null;
  qty: number | null;
  unit: string | null;
  raw: string[];
}

function recordComplete(r: PendingRecord): boolean {
  return r.nameParts.length > 0 && r.w != null && r.h != null;
}

// Header tables are already vetted (real header + a table's worth of rows), so
// the description gate is looser than the prose heuristic's: door/drawer-style
// names ("Pair Door - Single Drawer") are real carcasses in these schedules.
const HEADER_NOUN =
  /\b(doors?|drawers?|shel(?:f|ves)|hamper|pull\s?-?\s?outs?|rollout|microwave|spice|wine|appliance)\b/i;

function finishRecord(r: PendingRecord, page: number): CabinetLineItem | null {
  if (!recordComplete(r)) return null;
  const desc = r.nameParts
    .sort((a, b) => a.y - b.y)
    .map((p) => p.text)
    .join(" ")
    .replace(/\s+/g, " ")
    .trim();
  if (!CABINET_NOUN.test(desc) && !HEADER_NOUN.test(desc)) return null;
  const w = r.w as number;
  const h = r.h as number;
  // Header-mapped tables are trusted further than the prose heuristic, but the
  // dims must still be physical cabinet-box inches.
  if (!(w > 2 && w <= 130 && h > 2 && h <= 130)) return null;
  const { category, filler } = categoryFor(desc);
  const depth =
    r.d != null && r.d > 3 && r.d <= 40 ? r.d : category === "casework_wall" ? 12 : 24;
  const qty = r.qty != null && r.qty >= 1 && r.qty <= 50 ? Math.round(r.qty) : 1;
  const tag = `${desc} ${w % 1 === 0 ? w : w.toFixed(3).replace(/0+$/, "")}`
    .replace(/\s+/g, " ")
    .trim();
  return {
    source_page: page,
    tag: filler ? `${tag} Filler` : tag,
    room: null,
    qty,
    category,
    width_in: w,
    height_in: h,
    depth_in: depth,
    door_style: null,
    material: null,
    finish: null,
    assembled: null,
    notes: `schedule: ${r.raw.join(" ")}${r.unit ? ` [unit ${r.unit}]` : ""}`,
    confidence: 0.9,
    estimated: false,
    bbox_2d: null,
  };
}

// Parse all header-defined cabinet tables on one page.
//
// Records are segmented by WIDTH anchors: every record has exactly one value in
// the width column, while its NAME can wrap onto rows above or below it and its
// height/depth/qty can land on a different visual row than the width (both
// occur in real packets). So: find the width rows, then attach every other row
// to the nearest width anchor by vertical distance.
//
// `carry` is a header still open from the PREVIOUS page: long tables continue
// onto the next page without repeating their header, so rows above this page's
// first header belong to the carried table. The returned `carry` is the header
// still open at the bottom of this page (null after a money table closed it).
export function parseHeaderTables(
  fragments: TextFragment[],
  page: number,
  carry: HeaderCols | null = null
): { lines: CabinetLineItem[]; carry: HeaderCols | null; money: boolean } {
  const rows = reconstructRowCells(fragments);
  const out: CabinetLineItem[] = [];

  // Split the page into table sections (header row → rows until next header).
  let hdr: HeaderCols | null = carry;
  let section: RowCells[] = [];
  let money = false;

  const flush = () => {
    if (hdr) out.push(...parseSection(hdr, section, page));
    section = [];
  };

  for (const row of rows) {
    const found = findHeader(row);
    if (found === "money") {
      flush();
      hdr = null;
      money = true;
    } else if (found) {
      flush();
      hdr = found;
    } else if (hdr) {
      section.push(row);
    }
  }
  flush();
  return { lines: out, carry: hdr, money };
}

function parseSection(
  hdr: HeaderCols,
  rows: RowCells[],
  page: number
): CabinetLineItem[] {
  // Classify every cell once.
  interface Cell {
    y: number;
    role: ColRole;
    text: string;
  }
  const cells: Cell[] = [];
  for (const row of rows) {
    for (const c of row.cells) {
      const role = columnFor(hdr, c.x);
      if (role) cells.push({ y: row.y, role, text: c.text });
    }
  }

  // Width anchors define the records.
  const anchors: { y: number; w: number; rec: PendingRecord }[] = [];
  for (const c of cells) {
    if (c.role !== "width") continue;
    const v = parseDimCell(c.text.replace(/\.00$/, ""));
    if (v == null) continue;
    anchors.push({
      y: c.y,
      w: v,
      rec: { nameParts: [], w: v, h: null, d: null, qty: null, unit: null, raw: [c.text] },
    });
  }
  if (anchors.length === 0) return [];
  anchors.sort((a, b) => a.y - b.y);

  const nearest = (y: number) => {
    let best = anchors[0];
    let bestD = Infinity;
    for (const a of anchors) {
      const d = Math.abs(a.y - y);
      if (d < bestD) {
        bestD = d;
        best = a;
      }
    }
    return best;
  };

  for (const c of cells) {
    if (c.role === "width") continue;
    const { rec } = nearest(c.y);
    if (c.role === "name") {
      rec.nameParts.push({ y: c.y, text: c.text });
      rec.raw.push(c.text);
    } else if (c.role === "unit") {
      rec.unit = rec.unit ?? c.text;
    } else {
      const v = parseDimCell(c.text.replace(/\.00$/, ""));
      if (v == null) continue;
      if (c.role === "height" && rec.h == null) rec.h = v;
      else if (c.role === "depth" && rec.d == null) rec.d = v;
      else if (c.role === "qty" && rec.qty == null) rec.qty = v;
      rec.raw.push(c.text);
    }
  }

  const out: CabinetLineItem[] = [];
  for (const a of anchors) {
    const line = finishRecord(a.rec, page);
    if (line) out.push(line);
  }
  return out;
}

// Some packets print the same schedule table more than once (one copy per door-
// style option). Two pages whose parsed rows are IDENTICAL multisets are one
// schedule printed twice — keep the first. (Distinct pages of one long schedule
// never have identical row sets, so this only drops true reprints.)
export function dedupeSchedulePages(extraction: ScheduleExtraction): ScheduleExtraction {
  const signature = (page: number) =>
    extraction.lines
      .filter((l) => l.source_page === page)
      .map((l) => `${l.tag}|${l.width_in}|${l.height_in}|${l.depth_in}|${l.qty}`)
      .sort()
      .join("\n");
  const seen = new Map<string, number>();
  const dropPages = new Set<number>();
  for (const page of extraction.schedulePages) {
    const sig = signature(page);
    if (seen.has(sig)) dropPages.add(page);
    else seen.set(sig, page);
  }
  if (dropPages.size === 0) return extraction;
  return {
    lines: extraction.lines.filter((l) => !dropPages.has(l.source_page ?? -1)),
    schedulePages: extraction.schedulePages.filter((p) => !dropPages.has(p)),
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
  // Pass 1 — header-defined tables (exact column mapping), with the open
  // header carried across page breaks so a table's continuation rows on the
  // next page still parse.
  const headerLinesByPage = new Map<number, CabinetLineItem[]>();
  // Pages carrying a priced component list (doors/fronts): the positional
  // heuristic would slurp those rows as cabinets, so bar them from pass 2.
  const moneyPages = new Set<number>();
  let carry: ReturnType<typeof parseHeaderTables>["carry"] = null;
  for (const { page, fragments } of pages) {
    const res = parseHeaderTables(fragments, page, carry);
    carry = res.carry;
    if (res.money) moneyPages.add(page);
    if (res.lines.length > 0) headerLinesByPage.set(page, res.lines);
  }
  const headerLines = [...headerLinesByPage.values()].flat();
  // Gate on REAL cabinet rows: a header misfire or a filler/drawer-box-only
  // table must not claim the document (or suppress the legacy heuristic).
  const realHeaderRows = headerLines.filter((l) => !isNonBoxCasework(l)).length;
  const useHeader = realHeaderRows >= MIN_SCHEDULE_ROWS;

  const lines: CabinetLineItem[] = [];
  const schedulePages: number[] = [];
  if (useHeader) {
    for (const [page, ls] of headerLinesByPage) {
      // A page whose rows are all fillers/panels/drawer-boxes isn't a cabinet
      // schedule page (the packet's accessory lists parse but don't qualify).
      if (!ls.some((l) => !isNonBoxCasework(l))) continue;
      schedulePages.push(page);
      lines.push(...ls);
    }
  }

  // Pass 2 — positional row heuristic on pages the header pass didn't claim
  // (mixed packets carry both header tables and R1C1-style rows).
  for (const { page, fragments } of pages) {
    if (moneyPages.has(page)) continue;
    if (useHeader && headerLinesByPage.has(page)) continue;
    const parsed = reconstructRows(fragments)
      .map(parseRow)
      .filter((l): l is CabinetLineItem => l != null)
      .map((l) => ({ ...l, source_page: page }));
    if (
      parsed.length >= MIN_SCHEDULE_ROWS &&
      parsed.some((l) => !isNonBoxCasework(l))
    ) {
      schedulePages.push(page);
      lines.push(...parsed);
    }
  }
  schedulePages.sort((a, b) => a - b);
  // A packet that prints the same schedule once per door-style option must not
  // double the cabinet list.
  return dedupeSchedulePages({ lines, schedulePages });
}
