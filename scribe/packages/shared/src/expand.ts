import type { CabinetLineItem } from "./schemas.js";
import { ESTIMATED_NOTE_PREFIX } from "./estimate.js";

// Box → component expansion (PRD §6.4): a cabinet is a box PLUS the doors and
// drawer fronts on its face. CabinetNow prices those faces separately, by the
// square foot, so to reproduce a quote each cabinet must spawn its door/front
// line items. This is a deterministic, IO-free catalog: given a cabinet's
// category + width + height + door/drawer config, it returns the face line
// items. Face sizes are standard estimates (good enough for ft² pricing).

const CABINET_CATEGORIES = [
  "casework_base",
  "casework_wall",
  "casework_tall",
  "vanity",
];

// Toe-kick / counter allowance removed from the cabinet height to get the
// door+front face height (wall cabinets have no toe kick).
const TOE_KICK_IN = 4.5;
// A drawer bank sitting above doors uses a short front; standalone drawer
// stacks split the whole face.
const STACKED_DRAWER_MAX_H = 6;

function round2(n: number): number {
  return Math.round(n * 100) / 100;
}

// Pull explicit door/drawer counts out of the cabinet's notes (the estimator
// writes e.g. "2 doors 1 drawer", "3 drawers").
function parseConfig(notes: string | null): { doors: number; drawers: number } {
  const text = notes ?? "";
  const d = text.match(/(\d+)\s*door/i);
  const dr = text.match(/(\d+)\s*drawer/i);
  return { doors: d ? Number(d[1]) : 0, drawers: dr ? Number(dr[1]) : 0 };
}

function faceLine(
  parent: CabinetLineItem,
  kind: "door" | "drawer_front",
  widthIn: number,
  heightIn: number,
  countPerCabinet: number
): CabinetLineItem {
  const label = kind === "door" ? "Door" : "Drawer Front";
  const base = (parent.notes ?? "").replace(ESTIMATED_NOTE_PREFIX, "").trim();
  return {
    source_page: parent.source_page,
    tag: `${label} — ${parent.tag ?? parent.category}`,
    room: parent.room,
    qty: countPerCabinet * parent.qty,
    category: kind,
    width_in: round2(widthIn),
    height_in: round2(heightIn),
    depth_in: 0.75,
    door_style: parent.door_style,
    material: parent.material,
    finish: parent.finish,
    assembled: parent.assembled,
    notes: `${ESTIMATED_NOTE_PREFIX} ${label.toLowerCase()} of ${parent.tag ?? parent.category}${base ? ` (${base})` : ""}`,
    confidence: parent.confidence,
    estimated: parent.estimated,
  };
}

// Expand one cabinet into its door + drawer-front faces. Returns [] for lines
// that are not cabinets (or lack dimensions) — so it's safe to map over all
// lines. The cabinet (box) line itself is kept by the caller; these are added.
export function expandToComponents(cab: CabinetLineItem): CabinetLineItem[] {
  if (!CABINET_CATEGORIES.includes(cab.category)) return [];
  const w = cab.width_in;
  const h = cab.height_in;
  if (w == null || h == null || w <= 0 || h <= 0) return [];

  let { doors, drawers } = parseConfig(cab.notes);
  const tag = (cab.tag ?? "").toLowerCase();
  const isWall = cab.category === "casework_wall";

  // Fall back to standard configs when the notes don't spell it out.
  if (doors === 0 && drawers === 0) {
    if (/sink/.test(tag)) doors = 2;
    else if (/drawer/.test(tag)) drawers = 3;
    else if (/fridge|refrigerator|surround|panel|filler|cubby|locker|open/.test(tag))
      return []; // surrounds / panels / open cubbies have no doors or fronts
    else doors = w >= 24 ? 2 : 1;
  }

  const faceH = isWall ? h : Math.max(1, h - TOE_KICK_IN);
  const faces: CabinetLineItem[] = [];

  let usedH = 0;
  if (drawers > 0) {
    const drawerH =
      doors > 0 ? Math.min(STACKED_DRAWER_MAX_H, faceH / (drawers + 2)) : faceH / drawers;
    usedH = drawerH * drawers;
    faces.push(faceLine(cab, "drawer_front", w, drawerH, drawers));
  }
  if (doors > 0) {
    const doorH = Math.max(1, faceH - usedH);
    faces.push(faceLine(cab, "door", w / doors, doorH, doors));
  }
  return faces;
}
