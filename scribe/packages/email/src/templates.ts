export interface InviteEmailInput {
  to: string;
  name: string | null;
  inviterName: string;
  link: string;
  expiresAt: Date;
  creditsGranted: number;
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// Invitation wording — placeholder while the owner writes the real copy
// (2026-10-21). Edit these two lines; the link, expiry and sign-off stay.
export const INVITE_SUBJECT = "Test invitation to Scribe";
export const INVITE_INTRO = "This is a test invitation to Scribe.";

export function inviteEmail(input: InviteEmailInput): {
  to: string;
  subject: string;
  html: string;
  text: string;
} {
  const greeting = input.name ? `Hi ${input.name},` : "Hi,";
  const days = Math.max(
    1,
    Math.round((input.expiresAt.getTime() - Date.now()) / 86_400_000)
  );
  const credits =
    input.creditsGranted > 0
      ? ` Your account starts with ${input.creditsGranted} pages of reading included.`
      : "";
  const subject = INVITE_SUBJECT;
  const text = [
    greeting,
    "",
    `${INVITE_INTRO}${credits}`,
    "",
    "Create your account here:",
    input.link,
    "",
    `This link is for ${input.to} only and expires in ${days} day${days === 1 ? "" : "s"}.`,
    "",
    "— Scribe by sauce.ai",
  ].join("\n");
  const html = `<!doctype html><html><body style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;color:#1a1a1a;line-height:1.5;max-width:520px;margin:0 auto;padding:24px">
<p>${escapeHtml(greeting)}</p>
<p>${escapeHtml(INVITE_INTRO)}${escapeHtml(credits)}</p>
<p style="margin:28px 0"><a href="${escapeHtml(input.link)}" style="background:#1a1a1a;color:#fff;text-decoration:none;padding:12px 20px;border-radius:6px;display:inline-block">Create your account</a></p>
<p style="font-size:13px;color:#666">Or paste this link into your browser:<br><a href="${escapeHtml(input.link)}" style="color:#666">${escapeHtml(input.link)}</a></p>
<p style="font-size:13px;color:#666">This link is for ${escapeHtml(input.to)} only and expires in ${days} day${days === 1 ? "" : "s"}.</p>
<p style="font-size:13px;color:#666">— Scribe by sauce.ai</p>
</body></html>`;
  return { to: input.to, subject, html, text };
}

export function magicLinkEmail(input: { to: string; name: string | null; link: string }): {
  to: string;
  subject: string;
  html: string;
  text: string;
} {
  const greeting = input.name ? `Hi ${input.name},` : "Hi,";
  const subject = "Your Scribe sign-in link";
  const text = [
    greeting,
    "",
    "Click to sign in to Scribe:",
    input.link,
    "",
    "The link works once and expires in 15 minutes. If you didn't ask for it, ignore this email.",
    "",
    "— Scribe by sauce.ai",
  ].join("\n");
  const html = `<!doctype html><html><body style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;color:#1a1a1a;line-height:1.5;max-width:520px;margin:0 auto;padding:24px">
<p>${escapeHtml(greeting)}</p>
<p style="margin:28px 0"><a href="${escapeHtml(input.link)}" style="background:#1a1a1a;color:#fff;text-decoration:none;padding:12px 20px;border-radius:6px;display:inline-block">Sign in to Scribe</a></p>
<p style="font-size:13px;color:#666">Or paste this link into your browser:<br><a href="${escapeHtml(input.link)}" style="color:#666">${escapeHtml(input.link)}</a></p>
<p style="font-size:13px;color:#666">The link works once and expires in 15 minutes. If you didn't ask for it, ignore this email.</p>
<p style="font-size:13px;color:#666">— Scribe by sauce.ai</p>
</body></html>`;
  return { to: input.to, subject, html, text };
}

export interface ReceiptEmailInput {
  to: string;
  name: string | null;
  pages: number;
  amountCents: number;
  balance: number;
  accountLink: string;
}

// Receipt for a page-pack purchase (Stripe's own receipts stay off so all
// mail comes from one sender).
export function receiptEmail(input: ReceiptEmailInput): {
  to: string;
  subject: string;
  html: string;
  text: string;
} {
  const greeting = input.name ? `Hi ${input.name},` : "Hi,";
  const amount = `$${(input.amountCents / 100).toFixed(2)}`;
  const subject = `Your Scribe receipt — ${input.pages} pages`;
  const lines = [
    greeting,
    "",
    `Thanks for your purchase. ${input.pages} pages have been added to your Scribe account.`,
    "",
    `Paid: ${amount}`,
    `Pages added: ${input.pages}`,
    `Balance now: ${input.balance} pages`,
    "",
    `Your account and page history: ${input.accountLink}`,
  ];
  const html = `<p>${escapeHtml(greeting)}</p>
<p>Thanks for your purchase. ${input.pages} pages have been added to your Scribe account.</p>
<table cellpadding="4">
<tr><td>Paid</td><td><strong>${amount}</strong></td></tr>
<tr><td>Pages added</td><td>${input.pages}</td></tr>
<tr><td>Balance now</td><td>${input.balance} pages</td></tr>
</table>
<p><a href="${escapeHtml(input.accountLink)}">Your account and page history</a></p>`;
  return { to: input.to, subject, html, text: lines.join("\n") };
}

export interface QuoteEmailInput {
  to: string[];
  subject: string;
  message: string;
  senderName: string;
  orgName: string;
}

// A quote sent to a customer: the sender's own message, the PDF attached.
// Plain on purpose — it should read like the estimator's email, not ours.
export function quoteEmail(input: QuoteEmailInput): {
  to: string[];
  subject: string;
  html: string;
  text: string;
} {
  const text = `${input.message.trim()}\n\n— ${input.senderName}, ${input.orgName}\n(The quote is attached as a PDF.)`;
  const paragraphs = input.message
    .trim()
    .split(/\n{2,}/)
    .map((p) => `<p>${escapeHtml(p).replace(/\n/g, "<br>")}</p>`)
    .join("\n");
  const html = `<!doctype html><html><body style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;color:#18222e;line-height:1.5;max-width:560px;margin:0 auto;padding:24px">
${paragraphs}
<p style="color:#5c6876">— ${escapeHtml(input.senderName)}, ${escapeHtml(input.orgName)}</p>
<p style="font-size:13px;color:#8b95a1">The quote is attached as a PDF.</p>
</body></html>`;
  return { to: input.to, subject: input.subject, html, text };
}
