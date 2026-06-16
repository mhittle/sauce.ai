import Fastify, { FastifyInstance } from "fastify";
import cookie from "@fastify/cookie";
import cors from "@fastify/cors";
import multipart from "@fastify/multipart";
import { authPlugin } from "./auth.js";
import { authRoutes } from "./routes/auth.js";
import { healthRoutes } from "./routes/health.js";
import { takeoffRoutes } from "./routes/takeoffs.js";
import { quoteRoutes } from "./routes/quotes.js";
import { projectRoutes } from "./routes/projects.js";
import { adminRoutes } from "./routes/admin.js";
import { dashboardRoutes } from "./routes/dashboard.js";

export async function buildApp(): Promise<FastifyInstance> {
  const app = Fastify({
    logger: { level: process.env.LOG_LEVEL ?? "info" },
    bodyLimit: 10 * 1024 * 1024,
  });

  await app.register(cors, {
    origin: process.env.WEB_PUBLIC_URL?.split(",") ?? true,
    credentials: true,
    // web and api are cross-site (different *.up.railway.app subdomains), so
    // mutating verbs need an explicit preflight allow-list — the default omits
    // PUT/PATCH/DELETE and silently blocks every save from the SPA (SCR-002).
    methods: ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
  });
  await app.register(cookie);
  await app.register(multipart, {
    limits: { fileSize: 500 * 1024 * 1024 },
  });
  await app.register(authPlugin);

  await app.register(healthRoutes);
  await app.register(authRoutes);
  await app.register(takeoffRoutes);
  await app.register(quoteRoutes);
  await app.register(projectRoutes);
  await app.register(adminRoutes);
  await app.register(dashboardRoutes);

  return app;
}
