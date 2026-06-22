import PDFDocument from "pdfkit";
import { formatUsd } from "@scribe/shared";
import type { OrgSettingsRow } from "./settings.js";

// Server-side branded quote PDF (PRD §7.1). A clean, customer-facing layout:
// logo/title band, quote meta, room-grouped itemized table with per-row
// heights (no overlap), and a totals box. Money is rendered from cents.

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

// Brand palette (CabinetNow maroon) + neutrals.
const BRAND = "#7a1f1f";
const INK = "#1f1f1f";
const MUTED = "#6b6b6b";
const RULE = "#d9d4d2";
const ZEBRA = "#f6f4f3";

// LETTER content box: 50 → 562 (width 512).
const LEFT = 50;
const RIGHT = 562;
const PAGE_BOTTOM = 740;

// Columns: Item | Description | Qty | Unit | Total (numeric cols right-aligned).
const COL = {
  item: { x: 50, w: 92 },
  desc: { x: 148, w: 268 },
  qty: { x: 420, w: 34, align: "right" as const },
  unit: { x: 458, w: 50, align: "right" as const },
  total: { x: 512, w: 50, align: "right" as const },
};

export function renderQuotePdf(input: QuotePdfInput): Promise<Buffer> {
  return new Promise((resolve, reject) => {
    const doc = new PDFDocument({ size: "LETTER", margin: 50 });
    const chunks: Buffer[] = [];
    doc.on("data", (c: Buffer) => chunks.push(c));
    doc.on("end", () => resolve(Buffer.concat(chunks)));
    doc.on("error", reject);

    // ── Header band ──────────────────────────────────────────────────────────
    let headerBottom = 50;
    if (input.logo) {
      try {
        doc.image(input.logo, LEFT, 42, { fit: [170, 56] });
        headerBottom = 104;
      } catch {
        // non-PNG/JPEG logo — fall through to text title
      }
    }
    // Right-aligned "QUOTE" + meta block.
    doc.font("Helvetica-Bold").fontSize(22).fillColor(BRAND).text("QUOTE", LEFT, 46, {
      width: RIGHT - LEFT,
      align: "right",
    });
    doc.font("Helvetica").fontSize(9).fillColor(MUTED);
    const meta: string[] = [
      `Quote #: ${input.quote_number}`,
      `Date: ${input.created_at.toISOString().slice(0, 10)}`,
    ];
    if (input.valid_until) meta.push(`Valid until: ${input.valid_until.toISOString().slice(0, 10)}`);
    if (input.max_lead_time_days != null) meta.push(`Lead time: up to ${input.max_lead_time_days} days`);
    doc.text(meta.join("    "), LEFT, 74, { width: RIGHT - LEFT, align: "right" });

    let y = Math.max(headerBottom, 92);
    // "Prepared for" + tier badge line.
    doc.font("Helvetica").fontSize(10).fillColor(INK);
    if (input.customer_company) {
      doc.text(`Prepared for: ${input.customer_company}`, LEFT, y);
      y = doc.y + 2;
    }
    if (input.tier_label) {
      doc.font("Helvetica-Bold").fontSize(10).fillColor(BRAND).text(`${input.tier_label} estimate`, LEFT, y);
      y = doc.y + 4;
    }

    // Divider under header.
    doc.moveTo(LEFT, y + 4).lineTo(RIGHT, y + 4).lineWidth(1.5).strokeColor(BRAND).stroke();
    doc.y = y + 12;

    // ── Table header (repeats on each page) ───────────────────────────────────
    const drawTableHeader = () => {
      const hy = doc.y;
      doc.rect(LEFT, hy, RIGHT - LEFT, 18).fill(BRAND);
      doc.font("Helvetica-Bold").fontSize(9).fillColor("#ffffff");
      doc.text("Item", COL.item.x + 4, hy + 5, { width: COL.item.w });
      doc.text("Description", COL.desc.x, hy + 5, { width: COL.desc.w });
      doc.text("Qty", COL.qty.x, hy + 5, { width: COL.qty.w, align: COL.qty.align });
      doc.text("Unit", COL.unit.x, hy + 5, { width: COL.unit.w, align: COL.unit.align });
      doc.text("Total", COL.total.x, hy + 5, { width: COL.total.w, align: COL.total.align });
      doc.y = hy + 22;
    };
    drawTableHeader();

    // ── Itemized rows (room-grouped, per-row height, zebra striping) ──────────
    let zebra = false;
    let currentRoom: string | null | undefined = undefined;

    const ensureSpace = (rowH: number) => {
      if (doc.y + rowH > PAGE_BOTTOM) {
        doc.addPage();
        drawTableHeader();
        zebra = false;
      }
    };

    for (const line of input.lines) {
      // Room subheader when the room changes.
      const room = line.room ?? "Other";
      if (room !== currentRoom) {
        ensureSpace(20);
        const ry = doc.y;
        doc.font("Helvetica-Bold").fontSize(9.5).fillColor(BRAND).text(room, COL.item.x, ry + 4);
        doc.y = ry + 18;
        currentRoom = room;
        zebra = false;
      }

      doc.font("Helvetica").fontSize(9).fillColor(INK);
      const itemH = doc.heightOfString(line.tag ?? "—", { width: COL.item.w - 4 });
      const descH = doc.heightOfString(line.description, { width: COL.desc.w });
      const rowH = Math.max(itemH, descH, 11) + 7;
      ensureSpace(rowH);

      const ry = doc.y;
      if (zebra) doc.rect(LEFT, ry - 1, RIGHT - LEFT, rowH).fill(ZEBRA);
      doc.fillColor(INK).font("Helvetica").fontSize(9);
      doc.text(line.tag ?? "—", COL.item.x + 4, ry + 2, { width: COL.item.w - 4 });
      doc.text(line.description, COL.desc.x, ry + 2, { width: COL.desc.w });
      doc.text(String(line.qty), COL.qty.x, ry + 2, { width: COL.qty.w, align: COL.qty.align });
      doc.text(formatUsd(line.unit_cents), COL.unit.x, ry + 2, { width: COL.unit.w, align: COL.unit.align });
      doc.fillColor(INK).text(formatUsd(line.total_cents), COL.total.x, ry + 2, {
        width: COL.total.w,
        align: COL.total.align,
      });
      doc.y = ry + rowH;
      zebra = !zebra;
    }

    // ── Totals box (right-aligned) ────────────────────────────────────────────
    ensureSpace(120);
    doc.moveDown(0.5);
    const boxX = 332;
    const boxW = RIGHT - boxX;
    let ty = doc.y + 4;
    doc.moveTo(boxX, ty).lineTo(RIGHT, ty).lineWidth(1).strokeColor(RULE).stroke();
    ty += 6;

    const totalsRow = (label: string, cents: number, opts: { bold?: boolean; brand?: boolean } = {}) => {
      doc.font(opts.bold ? "Helvetica-Bold" : "Helvetica").fontSize(opts.bold ? 11 : 9.5);
      doc.fillColor(opts.brand ? BRAND : opts.bold ? INK : MUTED);
      doc.text(label, boxX, ty, { width: boxW - 70 });
      doc.fillColor(opts.brand ? BRAND : INK).text(formatUsd(cents), RIGHT - 70, ty, {
        width: 70,
        align: "right",
      });
      ty += opts.bold ? 18 : 14;
    };

    totalsRow("Subtotal", input.subtotal_cents);
    if (input.markup_cents !== 0) totalsRow("Adjustment", input.markup_cents);
    if (input.handling_cents !== 0) totalsRow("Handling", input.handling_cents);
    totalsRow(
      `Freight (${input.freight_pallets} pallet${input.freight_pallets === 1 ? "" : "s"})`,
      input.freight_cents
    );
    doc.moveTo(boxX, ty + 1).lineTo(RIGHT, ty + 1).lineWidth(1).strokeColor(RULE).stroke();
    ty += 8;
    totalsRow("Total", input.total_cents, { bold: true, brand: true });

    // ── Terms + footer ────────────────────────────────────────────────────────
    doc.y = Math.max(doc.y, ty) + 18;
    if (doc.y > PAGE_BOTTOM - 60) doc.addPage();
    doc.font("Helvetica-Bold").fontSize(8.5).fillColor(INK).text("Terms", LEFT, doc.y);
    doc.font("Helvetica").fontSize(8).fillColor(MUTED).text(input.settings.quoteTermsMd, LEFT, doc.y + 2, {
      width: RIGHT - LEFT,
    });
    if (input.settings.quoteFooterMd) {
      doc.moveDown(0.8);
      doc.fillColor("#999").fontSize(7.5).text(input.settings.quoteFooterMd, LEFT, doc.y, {
        width: RIGHT - LEFT,
      });
    }

    doc.end();
  });
}
