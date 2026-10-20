import { desc, eq, sql } from "drizzle-orm";
import { type CreditSettings, jobCharge, type JobCharge } from "@scribe/shared";
import type { Db } from "./index.js";
import { creditLedger, platformSettings, takeoffs } from "./schema.js";

// Credit ledger writes (accounts-plan.md §3.1). Every write locks the org row,
// so balance_after and orgs.credit_balance are computed under the lock, in
// SQL, never from a value read earlier in JS.

type Tx = Db | Parameters<Parameters<Db["transaction"]>[0]>[0];

export type CreditReason =
  | "signup_grant"
  | "admin_grant"
  | "purchase"
  | "hold"
  | "settle"
  | "release"
  | "refund"
  | "adjust";

export interface LedgerEntry {
  orgId: string;
  delta: number;
  reason: CreditReason;
  takeoffId?: string | null;
  holdId?: number | null;
  actorUserId?: string | null;
  externalRef?: string | null;
  note?: string | null;
}

export type LedgerRow = typeof creditLedger.$inferSelect;

// Callers that are not already in a transaction pass the db; the write still
// runs in its own transaction.
export async function writeLedger(db: Tx, entry: LedgerEntry): Promise<LedgerRow> {
  const run = async (tx: Tx) => {
    const locked = await tx.execute(
      sql`SELECT credit_balance FROM orgs WHERE id = ${entry.orgId} FOR UPDATE`
    );
    if (locked.rows.length === 0) throw new Error(`org ${entry.orgId} not found`);
    const balanceAfter = Number((locked.rows[0] as { credit_balance: number }).credit_balance) + entry.delta;
    const [row] = await tx
      .insert(creditLedger)
      .values({
        orgId: entry.orgId,
        delta: entry.delta,
        reason: entry.reason,
        takeoffId: entry.takeoffId ?? null,
        holdId: entry.holdId ?? null,
        balanceAfter,
        actorUserId: entry.actorUserId ?? null,
        externalRef: entry.externalRef ?? null,
        note: entry.note ?? null,
      })
      .returning();
    await tx.execute(
      sql`UPDATE orgs SET credit_balance = ${balanceAfter} WHERE id = ${entry.orgId}`
    );
    return row;
  };
  return "rollback" in db ? run(db) : (db as Db).transaction(run);
}

const DEFAULT_SETTINGS: CreditSettings = {
  minPagesPerJob: 1,
  firstJobFree: true,
  creditsEnforced: false,
};

export async function getCreditSettings(db: Tx): Promise<CreditSettings> {
  const [row] = await db.select().from(platformSettings).where(eq(platformSettings.id, 1));
  return row
    ? {
        minPagesPerJob: row.minPagesPerJob,
        firstJobFree: row.firstJobFree,
        creditsEnforced: row.creditsEnforced,
      }
    : DEFAULT_SETTINGS;
}

// The free first job is used once a job's hold has not been given back: a
// first job that fails (released) leaves it available.
export async function firstJobFreeAvailable(
  db: Tx,
  orgId: string,
  settings: CreditSettings
): Promise<boolean> {
  if (!settings.firstJobFree) return false;
  const used = await db.execute(sql`
    SELECT 1 FROM credit_ledger h
    WHERE h.org_id = ${orgId} AND h.reason = 'hold'
      AND NOT EXISTS (
        SELECT 1 FROM credit_ledger r WHERE r.hold_id = h.id AND r.reason = 'release'
      )
    LIMIT 1
  `);
  return used.rows.length === 0;
}

export async function orgBalance(db: Tx, orgId: string): Promise<number> {
  const r = await db.execute(sql`SELECT credit_balance FROM orgs WHERE id = ${orgId}`);
  return Number((r.rows[0] as { credit_balance: number } | undefined)?.credit_balance ?? 0);
}

// Serialize an org's credit decisions (quote → hold) inside a transaction.
export async function lockOrg(tx: Tx, orgId: string): Promise<void> {
  await tx.execute(sql`SELECT 1 FROM orgs WHERE id = ${orgId} FOR UPDATE`);
}

// What submitting `pages` would cost this org right now.
export async function quoteJob(
  db: Tx,
  orgId: string,
  pages: number
): Promise<{ charge: JobCharge; balance: number; settings: CreditSettings }> {
  const settings = await getCreditSettings(db);
  const free = await firstJobFreeAvailable(db, orgId, settings);
  return {
    charge: jobCharge(pages, settings, free),
    balance: await orgBalance(db, orgId),
    settings,
  };
}

// Open the job's hold (Pages submit, or upload for an image/spreadsheet).
// A free first job still writes a 0-page hold, so it is visible and counts
// as used. Idempotent: a takeoff with an open hold keeps it.
export async function openHold(
  tx: Tx,
  input: { orgId: string; takeoffId: string; charge: JobCharge; actorUserId: string | null }
): Promise<LedgerRow | null> {
  const [t] = await tx
    .select({ holdId: takeoffs.creditHoldId })
    .from(takeoffs)
    .where(eq(takeoffs.id, input.takeoffId));
  if (t?.holdId != null && !(await holdClosed(tx, t.holdId))) return null;
  const hold = await writeLedger(tx, {
    orgId: input.orgId,
    delta: -input.charge.credits,
    reason: "hold",
    takeoffId: input.takeoffId,
    actorUserId: input.actorUserId,
    note: input.charge.free
      ? `first job free (${input.charge.pages} pages)`
      : `${input.charge.pages} pages`,
  });
  await tx
    .update(takeoffs)
    .set({ creditHoldId: hold.id, pagesCharged: input.charge.credits })
    .where(eq(takeoffs.id, input.takeoffId));
  return hold;
}

