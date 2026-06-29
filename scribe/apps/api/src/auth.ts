import { createHmac, timingSafeEqual } from "node:crypto";
import fp from "fastify-plugin";
import type { FastifyReply, FastifyRequest } from "fastify";
import { eq } from "drizzle-orm";
import { getDb, users } from "@scribe/db";
import type { UserRole } from "@scribe/shared";

// Google OAuth (PRD §3: no self-signup — only emails already in users may log
// in). Sessions are HMAC-signed cookies. When GOOGLE_CLIENT_ID is unset and
// not in production, a dev-bypass auto-authenticates as a local admin.

export interface SessionUser {
  id: string;
  email: string;
  role: UserRole;
  name: string | null;
}

declare module "fastify" {
  interface FastifyRequest {
    user: SessionUser | null;
  }
  interface FastifyInstance {
    requireUser: (req: FastifyRequest, reply: FastifyReply) => Promise<void>;
    requireAdmin: (req: FastifyRequest, reply: FastifyReply) => Promise<void>;
  }
}

export const SESSION_COOKIE = "scribe_session";
const SESSION_TTL_MS = 1000 * 60 * 60 * 24 * 14;

function secret(): string {
  return process.env.SESSION_SECRET ?? "dev-only-secret";
}

export function signSession(userId: string): string {
  const exp = Date.now() + SESSION_TTL_MS;
  const payload = `${userId}.${exp}`;
  const mac = createHmac("sha256", secret()).update(payload).digest("base64url");
  return `${payload}.${mac}`;
}

export function verifySession(token: string): string | null {
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  const [userId, expStr, mac] = parts;
  const expected = createHmac("sha256", secret())
    .update(`${userId}.${expStr}`)
    .digest("base64url");
  const a = Buffer.from(mac);
  const b = Buffer.from(expected);
  if (a.length !== b.length || !timingSafeEqual(a, b)) return null;
  if (Date.now() > Number(expStr)) return null;
  return userId;
}

export function devBypassEnabled(): boolean {
  return !process.env.GOOGLE_CLIENT_ID && process.env.NODE_ENV !== "production";
}

// Service-to-service auth: a trusted caller (e.g. sauce.ai/signal sending a bid
// PDF to be quoted) presents `Authorization: Bearer ${SERVICE_TOKEN}`. It maps
// to a single machine user so takeoffs still have a valid uploadedBy. Disabled
// unless SERVICE_TOKEN is set; compared timing-safe.
const SERVICE_EMAIL = "signal-connector@scribe.local";

function tokensMatch(presented: string, expected: string): boolean {
  const a = Buffer.from(presented);
  const b = Buffer.from(expected);
  if (a.length !== b.length) return false;
  return timingSafeEqual(a, b);
}

async function serviceUser(): Promise<SessionUser> {
  const db = getDb();
  const existing = await db
    .select()
    .from(users)
    .where(eq(users.email, SERVICE_EMAIL));
  if (existing.length > 0) {
    const u = existing[0];
    return { id: u.id, email: u.email, role: u.role as UserRole, name: u.name };
  }
  const [u] = await db
    .insert(users)
    .values({ email: SERVICE_EMAIL, name: "Signal Connector", role: "estimator" })
    .returning();
  return { id: u.id, email: u.email, role: u.role as UserRole, name: u.name };
}

async function devUser(): Promise<SessionUser> {
  const db = getDb();
  const existing = await db
    .select()
    .from(users)
    .where(eq(users.email, "dev@scribe.local"));
  if (existing.length > 0) {
    const u = existing[0];
    return {
      id: u.id,
      email: u.email,
      role: u.role as UserRole,
      name: u.name,
    };
  }
  const [u] = await db
    .insert(users)
    .values({ email: "dev@scribe.local", name: "Dev User", role: "admin" })
    .returning();
  return { id: u.id, email: u.email, role: u.role as UserRole, name: u.name };
}

// The session travels as an HMAC-signed token, either in a cookie (same-site
// deploys) or an Authorization: Bearer header (cross-site deploys — Railway's
// up.railway.app is on the Public Suffix List, so web and api subdomains are
// cross-site and browsers refuse the cookie on fetches).
function sessionTokenFrom(req: FastifyRequest): string | null {
  const header = req.headers.authorization;
  if (header?.startsWith("Bearer ")) return header.slice("Bearer ".length);
  return req.cookies[SESSION_COOKIE] ?? null;
}

export const authPlugin = fp(async (app) => {
  app.decorateRequest("user", null);

  app.addHook("onRequest", async (req) => {
    const token = sessionTokenFrom(req);
    if (token) {
      const userId = verifySession(token);
      if (userId) {
        const db = getDb();
        const rows = await db.select().from(users).where(eq(users.id, userId));
        if (rows.length > 0) {
          const u = rows[0];
          req.user = {
            id: u.id,
            email: u.email,
            role: u.role as UserRole,
            name: u.name,
          };
          return;
        }
      }
    }
    const serviceToken = process.env.SERVICE_TOKEN;
    if (!req.user && serviceToken && token && tokensMatch(token, serviceToken)) {
      try {
        req.user = await serviceUser();
        return;
      } catch {
        // DB not up yet — fall through (unauthenticated).
      }
    }
    if (devBypassEnabled() && req.url.startsWith("/") && !req.user) {
      try {
        req.user = await devUser();
      } catch {
        // DB not up yet — health endpoints still work unauthenticated
        req.user = null;
      }
    }
  });

  app.decorate(
    "requireUser",
    async (req: FastifyRequest, reply: FastifyReply) => {
      if (!req.user) {
        await reply.code(401).send({ error: "authentication required" });
      }
    }
  );

  app.decorate(
    "requireAdmin",
    async (req: FastifyRequest, reply: FastifyReply) => {
      if (!req.user) {
        await reply.code(401).send({ error: "authentication required" });
        return;
      }
      if (req.user.role !== "admin") {
        await reply.code(403).send({ error: "admin role required" });
      }
    }
  );
});
