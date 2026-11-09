import { describe, expect, it } from "vitest";
import { parseExternalLink } from "../src/lib/external.js";

describe("parseExternalLink", () => {
  const svc = { isService: true, production: true };
  it("accepts the full triple from the service user", () => {
    expect(
      parseExternalLink(
        { external_source: "cabinethub", external_ref: "abc", callback_url: "https://api.example.com/webhooks/scribe" },
        svc
      )
    ).toEqual({
      externalSource: "cabinethub",
      externalRef: "abc",
      callbackUrl: "https://api.example.com/webhooks/scribe",
    });
  });
  it("is all-null for an in-app upload", () => {
    expect(parseExternalLink(undefined, { isService: false, production: false })).toEqual({
      externalSource: null, externalRef: null, callbackUrl: null,
    });
  });
  it("refuses a callback from a signed-in (non-service) user", () => {
    const r = parseExternalLink(
      { external_source: "x", external_ref: "y", callback_url: "https://evil.example/" },
      { isService: false, production: true }
    );
    expect(r).toEqual({ error: "callback_url requires service auth" });
  });
  it("refuses http in production, allows it in dev", () => {
    const q = { external_source: "x", external_ref: "y", callback_url: "http://localhost:3011/webhooks/scribe" };
    expect(parseExternalLink(q, svc)).toEqual({ error: "callback_url must be https" });
    expect(parseExternalLink(q, { isService: true, production: false })).toMatchObject({ callbackUrl: q.callback_url });
  });
  it("refuses a callback without source + ref, and a bad source slug", () => {
    expect(parseExternalLink({ callback_url: "https://a.b/c" }, svc)).toHaveProperty("error");
    expect(parseExternalLink({ external_source: "Cabinet Hub", external_ref: "y" }, svc)).toHaveProperty("error");
  });
});
