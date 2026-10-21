// Bulk invites from a CSV (Admin › Users › Import CSV). Pure, so the web's
// preview and the API's validation read a file the same way.

export const INVITE_CSV_COLUMNS = ["email", "name", "company", "pages_included", "note"] as const;

// The downloadable template: the header plus one example row.
export const INVITE_CSV_TEMPLATE =
  "email,name,company,pages_included,note\r\n" +
  "pat@example.com,Pat Smith,Pat's Cabinets,0,met at KBIS\r\n";

export interface InviteCsvRow {
  line: number;
  email: string;
  name: string | null;
  company: string | null;
  pagesIncluded: number;
  note: string | null;
}

export interface InviteCsvResult {
  rows: InviteCsvRow[];
  errors: { line: number; message: string }[];
}

const EMAIL_RE = /^[^\s@,;]+@[^\s@,;]+\.[^\s@,;]+$/;

// RFC-4180-ish: quoted fields, doubled quotes, commas/newlines inside quotes,
// CRLF or LF, a leading BOM.
export function parseCsv(text: string): string[][] {
  const src = text.replace(/^﻿/, "");
  const out: string[][] = [];
  let row: string[] = [];
  let field = "";
  let quoted = false;
  for (let i = 0; i < src.length; i++) {
    const ch = src[i];
    if (quoted) {
      if (ch === '"') {
        if (src[i + 1] === '"') {
          field += '"';
          i++;
        } else quoted = false;
      } else field += ch;
    } else if (ch === '"') quoted = true;
    else if (ch === ",") {
      row.push(field);
      field = "";
    } else if (ch === "\n" || ch === "\r") {
      if (ch === "\r" && src[i + 1] === "\n") i++;
      row.push(field);
      out.push(row);
      row = [];
      field = "";
    } else field += ch;
  }
  if (field !== "" || row.length > 0) {
    row.push(field);
    out.push(row);
  }
  return out.filter((r) => r.some((c) => c.trim() !== ""));
}

const norm = (h: string) => h.trim().toLowerCase().replace(/[\s-]+/g, "_");

export function parseInviteCsv(text: string, maxRows = 500): InviteCsvResult {
  const table = parseCsv(text);
  const errors: InviteCsvResult["errors"] = [];
  if (table.length === 0) return { rows: [], errors: [{ line: 1, message: "the file is empty" }] };
  const header = table[0].map(norm);
  const col = (name: string, ...alts: string[]) =>
    [name, ...alts].map((n) => header.indexOf(n)).find((i) => i >= 0) ?? -1;
  const iEmail = col("email", "email_address", "e_mail");
  if (iEmail < 0) {
    return { rows: [], errors: [{ line: 1, message: 'the first row must be the header, with an "email" column' }] };
  }
  const iName = col("name", "full_name");
  const iCompany = col("company", "company_name", "org", "organization");
  const iPages = col("pages_included", "pages", "credits");
  const iNote = col("note", "notes");
  const cell = (r: string[], i: number) => (i >= 0 ? (r[i] ?? "").trim() : "");

  const rows: InviteCsvRow[] = [];
  const seen = new Set<string>();
  table.slice(1).forEach((r, k) => {
    const line = k + 2;
    const email = cell(r, iEmail).toLowerCase();
    if (!EMAIL_RE.test(email)) {
      errors.push({ line, message: email ? `"${email}" is not an email address` : "no email" });
      return;
    }
    if (seen.has(email)) {
      errors.push({ line, message: `${email} is already in this file` });
      return;
    }
    const pagesRaw = cell(r, iPages);
    const pages = pagesRaw === "" ? 0 : Number(pagesRaw);
    if (!Number.isInteger(pages) || pages < 0 || pages > 10_000) {
      errors.push({ line, message: `pages_included "${pagesRaw}" must be a whole number from 0 to 10000` });
      return;
    }
    if (rows.length >= maxRows) {
      errors.push({ line, message: `only ${maxRows} invites per file` });
      return;
    }
    seen.add(email);
    rows.push({
      line,
      email,
      name: cell(r, iName).slice(0, 120) || null,
      company: cell(r, iCompany).slice(0, 120) || null,
      pagesIncluded: pages,
      note: cell(r, iNote).slice(0, 500) || null,
    });
  });
  return { rows, errors };
}
