import { z } from "zod";

// ---------------------------------------------------------------------------
// Takeoff line items (PRD §6.3)
// ---------------------------------------------------------------------------

export const LineCategory = z.enum([
  "casework_base",
  "casework_wall",
  "casework_tall",
  "vanity",
  "closet",
  "door",
  "drawer_front",
  "drawer_box",
  "panel",
  "filler",
  "trim",
  "hardware",
  "countertop",
  "unknown",
]);
export type LineCategory = z.infer<typeof LineCategory>;

export const CabinetLineItem = z.object({
  source_page: z.number().int().nullable(),
  tag: z.string().nullable(),
  room: z.string().nullable(),
  qty: z.number().positive(),
  category: LineCategory,
  width_in: z.number().positive().nullable(),
  height_in: z.number().positive().nullable(),
  depth_in: z.number().positive().nullable(),
  door_style: z.string().nullable(),
  material: z.string().nullable(),
  finish: z.string().nullable(),
  assembled: z.boolean().nullable(),
  notes: z.string().nullable(),
  confidence: z.number().min(0).max(1),
  // True when this line was estimated from a floor plan / interior elevation
  // rather than read off a cabinet schedule (PRD §4 — no-schedule sets).
  // Estimated lines are forced to low confidence and noted so they surface for
  // review and never pass as schedule-grade quantities. Defaults false.
  estimated: z.boolean().default(false),
  // [x0,y0,x1,y1] in pixels of the exact image the model read — the visual
  // anchor for the box-review gate. Advisory-quality (self-reported boxes are
  // loose); the reviewer corrects them. Lenient: a missing or malformed box
  // becomes null rather than dropping the whole line.
  bbox_2d: z
    .tuple([z.number(), z.number(), z.number(), z.number()])
    .nullable()
    .catch(null)
    .default(null),
});
export type CabinetLineItem = z.infer<typeof CabinetLineItem>;

export const LOW_CONFIDENCE_THRESHOLD = 0.8;

// What the extraction model returns for one page (lines + page-level notes).
export const PageExtraction = z.object({
  lines: z.array(CabinetLineItem),
  unit_multipliers: z
    .array(
      z.object({
        unit_type: z.string(),
        count: z.number().int().positive().nullable(),
        ambiguous: z.boolean(),
      })
    )
    .default([]),
  uncertainties: z.array(z.string()).default([]),
  unreadable: z.boolean().default(false),
});
export type PageExtraction = z.infer<typeof PageExtraction>;

// ---------------------------------------------------------------------------
// Page classification (PRD §6.2)
// ---------------------------------------------------------------------------

export const PageClass = z.enum([
  "cover_index",
  "floor_plan",
  "kitchen_or_millwork_elevation",
  "cabinet_schedule_table",
  "finish_schedule",
  "spec_text",
  "other",
]);
export type PageClass = z.infer<typeof PageClass>;

export const RELEVANT_PAGE_CLASSES: PageClass[] = [
  "cabinet_schedule_table",
  "kitchen_or_millwork_elevation",
  "finish_schedule",
];

export const PageClassification = z.object({
  page: z.number().int(),
  class: PageClass,
  confidence: z.number().min(0).max(1),
});
export type PageClassification = z.infer<typeof PageClassification>;

// One user-picked page from the page-selection gate. `class` is set only when
// the user overrode (or confirmed) the classifier's suggested type; absent
// means "use the classifier's call".
export const SelectedPage = z.object({
  page: z.number().int().positive(),
  class: PageClass.optional(),
});
export type SelectedPage = z.infer<typeof SelectedPage>;

// ---------------------------------------------------------------------------
// Pricing (PRD §6.4)
// ---------------------------------------------------------------------------

export const SizeMeasure = z.enum(["lf", "sqft", "unit"]);
export type SizeMeasure = z.infer<typeof SizeMeasure>;

