import { describe, expect, it } from "vitest";
import { INVITE_CSV_TEMPLATE, parseCsv, parseInviteCsv } from "../src/invite-csv.js";

describe("parseCsv", () => {
  it("handles quotes, commas and newlines inside quotes, CRLF and a BOM", () => {
    expect(parseCsv('﻿a,b\r\n"x, y","say ""hi"""\n"two\nlines",z\n')).toEqual([
      ["a", "b"],
      ["x, y", 'say "hi"'],
      ["two\nlines", "z"],
    ]);
  });
});

describe("parseInviteCsv", () => {
  it("reads the downloadable template as one valid invite", () => {
    const r = parseInviteCsv(INVITE_CSV_TEMPLATE);
    expect(r.errors).toEqual([]);
    expect(r.rows).toEqual([
      { line: 2, email: "pat@example.com", name: "Pat Smith", company: "Pat's Cabinets", pagesIncluded: 0, note: "met at KBIS" },
    ]);
  });

  it("accepts header variants and a bare email column", () => {
    const r = parseInviteCsv("Email Address,Full Name\nA@B.co,Ann\nc@d.io,\n");
    expect(r.rows.map((x) => [x.email, x.name, x.pagesIncluded])).toEqual([["a@b.co", "Ann", 0], ["c@d.io", null, 0]]);
  });

  it("reports bad rows by line and keeps the good ones", () => {
    const r = parseInviteCsv("email,pages_included\nnot-an-email,1\nx@y.co,2.5\nok@y.co,3\nok@y.co,1\n,\n");
    expect(r.rows.map((x) => x.email)).toEqual(["ok@y.co"]);
    expect(r.errors.map((e) => e.line)).toEqual([2, 3, 5]);
  });

  it("refuses a file without an email header", () => {
    expect(parseInviteCsv("name\nAnn\n").errors[0].message).toMatch(/email/);
  });
});
