import { SEED_PRICING_SNAPSHOT, SEED_PRODUCT_LINES } from "@scribe/pricing";
import { DEFAULT_TEMPLATES } from "@scribe/export";
import { closeDb, getPool } from "./index.js";
import { migrate } from "./migrate.js";

// Idempotent first-run seed: starter product lines (rates marked NEEDS REVIEW),
// pricing config v1, default export templates, org settings, allowed users,
// and Wave-1 crawler sources (PRD §5.2 — jurisdiction list is config, not code).

const SEED_SOURCES = [
  {
    // Permit datasets are signals only — they carry no drawings, so they are
    // seeded paused. Re-enable from Admin if permit signals are wanted.
    name: "San Francisco permits (Socrata)",
    type: "socrata",
    status: "inactive",
    base_url: "https://data.sfgov.org",
    config: {
      dataset: "i98e-djp9",
      jurisdiction: "San Francisco, CA",
      field_map: {
        permit_number: "permit_number",
        description: "description",
        address: "street_number,street_name",
        valuation: "estimated_cost",
        issued_date: "issued_date",
      },
      cursor_field: "issued_date",
    },
  },
  {
    name: "Los Angeles permits (Socrata)",
    type: "socrata",
    status: "inactive",
    base_url: "https://data.lacity.org",
    config: {
      dataset: "nbyu-2ha9",
      jurisdiction: "Los Angeles, CA",
      field_map: {
        permit_number: "pcis_permit",
        description: "work_description",
        address: "primary_address",
        valuation: "valuation",
        issued_date: "issue_date",
      },
      cursor_field: "issue_date",
    },
  },
  {
    name: "NYC DOB permits (Socrata)",
    type: "socrata",
    status: "inactive",
    base_url: "https://data.cityofnewyork.us",
    config: {
      dataset: "ipu4-2q9a",
      jurisdiction: "New York, NY",
      field_map: {
        permit_number: "job__",
        description: "job_description",
        address: "house__,street_name",
        valuation: "initial_cost",
        issued_date: "issuance_date",
      },
      cursor_field: "issuance_date",
    },
  },
  {
    // Federal solicitations frequently attach full plan sets as public PDFs —
    // the active drawings-bearing source. Needs the free SAMGOV_API_KEY.
    name: "SAM.gov solicitations",
    type: "samgov",
    status: "active",
    base_url: "https://api.sam.gov",
    config: {
      // keywords tuned for casework-bearing solicitations
      keywords: [
        "cabinet",
        "casework",
        "millwork",
        "architectural woodwork",
        "kitchen renovation",
      ],
      jurisdiction: "Federal",
    },
  },
];

export async function seed(): Promise<void> {
  await migrate();
  const pool = getPool();

  for (const pl of SEED_PRODUCT_LINES) {
    await pool.query(
      `INSERT INTO product_lines
         (id, name, categories, size_measure, material_rates, finish_adders,
          assembly_adder, dim_bounds, lead_time_days, active)
       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
       ON CONFLICT (id) DO NOTHING`,
      [
        pl.id,
        pl.name,
        JSON.stringify(pl.categories),
        pl.size_measure,
        JSON.stringify(pl.material_rates),
        JSON.stringify(pl.finish_adders),
        pl.assembly_adder ? JSON.stringify(pl.assembly_adder) : null,
        JSON.stringify(pl.dim_bounds),
        pl.lead_time_days,
        pl.active,
      ]
    );
  }

  await pool.query(
    `INSERT INTO pricing_configs (version, snapshot)
     VALUES (1, $1)
     ON CONFLICT (version) DO NOTHING`,
    [JSON.stringify(SEED_PRICING_SNAPSHOT)]
  );

  for (const t of DEFAULT_TEMPLATES) {
    await pool.query(
      `INSERT INTO export_templates (name, target, delimiter, unit_format, columns)
       VALUES ($1,$2,$3,$4,$5)
       ON CONFLICT (name) DO NOTHING`,
      [t.name, t.target, t.delimiter, t.unit_format, JSON.stringify(t.columns)]
    );
  }

  await pool.query(
    `INSERT INTO org_settings (id, quote_terms_md, quote_footer_md, pallet_config)
     VALUES (1, $1, $2, $3)
     ON CONFLICT (id) DO NOTHING`,
    [
      [
        "- Customer must verify all measurements and quantities before ordering.",
        "- Pricing is valid for 10 days from the quote date.",
        "- Freight is estimated and confirmed at order time.",
      ].join("\n"),
      "CabinetNow.com — custom cabinet products, shipped nationwide.",
      JSON.stringify({
        pallet_width_in: 48,
        pallet_depth_in: 40,
        pallet_height_in: 72,
        max_weight_lb: 1500,
        assembled_volumetric_efficiency: 0.4,
        flat_volumetric_efficiency: 0.75,
      }),
    ]
  );

  for (const s of SEED_SOURCES) {
    await pool.query(
      `INSERT INTO sources (name, type, status, base_url, config)
       SELECT $1, $2, $3, $4, $5
       WHERE NOT EXISTS (SELECT 1 FROM sources WHERE name = $1)`,
      [s.name, s.type, s.status, s.base_url, JSON.stringify(s.config)]
    );
  }

  const allowed = (process.env.AUTH_ALLOWED_EMAILS ?? "")
    .split(",")
    .map((e) => e.trim())
    .filter(Boolean);
  for (const [i, email] of allowed.entries()) {
    await pool.query(
      `INSERT INTO users (email, role) VALUES ($1, $2)
       ON CONFLICT (email) DO NOTHING`,
      [email, i === 0 ? "admin" : "estimator"]
    );
  }
}

const isMain =
  process.argv[1] && import.meta.url === `file://${process.argv[1]}`;
if (isMain) {
  seed()
    .then(() => {
      console.log("seed complete");
      return closeDb();
    })
    .catch((err) => {
      console.error(err);
      process.exit(1);
    });
}
