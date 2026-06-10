import {
  LinePriceResult,
  priceLine,
  priceQuote,
  QuoteTotals,
} from "@scribe/pricing";
import {
  createProvider,
  freightVerificationRequired,
  ProviderName,
} from "@scribe/freight";
import {
  PricingSnapshot,
  ResolvedParams,
  ShipmentSpec,
} from "@scribe/shared";
import type { OrgSettingsRow } from "./settings.js";

// Prices an approved takeoff's matched lines against a pinned pricing
// snapshot and estimates freight. Shared by quote create and re-price.

export interface DbLine {
  id: string;
  tag: string | null;
  room: string | null;
  qty: number;
  category: string;
  widthIn: number | null;
  heightIn: number | null;
  depthIn: number | null;
  material: string | null;
  finish: string | null;
  assembled: boolean | null;
  productLineId: string | null;
  resolvedParams: unknown;
}

export interface PricedLine {
  takeoff_line_id: string;
  product_line_id: string;
  unit_cents: number;
  total_cents: number;
  lead_time_days: number;
  needs_review: boolean;
}

export interface PricingRun {
  priced: PricedLine[];
  unpriced: { takeoff_line_id: string; reason: string }[];
  totals: QuoteTotals;
  freight_pallets: number;
  freight_verification_required: boolean;
}

export async function runPricing(
  lines: DbLine[],
  snapshot: PricingSnapshot,
  settings: OrgSettingsRow,
  opts: { markup_pct: number; handling_cents: number; freight_override_cents?: number }
): Promise<PricingRun> {
  const priced: PricedLine[] = [];
  const unpriced: PricingRun["unpriced"] = [];
  const lineResults: LinePriceResult[] = [];

  for (const line of lines) {
    if (!line.productLineId || !line.resolvedParams) {
      unpriced.push({
        takeoff_line_id: line.id,
        reason: "unmatched — resolve in the review screen",
      });
      continue;
    }
    const pl = snapshot.product_lines.find((p) => p.id === line.productLineId);
    if (!pl) {
      unpriced.push({
        takeoff_line_id: line.id,
        reason: `product line ${line.productLineId} missing from pricing config`,
      });
      continue;
    }
    const params = ResolvedParams.parse(line.resolvedParams);
    const result = priceLine(pl, params);
    if (!result.ok) {
      unpriced.push({ takeoff_line_id: line.id, reason: result.detail });
      continue;
    }
    lineResults.push(result);
    priced.push({
      takeoff_line_id: line.id,
      product_line_id: pl.id,
      unit_cents: result.unit_cents,
      total_cents: result.total_cents,
      lead_time_days: result.lead_time_days,
      needs_review: result.needs_review,
    });
  }

  const shipment: ShipmentSpec = {
    destination_zip: null,
    lines: lines
      .filter((l) => l.productLineId)
      .map((l) => ({
        qty: l.qty,
        width_in: l.widthIn,
        height_in: l.heightIn,
        depth_in: l.depthIn,
        assembled: l.assembled ?? false,
        category: l.category as ShipmentSpec["lines"][number]["category"],
      })),
  };

  const provider = createProvider(settings.freightProvider as ProviderName, {
    pallet_rate_cents: settings.palletRateCents,
    pallet_config: settings.palletConfig,
  });
  const freightQuote = await provider.quote(shipment);
  const freightCents = opts.freight_override_cents ?? freightQuote.total_cents;

  const totals = priceQuote(lineResults, {
    markup_pct: opts.markup_pct,
    handling_cents: opts.handling_cents,
    freight_cents: freightCents,
  });

  return {
    priced,
    unpriced,
    totals,
    freight_pallets: freightQuote.pallets,
    freight_verification_required: freightVerificationRequired(
      totals.subtotal_cents,
      shipment
    ),
  };
}
