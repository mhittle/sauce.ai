// PDF splitting/rasterization via mupdf WASM (PRD §4). Thumbnails for
// classification, ~200 DPI renders for extraction. Tesseract OCR fallback for
// scan-only pages is a roadmap item.

import * as mupdf from "mupdf";

export interface OpenPdf {
  pageCount: number;
  renderPage(pageIndex: number, dpi: number): Uint8Array;
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
    close() {
      doc.destroy();
    },
  };
}

export const THUMBNAIL_DPI = 50;
export const EXTRACTION_DPI = 200;
