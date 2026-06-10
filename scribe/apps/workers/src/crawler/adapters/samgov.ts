import { z } from "zod";
import type { NormalizedProject } from "@scribe/shared";
import {
  FetchResult,
  politeFetch,
  SourceAdapter,
  SourceRow,
} from "./types.js";

// SAM.gov opportunities adapter (PRD §5.2: public procurement / bid boards —
// these frequently attach full plan sets as public PDFs). Requires the free
// SAMGOV_API_KEY. Cursor = last postedDate seen.

const SamGovConfig = z.object({
  keywords: z.array(z.string()).default(["casework", "cabinet", "millwork"]),
  jurisdiction: z.string().default("Federal"),
});

function fmt(d: Date): string {
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${mm}/${dd}/${d.getFullYear()}`;
}

export const samgovAdapter: SourceAdapter = {
  type: "samgov",

  async fetchSince(source: SourceRow, cursor: string | null): Promise<FetchResult> {
    const apiKey = process.env.SAMGOV_API_KEY;
    if (!apiKey) {
      throw new Error("SAMGOV_API_KEY not set — source blocked until configured");
    }
    const cfg = SamGovConfig.parse(source.config);

    const from = cursor
      ? new Date(cursor)
      : new Date(Date.now() - 30 * 24 * 3600 * 1000);
    const to = new Date();

    const projects: NormalizedProject[] = [];
    let latestPosted = cursor;

    for (const keyword of cfg.keywords) {
      const params = new URLSearchParams({
        api_key: apiKey,
        postedFrom: fmt(from),
        postedTo: fmt(to),
        title: keyword,
        limit: "100",
        ptype: "o,k", // solicitations + combined synopsis/solicitation
      });
      const url = `${source.baseUrl}/opportunities/v2/search?${params}`;
      const res = await politeFetch(url);
      if (!res.ok) {
        throw new Error(`samgov: HTTP ${res.status} for keyword "${keyword}"`);
      }
      const body = (await res.json()) as {
        opportunitiesData?: Record<string, unknown>[];
      };
      const fetchedAt = new Date().toISOString();

      for (const opp of body.opportunitiesData ?? []) {
        const posted = String(opp.postedDate ?? "");
        if (posted && (!latestPosted || posted > latestPosted)) {
          latestPosted = posted;
        }
        const office = (opp.officeAddress ?? {}) as Record<string, unknown>;
        const links = (opp.resourceLinks ?? []) as string[];
        projects.push({
          canonical_address:
            [office.city, office.state].filter(Boolean).join(", ") || null,
          jurisdiction: cfg.jurisdiction,
          permit_number: String(opp.solicitationNumber ?? "") || null,
          parcel: null,
          project_type: "government",
          valuation_cents: null,
          description:
            [opp.title, opp.description].filter(Boolean).join(" — ") || null,
          gc_name: String(opp.fullParentPathName ?? "") || null,
          gc_contact: null,
          document_urls: links,
          source_ref: {
            source_id: source.id,
            external_id: String(opp.noticeId ?? opp.solicitationNumber ?? ""),
            url: String(opp.uiLink ?? url),
            fetched_at: fetchedAt,
          },
        });
      }
    }

    return { projects, nextCursor: latestPosted };
  },
};
