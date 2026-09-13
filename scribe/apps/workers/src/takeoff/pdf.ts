// PDF splitting/rasterization via mupdf WASM (PRD §4). Thumbnails for
// classification, ~200 DPI renders for extraction, and clipped region renders
// so large-format sheets can be read at a legible resolution instead of being
// downscaled to the model's native size (see @scribe/shared regions.ts).
// Tesseract OCR fallback for scan-only pages is a roadmap item.
//
// SIDEWAYS-CONTENT NORMALIZATION (2026-08-11): some exports draw a landscape
// sheet rotated on a portrait page with NO /Rotate flag (mupdf honors /Rotate;
// these pages simply have sideways content — the Braun "webdownload" set).
// Sideways label text tanks vision reads, so every page's dominant text
// orientation is detected from the text layer and all outputs of this module
// (dims, renders, region crops, text fragments) are served in the NORMALIZED
// (upright) page space. Callers never see the raw sideways space.

import * as mupdf from "mupdf";
import { mergeSegments, type PageSegments, type RectPt, type Segment } from "@scribe/shared";

export interface OpenPdf {
  pageCount: number;
  renderPage(pageIndex: number, dpi: number): Uint8Array;
  // Render only a sub-rectangle of a page (rectangle in PDF points) at the
  // given DPI. Used to crop one drawing off a sheet at full resolution.
  renderRegion(pageIndex: number, rect: RectPt, dpi: number): Uint8Array;
  pageDimsPt(pageIndex: number): { widthPt: number; heightPt: number };
  // Positioned text fragments of a page's text layer (empty for scanned/image-
  // only pages). Each fragment carries its top-left (x,y) in PDF points so the
  // caller can reconstruct column-aligned rows (schedule/BOM tables) that a flat
  // text dump collapses. See @scribe/shared reconstructRows.
  pageTextFragments(pageIndex: number): TextFragment[];
  // Axis-aligned vector line segments of a page (stroked paths and thin
  // filled rectangles), in the same upright top-left-origin point space as
  // pageTextFragments. Empty for scanned/image-only pages. Optional rect
  // (page points) keeps only segments that touch it. Cached per page.
  pageSegments(pageIndex: number, opts?: { rect?: RectPt; minLenPt?: number }): PageSegments;
  close(): void;
}

export interface TextFragment {
  x: number;
  y: number;
  text: string;
  // Text line box size in points (upright-normalized), when known.
  w?: number;
  h?: number;
}

interface StextJson {
  blocks?: {
    lines?: {
      bbox?: { x?: number; y?: number; w?: number; h?: number };
      x?: number;
      y?: number;
      text?: string;
      spans?: { text?: string }[];
    }[];
  }[];
}

function lineText(line: {
  text?: string;
  spans?: { text?: string }[];
}): string {
  return (
    line.text ?? (line.spans ?? []).map((s) => s.text ?? "").join("")
  ).trim();
}

// CLOCKWISE degrees that make a page's sideways content upright, judged by
// the dominant text orientation (weighted by text length). Vertical text has
// a taller-than-wide line bbox; the baseline anchor tells the reading
// direction — anchor at the bbox BOTTOM means bottom-to-top text (drawn
// rotated CCW), fixed by rotating the image CW; anchor at the top is the
// opposite. Pages without clearly dominant vertical text stay untouched.
export function detectContentRotation(json: StextJson): 0 | 90 | 270 {
  let horiz = 0;
  let bottomUp = 0;
  let topDown = 0;
  for (const block of json.blocks ?? []) {
    for (const line of block.lines ?? []) {
      const text = lineText(line);
      if (text.length < 3) continue;
      const bb = line.bbox ?? {};
      const w = bb.w ?? 0;
      const h = bb.h ?? 0;
      if (w <= 0 || h <= 0) continue;
      if (w >= h) horiz += text.length;
      else if ((line.y ?? 0) > (bb.y ?? 0) + h / 2) bottomUp += text.length;
      else topDown += text.length;
    }
  }
  const vertical = bottomUp + topDown;
  if (vertical > Math.max(40, horiz * 2)) {
    return bottomUp >= topDown ? 90 : 270;
  }
  return 0;
}

