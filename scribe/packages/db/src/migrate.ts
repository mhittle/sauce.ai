import { readdir, readFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { getPool, closeDb } from "./index.js";

// Applies migrations/*.sql in filename order, tracked in _migrations.
// Idempotent: already-applied files are skipped.

export async function migrate(): Promise<string[]> {
  const pool = getPool();
  const dir = join(dirname(fileURLToPath(import.meta.url)), "..", "migrations");
  const files = (await readdir(dir)).filter((f) => f.endsWith(".sql")).sort();

  await pool.query(
    `CREATE TABLE IF NOT EXISTS _migrations (
       name text PRIMARY KEY,
       applied_at timestamptz NOT NULL DEFAULT now()
     )`
  );

  const applied: string[] = [];
  for (const file of files) {
    const { rows } = await pool.query(
      "SELECT 1 FROM _migrations WHERE name = $1",
      [file]
    );
    if (rows.length > 0) continue;

    const sql = await readFile(join(dir, file), "utf8");
    const client = await pool.connect();
    try {
      await client.query("BEGIN");
      await client.query(sql);
      await client.query("INSERT INTO _migrations (name) VALUES ($1)", [file]);
      await client.query("COMMIT");
      applied.push(file);
    } catch (err) {
      await client.query("ROLLBACK");
      throw err;
    } finally {
      client.release();
    }
  }
  return applied;
}

const isMain =
  process.argv[1] && import.meta.url === `file://${process.argv[1]}`;
if (isMain) {
  migrate()
    .then((applied) => {
      console.log(
        applied.length > 0
          ? `applied: ${applied.join(", ")}`
          : "no pending migrations"
      );
      return closeDb();
    })
    .catch((err) => {
      console.error(err);
      process.exit(1);
    });
}
