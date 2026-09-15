import type { FastifyInstance } from "fastify";
import { z } from "zod";
import { desc, eq } from "drizzle-orm";
import { getDb, invites, users } from "@scribe/db";
import { emailConfigured, inviteEmail, sendEmail } from "@scribe/email";
import { hashToken, inviteState, newToken } from "../lib/tokens.js";

const INVITE_TTL_MS = 14 * 86_400_000;

function webUrl(): string {
  return (process.env.WEB_PUBLIC_URL ?? "http://localhost:5173").split(",")[0];
}

export function signupLink(token: string): string {
  return `${webUrl()}/signup?token=${token}`;
}

type InviteRow = typeof invites.$inferSelect;

function publicInvite(row: InviteRow) {
  return {
    id: row.id,
    email: row.email,
    name: row.name,
    orgName: row.orgName,
    creditsGranted: row.creditsGranted,
    note: row.note,
    invitedBy: row.invitedBy,
    expiresAt: row.expiresAt,
    usedAt: row.usedAt,
    revokedAt: row.revokedAt,
    lastSentAt: row.lastSentAt,
    createdAt: row.createdAt,
    state: inviteState(row),
  };
}

async function emailInvite(
  app: FastifyInstance,
  row: InviteRow,
  token: string,
  inviterName: string
): Promise<{ sent: boolean; link: string }> {
  const link = signupLink(token);
  const msg = inviteEmail({
    to: row.email,
    name: row.name,
    inviterName,
    link,
    expiresAt: row.expiresAt,
    creditsGranted: row.creditsGranted,
  });
  const result = await sendEmail(msg, (obj, m) => app.log.warn(obj, m));
  if (result.sent) {
    await getDb()
      .update(invites)
      .set({ lastSentAt: new Date() })
      .where(eq(invites.id, row.id));
  }
  return { sent: result.sent, link };
}

export async function inviteRoutes(app: FastifyInstance): Promise<void> {
  // Public: the sign-up page asks what this token is before showing the form.
  // Never echoes the token; answers the same shape for every non-pending state.
  app.get<{ Params: { token: string } }>("/signup/:token", async (req, reply) => {
    const db = getDb();
    const rows = await db
      .select()
      .from(invites)
      .where(eq(invites.tokenHash, hashToken(req.params.token)));
    if (rows.length === 0) return reply.code(404).send({ error: "invite not found" });
    const row = rows[0];
    const state = inviteState(row);
    if (state !== "pending") return { state };
    const existing = await db.select({ id: users.id }).from(users).where(eq(users.email, row.email));
    if (existing.length > 0) return { state: "used" };
    const [inviter] = await db.select({ name: users.name, email: users.email }).from(users).where(eq(users.id, row.invitedBy));
    return {
      state,
      email: row.email,
      name: row.name,
      orgName: row.orgName,
      creditsGranted: row.creditsGranted,
      inviterName: inviter?.name ?? inviter?.email ?? "Scribe",
      expiresAt: row.expiresAt,
    };
  });

  await app.register(async (admin) => {
    admin.addHook("preHandler", app.requireAdmin);

    admin.get("/admin/invites", async () => {
      const db = getDb();
      const rows = await db.select().from(invites).orderBy(desc(invites.createdAt));
      return { emailConfigured: emailConfigured(), invites: rows.map(publicInvite) };
    });

    admin.post("/admin/invites", async (req, reply) => {
      const body = z
        .object({
          email: z.string().email(),
          name: z.string().trim().max(120).optional(),
          orgName: z.string().trim().max(120).optional(),
          creditsGranted: z.number().int().min(0).max(10_000).default(0),
          note: z.string().trim().max(500).optional(),
        })
        .parse(req.body);
      const email = body.email.toLowerCase();
      const db = getDb();
      const existing = await db.select({ id: users.id }).from(users).where(eq(users.email, email));
      if (existing.length > 0) {
        return reply.code(409).send({ error: "that email already has an account" });
      }
      const token = newToken();
      const [row] = await db
        .insert(invites)
        .values({
          tokenHash: hashToken(token),
          email,
          name: body.name || null,
          orgName: body.orgName || null,
          creditsGranted: body.creditsGranted,
          invitedBy: req.user!.id,
          note: body.note || null,
          expiresAt: new Date(Date.now() + INVITE_TTL_MS),
        })
        .returning();
      const { sent, link } = await emailInvite(app, row, token, req.user!.name ?? req.user!.email);
      // The link is returned so the admin can paste it when email is not
      // configured; it is the only time the raw token leaves the server.
      return reply.code(201).send({ ...publicInvite({ ...row, lastSentAt: sent ? new Date() : null }), sent, link });
    });

    // A new token: the old link stops working, the new one is emailed (and
    // returned). Also the way to extend an expired invite.
    admin.post<{ Params: { id: string } }>("/admin/invites/:id/resend", async (req, reply) => {
      const db = getDb();
      const rows = await db.select().from(invites).where(eq(invites.id, req.params.id));
      if (rows.length === 0) return reply.code(404).send({ error: "invite not found" });
      const current = rows[0];
      const state = inviteState(current);
      if (state === "used" || state === "revoked") {
        return reply.code(409).send({ error: `invite is ${state}` });
      }
      const token = newToken();
      const [row] = await db
        .update(invites)
        .set({ tokenHash: hashToken(token), expiresAt: new Date(Date.now() + INVITE_TTL_MS) })
        .where(eq(invites.id, current.id))
        .returning();
      const { sent, link } = await emailInvite(app, row, token, req.user!.name ?? req.user!.email);
      return { ...publicInvite({ ...row, lastSentAt: sent ? new Date() : row.lastSentAt }), sent, link };
    });

    admin.delete<{ Params: { id: string } }>("/admin/invites/:id", async (req, reply) => {
      const db = getDb();
      const rows = await db.select().from(invites).where(eq(invites.id, req.params.id));
      if (rows.length === 0) return reply.code(404).send({ error: "invite not found" });
      if (rows[0].usedAt) return reply.code(409).send({ error: "invite was already used" });
      const [row] = await db
        .update(invites)
        .set({ revokedAt: new Date() })
        .where(eq(invites.id, rows[0].id))
        .returning();
      return publicInvite(row);
    });
  });
}
