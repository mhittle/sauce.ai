// Client-facing copy for what the pipeline writes into `takeoffs.error`,
// `takeoffs.docSummary.warnings` and `takeoff_detections.error`. The worker
// keeps writing the technical sentence (it is the evidence a developer needs);
// the screen shows a short plain-language line to the customer and the raw
// text only to admins (see TechnicalDetail). A note that maps to `null` is
// developer-only and is hidden from customers entirely.

export interface FriendlyMessage {
  text: string;
  detail: string;
}

const ERROR_RULES: [RegExp, string][] = [
  [
    /credit balance|invalid_request_error|overloaded|rate.?limit|\b529\b|\b429\b|ANTHROPIC_API_KEY/i,
    "The reading service isn't available right now. Please try again in a few minutes.",
  ],
  [
    /media.?type|image\/png|image\/jpeg/i,
    "This image couldn't be read. Try uploading it as a PNG or JPEG file.",
  ],
  [
    /no usable sizes|measuring step/i,
    "We couldn't measure the cabinets this time. Please try Build again.",
  ],
  [
    /^build takeoff failed/i,
    "We couldn't finish building this takeoff. Please try Build again.",
  ],
  [
    /nothing new to build/i,
    "Every marked area is already in the takeoff — change an area or add one to build again.",
  ],
];

export function friendlyError(raw: string): FriendlyMessage {
  for (const [re, text] of ERROR_RULES) {
    if (re.test(raw)) return { text, detail: raw };
  }
  return {
    text: "Something went wrong while reading this file. Please try again.",
    detail: raw,
  };
}

export function friendlyAreaError(raw: string | null): FriendlyMessage {
  return {
    text: "This area couldn't be scanned. Try Find again, or redraw the area.",
    detail: raw ?? "unknown",
  };
}

// Read notes: [pattern, customer text | null (developer-only)]. `$1`/`$2`
// substitute the pattern's capture groups.
const NOTE_RULES: [RegExp, string | null][] = [
  [
    /^No cabinet schedule detected/,
    "No cabinet schedule was found, so the quantities are estimated from the drawings — check them before quoting.",
  ],
  [/not valid JSON.*nothing defaulted/, null],
  [
    /not valid JSON.*?(\d+) of (\d+) defaulted/,
    "$1 cabinets couldn't be measured and use standard sizes — check them.",
  ],
  [
    /not valid JSON|not parseable JSON|no cabinets array|sizes defaulted/,
    "The cabinet sizes couldn't be read from the drawings, so standard sizes were used — check every size.",
  ],
  [
    /^(\d+) of (\d+) cabinets have estimated dimensions/,
    "$1 cabinets have estimated sizes — check them against the drawing.",
  ],
  [
    /cut off at the token limit/,
    "The measuring step was cut short, so some cabinets may have standard sizes — check them.",
  ],
  [
    /context page\(s\) beyond the .*page cap/,
    "This set is large, so some pages weren't used when measuring.",
  ],
  [
    /plan regions found — only the first/,
    "Some floor-plan areas were measured at lower detail — check their cabinets.",
  ],
  [
    /^plan run .* kept the first/,
    "A long run was split into many cabinets — check it.",
  ],
  [
    /^plan run .* undecomposed/,
    "One run was counted as a single cabinet, but it may hold several — check it.",
  ],
  [
    /^plan run .*(over-split|over-wide|probably missing)/,
    "The cabinets along one run don't add up to its length — check that run.",
  ],
  [
    /is not read by the wizard yet/,
    "One selected page type isn't read automatically yet — check its counts by hand.",
  ],
  [
    /None of the selected pages has a readable type/,
    "None of the selected pages could be read. Re-tag the pages if this is wrong.",
  ],
  [/cross-val/, null],
  [
    /extraction failed|estimate failed|region detection skipped/,
    "Part of a page couldn't be read — check its cabinets.",
  ],
];

const DEFAULT_NOTE = "Some of the drawing couldn't be read fully — check the breakdown.";

export function friendlyNote(raw: string): { text: string | null; detail: string } {
  for (const [re, text] of NOTE_RULES) {
    const m = raw.match(re);
    if (m) {
      return {
        text: text == null ? null : text.replace(/\$(\d)/g, (_, i) => m[Number(i)] ?? ""),
        detail: raw,
      };
    }
  }
  return { text: DEFAULT_NOTE, detail: raw };
}