export const Adder = z.discriminatedUnion("kind", [
  z.object({ kind: z.literal("flat"), cents: z.number().int() }),
  z.object({ kind: z.literal("pct"), pct: z.number() }),
]);
export type Adder = z.infer<typeof Adder>;

export const MaterialRate = z.object({
  // $ per LF / sqft / unit, in cents
  rate_cents: z.number().int().nonnegative(),
  // Seeded placeholder rates ship as true; quote send is blocked while any
  // priced line uses a NEEDS REVIEW rate (PRD §12).
  needs_review: z.boolean().default(false),
});
export type MaterialRate = z.infer<typeof MaterialRate>;

export const DimBound = z.object({
  min_in: z.number().positive(),
  max_in: z.number().positive(),
  increment_in: z.number().positive().nullable().default(null),
});

export const DimBounds = z.object({
  width: DimBound.nullable().default(null),
  height: DimBound.nullable().default(null),
  depth: DimBound.nullable().default(null),
});
export type DimBounds = z.infer<typeof DimBounds>;

export const ProductLineConfig = z.object({
  id: z.string(),
  name: z.string(),
  categories: z.array(LineCategory),
  size_measure: SizeMeasure,
  material_rates: z.record(MaterialRate),
  finish_adders: z.record(Adder),
  assembly_adder: Adder.nullable(),
  dim_bounds: DimBounds,
  lead_time_days: z.number().int().nonnegative(),
  active: z.boolean(),
});
export type ProductLineConfig = z.infer<typeof ProductLineConfig>;

export const PricingSnapshot = z.object({
  version: z.number().int(),
  product_lines: z.array(ProductLineConfig),
});
export type PricingSnapshot = z.infer<typeof PricingSnapshot>;

export const ResolvedParams = z.object({
  product_line_id: z.string(),
  qty: z.number().positive(),
  width_in: z.number().positive().nullable(),
  height_in: z.number().positive().nullable(),
  depth_in: z.number().positive().nullable(),
  material: z.string(),
  finish: z.string().nullable(),
  assembled: z.boolean(),
});
export type ResolvedParams = z.infer<typeof ResolvedParams>;

// ---------------------------------------------------------------------------
// Freight (PRD §6.5)
// ---------------------------------------------------------------------------

export const PalletConfig = z.object({
  pallet_width_in: z.number().positive().default(48),
  pallet_depth_in: z.number().positive().default(40),
  pallet_height_in: z.number().positive().default(72),
  max_weight_lb: z.number().positive().default(1500),
  assembled_volumetric_efficiency: z.number().positive().max(1).default(0.4),
  flat_volumetric_efficiency: z.number().positive().max(1).default(0.75),
});
export type PalletConfig = z.infer<typeof PalletConfig>;

export const ShipmentLine = z.object({
  qty: z.number().positive(),
  width_in: z.number().positive().nullable(),
  height_in: z.number().positive().nullable(),
  depth_in: z.number().positive().nullable(),
  assembled: z.boolean(),
  category: LineCategory,
});
export type ShipmentLine = z.infer<typeof ShipmentLine>;

export const ShipmentSpec = z.object({
  lines: z.array(ShipmentLine),
  destination_zip: z.string().nullable().default(null),
});
export type ShipmentSpec = z.infer<typeof ShipmentSpec>;

export const FreightQuote = z.object({
  provider: z.string(),
  pallets: z.number().int().nonnegative(),
  total_cents: z.number().int().nonnegative(),
  detail: z.string(),
});
export type FreightQuote = z.infer<typeof FreightQuote>;

// ---------------------------------------------------------------------------
// Prospector (PRD §5)
// ---------------------------------------------------------------------------

export const ProjectStatus = z.enum([
  "new",
  "triaged",
  "quoting",
  "quoted",
  "won",
  "lost",
  "ignored",
]);
export type ProjectStatus = z.infer<typeof ProjectStatus>;

export const RawRecord = z.object({
  source_id: z.string(),
  external_id: z.string(),
  fetched_from_url: z.string(),
  fetched_at: z.string(),
  payload: z.record(z.unknown()),
});
export type RawRecord = z.infer<typeof RawRecord>;

