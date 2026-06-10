import { z } from "zod";
import type { NormalizedProject } from "@scribe/shared";
import {
  FetchResult,
  politeFetch,
  SourceAdapter,
  SourceRow,
} from "./types.js";

// Generic Socrata (SODA) building-permit adapter. One adapter covers every
// Socrata-backed jurisdiction; the dataset id + field map live in source
// config (jurisdiction list is config, not code — PRD §5.2).

const SocrataConfig = z.object({
  dataset: z.string(),
  jurisdiction: z.string(),
  field_map: z.object({
    permit_number: z.string(),
    description: z.string(),
    address: z.string(), // comma-separated source fields, concatenated
    valuation: z.string(),
    issued_date: z.string(),
  }),
  cursor_field: z.string(),
  page_size: z.number().int().positive().default(500),
});

function fieldValue(record: Record<string, unknown>, spec: string): string {
  return spec
    .split(",")
    .map((f) => String(record[f.trim()] ?? "").trim())
    .filter(Boolean)
    .join(" ");
}

export const socrataAdapter: SourceAdapter = {
  type: "socrata",

  async fetchSince(source: SourceRow, cursor: string | null): Promise<FetchResult> {
    const cfg = SocrataConfig.parse(source.config);
    const params = new URLSearchParams({
      $limit: String(cfg.page_size),
      $order: `${cfg.cursor_field} ASC`,
    });
    if (cursor) {
      params.set("$where", `${cfg.cursor_field} > '${cursor}'`);
    } else {
      // First run: last 30 days only
      const since = new Date(Date.now() - 30 * 24 * 3600 * 1000)
        .toISOString()
        .slice(0, 10);
      params.set("$where", `${cfg.cursor_field} > '${since}'`);
    }
    const url = `${source.baseUrl}/resource/${cfg.dataset}.json?${params}`;
    const headers: Record<string, string> = {};
    if (process.env.SOCRATA_APP_TOKEN) {
      headers["X-App-Token"] = process.env.SOCRATA_APP_TOKEN;
    }

    const res = await politeFetch(url, { headers });
    if (!res.ok) {
      throw new Error(`socrata ${source.name}: HTTP ${res.status}`);
    }
    const records = (await res.json()) as Record<string, unknown>[];
    const fetchedAt = new Date().toISOString();

    const projects: NormalizedProject[] = records.map((r) => {
      const valuationRaw = fieldValue(r, cfg.field_map.valuation);
      const valuation = Number(valuationRaw.replace(/[$,]/g, ""));
      return {
        canonical_address: fieldValue(r, cfg.field_map.address) || null,
        jurisdiction: cfg.jurisdiction,
        permit_number: fieldValue(r, cfg.field_map.permit_number) || null,
        parcel: null,
        project_type: null,
        valuation_cents: Number.isFinite(valuation)
          ? Math.round(valuation * 100)
          : null,
        description: fieldValue(r, cfg.field_map.description) || null,
        gc_name: null,
        gc_contact: null,
        document_urls: [],
        source_ref: {
          source_id: source.id,
          external_id:
            fieldValue(r, cfg.field_map.permit_number) ||
            JSON.stringify(r).slice(0, 64),
          url,
          fetched_at: fetchedAt,
        },
      };
    });

    let nextCursor = cursor;
    for (const r of records) {
      const v = fieldValue(r, cfg.cursor_field);
      if (v && (!nextCursor || v > nextCursor)) nextCursor = v;
    }

    return { projects, nextCursor };
  },
};
