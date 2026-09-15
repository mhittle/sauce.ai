// Transactional email via Resend's REST API (no SDK — one endpoint). Without
// RESEND_API_KEY every send is logged instead, so dev, tests and a prod
// deploy that has not finished the DNS setup keep working; the caller gets
// `sent: false` and can show the link another way.

export interface EmailMessage {
  to: string;
  subject: string;
  html: string;
  text: string;
}

export interface SendResult {
  sent: boolean;
  id?: string;
  reason?: string;
}

export function emailConfigured(): boolean {
  return Boolean(process.env.RESEND_API_KEY && process.env.EMAIL_FROM);
}

export async function sendEmail(
  msg: EmailMessage,
  log: (obj: Record<string, unknown>, msg: string) => void = () => {}
): Promise<SendResult> {
  const key = process.env.RESEND_API_KEY;
  const from = process.env.EMAIL_FROM;
  if (!key || !from) {
    log({ to: msg.to, subject: msg.subject }, "email not configured — not sent");
    return { sent: false, reason: "email not configured" };
  }
  const res = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      authorization: `Bearer ${key}`,
      "content-type": "application/json",
    },
    body: JSON.stringify({
      from,
      to: [msg.to],
      subject: msg.subject,
      html: msg.html,
      text: msg.text,
      ...(process.env.EMAIL_REPLY_TO ? { reply_to: process.env.EMAIL_REPLY_TO } : {}),
    }),
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    log({ to: msg.to, status: res.status, body: body.slice(0, 300) }, "email send failed");
    return { sent: false, reason: `resend ${res.status}` };
  }
  const data = (await res.json()) as { id?: string };
  return { sent: true, id: data.id };
}

export { inviteEmail, magicLinkEmail } from "./templates.js";
export type { InviteEmailInput } from "./templates.js";