export const NormalizedProject = z.object({
  canonical_address: z.string().nullable(),
  jurisdiction: z.string(),
  permit_number: z.string().nullable(),
  parcel: z.string().nullable(),
  project_type: z.string().nullable(),
  valuation_cents: z.number().int().nullable(),
  description: z.string().nullable(),
  gc_name: z.string().nullable(),
  gc_contact: z.record(z.string()).nullable(),
  document_urls: z.array(z.string()).default([]),
  source_ref: z.object({
    source_id: z.string(),
    external_id: z.string(),
    url: z.string(),
    fetched_at: z.string(),
  }),
});
export type NormalizedProject = z.infer<typeof NormalizedProject>;

export const RelevanceScore = z.object({
  cabinet_relevance_score: z.number().min(0).max(100),
  est_cabinet_scope_usd: z.number().nonnegative(),
  rationale: z.string(),
});
export type RelevanceScore = z.infer<typeof RelevanceScore>;

// ---------------------------------------------------------------------------
// Export templates (PRD §7.3)
// ---------------------------------------------------------------------------

export const ExportTarget = z.enum(["mozaik", "kcd", "generic"]);
export type ExportTarget = z.infer<typeof ExportTarget>;

export const UnitFormat = z.enum(["decimal_in", "mm"]);
export type UnitFormat = z.infer<typeof UnitFormat>;

export const ExportColumn = z.object({
  header: z.string(),
  // Field on the takeoff line, or "literal:<value>" for a constant column.
  field: z.string(),
});
export type ExportColumn = z.infer<typeof ExportColumn>;

export const ExportTemplate = z.object({
  name: z.string(),
  target: ExportTarget,
  delimiter: z.string().default(","),
  unit_format: UnitFormat.default("decimal_in"),
  columns: z.array(ExportColumn),
});
export type ExportTemplate = z.infer<typeof ExportTemplate>;

// ---------------------------------------------------------------------------
// Quotes
// ---------------------------------------------------------------------------

export const QuoteStatus = z.enum(["draft", "sent", "won", "lost", "expired"]);
export type QuoteStatus = z.infer<typeof QuoteStatus>;

export const QUOTE_VALIDITY_DAYS = 10;

// Two-gate flow (2026-08): processing → awaiting_pages → processing →
// awaiting_boxes → review → approved. `extracted` is dead (old rows may still
// carry it — don't repurpose); spreadsheets skip both gates (no pages/boxes to
// review) and go straight to review.
export const TakeoffStatus = z.enum([
  "processing",
  "awaiting_pages",
  "awaiting_boxes",
  "extracted",
  "review",
  "approved",
  "failed",
]);
export type TakeoffStatus = z.infer<typeof TakeoffStatus>;

// Legal status transitions. Workers own the transitions OUT of processing;
// the API owns the human-gate transitions back INTO processing and the final
// approve. `extracted` is a dead legacy status that can still be approved.
export const TAKEOFF_STATUS_TRANSITIONS: Record<TakeoffStatus, TakeoffStatus[]> =
  {
    processing: ["awaiting_pages", "awaiting_boxes", "review", "failed"],
    awaiting_pages: ["processing", "failed"],
    awaiting_boxes: ["processing", "failed"],
    extracted: ["approved"],
    review: ["approved"],
    approved: [],
    failed: [],
  };

export function canTransitionTakeoff(
  from: TakeoffStatus,
  to: TakeoffStatus
): boolean {
  return TAKEOFF_STATUS_TRANSITIONS[from]?.includes(to) ?? false;
}

export const SourceKind = z.enum(["pdf", "xlsx", "csv", "image"]);
export type SourceKind = z.infer<typeof SourceKind>;

export const UserRole = z.enum(["estimator", "sales", "admin"]);
export type UserRole = z.infer<typeof UserRole>;