// Customer-visible notes, deduplicated by text; developer-only notes drop
// out unless `includeHidden` (admins see everything).
export function friendlyNotes(
  raws: string[],
  includeHidden = false
): { text: string; details: string[] }[] {
  const byText = new Map<string, string[]>();
  for (const raw of raws) {
    const { text, detail } = friendlyNote(raw);
    const key = text ?? (includeHidden ? `(developer note) ${raw}` : null);
    if (key == null) continue;
    const list = byText.get(key) ?? [];
    list.push(detail);
    byText.set(key, list);
  }
  return [...byText.entries()].map(([text, details]) => ({ text, details }));
}

// Admin → Usage could not be fetched (admin-only screen).
export const USAGE_LOAD_FAILED = "Usage couldn't be loaded. Try again in a moment.";

// --- Credits (one page read = one credit) ---

const plural = (n: number, one: string, many: string) => `${n} ${Math.abs(n) === 1 ? one : many}`;

// Top-bar balance.
export function creditsShort(balance: number, firstJobFree: boolean): string {
  if (firstJobFree && balance <= 0) return "First job free";
  return plural(balance, "page left", "pages left");
}

// Cost preview where a job is submitted.
export function creditCostLine(
  charge: { pages: number; credits: number; free: boolean },
  balance: number
): string {
  if (charge.free) return `Your first job is free — reading ${plural(charge.pages, "page", "pages")} uses nothing from your balance.`;
  const left = balance - charge.credits;
  const minimum = charge.credits > charge.pages ? ` (${charge.credits}-page minimum per job)` : "";
  return `Reading ${plural(charge.pages, "page", "pages")} uses ${charge.credits} from your balance${minimum}. ${
    left >= 0 ? `${left} left after this job.` : `Your balance is ${balance}.`
  }`;
}

// Shown when enforced credits don't cover a job (API 402).
export const CREDITS_INSUFFICIENT =
  "You don't have enough pages left for this job. Buy more pages on your Account page, or select fewer pages.";

// Toast body for a failed job submit: the plain credits line for a 402,
// else the server's text.
export function submitErrorText(err: unknown): string {
  if ((err as { status?: number })?.status === 402) return CREDITS_INSUFFICIENT;
  return err instanceof Error ? err.message : String(err);
}

export const CREDIT_REASON_LABEL: Record<string, string> = {
  signup_grant: "Included with your account",
  admin_grant: "Pages added",
  purchase: "Pages bought",
  hold: "Job submitted",
  settle: "Job finished",
  release: "Pages returned",
  refund: "Refund",
  adjust: "Correction",
};

// Admin → Credits could not be fetched (admin-only screen).
export const CREDITS_LOAD_FAILED = "Credits couldn't be loaded. Try again in a moment.";

// --- Buying pages (Stripe Checkout) ---

export function packLabel(pages: number, priceCents: number): string {
  return `${pages} pages — $${(priceCents / 100).toLocaleString("en-US")}`;
}

export const BILLING_OFF =
  "Buying pages online isn't switched on yet. Contact us and we'll add pages to your account.";

export const PURCHASE_PENDING =
  "Payment received — your pages will appear here in a moment.";

export const PURCHASE_DONE = "Payment received — your pages have been added.";

// Toast body when Checkout could not be opened.
export function checkoutErrorText(err: unknown): string {
  if ((err as { status?: number })?.status === 503) return BILLING_OFF;
  return "We couldn't open the payment page. Please try again.";
}

// Custom page amount on Account → Pages.
export function customBuyLabel(pages: number, pagePriceCents: number): string {
  return `Buy for $${((pages * pagePriceCents) / 100).toLocaleString("en-US")}`;
}

export function customHint(
  pages: number,
  custom: { min: number; max: number; pagePriceCents: number }
): string {
  if (!Number.isInteger(pages) || pages < custom.min) return `Minimum ${custom.min} pages.`;
  if (pages > custom.max) return `Up to ${custom.max.toLocaleString("en-US")} pages at a time.`;
  return `$${(custom.pagePriceCents / 100).toLocaleString("en-US")} a page. The 100 and 500 packs cost less per page.`;
}

// --- Lines the quote can't price (SCR-016) ---

