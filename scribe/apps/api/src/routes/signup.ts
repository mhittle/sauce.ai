import type { FastifyInstance } from "fastify";
import { z } from "zod";
import { eq } from "drizzle-orm";
import { getDb, invites, loginTokens, orgs, users } from "@scribe/db";
import { magicLinkEmail, sendEmail } from "@scribe/email";
import { SESSION_COOKIE, signSession } from "../auth.js";
import { hashToken, inviteState, newToken } from "../lib/tokens.js";
import { cloneSampleTakeoff } from "../lib/sample.js";
import { apiUrl, cookieOpts, webUrl } from "./auth.js";

const MAGIC_TTL_MS = 15 * 60_000;

export function termsVersion(): string {
  return process.env.TERMS_VERSION ?? "2026-09";
}

export function legalUrls() {
  return {
    termsUrl: process.env.TERMS_URL ?? null,
    privacyUrl: process.env.PRIVACY_URL ?? null,
  };
}

// Sign-up (accounts-plan.md §1.2) and email magic links (§1.4). Both public.
export async function signupRoutes(app: FastifyInstance): Promise<void> {
  // The emailed token proves the mailbox, so submitting the form signs the
  // user in directly: org + user + invite consumed in one transaction.
  app.post("/signup", async (req, reply) => {
    const body = z
      .object({
        token: z.string().min(20).max(200),
        name: z.string().trim().min(1).max(120),
        phone: z.string().trim().max(40).optional(),
      })
      .parse(req.body);
    const db = getDb();
    const rows = await db
      .select()
      .from(invites)
      .where(eq(invites.tokenHash, hashToken(body.token)));
    if (rows.length === 0) return reply.code(404).send({ error: "invite not found" });
    const invite = rows[0];
    const state = inviteState(invite);
    if (state !== "pending") return reply.code(409).send({ error: `invite is ${state}`, state });
    const existing = await db.select({ id: users.id }).from(users).where(eq(users.email, invite.email));
    if (existing.length > 0) {
      return reply.code(409).send({ error: "that email already has an account", state: "used" });
    }

    const user = await db.transaction(async (tx) => {
      let orgId = invite.orgId;
      let orgRole: "owner" | "member" = "member";
      if (!orgId) {
        const [org] = await tx
          .insert(orgs)
          .values({ name: invite.orgName || body.name })
          .returning();
        orgId = org.id;
        orgRole = "owner";
      }
      const [u] = await tx
        .insert(users)
        .values({
          email: invite.email,
          name: body.name,
          phone: body.phone || null,
          role: "estimator",
          orgId,
          orgRole,
          termsAcceptedAt: new Date(),
          termsVersion: termsVersion(),
          termsIp: req.ip,
          lastSignInAt: new Date(),
        })
        .returning();
      await tx
        .update(invites)
        .set({ usedAt: new Date(), usedBy: u.id })
        .where(eq(invites.id, invite.id));
      return u;
    });
    req.log.info({ userId: user.id, orgId: user.orgId, invite: invite.id }, "signup completed");
    try {
      await cloneSampleTakeoff(user.orgId, user.id);
    } catch (err) {
      req.log.warn({ err, orgId: user.orgId }, "sample job not seeded");
    }

    const token = signSession(user.id);
    reply.setCookie(SESSION_COOKIE, token, cookieOpts);
    return reply.code(201).send({ session: token, userId: user.id, orgId: user.orgId });
  });

  // Always 200: the response must not reveal whether an account exists.
  app.post("/auth/magic-link", async (req, reply) => {
    const body = z.object({ email: z.string().email() }).parse(req.body);
    const email = body.email.toLowerCase();
    const db = getDb();
    const rows = await db.select().from(users).where(eq(users.email, email));
    if (rows.length > 0) {
      const u = rows[0];
      const token = newToken();
      await db.insert(loginTokens).values({
        tokenHash: hashToken(token),
        userId: u.id,
        expiresAt: new Date(Date.now() + MAGIC_TTL_MS),
      });
      const link = `${apiUrl()}/auth/magic/${token}`;
      const result = await sendEmail(
        magicLinkEmail({ to: u.email, name: u.name, link }),
        (obj, m) => req.log.warn(obj, m)
      );
      if (!result.sent) req.log.warn({ email, link }, "magic link not emailed");
    }
    return reply.send({ ok: true });
  });

  app.get<{ Params: { token: string } }>("/auth/magic/:token", async (req, reply) => {
    const db = getDb();
    const rows = await db
      .select()
      .from(loginTokens)
      .where(eq(loginTokens.tokenHash, hashToken(req.params.token)));
    const row = rows[0];
    if (!row || row.usedAt || row.expiresAt.getTime() <= Date.now()) {
      return reply.redirect(`${webUrl()}/?auth_error=link_expired`);
    }
    await db.update(loginTokens).set({ usedAt: new Date() }).where(eq(loginTokens.id, row.id));
    await db.update(users).set({ lastSignInAt: new Date() }).where(eq(users.id, row.userId));
    const token = signSession(row.userId);
    reply.setCookie(SESSION_COOKIE, token, cookieOpts);
    return reply.redirect(`${webUrl()}/#session=${token}`);
  });
}
