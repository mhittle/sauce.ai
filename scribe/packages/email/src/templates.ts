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
  const subject = `${input.inviterName} invited you to Scribe`;
  const text = [
    greeting,
    "",
    `${input.inviterName} has invited you to Scribe, the cabinet takeoff tool: upload a plan set, mark the cabinet areas, and get a priced takeoff to review.${credits}`,
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
<p>${escapeHtml(input.inviterName)} has invited you to <strong>Scribe</strong>, the cabinet takeoff tool: upload a plan set, mark the cabinet areas, and get a priced takeoff to review.${escapeHtml(credits)}</p>
<p style="margin:28px 0"><a href="${escapeHtml(input.link)}" style="background:#1a1a1a;color:#fff;text-decoration:none;padding:12px 20px;border-radius:6px;display:inline-block">Create your account</a></p>
<p style="font-size:13px;color:#666">Or paste this link into your browser:<br><a href="${escapeHtml(input.link)}" style="color:#666">${escapeHtml(input.link)}</a></p>
<p style="font-size:13px;color:#666">This link is for ${escapeHtml(input.to)} only and expires in ${days} day${days === 1 ? "" : "s"}.</p>
<p style="font-size:13px;color:#666">— Scribe by sauce.ai</p>
</body></html>`;
  return { to: input.to, subject, html, text };
}
