import type { NormalizedProject } from "@scribe/shared";

// One adapter module per source (PRD §5.4). Adapters must respect robots.txt
// and rate limits (≤ 1 req/sec/host default), send an honest User-Agent, and
// never bypass logins/paywalls/CAPTCHAs. Public, unauthenticated data only.

export interface SourceRow {
  id: string;
  name: string;
  type: string;
  baseUrl: string;
  config: Record<string, unknown>;
}

export interface FetchResult {
  projects: NormalizedProject[];
  nextCursor: string | null;
}

export interface SourceAdapter {
  type: string;
  fetchSince(source: SourceRow, cursor: string | null): Promise<FetchResult>;
}

export const USER_AGENT =
  "ScribeBot/0.1 (CabinetNow estimating; contact: hank@cabinetnow.com)";

const lastRequestByHost = new Map<string, number>();

// Default ≤ 1 req/sec/host with exponential backoff on 429/5xx (PRD §5.3).
export async function politeFetch(
  url: string,
  init: RequestInit = {},
  minIntervalMs = 1000
): Promise<Response> {
  const host = new URL(url).host;
  const last = lastRequestByHost.get(host) ?? 0;
  const wait = last + minIntervalMs - Date.now();
  if (wait > 0) await new Promise((r) => setTimeout(r, wait));
  lastRequestByHost.set(host, Date.now());

  let backoff = 2000;
  for (let attempt = 0; attempt < 4; attempt++) {
    const res = await fetch(url, {
      ...init,
      headers: { "user-agent": USER_AGENT, ...(init.headers ?? {}) },
    });
    if (res.status !== 429 && res.status < 500) return res;
    await new Promise((r) => setTimeout(r, backoff));
    backoff *= 2;
  }
  return fetch(url, {
    ...init,
    headers: { "user-agent": USER_AGENT, ...(init.headers ?? {}) },
  });
}
