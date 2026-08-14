import { isNonBoxCasework } from "@scribe/shared";
import { carcassSqft, isCabinetBox } from "./boxes.js";

// Material requirements roll-up for a takeoff's line set (PRD-adjacent shop
// stats, not a cut list): carcass panel area from the box family formulas,
// door/front face area, and a sheet-goods estimate at 4×8 with a flat waste
// factor. Faces must already be expanded to lines (they are by review time).

export const SHEET_AREA_SQFT = 32; // 4×8 sheet
export const MATERIAL_WASTE_PCT = 15;

export interface MaterialLine {
  category: string;
  tag: string | null;
  notes?: string | null;
  qty: number;
  width_in: number | null;
  height_in: number | null;
  depth_in?: number | null;
}

export interface MaterialStats {
  box_count: number;
  carcass_sqft: number;
  carcass_sheets: number;
  door_count: number;
  door_sqft: number;
  drawer_front_count: number;
  front_sqft: number;
  face_sheets: number;
  skipped_no_dims: number;
  waste_pct: number;
  sheet_area_sqft: number;
}

const round1 = (n: number) => Math.round(n * 10) / 10;

function sheets(areaSqft: number): number {
  if (areaSqft <= 0) return 0;
  return Math.ceil((areaSqft * (1 + MATERIAL_WASTE_PCT / 100)) / SHEET_AREA_SQFT);
}

function faceSqft(line: MaterialLine): number {
  if (line.width_in == null || line.height_in == null) return 0;
  return ((line.width_in * line.height_in) / 144) * line.qty;
}

export function materialStats(lines: MaterialLine[]): MaterialStats {
  let boxCount = 0;
  let carcass = 0;
  let skipped = 0;
  let doorCount = 0;
  let doorSqft = 0;
  let frontCount = 0;
  let frontSqft = 0;

  for (const line of lines) {
    if (isCabinetBox(line.category)) {
      if (isNonBoxCasework(line)) continue; // fillers/trim aren't carcasses
      const sqft = carcassSqft(line);
      if (sqft == null) {
        skipped += line.qty;
        continue;
      }
      boxCount += line.qty;
      carcass += sqft * line.qty;
    } else if (line.category === "door") {
      doorCount += line.qty;
      doorSqft += faceSqft(line);
    } else if (line.category === "drawer_front") {
      frontCount += line.qty;
      frontSqft += faceSqft(line);
    }
  }

  return {
    box_count: boxCount,
    carcass_sqft: round1(carcass),
    carcass_sheets: sheets(carcass),
    door_count: doorCount,
    door_sqft: round1(doorSqft),
    drawer_front_count: frontCount,
    front_sqft: round1(frontSqft),
    face_sheets: sheets(doorSqft + frontSqft),
    skipped_no_dims: skipped,
    waste_pct: MATERIAL_WASTE_PCT,
    sheet_area_sqft: SHEET_AREA_SQFT,
  };
}
