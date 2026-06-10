import { CabinetLineItem, ExportTemplate } from "@scribe/shared";

// Mozaik/KCD CSV export with configurable column-mapping templates (PRD §7.3).
// Import dialects vary by tool version, so the admin mapping editor — not
// code — is the safety valve: reps adjust headers/order/units to match their
// import dialog and the mapping persists in export_templates.

export type ExportableLine = CabinetLineItem & Record<string, unknown>;

const DIM_FIELDS = new Set(["width_in", "height_in", "depth_in"]);

function csvEscape(value: string, delimiter: string): string {
  if (
    value.includes(delimiter) ||
    value.includes('"') ||
    value.includes("\n")
  ) {
    return `"${value.replace(/"/g, '""')}"`;
  }
  return value;
}

function formatValue(
  raw: unknown,
  field: string,
  template: ExportTemplate
): string {
  if (raw == null) return "";
  if (typeof raw === "number" && DIM_FIELDS.has(field)) {
    if (template.unit_format === "mm") {
      return (raw * 25.4).toFixed(1);
    }
    return String(raw);
  }
  if (typeof raw === "boolean") return raw ? "Y" : "N";
  return String(raw);
}

export function exportCsv(
  lines: ExportableLine[],
  template: ExportTemplate
): string {
  const d = template.delimiter;
  const header = template.columns
    .map((c) => csvEscape(c.header, d))
    .join(d);

  const rows = lines.map((line) =>
    template.columns
      .map((col) => {
        if (col.field.startsWith("literal:")) {
          return csvEscape(col.field.slice("literal:".length), d);
        }
        return csvEscape(formatValue(line[col.field], col.field, template), d);
      })
      .join(d)
  );

  return [header, ...rows].join("\r\n") + "\r\n";
}

// Best-effort default templates (PRD §7.3). Expect the reps to tweak headers
// in the admin mapping editor against their actual import dialog.

export const DEFAULT_MOZAIK_TEMPLATE: ExportTemplate = {
  name: "Mozaik (default)",
  target: "mozaik",
  delimiter: ",",
  unit_format: "decimal_in",
  columns: [
    { header: "Name", field: "tag" },
    { header: "Qty", field: "qty" },
    { header: "Width", field: "width_in" },
    { header: "Height", field: "height_in" },
    { header: "Depth", field: "depth_in" },
    { header: "Material", field: "material" },
    { header: "Finish", field: "finish" },
    { header: "Room", field: "room" },
    { header: "Comments", field: "notes" },
  ],
};

export const DEFAULT_KCD_TEMPLATE: ExportTemplate = {
  name: "KCD (default)",
  target: "kcd",
  delimiter: ",",
  unit_format: "decimal_in",
  columns: [
    { header: "Item", field: "tag" },
    { header: "Quantity", field: "qty" },
    { header: "W", field: "width_in" },
    { header: "H", field: "height_in" },
    { header: "D", field: "depth_in" },
    { header: "Material", field: "material" },
    { header: "Finish", field: "finish" },
    { header: "Assembled", field: "assembled" },
    { header: "Room", field: "room" },
  ],
};

export const DEFAULT_GENERIC_TEMPLATE: ExportTemplate = {
  name: "Generic (all fields)",
  target: "generic",
  delimiter: ",",
  unit_format: "decimal_in",
  columns: [
    { header: "Tag", field: "tag" },
    { header: "Room", field: "room" },
    { header: "Qty", field: "qty" },
    { header: "Category", field: "category" },
    { header: "Width (in)", field: "width_in" },
    { header: "Height (in)", field: "height_in" },
    { header: "Depth (in)", field: "depth_in" },
    { header: "Door Style", field: "door_style" },
    { header: "Material", field: "material" },
    { header: "Finish", field: "finish" },
    { header: "Assembled", field: "assembled" },
    { header: "Notes", field: "notes" },
    { header: "Source Page", field: "source_page" },
  ],
};

export const DEFAULT_TEMPLATES = [
  DEFAULT_MOZAIK_TEMPLATE,
  DEFAULT_KCD_TEMPLATE,
  DEFAULT_GENERIC_TEMPLATE,
];
