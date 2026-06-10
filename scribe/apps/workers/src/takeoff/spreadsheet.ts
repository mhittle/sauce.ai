import * as XLSX from "xlsx";
import { z } from "zod";
import {
  CabinetLineItem,
  LineCategory,
  parseTag,
  repairLine,
} from "@scribe/shared";
import {
  HEADER_INFERENCE_SYSTEM,
  HAIKU_MODEL,
} from "@scribe/prompts";
import {
  extractJson,
  getAnthropic,
  TakeoffBudget,
  textOf,
} from "../lib/anthropic.js";

// Deterministic column-mapping flow with model-assisted header inference
// (cheap, no vision) — PRD §6.1.

export type FieldName =
  | "tag"
  | "room"
  | "qty"
  | "category"
  | "width_in"
  | "height_in"
  | "depth_in"
  | "door_style"
  | "material"
  | "finish"
  | "assembled"
  | "notes"
  | "ignore";

const HEADER_SYNONYMS: Record<FieldName, string[]> = {
  tag: ["tag", "item", "name", "cabinet", "cab", "code", "mark", "sku", "model"],
  room: ["room", "location", "area", "space", "unit"],
  qty: ["qty", "quantity", "count", "ea", "qty.", "#", "no"],
  category: ["category", "type", "producttype"],
  width_in: ["width", "w", "wide"],
  height_in: ["height", "h", "hgt", "tall"],
  depth_in: ["depth", "d", "deep"],
  door_style: ["doorstyle", "style", "door"],
  material: ["material", "species", "wood", "mat"],
  finish: ["finish", "color", "paint", "stain"],
  assembled: ["assembled", "assembly", "rta"],
  notes: ["notes", "comments", "remarks", "description", "desc"],
  ignore: [],
};

