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
import type { RectPt } from "@scribe/shared";

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
  close(): void;
}

export interface TextFragment {
  x: number;
  y: number;
  text: string;
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
          // Same normalization as the renders, so row reconstruction
          // (schedules) and dim grounding see upright coordinates.
          if (rot === 90) out.push({ x: rawH - y, y: x, text });
          else if (rot === 270) out.push({ x: y, y: rawW - x, text });
          else out.push({ x, y, text });
        }
      }
      return out;
    },
    close() {
      doc.destroy();
    },
  };
}

export const THUMBNAIL_DPI = 50;
export const EXTRACTION_DPI = 200;
// Picker-gate thumbnails (stored to takeoffs/{id}/thumbs/): light enough to
// render every page of a big set, sharp enough for a human to tell a floor
// plan from an elevation. Also reused as the classification input.
export const PICKER_THUMBNAIL_DPI = 72;