// Plain words for pricing's reason a line can't be priced.
export function friendlyPriceIssue(raw: string): string {
  const limit = raw.match(/^(width|height|depth) ([\d.]+)" is (over|under) the ([\d.]+)" (max|min) set for (.+)$/);
  if (limit) {
    const [, which, value, side, bound, kind, product] = limit;
    const tip = which === "width" && side === "over"
      ? "Change the width, split it into two cabinets, or pick another product."
      : `Change the ${which}, or pick another product.`;
    return `${value}" ${which} is ${side} the ${bound}" ${kind} set for ${product} in Admin › Pricing. ${tip}`;
  }
  const dim = raw.match(/^(width|height|depth) ([\d.]+)" outside ([\d.]+)"–([\d.]+)"/);
  if (dim) {
    const [, which, value, min, max] = dim;
    const tip = which === "width" && Number(value) > Number(max)
      ? " Change the width, or split it into two cabinets."
      : ` Change the ${which}, or pick another product.`;
    return `${value}" ${which} is outside what this product takes (${min}"–${max}").${tip}`;
  }
  if (/^unmatched/.test(raw)) return "No product picked yet — pick one in the takeoff.";
  if (/missing from pricing config|not in the current price list/.test(raw)) {
    return "This product isn't in the price list this quote uses — pick the product again in the takeoff.";
  }
  if (/^material /.test(raw)) return "This product has no price for that material — change the material or pick another product.";
  if (/^finish /.test(raw)) return "This product has no price for that finish — change the finish or pick another product.";
  return raw;
}

export function unpricedLineTitle(tag: string | null, n: number): string {
  return tag?.trim() ? tag : `Line ${n}`;
}

// Toast body when a takeoff line edit is refused: a hand-picked product that
// can't price the line (422) gets the plain reason; anything else as sent.
export function lineSaveErrorText(err: unknown): string {
  const msg = err instanceof Error ? err.message : String(err);
  if ((err as { status?: number })?.status === 422) return friendlyPriceIssue(msg);
  return msg;
}

// --- Quote send blockers: placeholder rates ---

// The quote was built while placeholder rates were in use and real rates
// have been saved since: a quote keeps its price list, so it needs rebuilding.
export const QUOTE_OLD_RATES =
  "This quote was built with the old placeholder rates — build a new quote to use the current rates";
export const QUOTE_PLACEHOLDER_ADMIN = "Placeholder rates in use — enter real rates in Admin › Pricing";
export const QUOTE_PLACEHOLDER_MEMBER = "Pricing for this quote isn't finalized yet — ask an admin";
export const REBUILD_QUOTE = "Build a new quote";
export const QUOTE_REBUILT = "New quote built with the current rates";

// Admin › Pricing: per-product size limits.
export const SIZE_LIMITS_TITLE = "Size limits (inches)";
export const SIZE_LIMITS_HINT =
  "Leave blank for no limit. A cabinet outside a limit isn't priced on this product — the takeoff and quote say why.";

// --- Admin › Users: invites by CSV ---

export const INVITE_IMPORT_HINT =
  "One person per row: email (required), name, company, pages_included, note. Download the template to start. You'll see who is in the file before anything is sent.";

export const EMAIL_NOT_CONFIGURED =
  "Email is not set up on the API (SMTP_HOST / SMTP_USER / SMTP_PASS / EMAIL_FROM), so invites are not sent — copy each link after creating it.";

export const INVITE_STATUS_LABEL: Record<"sent" | "created" | "skipped", string> = {
  sent: "Invite emailed",
  created: "Invite created — email not set up, copy the link",
  skipped: "Skipped",
};

export function importPreviewLine(n: number): string {
  return n === 0 ? "no one to invite in this file." : `${n} ${n === 1 ? "person" : "people"} to invite.`;
}

export function importErrorsLine(n: number): string {
  return `${n} row${n === 1 ? "" : "s"} can't be used and will be left out:`;
}

export function importResultLine(results: { status: "sent" | "created" | "skipped" }[]): string {
  const c = (s: string) => results.filter((r) => r.status === s).length;
  const parts = [
    c("sent") ? `${c("sent")} emailed` : "",
    c("created") ? `${c("created")} created (copy links)` : "",
    c("skipped") ? `${c("skipped")} skipped` : "",
  ].filter(Boolean);
  return `Invites: ${parts.join(", ") || "none"}`;
}

// --- Door / drawer-front counts on the review (SCR-015) ---

export const FACE_GUESS_BADGE = "guessed";

export function faceCountTitle(counted: boolean): string {
  return counted
    ? "Doors and drawer fronts per cabinet, counted on the drawing or set by you. Clear a number to go back to the guess."
    : "Guessed from the cabinet's name — the drawing didn't show the face. Type the right numbers to fix the doors and fronts.";
}
