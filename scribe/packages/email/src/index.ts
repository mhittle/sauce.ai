import nodemailer, { type Transporter } from "nodemailer";

// Transactional email. SMTP (any provider: Gmail/Workspace, Microsoft 365,
// SES…) via nodemailer when SMTP_HOST is set; else Resend's REST API when
// RESEND_API_KEY is set; else every send is logged instead, so dev, tests and
// an unconfigured prod keep working — the caller gets `sent: false` and can
// show the link another way. EMAIL_FROM is the sender for both.

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

function smtpConfigured(): boolean {
  return Boolean(
    process.env.SMTP_HOST && process.env.SMTP_USER && process.env.SMTP_PASS && process.env.EMAIL_FROM
  );
}

export function emailConfigured(): boolean {
  return smtpConfigured() || Boolean(process.env.RESEND_API_KEY && process.env.EMAIL_FROM);
}

// SMTP_PORT 465 = implicit TLS; anything else (587) upgrades with STARTTLS.
export function smtpOptions(env: NodeJS.ProcessEnv = process.env) {
  const port = Number(env.SMTP_PORT ?? 587);
  return {
    host: env.SMTP_HOST,
    port,
    secure: port === 465,
    auth: { user: env.SMTP_USER, pass: env.SMTP_PASS },
  };
}

let transport: Transporter | null = null;

async function sendSmtp(
  msg: EmailMessage,
  log: (obj: Record<string, unknown>, msg: string) => void
): Promise<SendResult> {
  transport ??= nodemailer.createTransport(smtpOptions());
  try {
    const info = await transport.sendMail({
      from: process.env.EMAIL_FROM,
      to: msg.to,
      subject: msg.subject,
      html: msg.html,
      text: msg.text,
      ...(process.env.EMAIL_REPLY_TO ? { replyTo: process.env.EMAIL_REPLY_TO } : {}),
    });
    return { sent: true, id: info.messageId };
  } catch (err) {
    const e = err as { message?: string; code?: string; responseCode?: number };
    log({ to: msg.to, code: e.code, responseCode: e.responseCode, err: e.message }, "email send failed (smtp)");
    return { sent: false, reason: `smtp ${e.code ?? e.responseCode ?? "error"}` };
  }
}

export async function sendEmail(
  msg: EmailMessage,
  log: (obj: Record<string, unknown>, msg: string) => void = () => {}
): Promise<SendResult> {
  if (smtpConfigured()) return sendSmtp(msg, log);
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

export { inviteEmail, magicLinkEmail, receiptEmail } from "./templates.js";
export type { InviteEmailInput, ReceiptEmailInput } from "./templates.js";
