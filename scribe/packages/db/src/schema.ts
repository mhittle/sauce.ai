import {
  bigint,
  boolean,
  date,
  integer,
  jsonb,
  numeric,
  pgTable,
  primaryKey,
  text,
  timestamp,
  uuid,
} from "drizzle-orm/pg-core";

// Drizzle table definitions mirroring migrations/0001_init.sql. The SQL file
// is the source of truth for DDL; keep both in sync when migrating.

export const users = pgTable("users", {
  id: uuid("id").primaryKey().defaultRandom(),
  email: text("email").notNull().unique(),
  name: text("name"),
  role: text("role").notNull().default("estimator"),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
});

export const sources = pgTable("sources", {
  id: uuid("id").primaryKey().defaultRandom(),
  name: text("name").notNull(),
  type: text("type").notNull(),
  baseUrl: text("base_url").notNull(),
  config: jsonb("config").notNull().default({}),
  status: text("status").notNull().default("active"),
  lastCursor: text("last_cursor"),
  lastRunAt: timestamp("last_run_at", { withTimezone: true }),
  lastError: text("last_error"),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
});

export const projects = pgTable("projects", {
  id: uuid("id").primaryKey().defaultRandom(),
  canonicalAddress: text("canonical_address"),
  jurisdiction: text("jurisdiction"),
  permitNumber: text("permit_number"),
  parcel: text("parcel"),
  projectType: text("project_type"),
  valuationCents: bigint("valuation_cents", { mode: "number" }),
  estCabinetScopeUsd: numeric("est_cabinet_scope_usd", { mode: "number" }),
  description: text("description"),
  gcName: text("gc_name"),
  gcContact: jsonb("gc_contact"),
  status: text("status").notNull().default("new"),
  assignedTo: uuid("assigned_to"),
  cabinetRelevanceScore: numeric("cabinet_relevance_score", { mode: "number" }),
  scoreRationale: text("score_rationale"),
  sourceRefs: jsonb("source_refs").notNull().default([]),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
});

export const projectDocuments = pgTable("project_documents", {
  id: uuid("id").primaryKey().defaultRandom(),
  projectId: uuid("project_id").notNull(),
  s3Key: text("s3_key").notNull(),
  docClass: text("doc_class").notNull().default("other"),
  pageCount: integer("page_count"),
  sha256: text("sha256"),
  fetchedFromUrl: text("fetched_from_url").notNull(),
  fetchedAt: timestamp("fetched_at", { withTimezone: true }).notNull().defaultNow(),
});

export const productLines = pgTable("product_lines", {
  id: text("id").primaryKey(),
  name: text("name").notNull(),
  categories: jsonb("categories").notNull().default([]),
  sizeMeasure: text("size_measure").notNull(),
  materialRates: jsonb("material_rates").notNull().default({}),
  finishAdders: jsonb("finish_adders").notNull().default({}),
  assemblyAdder: jsonb("assembly_adder"),
  dimBounds: jsonb("dim_bounds").notNull().default({}),
  leadTimeDays: integer("lead_time_days").notNull().default(7),
  active: boolean("active").notNull().default(true),
  updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
});

export const pricingConfigs = pgTable("pricing_configs", {
  id: uuid("id").primaryKey().defaultRandom(),
  version: integer("version").notNull().unique(),
  snapshot: jsonb("snapshot").notNull(),
  createdBy: uuid("created_by"),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
});

export const takeoffs = pgTable("takeoffs", {
  id: uuid("id").primaryKey().defaultRandom(),
  projectId: uuid("project_id"),
  uploadedBy: uuid("uploaded_by"),
  sourceFileS3Key: text("source_file_s3_key").notNull(),
  sourceFilename: text("source_filename"),
  sourceKind: text("source_kind").notNull(),
  status: text("status").notNull().default("processing"),
  pageCount: integer("page_count"),
  classifiedPages: jsonb("classified_pages"),
  docConfidence: numeric("doc_confidence", { mode: "number" }),
  docSummary: jsonb("doc_summary"),
  promptVersion: text("prompt_version"),
  tokensUsed: bigint("tokens_used", { mode: "number" }).notNull().default(0),
  error: text("error"),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
});

