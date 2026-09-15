import { createHash, randomBytes } from "node:crypto";

// Single-use links (invites, magic links): the raw token goes out once, in
// the email; the DB keeps only its hash, so a leaked table cannot be replayed.

export function newToken(): string {
  return randomBytes(32).toString("base64url");
}

export function hashToken(token: string): string {
  return createHash("sha256").update(token).digest("hex");
}

export type InviteState = "pending" | "used" | "revoked" | "expired";

export function inviteState(row: {
  usedAt: Date | null;
  revokedAt: Date | null;
  expiresAt: Date;
}, now = new Date()): InviteState {
  if (row.usedAt) return "used";
  if (row.revokedAt) return "revoked";
  if (row.expiresAt.getTime() <= now.getTime()) return "expired";
  return "pending";
}
