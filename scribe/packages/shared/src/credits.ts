// Credits (accounts-plan.md §3): 1 credit = 1 page read. Pure, so the API's
// hold and the Pages screen's cost preview are the same number.

export interface CreditSettings {
  minPagesPerJob: number;
  firstJobFree: boolean;
  creditsEnforced: boolean;
}

export interface JobCharge {
  pages: number;
  credits: number;
  free: boolean;
}

// What a job of `pages` selected pages costs. `freeAvailable` is whether the
// org's free first job is still unused (and the setting is on).
export function jobCharge(
  pages: number,
  settings: Pick<CreditSettings, "minPagesPerJob">,
  freeAvailable: boolean
): JobCharge {
  if (freeAvailable) return { pages, credits: 0, free: true };
  return { pages, credits: Math.max(pages, settings.minPagesPerJob, 0), free: false };
}

// Only an enforced setting ever blocks; recording and showing never do.
export function chargeBlocked(
  charge: JobCharge,
  balance: number,
  settings: Pick<CreditSettings, "creditsEnforced">
): boolean {
  return settings.creditsEnforced && charge.credits > balance;
}

// Page packs sold through Stripe Checkout (owner, 2026-10-19). Prices are
// integer cents; the pack id is what the web sends and the webhook trusts.
export const PAGE_PACKS = [
  { id: "pages_25", pages: 25, priceCents: 2_500 },
  { id: "pages_100", pages: 100, priceCents: 9_000 },
  { id: "pages_500", pages: 500, priceCents: 40_000 },
] as const;

export interface PagePack {
  id: string;
  pages: number;
  priceCents: number;
}

// Any number of pages at list price (owner, 2026-10-20). The floor keeps
// Stripe's fixed fee from eating tiny purchases.
export const CUSTOM_PACK_ID = "custom";
export const PAGE_PRICE_CENTS = 100;
export const CUSTOM_PAGES_MIN = 5;
export const CUSTOM_PAGES_MAX = 5_000;

export function customPack(pages: number): PagePack | null {
  if (!Number.isInteger(pages) || pages < CUSTOM_PAGES_MIN || pages > CUSTOM_PAGES_MAX) return null;
  return { id: CUSTOM_PACK_ID, pages, priceCents: pages * PAGE_PRICE_CENTS };
}

// A fixed pack by id, or a custom amount; null for anything we don't sell.
// Used by checkout (to price) and by the webhook (to check what was paid).
export function findPack(id: string, pages?: number): PagePack | null {
  if (id === CUSTOM_PACK_ID) return pages == null ? null : customPack(pages);
  return PAGE_PACKS.find((p) => p.id === id) ?? null;
}
