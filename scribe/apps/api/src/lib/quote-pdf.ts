import { createRequire } from "node:module";
import PDFDocument from "pdfkit";
import { formatUsd } from "@scribe/shared";
import type { OrgSettingsRow } from "./settings.js";

// Server-side quote PDF (PRD §7.1), styled like the web app (owner,
// 2026-10-22): Archivo headings, IBM Plex Sans text, IBM Plex Mono numbers
// and small uppercase labels, navy ink on white, blue-grey rules, the redline
// accent used once. Room-grouped itemized table with per-row heights, a
// totals card, terms, and "page n of m". Money is rendered from cents.

export interface QuotePdfLine {
  tag: string | null;
  room: string | null;
  description: string;
  qty: number;
  unit_cents: number;
  total_cents: number;
}

export interface QuotePdfInput {
  quote_number: string;
  created_at: Date;
  valid_until: Date | null;
  org_name?: string | null;
  quote_name?: string | null;
  customer_company: string | null;
  tier_label: string | null;
  lines: QuotePdfLine[];
  subtotal_cents: number;
  markup_cents: number;
  handling_cents: number;
  freight_cents: number;
  freight_pallets: number;
  total_cents: number;
  max_lead_time_days: number | null;
  settings: OrgSettingsRow;
  logo: Buffer | null;
}

// The web app's light theme (apps/web/src/styles.css).
const C = {
  ink: "#18222e",
  muted: "#5c6876",
  faint: "#8b95a1",
  rule: "#d4dae1",
  ruleSoft: "#e7ebef",
  bg: "#f2f4f6",
  accent: "#e0522b",
};

const require = createRequire(import.meta.url);
const fontFile = (pkg: string, file: string) => require.resolve(`@fontsource/${pkg}/files/${file}`);
const FONTS = {
  display: fontFile("archivo", "archivo-latin-700-normal.woff"),
  displayMedium: fontFile("archivo", "archivo-latin-600-normal.woff"),
  sans: fontFile("ibm-plex-sans", "ibm-plex-sans-latin-400-normal.woff"),
  sansMedium: fontFile("ibm-plex-sans", "ibm-plex-sans-latin-500-normal.woff"),
  sansBold: fontFile("ibm-plex-sans", "ibm-plex-sans-latin-600-normal.woff"),
  // IBM's own Plex Mono build: fontkit can't subset the fontsource one.
  mono: require.resolve("@ibm/plex-mono/fonts/complete/woff/IBMPlexMono-Regular.woff"),
  monoMedium: require.resolve("@ibm/plex-mono/fonts/complete/woff/IBMPlexMono-Medium.woff"),
};

// LETTER content box: 50 → 562 (width 512).
const LEFT = 50;
const RIGHT = 562;
const WIDTH = RIGHT - LEFT;
const PAGE_BOTTOM = 730;

// Columns: Item | Description | Qty | Unit | Total (numbers right-aligned).
const COL = {
  item: { x: LEFT, w: 104 },
  desc: { x: 160, w: 228 },
  qty: { x: 392, w: 36 },
  unit: { x: 432, w: 60 },
  total: { x: 496, w: 66 },
};

const day = (d: Date) => d.toISOString().slice(0, 10);

