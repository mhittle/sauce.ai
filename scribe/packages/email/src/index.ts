import nodemailer, { type Transporter } from "nodemailer";

// Transactional email. SMTP (any provider: Gmail/Workspace, Microsoft 365,
// SES…) via nodemailer when SMTP_HOST is set; else Resend's REST API when
// RESEND_API_KEY is set; else every send is logged instead, so dev, tests and
// an unconfigured prod keep working — the caller gets `sent: false` and can
// show the link another way. EMAIL_FROM is the sender for both.

export interface EmailAttachment {
  filename: string;
  content: Buffer;
  contentType: string;
}

export interface EmailMessage {
  to: string | string[];
  cc?: string[];
  subject: string;
  html: string;
  text: string;
  // Replies go here instead of EMAIL_REPLY_TO (a quote's sender).
  replyTo?: string;
  // Display name on EMAIL_FROM's address ("Pat's Cabinets via Scribe").
  fromName?: string;
  attachments?: EmailAttachment[];
}

// EMAIL_FROM with its display name swapped; the address never changes (the
// provider only sends as the configured address).
export function fromHeader(emailFrom: string, fromName?: string): string {
  if (!fromName) return emailFrom;
  const address = emailFrom.match(/<([^>]+)>/)?.[1] ?? emailFrom.trim();
  return `"${fromName.replace(/["\\<>\r\n]/g, "")}" <${address}>`;
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
    const replyTo = msg.replyTo ?? process.env.EMAIL_REPLY_TO;
    const info = await transport.sendMail({
      from: fromHeader(process.env.EMAIL_FROM!, msg.fromName),
      to: msg.to,
      ...(msg.cc?.length ? { cc: msg.cc } : {}),
      subject: msg.subject,
      html: msg.html,
      text: msg.text,
      ...(replyTo ? { replyTo } : {}),
      ...(msg.attachments?.length ? { attachments: msg.attachments } : {}),
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
      from: fromHeader(from, msg.fromName),
      to: Array.isArray(msg.to) ? msg.to : [msg.to],
      ...(msg.cc?.length ? { cc: msg.cc } : {}),
      subject: msg.subject,
      html: msg.html,
      text: msg.text,
      ...((msg.replyTo ?? process.env.EMAIL_REPLY_TO) ? { reply_to: msg.replyTo ?? process.env.EMAIL_REPLY_TO } : {}),
      ...(msg.attachments?.length
        ? { attachments: msg.attachments.map((a) => ({ filename: a.filename, content: a.content.toString("base64") })) }
        : {}),
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

export { inviteEmail, magicLinkEmail, quoteEmail, receiptEmail } from "./templates.js";
export type { InviteEmailInput, QuoteEmailInput, ReceiptEmailInput } from "./templates.js";
