import { desc, eq } from "drizzle-orm";
import { getDb, orgSettings, pricingConfigs } from "@scribe/db";
import { PalletConfig, PricingSnapshot } from "@scribe/shared";

export interface OrgSettingsRow {
  logoS3Key: string | null;
  quoteTermsMd: string;
  quoteFooterMd: string;
  defaultHandlingCents: number;
  palletRateCents: number;
  palletConfig: PalletConfig;
  freightProvider: string;
}

export async function loadOrgSettings(): Promise<OrgSettingsRow> {
  const db = getDb();
  const rows = await db.select().from(orgSettings).where(eq(orgSettings.id, 1));
  if (rows.length === 0) {
    throw new Error("org_settings not seeded — run pnpm db:seed");
  }
  const r = rows[0];
  return {
    logoS3Key: r.logoS3Key,
    quoteTermsMd: r.quoteTermsMd,
    quoteFooterMd: r.quoteFooterMd,
    defaultHandlingCents: r.defaultHandlingCents,
    palletRateCents: r.palletRateCents,
    palletConfig: PalletConfig.parse(r.palletConfig ?? {}),
    freightProvider: r.freightProvider,
  };
}

export async function loadLatestPricingConfig(): Promise<{
  id: string;
  version: number;
  snapshot: PricingSnapshot;
}> {
  const db = getDb();
  const rows = await db
    .select()
    .from(pricingConfigs)
    .orderBy(desc(pricingConfigs.version))
    .limit(1);
  if (rows.length === 0) {
    throw new Error("no pricing_configs — run pnpm db:seed");
  }
  return {
    id: rows[0].id,
    version: rows[0].version,
    snapshot: PricingSnapshot.parse(rows[0].snapshot),
  };
}

export async function loadPricingConfigById(id: string): Promise<{
  id: string;
  version: number;
  snapshot: PricingSnapshot;
}> {
  const db = getDb();
  const rows = await db
    .select()
    .from(pricingConfigs)
    .where(eq(pricingConfigs.id, id));
  if (rows.length === 0) throw new Error(`pricing config ${id} not found`);
  return {
    id: rows[0].id,
    version: rows[0].version,
    snapshot: PricingSnapshot.parse(rows[0].snapshot),
  };
}