async function holdClosed(db: Tx, holdId: number): Promise<boolean> {
  const r = await db.execute(sql`
    SELECT 1 FROM credit_ledger WHERE hold_id = ${holdId} AND reason IN ('settle','release') LIMIT 1
  `);
  return r.rows.length > 0;
}

// Close the takeoff's open hold: settle (job reached review — the pages stay
// spent) or release (job failed — the pages come back). No hold, or one
// already closed, is a no-op, so both are safe to call on every transition.
export async function closeHold(
  db: Db,
  takeoffId: string,
  kind: "settle" | "release",
  note: string | null = null
): Promise<LedgerRow | null> {
  return db.transaction(async (tx) => {
    const [t] = await tx
      .select({ orgId: takeoffs.orgId, holdId: takeoffs.creditHoldId })
      .from(takeoffs)
      .where(eq(takeoffs.id, takeoffId));
    if (!t?.holdId) return null;
    // Lock first so a concurrent close sees this one.
    await tx.execute(sql`SELECT 1 FROM orgs WHERE id = ${t.orgId} FOR UPDATE`);
    if (await holdClosed(tx, t.holdId)) return null;
    const [hold] = await tx.select().from(creditLedger).where(eq(creditLedger.id, t.holdId));
    return writeLedger(tx, {
      orgId: t.orgId,
      delta: kind === "release" ? -hold.delta : 0,
      reason: kind,
      takeoffId,
      holdId: hold.id,
      note,
    });
  });
}

// Holds whose job stopped short of review — abandoned at Mark, or a worker
// that died mid-job — are given back after `hours` without activity (hold,
// takeoff row, or a drawn/scanned area). Returns the takeoff ids released.
export async function sweepStaleHolds(db: Db, hours = 24): Promise<string[]> {
  const stale = await db.execute(sql`
    SELECT t.id
    FROM takeoffs t
    JOIN credit_ledger h ON h.id = t.credit_hold_id
    WHERE t.status IN ('processing', 'awaiting_pages', 'awaiting_boxes')
      AND NOT EXISTS (
        SELECT 1 FROM credit_ledger c WHERE c.hold_id = h.id AND c.reason IN ('settle', 'release')
      )
      AND GREATEST(
        h.created_at,
        t.updated_at,
        COALESCE((SELECT max(d.created_at) FROM takeoff_detections d WHERE d.takeoff_id = t.id), h.created_at)
      ) < now() - make_interval(hours => ${hours})
  `);
  const released: string[] = [];
  for (const row of stale.rows as { id: string }[]) {
    const r = await closeHold(db, row.id, "release", `job not finished within ${hours} h`);
    if (r) released.push(row.id);
  }
  return released;
}

// "Charge again" (owner, 2026-10-20): a job whose hold was released — swept
// for inactivity — and is then picked back up opens a fresh hold at the
// action that costs us again (Find, Build). A job whose hold is open or
// settled is not charged again; re-runs stay free.
export async function reholdIfReleased(
  tx: Tx,
  input: { orgId: string; takeoffId: string; actorUserId: string | null }
): Promise<{ charge: JobCharge; balance: number; settings: CreditSettings } | null> {
  const [t] = await tx
    .select({ holdId: takeoffs.creditHoldId, selected: takeoffs.selectedPages, kind: takeoffs.sourceKind })
    .from(takeoffs)
    .where(eq(takeoffs.id, input.takeoffId));
  if (!t?.holdId) return null;
  const released = await tx.execute(sql`
    SELECT 1 FROM credit_ledger WHERE hold_id = ${t.holdId} AND reason = 'release' LIMIT 1
  `);
  if (released.rows.length === 0) return null;
  await lockOrg(tx, input.orgId);
  const pages =
    t.kind === "pdf" && Array.isArray(t.selected) && t.selected.length > 0 ? t.selected.length : 1;
  const q = await quoteJob(tx, input.orgId, pages);
  // The org's free first job stays free when it is picked back up, even if
  // later jobs were submitted while it sat unfinished.
  const [prior] = await tx.select().from(creditLedger).where(eq(creditLedger.id, t.holdId));
  if (prior && prior.delta === 0 && prior.note?.startsWith("first job free")) {
    return { ...q, charge: { pages, credits: 0, free: true } };
  }
  return q;
}

export async function recentLedger(db: Tx, orgId: string, limit = 50): Promise<LedgerRow[]> {
  return db
    .select()
    .from(creditLedger)
    .where(eq(creditLedger.orgId, orgId))
    .orderBy(desc(creditLedger.id))
    .limit(limit);
}
