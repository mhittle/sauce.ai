import { describe, expect, it } from "vitest";
import { inviteEmail } from "./templates.js";

describe("inviteEmail", () => {
  const base = {
    to: "pat@example.com",
    name: "Pat <Shop>",
    inviterName: "Mike",
    link: "https://app.example.com/signup?token=abc",
    expiresAt: new Date(Date.now() + 14 * 86_400_000),
    creditsGranted: 20,
  };

  it("names the inviter, carries the link, escapes html", () => {
    const m = inviteEmail(base);
    expect(m.subject).toBe("Mike invited you to Scribe");
    expect(m.text).toContain(base.link);
    expect(m.html).toContain(`href="${base.link}"`);
    expect(m.html).toContain("Pat &lt;Shop&gt;");
    expect(m.html).not.toContain("Pat <Shop>");
    expect(m.text).toContain("14 days");
    expect(m.text).toContain("20 pages");
  });

  it("omits the credits line at zero and greets without a name", () => {
    const m = inviteEmail({ ...base, name: null, creditsGranted: 0 });
    expect(m.text.startsWith("Hi,\n")).toBe(true);
    expect(m.text).not.toContain("pages of reading");
  });
});
