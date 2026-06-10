import type { FastifyInstance } from "fastify";
import { eq } from "drizzle-orm";
import { getDb, users } from "@scribe/db";
import { SESSION_COOKIE, signSession } from "../auth.js";

function apiUrl(): string {
  return process.env.API_PUBLIC_URL ?? "http://localhost:3001";
}

function webUrl(): string {
  return (process.env.WEB_PUBLIC_URL ?? "http://localhost:5173").split(",")[0];
}

const cookieOpts = {
  path: "/",
  httpOnly: true,
  sameSite: "lax" as const,
  secure: process.env.NODE_ENV === "production",
};

export async function authRoutes(app: FastifyInstance): Promise<void> {
  app.get("/auth/me", async (req, reply) => {
    if (!req.user) return reply.code(401).send({ error: "not signed in" });
    return req.user;
  });

  app.post("/auth/logout", async (_req, reply) => {
    reply.clearCookie(SESSION_COOKIE, cookieOpts);
    return { ok: true };
  });

  app.get("/auth/google", async (_req, reply) => {
    const clientId = process.env.GOOGLE_CLIENT_ID;
    if (!clientId) {
      return reply
        .code(501)
        .send({ error: "GOOGLE_CLIENT_ID not configured (dev-bypass active)" });
    }
    const params = new URLSearchParams({
      client_id: clientId,
      redirect_uri: `${apiUrl()}/auth/google/callback`,
      response_type: "code",
      scope: "openid email profile",
      prompt: "select_account",
    });
    return reply.redirect(
      `https://accounts.google.com/o/oauth2/v2/auth?${params}`
    );
  });

  app.get<{ Querystring: { code?: string; error?: string } }>(
    "/auth/google/callback",
    async (req, reply) => {
      const { code, error } = req.query;
      if (error || !code) {
        return reply.redirect(`${webUrl()}/?auth_error=denied`);
      }

      const tokenRes = await fetch("https://oauth2.googleapis.com/token", {
        method: "POST",
        headers: { "content-type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({
          code,
          client_id: process.env.GOOGLE_CLIENT_ID!,
          client_secret: process.env.GOOGLE_CLIENT_SECRET ?? "",
          redirect_uri: `${apiUrl()}/auth/google/callback`,
          grant_type: "authorization_code",
        }),
      });
      if (!tokenRes.ok) {
        req.log.error({ status: tokenRes.status }, "google token exchange failed");
        return reply.redirect(`${webUrl()}/?auth_error=token`);
      }
      const tokens = (await tokenRes.json()) as { access_token: string };

      const infoRes = await fetch(
        "https://openidconnect.googleapis.com/v1/userinfo",
        { headers: { authorization: `Bearer ${tokens.access_token}` } }
      );
      if (!infoRes.ok) {
        return reply.redirect(`${webUrl()}/?auth_error=userinfo`);
      }
      const info = (await infoRes.json()) as { email?: string; name?: string };
      if (!info.email) {
        return reply.redirect(`${webUrl()}/?auth_error=no_email`);
      }

      // No self-signup: the email must already exist in users (seeded from
      // AUTH_ALLOWED_EMAILS or added by an admin).
      const db = getDb();
      const rows = await db
        .select()
        .from(users)
        .where(eq(users.email, info.email.toLowerCase()));
      if (rows.length === 0) {
        return reply.redirect(`${webUrl()}/?auth_error=not_allowed`);
      }
      const u = rows[0];
      if (info.name && !u.name) {
        await db.update(users).set({ name: info.name }).where(eq(users.id, u.id));
      }

      reply.setCookie(SESSION_COOKIE, signSession(u.id), cookieOpts);
      return reply.redirect(webUrl());
    }
  );
}
