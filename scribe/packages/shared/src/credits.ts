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