export const takeoffLines = pgTable("takeoff_lines", {
  id: uuid("id").primaryKey().defaultRandom(),
  takeoffId: uuid("takeoff_id").notNull(),
  sourcePage: integer("source_page"),
  tag: text("tag"),
  room: text("room"),
  qty: numeric("qty", { mode: "number" }).notNull(),
  category: text("category").notNull(),
  widthIn: numeric("width_in", { mode: "number" }),
  heightIn: numeric("height_in", { mode: "number" }),
  depthIn: numeric("depth_in", { mode: "number" }),
  doorStyle: text("door_style"),
  material: text("material"),
  finish: text("finish"),
  assembled: boolean("assembled"),
  notes: text("notes"),
  confidence: numeric("confidence", { mode: "number" }).notNull(),
  productLineId: text("product_line_id"),
  resolvedParams: jsonb("resolved_params"),
  matchConfidence: numeric("match_confidence", { mode: "number" }),
  alternates: jsonb("alternates"),
  unmatchedReason: text("unmatched_reason"),
  reviewerEdited: boolean("reviewer_edited").notNull().default(false),
  rawModelOutput: jsonb("raw_model_output"),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
});

export const evalFixtures = pgTable("eval_fixtures", {
  id: uuid("id").primaryKey().defaultRandom(),
  takeoffId: uuid("takeoff_id").notNull(),
  extractedLines: jsonb("extracted_lines").notNull(),
  approvedLines: jsonb("approved_lines"),
  promptVersion: text("prompt_version"),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
});

export const customers = pgTable("customers", {
  id: uuid("id").primaryKey().defaultRandom(),
  company: text("company").notNull(),
  contact: jsonb("contact"),
  bigcommerceCustomerId: text("bigcommerce_customer_id"),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
});

export const quotes = pgTable("quotes", {
  id: uuid("id").primaryKey().defaultRandom(),
  takeoffId: uuid("takeoff_id").notNull(),
  customerId: uuid("customer_id"),
  status: text("status").notNull().default("draft"),
  pricingConfigId: uuid("pricing_config_id").notNull(),
  subtotalCents: bigint("subtotal_cents", { mode: "number" }).notNull().default(0),
  markupPct: numeric("markup_pct", { mode: "number" }).notNull().default(0),
  handlingCents: bigint("handling_cents", { mode: "number" }).notNull().default(0),
  freightCents: bigint("freight_cents", { mode: "number" }).notNull().default(0),
  freightPallets: integer("freight_pallets").notNull().default(0),
  freightVerified: boolean("freight_verified").notNull().default(false),
  actualFreightCents: bigint("actual_freight_cents", { mode: "number" }),
  totalCents: bigint("total_cents", { mode: "number" }).notNull().default(0),
  validUntil: date("valid_until"),
  maxLeadTimeDays: integer("max_lead_time_days"),
  linePrices: jsonb("line_prices"),
  pdfS3Key: text("pdf_s3_key"),
  bigcommerceDraftOrderId: text("bigcommerce_draft_order_id"),
  sentAt: timestamp("sent_at", { withTimezone: true }),
  createdBy: uuid("created_by"),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
});

export const orgSettings = pgTable("org_settings", {
  id: integer("id").primaryKey().default(1),
  logoS3Key: text("logo_s3_key"),
  quoteTermsMd: text("quote_terms_md").notNull().default(""),
  quoteFooterMd: text("quote_footer_md").notNull().default(""),
  defaultHandlingCents: bigint("default_handling_cents", { mode: "number" }).notNull().default(0),
  palletRateCents: bigint("pallet_rate_cents", { mode: "number" }).notNull().default(70000),
  palletConfig: jsonb("pallet_config").notNull().default({}),
  freightProvider: text("freight_provider").notNull().default("flat_pallet"),
  crossValidationEnabled: boolean("cross_validation_enabled").notNull().default(false),
  updatedBy: uuid("updated_by"),
  updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
});

export const exportTemplates = pgTable("export_templates", {
  id: uuid("id").primaryKey().defaultRandom(),
  name: text("name").notNull().unique(),
  target: text("target").notNull(),
  delimiter: text("delimiter").notNull().default(","),
  unitFormat: text("unit_format").notNull().default("decimal_in"),
  columns: jsonb("columns").notNull().default([]),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
});

export const tokenSpend = pgTable(
  "token_spend",
  {
    day: date("day").notNull(),
    bucket: text("bucket").notNull(),
    tokens: bigint("tokens", { mode: "number" }).notNull().default(0),
  },
  (t) => [primaryKey({ columns: [t.day, t.bucket] })]
);
