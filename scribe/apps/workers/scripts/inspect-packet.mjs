import { openPdf } from "../dist/takeoff/pdf.js";
import { readFileSync } from "node:fs";
const path = process.argv[2];
const buf = readFileSync(path);
const pdf = openPdf(buf);
console.log("pages:", pdf.pageCount);
for (let i = 0; i < pdf.pageCount; i++) {
  const d = pdf.pageDimsPt(i);
  const frags = pdf.pageTextFragments(i);
  console.log(
    `p${i + 1}: ${(d.widthPt / 72).toFixed(1)}x${(d.heightPt / 72).toFixed(1)}in, textFragments=${frags.length}`
  );
}
pdf.close();
