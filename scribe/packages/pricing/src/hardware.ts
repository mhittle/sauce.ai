import type { FaceLike } from "./tiers.js";

// CabinetNow's third quote list — drawer boxes + hardware — rolled up into a
// SINGLE "Hardware" subtotal (not a line per piece).
//
// The dovetail drawer-box price is the validated `drawerBoxes()` formula from
// the live store's pricing.js: per box, perimeter = 2·W + 2·D, a tier line
// (slope·perimeter + intercept) is picked by the drawer-front HEIGHT, then
//   price = ((tier × materialMult) + handlingCharge) × markup.
// Glides, shelf pins, and toe-kick skin are product-option SKUs (not formulas
// in pricing.js), so they are not yet modelled — drawer boxes are the bulk of
// the list and the only part we can price deterministically today.

// Drawer-box tier lines (price = perimeter·slope + intercept), keyed by the
// max drawer-front height that selects them. Straight from pricing.js.
interface DrawerBoxTier {
  maxHeight: number;
  slope: number;
  intercept: number;
}
const DRAWER_BOX_TIERS: DrawerBoxTier[] = [
  { maxHeight: 4, slope: 0.51, intercept: 17.68 },
  { maxHeight: 6, slope: 0.59, intercept: 18.45 },
  { maxHeight: 8, slope: 0.66, intercept: 20.75 },
  { maxHeight: 10, slope: 0.74, intercept: 21.53 },
  { maxHeight: 12, slope: 0.81, intercept: 22.3 },
  { maxHeight: 14, slope: 0.9, intercept: 23.06 },
  { maxHeight: 17, slope: 0.9, intercept: 23.06 },
];

const DRAWER_BOX_HANDLING = 10.06; // flat handling charge per box (pricing.js)
const DRAWER_BOX_MARKUP = 1.5; // retail markup (pricing.js)

// Drawer-box material multiplier (pricing.js title-keyed switch). The default
// 9-ply/birch box is the standard; this stays constant across door tiers since
// the drawer-box species is not the rep's door-style choice.
export const DRAWER_BOX_MULT: Record<string, number> = {
  aspen: 1.0,
  birch: 1.02813,
  beech: 1.02813,
  nine_ply: 1.02813,
  melamine: 0.9135,
  red_oak: 1.15,
  maple: 1.2,
  cherry: 1.25,
  walnut: 2.0,
};
export const DEFAULT_DRAWER_BOX_MATERIAL = "birch";

// Drawer box runs shallower than the cabinet; a typical 24" base takes a ~21"
// box. Faces don't carry cabinet depth, so use this when none is supplied.
const DEFAULT_DRAWER_BOX_DEPTH_IN = 21;

export interface HardwareOptions {
  drawerBoxMaterial?: string;
  drawerBoxDepthIn?: number;
}

// Per-drawer-box price in integer cents. width/height are the DRAWER FRONT's
// width/height (height selects the tier); depth is the box runner length.
export function priceDrawerBoxCents(
  widthIn: number,
  heightIn: number,
  opts: HardwareOptions = {}
): number | null {
  if (widthIn <= 0 || heightIn <= 0) return null;
  const depth = opts.drawerBoxDepthIn ?? DEFAULT_DRAWER_BOX_DEPTH_IN;
  const tier =
    DRAWER_BOX_TIERS.find((t) => heightIn <= t.maxHeight) ??
    DRAWER_BOX_TIERS[DRAWER_BOX_TIERS.length - 1];
  const mult =
    DRAWER_BOX_MULT[opts.drawerBoxMaterial ?? DEFAULT_DRAWER_BOX_MATERIAL] ??
    DRAWER_BOX_MULT[DEFAULT_DRAWER_BOX_MATERIAL];

  const perimeter = widthIn * 2 + depth * 2;
  const base = perimeter * tier.slope + tier.intercept;
  const price = (base * mult + DRAWER_BOX_HANDLING) * DRAWER_BOX_MARKUP;
  return Math.round(price * 100);
}

export interface HardwareSummary {
  drawer_box_count: number;
  hardware_cents: number;
}

// Roll the whole third list into ONE hardware subtotal. Today that's a dovetail
// drawer box behind every drawer front (qty applied). Faces other than
// drawer_front are ignored.
export function priceHardware(
  lines: (FaceLike & { depth_in?: number | null })[],
  opts: HardwareOptions = {}
): HardwareSummary {
  let total = 0;
  let count = 0;
  for (const line of lines) {
    if (line.category !== "drawer_front") continue;
    if (line.width_in == null || line.height_in == null) continue;
    const cents = priceDrawerBoxCents(line.width_in, line.height_in, opts);
    if (cents == null) continue;
    total += cents * line.qty;
    count += line.qty;
  }
  return { drawer_box_count: count, hardware_cents: total };
}
