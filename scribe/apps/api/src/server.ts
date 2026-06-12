import { buildApp } from "./app.js";
import { getPool, migrate, seed } from "@scribe/db";

// Boot-time migrate + seed (both idempotent). An advisory lock serializes
// concurrent replicas. In production a failure is fatal (better a failed
// deploy than a half-migrated app); in dev a missing DB just logs a warning
// so the API still boots for endpoint work. Set SKIP_BOOT_MIGRATIONS=1 to
// manage the schema manually.
async function bootstrapDb(): Promise<void> {
  if (process.env.SKIP_BOOT_MIGRATIONS === "1") return;
  if (!process.env.DATABASE_URL) {
    console.warn("DATABASE_URL not set — skipping boot migrations");
    return;
  }
  const pool = getPool();
  await pool.query("SELECT pg_advisory_lock(727501)");
  try {
    const applied = await migrate();
    console.log(
      applied.length > 0
        ? `migrations applied: ${applied.join(", ")}`
        : "migrations up to date"
    );
    await seed();
    console.log("seed ensured");
  } finally {
    await pool.query("SELECT pg_advisory_unlock(727501)");
  }
}

try {
  await bootstrapDb();
} catch (err) {
  if (process.env.NODE_ENV === "production") {
    console.error("boot migration failed", err);
    process.exit(1);
  }
  console.warn("boot migration skipped (DB unavailable?)", err);
}

const port = Number(process.env.PORT ?? 3001);

const app = await buildApp();
try {
  await app.listen({ port, host: "0.0.0.0" });
} catch (err) {
  app.log.error(err);
  process.exit(1);
}
