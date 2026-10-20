import {
  Adder,
  ProductLineConfig,
  ResolvedParams,
  roundCents,
} from "@scribe/shared";

// Pure parametric pricing engine (PRD §6.4). No IO. All variables come from a
// versioned pricing snapshot; quotes pin the snapshot version so the same
// lines + same pricing_config_id always produce the same total.
//
//   line_price = qty × [ base_rate × size_measure
//                        + finish_adder
//                        + assembly_adder (if assembled) ]
//   quote_total = subtotal × (1 + markup_pct) + handling + freight

export interface LinePriceResult {
  ok: true;
  unit_cents: number;
  total_cents: number;
  needs_review: boolean;
  lead_time_days: number;
  size_value: number;
}

export interface LinePriceError {
  ok: false;
  reason:
    | "inactive_product_line"
    | "unknown_material"
    | "unknown_finish"
    | "missing_dimension"
    | "size_limit";
  detail: string;
}

export type LinePriceOutcome = LinePriceResult | LinePriceError;

export function sizeMeasureValue(
  line: ProductLineConfig,
  params: ResolvedParams
): number | null {
  switch (line.size_measure) {
    case "lf":
      return params.width_in == null ? null : params.width_in / 12;
    case "sqft":
      return params.width_in == null || params.height_in == null
        ? null
        : (params.width_in * params.height_in) / 144;
    case "unit":
      return 1;
  }
}

function applyAdder(adder: Adder, baseCents: number): number {
  return adder.kind === "flat" ? adder.cents : (adder.pct / 100) * baseCents;
}

// The admin's size limits for this product (Admin › Pricing). A dimension
// that wasn't measured is not judged; an unset end is open.
export function checkSizeLimits(
  line: ProductLineConfig,
  params: ResolvedParams
): string | null {
  const limits = line.size_limits;
  if (!limits) return null;
  const dims = [
    ["width", params.width_in, limits.width],
    ["height", params.height_in, limits.height],
    ["depth", params.depth_in, limits.depth],
  ] as const;
  for (const [name, value, limit] of dims) {
    if (value == null || limit == null) continue;
    if (limit.max_in != null && value > limit.max_in) {
      return `${name} ${value}" is over the ${limit.max_in}" max set for ${line.name}`;
    }
    if (limit.min_in != null && value < limit.min_in) {
      return `${name} ${value}" is under the ${limit.min_in}" min set for ${line.name}`;
    }
  }
  return null;
}

export function priceLine(
  line: ProductLineConfig,
  params: ResolvedParams
): LinePriceOutcome {
  if (!line.active) {
    return {
      ok: false,
      reason: "inactive_product_line",
      detail: `product line ${line.name} is inactive`,
    };
  }

  // Only the limits an admin set (size_limits); the old seed `dim_bounds`
  // are not enforced (owner, 2026-10-20).
  const overLimit = checkSizeLimits(line, params);
  if (overLimit) return { ok: false, reason: "size_limit", detail: overLimit };

  // No material read → the product's first material, the same default the
  // matcher uses (a hand-picked line can carry an empty material).
  const material = params.material || Object.keys(line.material_rates)[0] || "";
  const materialRate = line.material_rates[material];
  if (!materialRate) {
    return {
      ok: false,
      reason: "unknown_material",
      detail: `material "${params.material}" not configured on ${line.name}`,
    };
  }

  const sizeValue = sizeMeasureValue(line, params);
  if (sizeValue == null) {
    return {
      ok: false,
      reason: "missing_dimension",
      detail: `size measure ${line.size_measure} needs dimensions that are missing`,
    };
  }

  const baseCents = materialRate.rate_cents * sizeValue;
  let unitCents = baseCents;

  if (params.finish != null && params.finish !== "") {
    const finishAdder = line.finish_adders[params.finish];
    if (!finishAdder) {
      return {
        ok: false,
        reason: "unknown_finish",
        detail: `finish "${params.finish}" not configured on ${line.name}`,
      };
    }
    unitCents += applyAdder(finishAdder, baseCents);
  }

  if (params.assembled && line.assembly_adder) {
    unitCents += applyAdder(line.assembly_adder, baseCents);
  }

  const unit = roundCents(unitCents);
  return {
    ok: true,
    unit_cents: unit,
    total_cents: roundCents(unit * params.qty),
    needs_review: materialRate.needs_review,
    lead_time_days: line.lead_time_days,
    size_value: sizeValue,
  };
}

export interface QuoteTotals {
  subtotal_cents: number;
  markup_cents: number;
  handling_cents: number;
  freight_cents: number;
  total_cents: number;
  max_lead_time_days: number;
  mixed_lead_times: boolean;
  any_needs_review: boolean;
}

export function priceQuote(
  linePrices: LinePriceResult[],
  opts: { markup_pct: number; handling_cents: number; freight_cents: number }
): QuoteTotals {
  const subtotal = linePrices.reduce((s, l) => s + l.total_cents, 0);
  const markup = roundCents(subtotal * (opts.markup_pct / 100));
  const leadTimes = new Set(linePrices.map((l) => l.lead_time_days));
  return {
    subtotal_cents: subtotal,
    markup_cents: markup,
    handling_cents: opts.handling_cents,
    freight_cents: opts.freight_cents,
    total_cents: subtotal + markup + opts.handling_cents + opts.freight_cents,
    max_lead_time_days: Math.max(0, ...leadTimes),
    mixed_lead_times: leadTimes.size > 1,
    any_needs_review: linePrices.some((l) => l.needs_review),
  };
}
