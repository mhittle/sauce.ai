import { describe, expect, it } from "vitest";
import * as mupdf from "mupdf";
import { openPdf } from "../src/takeoff/pdf.js";

// pageSegments walks the page's vector paths through a callback Device and
// returns axis-aligned segments in the same upright, top-left-origin point
// space as pageTextFragments — so a box in read-image pixels converts
// straight to points and snaps against them.

function makePdf(contents: string, mediabox: [number, number, number, number] = [0, 0, 612, 792]): Buffer {
  const doc = new mupdf.PDFDocument();
  const page = doc.addPage(mediabox, 0, doc.newDictionary(), contents);
  doc.insertPage(-1, page);
  return Buffer.from(doc.saveToBuffer().asUint8Array());
}

describe("pageSegments", () => {
  it("returns stroked rectangle edges as h/v segments in top-left-origin points", () => {
    // PDF user space is bottom-left origin: a rect from (100,100) to (300,250)
    // sits at y = 792-250 .. 792-100 in the top-down space we use everywhere.
    const pdf = openPdf(makePdf("1 w 100 100 m 300 100 l 300 250 l 100 250 l h S"));
    try {
      const segs = pdf.pageSegments(0);
      const h = segs.h.map((s) => [Math.round(s.at), Math.round(s.from), Math.round(s.to)]);
      const v = segs.v.map((s) => [Math.round(s.at), Math.round(s.from), Math.round(s.to)]);
      expect(h).toEqual(expect.arrayContaining([[542, 100, 300], [692, 100, 300]]));
      expect(v).toEqual(expect.arrayContaining([[100, 542, 692], [300, 542, 692]]));
      expect(segs.h.length).toBe(2);
      expect(segs.v.length).toBe(2);
    } finally {
      pdf.close();
    }
  });

  it("includes thin filled rectangles (CAD exports draw lines as fills) and drops diagonals", () => {
    const pdf = openPdf(makePdf("50 400 200 0.6 re f 10 10 m 60 80 l S"));
    try {
      const segs = pdf.pageSegments(0);
      // The filled bar's two long edges merge into one horizontal segment.
      expect(segs.h.length).toBe(1);
      expect(Math.round(segs.h[0].from)).toBe(50);
      expect(Math.round(segs.h[0].to)).toBe(250);
      // Its 0.6 pt short edges are below the length floor; the diagonal is not axis-aligned.
      expect(segs.v.length).toBe(0);
    } finally {
      pdf.close();
    }
  });

  it("restricts to a rect when asked, and returns nothing for a page with no vectors", () => {
    const pdf = openPdf(makePdf("1 w 100 100 m 300 100 l S 400 600 m 500 600 l S"));
    try {
      const inRect = pdf.pageSegments(0, { rect: { x0: 0, y0: 600, x1: 350, y1: 792 } });
      expect(inRect.h.length).toBe(1);
      expect(Math.round(inRect.h[0].at)).toBe(692);
    } finally {
      pdf.close();
    }
    const blank = openPdf(makePdf(""));
    try {
      expect(blank.pageSegments(0)).toEqual({ h: [], v: [] });
    } finally {
      blank.close();
    }
  });
});