export function openPdf(data: Buffer): OpenPdf {
  const doc = mupdf.Document.openDocument(data, "application/pdf");

  const stextJson = (pageIndex: number): StextJson => {
    const page = doc.loadPage(pageIndex);
    const stext = page.toStructuredText("preserve-whitespace");
    const json = JSON.parse(stext.asJSON()) as StextJson;
    stext.destroy();
    page.destroy();
    return json;
  };

  // Per-page content rotation, detected once (text extraction is cheap).
  const rotationCache = new Map<number, 0 | 90 | 270>();
  const rotation = (pageIndex: number): 0 | 90 | 270 => {
    let rot = rotationCache.get(pageIndex);
    if (rot === undefined) {
      rot = detectContentRotation(stextJson(pageIndex));
      rotationCache.set(pageIndex, rot);
    }
    return rot;
  };

  // RAW page dims (before normalization) — internal only.
  const rawDims = (pageIndex: number): { w: number; h: number } => {
    const page = doc.loadPage(pageIndex);
    const [x0, y0, x1, y1] = page.getBounds();
    page.destroy();
    return { w: x1 - x0, h: y1 - y0 };
  };

  const matrixFor = (rot: 0 | 90 | 270, scale: number): mupdf.Matrix =>
    rot === 0
      ? mupdf.Matrix.scale(scale, scale)
      : mupdf.Matrix.concat(
          mupdf.Matrix.rotate(rot),
          mupdf.Matrix.scale(scale, scale)
        );

  // Vector segments: run the page through a callback device, walk every
  // stroked/filled path, keep axis-aligned pieces, normalize upright like
  // the text layer. Raster-only pages simply produce no callbacks.
  const segmentsCache = new Map<number, PageSegments>();
  const extractSegments = (pageIndex: number): PageSegments => {
    const rot = rotation(pageIndex);
    const { w: rawW, h: rawH } = rawDims(pageIndex);
    const norm = (x: number, y: number): [number, number] =>
      rot === 90 ? [rawH - y, x] : rot === 270 ? [y, rawW - x] : [x, y];
    const h: Segment[] = [];
    const v: Segment[] = [];
    const push = (a: [number, number], b: [number, number]) => {
      const dx = b[0] - a[0];
      const dy = b[1] - a[1];
      const len = Math.hypot(dx, dy);
      if (len < 0.5) return;
      if (Math.abs(dy) <= AXIS_TAN * len) {
        h.push({ at: (a[1] + b[1]) / 2, from: Math.min(a[0], b[0]), to: Math.max(a[0], b[0]) });
      } else if (Math.abs(dx) <= AXIS_TAN * len) {
        v.push({ at: (a[0] + b[0]) / 2, from: Math.min(a[1], b[1]), to: Math.max(a[1], b[1]) });
      }
    };
    const collect = (path: mupdf.Path, ctm: mupdf.Matrix) => {
      const tp = (x: number, y: number): [number, number] =>
        norm(ctm[0] * x + ctm[2] * y + ctm[4], ctm[1] * x + ctm[3] * y + ctm[5]);
      let start: [number, number] | null = null;
      let cur: [number, number] | null = null;
      path.walk({
        moveTo(x, y) {
          start = cur = tp(x, y);
        },
        lineTo(x, y) {
          const p = tp(x, y);
          if (cur) push(cur, p);
          cur = p;
        },
        curveTo(_x1, _y1, _x2, _y2, x3, y3) {
          cur = tp(x3, y3);
        },
        closePath() {
          if (cur && start) push(cur, start);
          cur = start;
        },
      });
    };
    const page = doc.loadPage(pageIndex);
    try {
      const device = new mupdf.Device({
        fillPath(path, _evenOdd, ctm) {
          collect(path, ctm);
        },
        strokePath(path, _stroke, ctm) {
          collect(path, ctm);
        },
      });
      try {
        page.run(device, mupdf.Matrix.identity);
      } finally {
        device.destroy();
      }
    } catch {
      return { h: [], v: [] };
    } finally {
      page.destroy();
    }
    return mergeSegments({ h, v });
  };

  return {
    pageCount: doc.countPages(),
    renderPage(pageIndex: number, dpi: number): Uint8Array {
      const page = doc.loadPage(pageIndex);
      const scale = dpi / 72;
      const pixmap = page.toPixmap(
        matrixFor(rotation(pageIndex), scale),
        mupdf.ColorSpace.DeviceRGB,
        false,
        true
      );
      const png = pixmap.asPNG();
      pixmap.destroy();
      page.destroy();
      return png;
    },
    renderRegion(pageIndex: number, rect: RectPt, dpi: number): Uint8Array {
      const page = doc.loadPage(pageIndex);
      const scale = dpi / 72;
      const rot = rotation(pageIndex);
      // `rect` is in NORMALIZED (upright) points. The pixmap bbox lives in
      // post-transform device space, which for a rotated render is offset:
      // rotate(90) maps page (x,y)→(-y,x) so normalized X = x' + rawH;
      // rotate(270) maps (x,y)→(y,-x) so normalized Y = y' + rawW.
      const { w: rawW, h: rawH } = rawDims(pageIndex);
      const dx = rot === 90 ? -rawH : 0;
      const dy = rot === 270 ? -rawW : 0;
      const bbox: [number, number, number, number] = [
        Math.round((rect.x0 + dx) * scale),
        Math.round((rect.y0 + dy) * scale),
        Math.round((rect.x1 + dx) * scale),
        Math.round((rect.y1 + dy) * scale),
      ];
      const pixmap = new mupdf.Pixmap(mupdf.ColorSpace.DeviceRGB, bbox, false);
      pixmap.clear(255);
      const device = new mupdf.DrawDevice(mupdf.Matrix.identity, pixmap);
      page.run(device, matrixFor(rot, scale));
      device.close();
      const png = pixmap.asPNG();
      pixmap.destroy();
      page.destroy();
      return png;
    },
    pageDimsPt(pageIndex: number): { widthPt: number; heightPt: number } {
      const { w, h } = rawDims(pageIndex);
      return rotation(pageIndex) === 0
        ? { widthPt: w, heightPt: h }
        : { widthPt: h, heightPt: w };
    },
    pageSegments(pageIndex: number, opts: { rect?: RectPt; minLenPt?: number } = {}): PageSegments {
      let all = segmentsCache.get(pageIndex);
      if (!all) {
        all = extractSegments(pageIndex);
        segmentsCache.set(pageIndex, all);
      }
      const minLen = opts.minLenPt ?? MIN_SEGMENT_PT;
      const r = opts.rect;
      const keep = (s: Segment, alongIsX: boolean): boolean => {
        if (s.to - s.from < minLen) return false;
        if (!r) return true;
        const pad = 0.02 * Math.max(r.x1 - r.x0, r.y1 - r.y0);
        // alongIsX: horizontal segment (at = y, from..to = x)
        const x0 = alongIsX ? s.from : s.at;
        const x1 = alongIsX ? s.to : s.at;
        const y0 = alongIsX ? s.at : s.from;
        const y1 = alongIsX ? s.at : s.to;
        return x1 >= r.x0 - pad && x0 <= r.x1 + pad && y1 >= r.y0 - pad && y0 <= r.y1 + pad;
      };
      return { h: all.h.filter((s) => keep(s, true)), v: all.v.filter((s) => keep(s, false)) };
    },
    pageTextFragments(pageIndex: number): TextFragment[] {
      const json = stextJson(pageIndex);
      const rot = rotation(pageIndex);
      const { w: rawW, h: rawH } = rawDims(pageIndex);
      const out: TextFragment[] = [];
      for (const block of json.blocks ?? []) {
        for (const line of block.lines ?? []) {
          const text = lineText(line);
          if (!text) continue;
          const x = line.bbox?.x ?? 0;
          const y = line.bbox?.y ?? 0;
          const w = line.bbox?.w;
          const h = line.bbox?.h;
          // Same normalization as the renders, so row reconstruction
          // (schedules) and dim grounding see upright coordinates. The box
          // size rides along (swapped when rotated) so callers can centre a
          // dimension string on its segment (scale calibration).
          if (rot === 90) out.push({ x: rawH - y - (h ?? 0), y: x, w: h, h: w, text });
          else if (rot === 270) out.push({ x: y, y: rawW - x - (w ?? 0), w: h, h: w, text });
          else out.push({ x, y, w, h, text });
        }
      }
      return out;
    },
    close() {
      doc.destroy();
    },
  };
}

// Segments shorter than this are handles, hatch marks and text strokes.
const MIN_SEGMENT_PT = 4;
// Axis-aligned within ~1.5° (tan).
const AXIS_TAN = 0.026;

export const THUMBNAIL_DPI = 50;
export const EXTRACTION_DPI = 200;
// Picker-gate thumbnails (stored to takeoffs/{id}/thumbs/): light enough to
// render every page of a big set, sharp enough for a human to tell a floor
// plan from an elevation. Also reused as the classification input.
export const PICKER_THUMBNAIL_DPI = 72;
