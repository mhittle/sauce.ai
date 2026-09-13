// Human labels + tones for every status enum the UI shows, and the fixed
// cabinet-category palette shared by the drawing overlay, the line table and
// the quote. One map so the words are the same on every screen.

export type Tone = "neutral" | "blue" | "good" | "warn" | "bad";

interface StatusMeta {
  label: string;
  tone: Tone;
}

const STATUS: Record<string, StatusMeta> = {
  // takeoffs
  processing: { label: "Reading", tone: "blue" },
  awaiting_pages: { label: "Choose pages", tone: "warn" },
  awaiting_boxes: { label: "Mark cabinets", tone: "warn" },
  extracted: { label: "Needs review", tone: "warn" },
  review: { label: "Needs review", tone: "warn" },
  approved: { label: "Approved", tone: "good" },
  failed: { label: "Failed", tone: "bad" },
  // quotes
  draft: { label: "Draft quote", tone: "warn" },
  sent: { label: "Sent", tone: "good" },
  won: { label: "Won", tone: "good" },
  lost: { label: "Lost", tone: "bad" },
  expired: { label: "Expired", tone: "neutral" },
  // prospects
  new: { label: "New", tone: "blue" },
  triaged: { label: "Triaged", tone: "neutral" },
  quoting: { label: "Quoting", tone: "warn" },
  quoted: { label: "Quoted", tone: "good" },
  ignored: { label: "Ignored", tone: "neutral" },
  // crawler sources
  active: { label: "Active", tone: "good" },
  inactive: { label: "Paused", tone: "neutral" },
  blocked: { label: "Blocked", tone: "bad" },
};

export function labelFor(status: string): string {
  return STATUS[status]?.label ?? status.replace(/_/g, " ");
}

export function toneFor(status: string): Tone {
  return STATUS[status]?.tone ?? "neutral";
}

export const CATEGORY_LABELS: Record<string, string> = {
  casework_base: "Base",
  casework_wall: "Wall",
  casework_tall: "Tall",
  vanity: "Vanity",
  closet: "Closet",
  door: "Door",
  drawer_front: "Drawer front",
  drawer_box: "Drawer box",
  panel: "Panel",
  filler: "Filler",
  trim: "Trim",
  hardware: "Hardware",
  countertop: "Countertop",
  unknown: "Unknown",
};

export function categoryLabel(category: string): string {
  return CATEGORY_LABELS[category] ?? category.replace(/_/g, " ");
}

// Concrete hex (light palette) for SVG fills over the drawing image — the
// sheet is always white, so these don't follow the chrome theme.
export const CATEGORY_HEX: Record<string, string> = {
  casework_base: "#2c5a8c",
  casework_wall: "#2f8a66",
  casework_tall: "#7a55c4",
  vanity: "#c2782b",
};
export const CATEGORY_HEX_DEFAULT = "#e0522b";

export function categoryHex(category: string): string {
  return CATEGORY_HEX[category] ?? CATEGORY_HEX_DEFAULT;
}

// Tailwind class (theme-aware) for dots/legends drawn on chrome, not on the sheet.
export function categoryDotClass(category: string): string {
  switch (category) {
    case "casework_base":
      return "bg-cat-base";
    case "casework_wall":
      return "bg-cat-wall";
    case "casework_tall":
      return "bg-cat-tall";
    case "vanity":
      return "bg-cat-vanity";
    default:
      return "bg-cat-other";
  }
}

// Short human-readable reference for a quote (support/PDF footer). The job's
// filename is the primary name everywhere on screen.
export function quoteRef(id: string): string {
  return `#${id.slice(0, 8).toUpperCase()}`;
}
