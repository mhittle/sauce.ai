import { describe, expect, it } from "vitest";
import { PalletConfig, ShipmentSpec } from "@scribe/shared";
import {
  estimatePallets,
  FlatPalletProvider,
  freightVerificationRequired,
  UberFreightProvider,
} from "../src/index.js";

const config: PalletConfig = {
  pallet_width_in: 48,
  pallet_depth_in: 40,
  pallet_height_in: 72,
  max_weight_lb: 1500,
  assembled_volumetric_efficiency: 0.4,
  flat_volumetric_efficiency: 0.75,
};

function shipment(lines: ShipmentSpec["lines"]): ShipmentSpec {
  return { lines, destination_zip: null };
}

describe("estimatePallets", () => {
  it("returns 0 for an empty shipment", () => {
    expect(estimatePallets(shipment([]), config)).toBe(0);
  });

  it("rounds up and never returns less than 1 for non-empty shipments", () => {
    const s = shipment([
      {
        qty: 1,
        width_in: 12,
        height_in: 12,
        depth_in: 1,
        assembled: false,
        category: "panel",
      },
    ]);
    expect(estimatePallets(s, config)).toBe(1);
  });

  it("packs assembled casework less densely than flat product", () => {
    const line = {
      qty: 20,
      width_in: 30,
      height_in: 34.5,
      depth_in: 24,
      category: "casework_base" as const,
    };
    const flat = estimatePallets(
      shipment([{ ...line, assembled: false }]),
      config
    );
    const assembled = estimatePallets(
      shipment([{ ...line, assembled: true }]),
      config
    );
    expect(assembled).toBeGreaterThan(flat);
  });

  it("matches a hand-computed case", () => {
    // 10 assembled B30: 30×34.5×24 = 24,840 in³ each, ×10 / 0.4 eff = 621,000.
    // Pallet = 48×40×72 = 138,240 → ceil(621000/138240) = 5 pallets.
    const s = shipment([
      {
        qty: 10,
        width_in: 30,
        height_in: 34.5,
        depth_in: 24,
        assembled: true,
        category: "casework_base",
      },
    ]);
    expect(estimatePallets(s, config)).toBe(5);
  });
});

describe("FlatPalletProvider", () => {
  it("quotes pallets × rate", async () => {
    const provider = new FlatPalletProvider({
      pallet_rate_cents: 70000,
      pallet_config: config,
    });
    const q = await provider.quote(
      shipment([
        {
          qty: 10,
          width_in: 30,
          height_in: 34.5,
          depth_in: 24,
          assembled: true,
          category: "casework_base",
        },
      ])
    );
    expect(q.pallets).toBe(5);
    expect(q.total_cents).toBe(350000);
    expect(q.provider).toBe("flat_pallet");
  });
});

describe("UberFreightProvider stub", () => {
  it("throws until v1.1 wires the real API", async () => {
    await expect(
      new UberFreightProvider().quote(shipment([]))
    ).rejects.toThrow(/stub/);
  });
});

describe("freightVerificationRequired", () => {
  it("requires verification at the $35k threshold", () => {
    expect(freightVerificationRequired(35_000_00, shipment([]))).toBe(true);
    expect(freightVerificationRequired(34_999_99, shipment([]))).toBe(false);
  });

  it("requires verification for assembled casework regardless of total", () => {
    const s = shipment([
      {
        qty: 1,
        width_in: 24,
        height_in: 34.5,
        depth_in: 24,
        assembled: true,
        category: "casework_base",
      },
    ]);
    expect(freightVerificationRequired(1000, s)).toBe(true);
  });

  it("does not require verification for small flat orders", () => {
    const s = shipment([
      {
        qty: 5,
        width_in: 24,
        height_in: 30,
        depth_in: 1,
        assembled: false,
        category: "door",
      },
    ]);
    expect(freightVerificationRequired(1000, s)).toBe(false);
  });
});
