import { eq } from "drizzle-orm";
import { getDb, orgs } from "@scribe/db";

let platformOrgId: string | null = null;

// The org that owns the platform (CabinetNow). Seeded by migration 0014;
// machine users (dev bypass, signal connector) belong to it.
export async function getPlatformOrgId(): Promise<string> {
  if (platformOrgId) return platformOrgId;
  const rows = await getDb().select({ id: orgs.id }).from(orgs).where(eq(orgs.isPlatform, true));
  if (rows.length === 0) throw new Error("platform org missing — migration 0014 not applied");
  platformOrgId = rows[0].id;
  return platformOrgId;
}

// The org a request acts in: the user's own, or — for platform admins only —
// the one named in X-Org-Id (support: look at a customer's jobs).
export function resolveOrgId(
  user: { orgId: string; isPlatformAdmin: boolean },
  header: string | string[] | undefined
): string {
  const asked = Array.isArray(header) ? header[0] : header;
  if (asked && user.isPlatformAdmin && /^[0-9a-f-]{36}$/i.test(asked)) return asked;
  return user.orgId;
}
