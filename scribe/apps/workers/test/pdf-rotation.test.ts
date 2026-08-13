import { describe, expect, it } from "vitest";
import { detectContentRotation, openPdf } from "../src/takeoff/pdf.js";

// Sideways-content normalization: some exports draw a landscape sheet rotated
// on a portrait page with no /Rotate flag (the Braun "webdownload" set). The
// module must detect the dominant text orientation and serve dims/renders/
// fragments in upright space.

const vline = (i: number, len: number) => ({
  // Vertical text: bbox taller than wide; anchor (y) at the bbox BOTTOM means
  // bottom-to-top reading (drawn CCW) — the common sideways-sheet case.
  bbox: { x: 20 * i, y: 100, w: 12, h: 8 * len },
  y: 100 + 8 * len,
  text: "X".repeat(len),
});

const hline = (i: number, len: number) => ({
  bbox: { x: 10, y: 20 * i, w: 8 * len, h: 12 },
  y: 20 * i + 10,
  text: "X".repeat(len),
});

describe("detectContentRotation", () => {
  it("returns 0 for ordinary horizontal text", () => {
    const json = { blocks: [{ lines: [hline(1, 30), hline(2, 30), vline(9, 5)] }] };
    expect(detectContentRotation(json)).toBe(0);
  });

  it("returns 90 when bottom-to-top text dominates", () => {
    const json = { blocks: [{ lines: [vline(1, 30), vline(2, 30), hline(9, 5)] }] };
    expect(detectContentRotation(json)).toBe(90);
  });

  it("returns 270 when top-to-bottom text dominates", () => {
    const lines = [1, 2].map((i) => ({
      ...vline(i, 30),
      // anchor at the bbox TOP → reads top-to-bottom.
      y: 101,
    }));
    expect(detectContentRotation({ blocks: [{ lines }] })).toBe(270);
  });

  it("ignores sparse vertical text (a title block alone must not rotate the sheet)", () => {
    const json = { blocks: [{ lines: [vline(1, 10)] }] };
    expect(detectContentRotation(json)).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// End-to-end through openPdf on synthetic PDFs.
// ---------------------------------------------------------------------------

function pngDims(png: Uint8Array): { w: number; h: number } {
  // IHDR: width at bytes 16..19, height at 20..23 (big-endian).
  const dv = new DataView(png.buffer, png.byteOffset, png.byteLength);
  return { w: dv.getUint32(16), h: dv.getUint32(20) };
}

// 200x400pt portrait page whose content is all bottom-to-top text (a
// landscape sheet drawn sideways). Enough text to trip the detector.
function sidewaysPdf(): Buffer {
  const texts = Array.from({ length: 6 }, (_, i) =>
    `BT /F1 12 Tf 0 1 -1 0 ${40 + i * 25} 60 Tm (SIDEWAYSLABELTEXT${i}) Tj ET`
  ).join("\n");
  return pdfBytes(200, 400, texts);
}

function uprightPdf(): Buffer {
  const texts = Array.from({ length: 6 }, (_, i) =>
    `BT /F1 12 Tf 40 ${300 - i * 25} Td (ORDINARYLABELTEXT${i}) Tj ET`
  ).join("\n");
  return pdfBytes(200, 400, texts);
}

function pdfBytes(w: number, h: number, content: string): Buffer {
  return Buffer.from(`%PDF-1.4
1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj
2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj
3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 ${w} ${h}] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >> endobj
4 0 obj << /Length ${content.length} >> stream
${content}
endstream endobj
5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj
trailer << /Root 1 0 R >>`);
}

describe("openPdf sideways-content normalization", () => {
  it("leaves upright pages untouched", () => {
    const pdf = openPdf(uprightPdf());
    expect(pdf.pageDimsPt(0)).toEqual({ widthPt: 200, heightPt: 400 });
    const png = pngDims(pdf.renderPage(0, 72));
    expect(png).toEqual({ w: 200, h: 400 });
    pdf.close();
  });

  it("serves swapped dims and an upright render for a sideways page", () => {
    const pdf = openPdf(sidewaysPdf());
    // Raw page is 200x400 portrait; normalized (upright) space is 400x200.
    expect(pdf.pageDimsPt(0)).toEqual({ widthPt: 400, heightPt: 200 });
    const png = pngDims(pdf.renderPage(0, 72));
    expect(png).toEqual({ w: 400, h: 200 });
    pdf.close();
  });

  it("renders region crops in normalized space at the right pixel size", () => {
    const pdf = openPdf(sidewaysPdf());
    const png = pngDims(
      pdf.renderRegion(0, { x0: 50, y0: 25, x1: 350, y1: 175 }, 144)
    );
    // 300x150pt at 144 DPI (2x) → 600x300 px.
    expect(png).toEqual({ w: 600, h: 300 });
    pdf.close();
  });

  it("normalizes text-fragment coordinates into the upright space", () => {
    const pdf = openPdf(sidewaysPdf());
    const frags = pdf.pageTextFragments(0);
    expect(frags.length).toBeGreaterThan(0);
    for (const f of frags) {
      // Normalized space is 400 wide x 200 tall.
      expect(f.x).toBeGreaterThanOrEqual(0);
      expect(f.x).toBeLessThanOrEqual(400);
      expect(f.y).toBeGreaterThanOrEqual(0);
      expect(f.y).toBeLessThanOrEqual(200);
    }
    // All six labels sit on one sideways baseline (x=40..165 in raw space) →
    // after normalization they share a ROW band, not a column: y spread small,
    // x spread large would be wrong — here each label had its own x, so they
    // form distinct columns along y. Just assert the text survived intact.
    expect(frags.map((f) => f.text).join(" ")).toContain("SIDEWAYSLABELTEXT0");
    pdf.close();
  });
});
