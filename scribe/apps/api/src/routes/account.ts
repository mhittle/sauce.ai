import { randomUUID } from "node:crypto";
import type { FastifyInstance } from "fastify";
import { z } from "zod";
import { and, desc, eq } from "drizzle-orm";
import { getDb, invites, orgs, users } from "@scribe/db";
import { putObject, signedGetUrl } from "@scribe/storage";
import { createInvite, publicInvite } from "./invites.js";

// Account screens (accounts-plan.md §1.9 PR D): the signed-in user's profile,
// their org (name, logo), its members and teammate invites. Everything is
// scoped to req.orgId; owner-only writes go through requireOrgOwner.
export async function accountRoutes(app: FastifyInstance): Promise<void> {
  app.addHook("preHandler", app.requireUser);

  app.patch("/me", async (req) => {
    const body = z
      .object({
        name: z.string().trim().min(1).max(120).optional(),
        phone: z.string().trim().max(40).nullable().optional(),
      })
      .parse(req.body);
    const db = getDb();
    const [u] = await db
      .update(users)
      .set({
        ...(body.name !== undefined ? { name: body.name } : {}),
        ...(body.phone !== undefined ? { phone: body.phone || null } : {}),
      })
      .where(eq(users.id, req.user!.id))
      .returning({ id: users.id, name: users.name, phone: users.phone, email: users.email });
    return u;
  });

  app.get("/account", async (req) => {
    const db = getDb();
    const [me] = await db
      .select({ id: users.id, email: users.email, name: users.name, phone: users.phone })
      .from(users)
      .where(eq(users.id, req.user!.id));
    const [org] = await db.select().from(orgs).where(eq(orgs.id, req.orgId));
    const members = await db
      .select({
        id: users.id,
        email: users.email,
        name: users.name,
        orgRole: users.orgRole,
        lastSignInAt: users.lastSignInAt,
        createdAt: users.createdAt,
      })
      .from(users)
      .where(eq(users.orgId, req.orgId))
      .orderBy(users.createdAt);
    const pending = await db
      .select()
      .from(invites)
      .where(eq(invites.orgId, req.orgId))
      .orderBy(desc(invites.createdAt));
    return {
      me,
      org: {
        id: org.id,
        name: org.name,
        logo_url: org.logoS3Key ? await signedGetUrl(org.logoS3Key) : null,
      },
      orgRole: req.user!.orgRole,
      members,
      invites: pending.map(publicInvite).filter((i) => i.state === "pending"),
    };
  });

  await app.register(async (owner) => {
    owner.addHook("preHandler", app.requireOrgOwner);

    owner.patch("/account/org", async (req) => {
      const body = z.object({ name: z.string().trim().min(1).max(120) }).parse(req.body);
      const [org] = await getDb()
        .update(orgs)
        .set({ name: body.name })
        .where(eq(orgs.id, req.orgId))
        .returning();
      return { id: org.id, name: org.name };
    });

    owner.post("/account/org/logo", async (req, reply) => {
      const file = await req.file();
      if (!file) return reply.code(400).send({ error: "no file uploaded" });
      const ext = file.filename.split(".").pop()?.toLowerCase();
      if (!ext || !["png", "jpg", "jpeg"].includes(ext)) {
        return reply.code(400).send({ error: "logo must be PNG or JPEG" });
      }
      const key = `orgs/${req.orgId}/logo-${randomUUID()}.${ext}`;
      await putObject(key, await file.toBuffer(), file.mimetype);
      await getDb().update(orgs).set({ logoS3Key: key }).where(eq(orgs.id, req.orgId));
      return { url: await signedGetUrl(key) };
    });

    owner.patch<{ Params: { id: string } }>("/account/members/:id", async (req, reply) => {
      const body = z.object({ org_role: z.enum(["owner", "member"]) }).parse(req.body);
      if (req.params.id === req.user!.id && body.org_role === "member") {
        return reply.code(409).send({ error: "you cannot demote yourself" });
      }
      const [u] = await getDb()
        .update(users)
        .set({ orgRole: body.org_role })
        .where(and(eq(users.id, req.params.id), eq(users.orgId, req.orgId)))
        .returning({ id: users.id, orgRole: users.orgRole });
      if (!u) return reply.code(404).send({ error: "member not found" });
      return u;
    });

    // A teammate joins THIS org (invite.org_id set): no new org, no credits.
    owner.post("/account/invites", async (req, reply) => {
      const body = z
        .object({
          email: z.string().email(),
          name: z.string().trim().max(120).optional(),
        })
        .parse(req.body);
      const made = await createInvite(app, {
        email: body.email,
        name: body.name,
        orgId: req.orgId,
        invitedBy: req.user!,
      });
      if ("error" in made) return reply.code(409).send(made);
      return reply.code(201).send({ ...publicInvite(made.row), sent: made.sent, link: made.link });
    });

    owner.delete<{ Params: { id: string } }>("/account/invites/:id", async (req, reply) => {
      const db = getDb();
      const [row] = await db
        .update(invites)
        .set({ revokedAt: new Date() })
        .where(and(eq(invites.id, req.params.id), eq(invites.orgId, req.orgId)))
        .returning();
      if (!row) return reply.code(404).send({ error: "invite not found" });
      return publicInvite(row);
    });
  });
}
