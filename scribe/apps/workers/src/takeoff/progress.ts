import { eq, sql } from "drizzle-orm";
import { getDb, takeoffs } from "@scribe/db";
import type { TakeoffProgress, TakeoffStage } from "@scribe/shared";

// Writes takeoffs.progress at stage boundaries so the Reading screen can show
// where a job is. Best-effort: a failed write never fails the takeoff.
// started_at is kept from the first write of this processing run.
export async function setProgress(
  takeoffId: string,
  stage: TakeoffStage,
  opts: { done?: number | null; total?: number | null; message?: string | null } = {}
): Promise<void> {
  const now = new Date().toISOString();
  const next: Omit<TakeoffProgress, "started_at"> = {
    stage,
    done: opts.done ?? null,
    total: opts.total ?? null,
    message: opts.message ?? null,
    updated_at: now,
  };
  try {
    const db = getDb();
    await db
      .update(takeoffs)
      .set({
        // Keep the run's started_at if progress already exists; otherwise now.
        progress: sql`jsonb_build_object('started_at', COALESCE(${takeoffs.progress}->>'started_at', ${now}::text)) || ${JSON.stringify(next)}::jsonb`,
      })
      .where(eq(takeoffs.id, takeoffId));
  } catch {
    // advisory only
  }
}

// A fresh processing run (upload, page submit, wizard rebuild) resets the clock.
export async function resetProgress(takeoffId: string): Promise<void> {
  try {
    const db = getDb();
    await db.update(takeoffs).set({ progress: null }).where(eq(takeoffs.id, takeoffId));
  } catch {
    // advisory only
  }
}
