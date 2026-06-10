import {
  FreightQuote,
  PalletConfig,
  ShipmentLine,
  ShipmentSpec,
} from "@scribe/shared";

// Pure freight estimator behind a FreightProvider interface (PRD §6.5).
// v1 ships FlatPalletProvider ($/pallet flat, admin-editable). Uber Freight
// integration arrives in v1.1 behind the same interface; provider selection
// is config.

export interface FreightProvider {
  readonly name: string;
  quote(shipment: ShipmentSpec): Promise<FreightQuote>;
}

// Fallback per-item volume when dims are missing, by rough product size.
const FALLBACK_DIMS = { width_in: 24, height_in: 30, depth_in: 24 };

export function lineVolumeIn3(line: ShipmentLine): number {
  const w = line.width_in ?? FALLBACK_DIMS.width_in;
  const h = line.height_in ?? FALLBACK_DIMS.height_in;
  // Flat product effectively ships at panel thickness; the volumetric
  // efficiency factor handles air, so use real depth where known.
  const d = line.depth_in ?? (line.assembled ? FALLBACK_DIMS.depth_in : 1);
  return w * h * d * line.qty;
}

export function estimatePallets(
  shipment: ShipmentSpec,
  config: PalletConfig
): number {
  if (shipment.lines.length === 0) return 0;
  const palletVolume =
    config.pallet_width_in * config.pallet_depth_in * config.pallet_height_in;

  let adjustedVolume = 0;
  for (const line of shipment.lines) {
    const efficiency = line.assembled
      ? config.assembled_volumetric_efficiency
      : config.flat_volumetric_efficiency;
    adjustedVolume += lineVolumeIn3(line) / efficiency;
  }

  // Round pallets up; any non-empty shipment needs at least one.
  return Math.max(1, Math.ceil(adjustedVolume / palletVolume));
}

export interface FlatPalletOptions {
  pallet_rate_cents: number;
  pallet_config: PalletConfig;
}

export class FlatPalletProvider implements FreightProvider {
  readonly name = "flat_pallet";
  constructor(private readonly opts: FlatPalletOptions) {}

  async quote(shipment: ShipmentSpec): Promise<FreightQuote> {
    const pallets = estimatePallets(shipment, this.opts.pallet_config);
    return {
      provider: this.name,
      pallets,
      total_cents: pallets * this.opts.pallet_rate_cents,
      detail: `${pallets} pallet(s) × $${(
        this.opts.pallet_rate_cents / 100
      ).toFixed(2)}/pallet (flat rate; verify before sending)`,
    };
  }
}

// Stub only — wire the real Uber Freight API in v1.1 (PRD §14).
export class UberFreightProvider implements FreightProvider {
  readonly name = "uber_freight";

  async quote(_shipment: ShipmentSpec): Promise<FreightQuote> {
    throw new Error(
      "UberFreightProvider is a v1.1 stub — select the flat_pallet provider"
    );
  }
}

export type ProviderName = "flat_pallet" | "uber_freight";

export function createProvider(
  name: ProviderName,
  flatOptions: FlatPalletOptions
): FreightProvider {
  switch (name) {
    case "flat_pallet":
      return new FlatPalletProvider(flatOptions);
    case "uber_freight":
      return new UberFreightProvider();
  }
}

// Quotes ≥ $35k or containing assembled casework require the estimator to
// verify freight before send (PRD §6.5 — this gate is non-negotiable).
export const FREIGHT_VERIFY_THRESHOLD_CENTS = 35_000_00;

export function freightVerificationRequired(
  subtotalCents: number,
  shipment: ShipmentSpec
): boolean {
  if (subtotalCents >= FREIGHT_VERIFY_THRESHOLD_CENTS) return true;
  return shipment.lines.some(
    (l) =>
      l.assembled &&
      ["casework_base", "casework_wall", "casework_tall", "vanity"].includes(
        l.category
      )
  );
}