export function renderQuotePdf(input: QuotePdfInput): Promise<Buffer> {
  return new Promise((resolve, reject) => {
    const doc = new PDFDocument({ size: "LETTER", margin: 50, bufferPages: true });
    const chunks: Buffer[] = [];
    doc.on("data", (c: Buffer) => chunks.push(c));
    doc.on("end", () => resolve(Buffer.concat(chunks)));
    doc.on("error", reject);
    for (const [name, path] of Object.entries(FONTS)) doc.registerFont(name, path);

    // Small uppercase mono label, the web's "font-mono text-[11px] uppercase".
    const label = (text: string, x: number, y: number, opts: PDFKit.Mixins.TextOptions = {}) =>
      doc.font("monoMedium").fontSize(6.5).fillColor(C.muted).text(text.toUpperCase(), x, y, { characterSpacing: 0.8, ...opts });

    // ── Header ───────────────────────────────────────────────────────────────
    let leftBottom = 50;
    let drewLogo = false;
    if (input.logo) {
      try {
        doc.image(input.logo, LEFT, 46, { fit: [170, 52] });
        leftBottom = 102;
        drewLogo = true;
      } catch {
        // non-PNG/JPEG logo — fall back to the company name
      }
    }
    if (!drewLogo && input.org_name) {
      doc.font("display").fontSize(16).fillColor(C.ink).text(input.org_name, LEFT, 50, { width: 260 });
      leftBottom = doc.y + 2;
    }

    // Right: eyebrow + quote number, like the app's page title.
    label("Quote", 330, 50, { width: RIGHT - 330, align: "right" });
    doc.font("display").fontSize(20).fillColor(C.ink).text(`#${input.quote_number}`, 330, 60, { width: RIGHT - 330, align: "right" });

    // Meta row: label over value, mono.
    const meta: [string, string][] = [["Date", day(input.created_at)]];
    if (input.valid_until) meta.push(["Valid until", day(input.valid_until)]);
    if (input.max_lead_time_days != null) meta.push(["Lead time", `up to ${input.max_lead_time_days} days`]);
    const metaW = 92;
    meta.forEach(([k, v], i) => {
      const x = RIGHT - (meta.length - i) * metaW;
      label(k, x, 90, { width: metaW - 6, align: "right" });
      doc.font("mono").fontSize(8.5).fillColor(C.ink).text(v, x, 99, { width: metaW - 6, align: "right" });
    });

    let y = Math.max(leftBottom, 116) + 8;
    // Prepared for / job / tier — a quiet card.
    const facts: [string, string][] = [];
    if (input.customer_company) facts.push(["Prepared for", input.customer_company]);
    if (input.quote_name) facts.push(["Job", input.quote_name]);
    if (input.tier_label) facts.push(["Price level", input.tier_label]);
    if (facts.length > 0) {
      const cardH = 34;
      doc.roundedRect(LEFT, y, WIDTH, cardH, 4).fillAndStroke(C.bg, C.rule);
      const cw = WIDTH / facts.length;
      facts.forEach(([k, v], i) => {
        const x = LEFT + 12 + i * cw;
        label(k, x, y + 7, { width: cw - 20 });
        doc.font("sansMedium").fontSize(9.5).fillColor(C.ink).text(v, x, y + 17, { width: cw - 20, height: 12, ellipsis: true });
      });
      y += cardH + 14;
    }
    // The one accent mark: a short redline rule over the table.
    doc.rect(LEFT, y, 28, 2).fill(C.accent);
    doc.y = y + 10;

    // ── Table header (repeats on each page) ──────────────────────────────────
    const drawTableHeader = () => {
      const hy = doc.y;
      label("Item", COL.item.x, hy, { width: COL.item.w });
      label("Description", COL.desc.x, hy, { width: COL.desc.w });
      label("Qty", COL.qty.x, hy, { width: COL.qty.w, align: "right" });
      label("Unit", COL.unit.x, hy, { width: COL.unit.w, align: "right" });
      label("Total", COL.total.x, hy, { width: COL.total.w, align: "right" });
      doc.moveTo(LEFT, hy + 12).lineTo(RIGHT, hy + 12).lineWidth(0.75).strokeColor(C.rule).stroke();
      doc.y = hy + 18;
    };
    drawTableHeader();

    const ensureSpace = (rowH: number) => {
      if (doc.y + rowH > PAGE_BOTTOM) {
        doc.addPage();
        doc.y = 50;
        drawTableHeader();
      }
    };

    // ── Rows (room-grouped, per-row height, soft dividers) ───────────────────
    let currentRoom: string | null | undefined = undefined;
    for (const line of input.lines) {
      const room = line.room ?? "Other";
      if (room !== currentRoom) {
        // Room heading plus at least one row, so a heading never ends a page.
        ensureSpace(50);
        const ry = doc.y + (currentRoom === undefined ? 0 : 6);
        doc.font("displayMedium").fontSize(9.5).fillColor(C.ink).text(room, COL.item.x, ry);
        doc.y = ry + 16;
        currentRoom = room;
      }
      doc.font("sans").fontSize(8.5);
      const itemH = doc.heightOfString(line.tag ?? "—", { width: COL.item.w - 6 });
      const descH = doc.heightOfString(line.description, { width: COL.desc.w });
      const rowH = Math.max(itemH, descH, 10) + 8;
      ensureSpace(rowH);
      const ry = doc.y;
      doc.font("sansMedium").fontSize(8.5).fillColor(C.ink).text(line.tag ?? "—", COL.item.x, ry + 3, { width: COL.item.w - 6 });
      doc.font("sans").fontSize(8.5).fillColor(C.muted).text(line.description, COL.desc.x, ry + 3, { width: COL.desc.w });
      doc.font("mono").fontSize(8.5).fillColor(C.ink);
      doc.text(String(line.qty), COL.qty.x, ry + 3, { width: COL.qty.w, align: "right" });
      doc.text(formatUsd(line.unit_cents), COL.unit.x, ry + 3, { width: COL.unit.w, align: "right" });
      doc.font("monoMedium").text(formatUsd(line.total_cents), COL.total.x, ry + 3, { width: COL.total.w, align: "right" });
      doc.moveTo(LEFT, ry + rowH).lineTo(RIGHT, ry + rowH).lineWidth(0.5).strokeColor(C.ruleSoft).stroke();
      doc.y = ry + rowH;
    }

    // ── Totals card (right) ──────────────────────────────────────────────────
    const rows: [string, number][] = [["Subtotal", input.subtotal_cents]];
    if (input.markup_cents !== 0) rows.push(["Adjustment", input.markup_cents]);
    if (input.handling_cents !== 0) rows.push(["Handling", input.handling_cents]);
    rows.push([`Freight (${input.freight_pallets} pallet${input.freight_pallets === 1 ? "" : "s"})`, input.freight_cents]);
    const cardH = 16 + rows.length * 14 + 34;
    ensureSpace(cardH + 20);
    const boxX = 336;
    const boxW = RIGHT - boxX;
    let ty = doc.y + 14;
    doc.roundedRect(boxX, ty, boxW, cardH, 4).lineWidth(0.75).strokeColor(C.rule).stroke();
    let ry = ty + 10;
    for (const [k, v] of rows) {
      doc.font("sans").fontSize(8.5).fillColor(C.muted).text(k, boxX + 12, ry, { width: boxW - 100 });
      doc.font("mono").fontSize(8.5).fillColor(C.ink).text(formatUsd(v), RIGHT - 92, ry, { width: 80, align: "right" });
      ry += 14;
    }
    doc.moveTo(boxX + 12, ry + 2).lineTo(RIGHT - 12, ry + 2).lineWidth(0.5).strokeColor(C.rule).stroke();
    label("Total", boxX + 12, ry + 12);
    doc.font("monoMedium").fontSize(14).fillColor(C.ink).text(formatUsd(input.total_cents), RIGHT - 152, ry + 8, { width: 140, align: "right" });
    doc.y = ty + cardH;

    // ── Terms + footer ───────────────────────────────────────────────────────
    doc.y += 22;
    if (doc.y > PAGE_BOTTOM - 70) {
      doc.addPage();
      doc.y = 50;
    }
    label("Terms", LEFT, doc.y);
    doc.font("sans").fontSize(8).fillColor(C.muted).text(input.settings.quoteTermsMd, LEFT, doc.y + 4, { width: WIDTH, lineGap: 1.5 });
    if (input.settings.quoteFooterMd) {
      doc.moveDown(0.8);
      doc.font("sans").fontSize(7.5).fillColor(C.faint).text(input.settings.quoteFooterMd, LEFT, doc.y, { width: WIDTH });
    }

    // ── Page footer on every page ────────────────────────────────────────────
    const range = doc.bufferedPageRange();
    for (let i = range.start; i < range.start + range.count; i++) {
      doc.switchToPage(i);
      // The footer sits in the bottom margin; without this pdfkit would page.
      doc.page.margins.bottom = 0;
      doc.moveTo(LEFT, 752).lineTo(RIGHT, 752).lineWidth(0.5).strokeColor(C.ruleSoft).stroke();
      doc.font("mono").fontSize(6.5).fillColor(C.faint);
      doc.text(`QUOTE #${input.quote_number}`, LEFT, 757, { width: WIDTH / 2, lineBreak: false, characterSpacing: 0.6 });
      doc.text(`PAGE ${i - range.start + 1} OF ${range.count}`, LEFT + WIDTH / 2, 757, {
        width: WIDTH / 2,
        align: "right",
        lineBreak: false,
        characterSpacing: 0.6,
      });
    }

    doc.end();
  });
}
