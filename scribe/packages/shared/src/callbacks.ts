// Outbound "takeoff.approved" callback to an external caller (CabinetHub).
// Built by the api's approve handler; signed and delivered by the worker
// (apps/workers/src/callbacks/deliver.ts). Pure: this package is bundled for
// the browser too, so no node: imports here.

export interface CallbackTakeoff {
  id: string;
  externalSource: string | null;
  externalRef: string | null;
  sourceFilename: string | null;
}

export interface CallbackLineInput {
  id: string;
  tag: string | null;
  room: string | null;
  qty: number;
  category: string;
  widthIn: number | null;
  heightIn: number | null;
  depthIn: number | null;
  doorStyle: string | null;
  material: string | null;
  finish: string | null;
  assembled: boolean | null;
  notes: string | null;
  confidence: number;
  sourcePage: number | null;
}

export interface ApprovedCallbackLine {
  id: string;
  tag: string | null;
  room: string | null;
  qty: number;
  category: string;
  width_in: number | null;
  height_in: number | null;
  depth_in: number | null;
  door_style: string | null;
  material: string | null;
  finish: string | null;
  assembled: boolean | null;
  notes: string | null;
  confidence: number;
  source_page: number | null;
}

export interface ApprovedCallbackPayload {
  event: "takeoff.approved";
  event_id: string;
  takeoff_id: string;
  external_source: string;
  external_ref: string;
  approved_at: string;
  source_filename: string | null;
  lines: ApprovedCallbackLine[];
}

const num = (v: unknown): number | null =>
  v === null || v === undefined || Number.isNaN(Number(v)) ? null : Number(v);

export function buildApprovedPayload(
  takeoff: CallbackTakeoff,
  lines: readonly CallbackLineInput[],
  approvedAt: Date,
  eventId: string
): ApprovedCallbackPayload {
  return {
    event: "takeoff.approved",
    event_id: eventId,
    takeoff_id: takeoff.id,
    external_source: takeoff.externalSource ?? "",
    external_ref: takeoff.externalRef ?? "",
    approved_at: approvedAt.toISOString(),
    source_filename: takeoff.sourceFilename ?? null,
    lines: lines.map((l) => ({
      id: l.id,
      tag: l.tag ?? null,
      room: l.room ?? null,
      qty: Number(l.qty),
      category: l.category,
      width_in: num(l.widthIn),
      height_in: num(l.heightIn),
      depth_in: num(l.depthIn),
      door_style: l.doorStyle ?? null,
      material: l.material ?? null,
      finish: l.finish ?? null,
      assembled: l.assembled ?? null,
      notes: l.notes ?? null,
      confidence: Number(l.confidence),
      source_page: l.sourcePage ?? null,
    })),
  };
}
