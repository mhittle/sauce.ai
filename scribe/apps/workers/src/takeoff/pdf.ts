// PDF splitting/rasterization via mupdf WASM (PRD §4). Thumbnails for
// classification, ~200 DPI renders for extraction, and clipped region renders
// so large-format sheets can be read at a legible resolution instead of being
// downscaled to the model's native size (see @scribe/shared regions.ts).
// Tesseract OCR fallback for scan-only pages is a roadmap item.

import * as mupdf from "mupdf";
import type { RectPt } from "@scribe/shared";

export interface OpenPdf {
  pageCount: number;
  renderPage(pageIndex: number, dpi: number): Uint8Array;
  // Render only a sub-rectangle of a page (rectangle in PDF points) at the
  // given DPI. Used to crop one drawing off a sheet at full resolution.
  renderRegion(pageIndex: number, rect: RectPt, dpi: number): Uint8Array;
  pageDimsPt(pageIndex: number): { widthPt: number; heightPt: number };
  close(): void;
}

export function openPdf(data: Buffer): OpenPdf {
  const doc = mupdf.Document.openDocument(data, "application/pdf");
  return {
    pageCount: doc.countPages(),
    renderPage(pageIndex: number, dpi: number): Uint8Array {
      const page = doc.loadPage(pageIndex);
      const scale = dpi / 72;
      const pixmap = page.toPixmap(
        mupdf.Matrix.scale(scale, scale),
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
      // Pixmap bbox is in device space (post-scale); a pixmap covering only the
      // crop clips the page render to that region.
      const bbox: [number, number, number, number] = [
        Math.round(rect.x0 * scale),
        Math.round(rect.y0 * scale),
        Math.round(rect.x1 * scale),
        Math.round(rect.y1 * scale),
      ];
      const pixmap = new mupdf.Pixmap(mupdf.ColorSpace.DeviceRGB, bbox, false);
      pixmap.clear(255);
      const device = new mupdf.DrawDevice(mupdf.Matrix.identity, pixmap);
      page.run(device, mupdf.Matrix.scale(scale, scale));
      device.close();
      const png = pixmap.asPNG();
      pixmap.destroy();
      page.destroy();
      return png;
    },
    pageDimsPt(pageIndex: number): { widthPt: number; heightPt: number } {
      const page = doc.loadPage(pageIndex);
      const [x0, y0, x1, y1] = page.getBounds();
      page.destroy();
      return { widthPt: x1 - x0, heightPt: y1 - y0 };
    },
    close() {
      doc.destroy();
    },
  };
}

export const THUMBNAIL_DPI = 50;
export const EXTRACTION_DPI = 200;
