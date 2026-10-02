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
  "You don't have enough pages left for this job. Buy more pages, or select fewer pages.";

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
  release: "Job failed — pages returned",
  refund: "Refund",
  adjust: "Correction",
};

// Admin → Credits could not be fetched (admin-only screen).
export const CREDITS_LOAD_FAILED = "Credits couldn't be loaded. Try again in a moment.";