function norm(s: unknown): string {
  return String(s ?? "")
    .toLowerCase()
    .replace(/[^a-z0-9#]/g, "");
}

export function inferMapping(
  headerRow: unknown[]
): Partial<Record<number, FieldName>> {
  const mapping: Partial<Record<number, FieldName>> = {};
  for (const [i, cell] of headerRow.entries()) {
    const h = norm(cell);
    if (!h) continue;
    for (const [field, synonyms] of Object.entries(HEADER_SYNONYMS) as [
      FieldName,
      string[],
    ][]) {
      if (synonyms.includes(h)) {
        mapping[i] = field;
        break;
      }
    }
  }
  return mapping;
}

function findHeaderRow(rows: unknown[][]): number {
  let best = 0;
  let bestHits = 0;
  for (let r = 0; r < Math.min(rows.length, 10); r++) {
    const hits = Object.keys(inferMapping(rows[r] ?? [])).length;
    if (hits > bestHits) {
      best = r;
      bestHits = hits;
    }
  }
  return bestHits >= 2 ? best : -1;
}

const ModelMapping = z.object({
  mapping: z.record(z.string()),
  header_row: z.number().int().nonnegative(),
});

async function modelAssistMapping(
  rows: unknown[][],
  budget: TakeoffBudget
): Promise<{ mapping: Partial<Record<number, FieldName>>; headerRow: number }> {
  const client = getAnthropic();
  const sample = rows
    .slice(0, 8)
    .map((r, i) => `${i}: ${JSON.stringify(r.slice(0, 20))}`)
    .join("\n");
  const message = await client.messages.create({
    model: HAIKU_MODEL,
    max_tokens: 1000,
    system: HEADER_INFERENCE_SYSTEM,
    messages: [
      {
        role: "user",
        content: `First rows of the spreadsheet:\n${sample}\nRespond with the JSON object only.`,
      },
    ],
  });
  budget.record(message.usage);
  const parsed = ModelMapping.parse(extractJson(textOf(message)));
  const mapping: Partial<Record<number, FieldName>> = {};
  const valid = new Set(Object.keys(HEADER_SYNONYMS));
  for (const [col, field] of Object.entries(parsed.mapping)) {
    if (valid.has(field)) mapping[Number(col)] = field as FieldName;
  }
  return { mapping, headerRow: parsed.header_row };
}

function toNumber(v: unknown): number | null {
  if (v == null || v === "") return null;
  if (typeof v === "number") return Number.isFinite(v) ? v : null;
  // Handle fractions like 34 1/2 and quotes like 24"
  const s = String(v).replace(/"/g, "").trim();
  const frac = s.match(/^(\d+)\s+(\d+)\/(\d+)$/);
  if (frac) {
    return parseInt(frac[1], 10) + parseInt(frac[2], 10) / parseInt(frac[3], 10);
  }
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}

function toBool(v: unknown): boolean | null {
  if (v == null || v === "") return null;
  const s = norm(v);
  if (["y", "yes", "true", "1", "assembled"].includes(s)) return true;
  if (["n", "no", "false", "0", "rta", "flat", "flatpack"].includes(s)) return false;
  return null;
}

function rowToLine(
  row: unknown[],
  mapping: Partial<Record<number, FieldName>>
): CabinetLineItem | null {
  const get = (field: FieldName): unknown => {
    for (const [col, f] of Object.entries(mapping)) {
      if (f === field) return row[Number(col)];
    }
    return undefined;
  };

  const tag = get("tag") != null && get("tag") !== "" ? String(get("tag")) : null;
  const qty = toNumber(get("qty")) ?? (tag ? 1 : null);
  if (!tag && qty == null) return null;

  const rawCategory = norm(get("category"));
  const category = LineCategory.options.includes(
    rawCategory as LineCategory
  )
    ? (rawCategory as LineCategory)
    : (tag ? parseTag(tag)?.category : null) ?? "unknown";

  const line: CabinetLineItem = {
    source_page: null,
    tag,
    room: get("room") != null && get("room") !== "" ? String(get("room")) : null,
    qty: qty ?? 1,
    category,
    width_in: toNumber(get("width_in")),
    height_in: toNumber(get("height_in")),
    depth_in: toNumber(get("depth_in")),
    door_style:
      get("door_style") != null && get("door_style") !== ""
        ? String(get("door_style"))
        : null,
    material:
      get("material") != null && get("material") !== ""
        ? String(get("material"))
        : null,
    finish:
      get("finish") != null && get("finish") !== "" ? String(get("finish")) : null,
    assembled: toBool(get("assembled")),
    notes:
      get("notes") != null && get("notes") !== "" ? String(get("notes")) : null,
    // Deterministic intake: high confidence; tag/dim conflicts lower it below.
    confidence: 0.95,
  };
  return repairLine(line);
}

export async function parseSpreadsheet(
  data: Buffer,
  budget: TakeoffBudget,
  opts: { modelAssist: boolean }
): Promise<{ lines: CabinetLineItem[]; warnings: string[] }> {
  const wb = XLSX.read(data, { type: "buffer" });
  const warnings: string[] = [];
  const lines: CabinetLineItem[] = [];

  for (const sheetName of wb.SheetNames) {
    const sheet = wb.Sheets[sheetName];
    const rows = XLSX.utils.sheet_to_json<unknown[]>(sheet, {
      header: 1,
      defval: null,
    });
    if (rows.length === 0) continue;

    let headerRow = findHeaderRow(rows);
    let mapping =
      headerRow >= 0 ? inferMapping(rows[headerRow] ?? []) : {};

    if (Object.keys(mapping).length < 2 && opts.modelAssist) {
      try {
        const assisted = await modelAssistMapping(rows, budget);
        if (Object.keys(assisted.mapping).length >= 2) {
          mapping = assisted.mapping;
          headerRow = assisted.headerRow;
        }
      } catch (err) {
        warnings.push(
          `sheet "${sheetName}": model header inference failed (${String(err)})`
        );
      }
    }

    if (Object.keys(mapping).length < 2) {
      warnings.push(
        `sheet "${sheetName}": could not infer column mapping — skipped`
      );
      continue;
    }

    for (const row of rows.slice(headerRow + 1)) {
      const line = rowToLine(row, mapping);
      if (line) lines.push(line);
    }
  }

  if (lines.length === 0) {
    warnings.push("no line items found in any sheet");
  }
  return { lines, warnings };
}
