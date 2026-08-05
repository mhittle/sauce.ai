// Ad-hoc: rasterize specific pages of ANY pdf to PNGs for inspection.
// Usage: node scripts/rasterize-pages.mjs <pdf> <outDir> <dpi> <page,page,...>
import { openPdf } from "../dist/takeoff/pdf.js";
import { readFileSync, mkdirSync, writeFileSync } from "node:fs";

const [pdfPath, outDir, dpiStr, pagesStr] = process.argv.slice(2);
const dpi = Number(dpiStr);
const pages = pagesStr.split(",").map(Number);
mkdirSync(outDir, { recursive: true });
const pdf = openPdf(readFileSync(pdfPath));
for (const p of pages) {
  const png = pdf.renderPage(p - 1, dpi);
  const out = `${outDir}/p${String(p).padStart(2, "0")}.png`;
  writeFileSync(out, png);
  console.log(out);
}
pdf.close();
