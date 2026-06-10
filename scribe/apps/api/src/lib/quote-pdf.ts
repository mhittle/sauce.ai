import PDFDocument from "pdfkit";
import { formatUsd } from "@scribe/shared";
import type { OrgSettingsRow } from "./settings.js";

// Server-side branded quote PDF (PRD §7.1). Logo + terms/footer come from
// org_settings; money is rendered from cents.

export interface QuotePdfLine {
  tag: string | null;
  room: string | null;
  description: string;
  qty: number;
  unit_cents: number;
  total_cents: number;
  lead_time_days: number;
}

export interface QuotePdfInput {
  quote_number: string;
  created_at: Date;
  valid_until: Date | null;
  customer_company: string | null;
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

export function renderQuotePdf(input: QuotePdfInput): Promise<Buffer> {
  return new Promise((resolve, reject) => {
    const doc = new PDFDocument({ size: "LETTER", margin: 50 });
    const chunks: Buffer[] = [];
    doc.on("data", (c: Buffer) => chunks.push(c));
    doc.on("end", () => resolve(Buffer.concat(chunks)));
    doc.on("error", reject);

    if (input.logo) {
      try {
        doc.image(input.logo, 50, 40, { fit: [160, 60] });
        doc.moveDown(2);
      } catch {
        // non-PNG/JPEG logo — skip silently
      }
    }

    doc.fontSize(20).text("Quote", 50, input.logo ? 120 : 50);
    doc.fontSize(10).fillColor("#444");
    doc.text(`Quote #: ${input.quote_number}`);
    doc.text(`Date: ${input.created_at.toISOString().slice(0, 10)}`);
    if (input.valid_until) {
      doc.text(`Valid until: ${input.valid_until.toISOString().slice(0, 10)}`);
    }
    if (input.customer_company) doc.text(`Prepared for: ${input.customer_company}`);
    if (input.max_lead_time_days != null) {
      doc
        .fillColor("#000")
        .fontSize(11)
        .text(`Lead time: up to ${input.max_lead_time_days} days`, {
          underline: true,
        });
    }
    doc.moveDown();

    // Table header
    const cols = { tag: 50, desc: 120, qty: 360, unit: 410, total: 490 };
    doc.fontSize(9).fillColor("#000").font("Helvetica-Bold");
    const headerY = doc.y;
    doc.text("Tag", cols.tag, headerY);
    doc.text("Description", cols.desc, headerY);
    doc.text("Qty", cols.qty, headerY);
    doc.text("Unit", cols.unit, headerY);
    doc.text("Total", cols.total, headerY);
    doc
      .moveTo(50, doc.y + 2)
      .lineTo(562, doc.y + 2)
      .stroke("#999");
    doc.font("Helvetica").moveDown(0.5);

    for (const line of input.lines) {
      if (doc.y > 680) doc.addPage();
      const y = doc.y;
      doc.text(line.tag ?? "—", cols.tag, y, { width: 65 });
      doc.text(
        `${line.description}${line.room ? ` (${line.room})` : ""} — ${line.lead_time_days}d lead`,
        cols.desc,
        y,
        { width: 230 }
      );
      doc.text(String(line.qty), cols.qty, y);
      doc.text(formatUsd(line.unit_cents), cols.unit, y);
      doc.text(formatUsd(line.total_cents), cols.total, y);
      doc.moveDown(0.4);
    }

    doc.moveDown();
    doc
      .moveTo(360, doc.y)
      .lineTo(562, doc.y)
      .stroke("#999");
    doc.moveDown(0.3);

    const totalsRow = (label: string, cents: number, bold = false) => {
      const y = doc.y;
      doc.font(bold ? "Helvetica-Bold" : "Helvetica");
      doc.text(label, 360, y);
      doc.text(formatUsd(cents), cols.total, y);
      doc.moveDown(0.3);
    };
    totalsRow("Subtotal", input.subtotal_cents);
    if (input.markup_cents !== 0) totalsRow("Adjustment", input.markup_cents);
    totalsRow("Handling", input.handling_cents);
    totalsRow(
      `Freight (${input.freight_pallets} pallet${input.freight_pallets === 1 ? "" : "s"})`,
      input.freight_cents
    );
    totalsRow("Total", input.total_cents, true);

    doc.moveDown(2);
    doc.font("Helvetica").fontSize(8).fillColor("#333");
    doc.text("Terms", 50, doc.y, { underline: true });
    doc.text(input.settings.quoteTermsMd, { width: 500 });
    doc.moveDown();
    doc.fillColor("#666").text(input.settings.quoteFooterMd, { width: 500 });

    doc.end();
  });
}
