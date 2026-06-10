import type { FastifyInstance } from "fastify";
import { getPool } from "@scribe/db";

export async function healthRoutes(app: FastifyInstance): Promise<void> {
  app.get("/health", async () => ({ ok: true, service: "scribe-api" }));

  app.get("/health/db", async (_req, reply) => {
    try {
      await getPool().query("SELECT 1");
      return { ok: true };
    } catch (err) {
      return reply.code(503).send({ ok: false, error: String(err) });
    }
  });
}
