import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../api";
import { Button, Card, Input } from "../ui";
import { BoxOverlay, type BBox, type OverlayBox } from "./BoxOverlay";

// Interactive source panel for the takeoff review screen: the exact images
// the model read, tabbed by page, with each detected cabinet's bounding box
// drawn on top. Selecting a box selects its line (and vice versa — the parent
// switches the tab); boxes can be moved/resized, and drawing a new box
// creates a new cabinet line. Boxes are advisory anchors; the inch fields on
// the line drive pricing.

export interface PanelLine {
  id: string;
  sourcePage: number | null;
  tag: string | null;
  category: string;
  bbox: BBox | null;
  readImageKey: string | null;
}

const CATEGORIES = [
  "casework_base",
  "casework_wall",
  "casework_tall",
  "vanity",
  "closet",
  "door",
  "drawer_front",
  "drawer_box",
  "panel",
  "filler",
  "trim",
  "hardware",
  "countertop",
  "unknown",
];

// takeoffs/{id}/reads/p3-c0-full.png -> p3-c0-full (the API's readId slug)
function readSlug(key: string): string {
  return (key.split("/").pop() ?? key).replace(/\.png$/, "");
}

function pageFromSlug(key: string): number | null {
  const m = /^p(\d+)-/.exec(readSlug(key));
  return m ? Number(m[1]) : null;
}

export function SourceBoxPanel({
  takeoffId,
  lines,
  selectedId,
  editable,
  onSelect,
  onPatchBbox,
  onCreate,
}: {
  takeoffId: string;
  lines: PanelLine[];
  selectedId: string | null;
  // false once the takeoff is approved — boxes become view-only.
  editable: boolean;
  onSelect: (id: string | null) => void;
  onPatchBbox: (id: string, bbox: BBox) => void;
  onCreate: (body: Record<string, unknown>) => void;
}) {
  const [currentKey, setCurrentKey] = useState<string | null>(null);
  const [drawMode, setDrawMode] = useState(false);
  const [pendingBox, setPendingBox] = useState<BBox | null>(null);

  const imageGroups = useMemo(() => {
    const keys: string[] = [];
    const byKey = new Map<string, PanelLine[]>();
    for (const l of lines) {
      if (l.readImageKey == null) continue;
      if (!byKey.has(l.readImageKey)) {
        byKey.set(l.readImageKey, []);
        keys.push(l.readImageKey);
      }
      byKey.get(l.readImageKey)!.push(l);
    }
    return keys.map((k) => ({ key: k, lines: byKey.get(k)! }));
  }, [lines]);

  // "Page 1", "Page 2", … with an a/b suffix when a page has several crops.
  const labelByKey = useMemo(() => {
    const byPage = new Map<number, string[]>();
    for (const g of imageGroups) {
      const p = pageFromSlug(g.key);
      if (p != null) byPage.set(p, [...(byPage.get(p) ?? []), g.key]);
    }
    const labels = new Map<string, string>();
    for (const g of imageGroups) {
      const p = pageFromSlug(g.key);
      if (p == null) {
        labels.set(g.key, readSlug(g.key));
        continue;
      }
      const siblings = byPage.get(p)!;
      labels.set(
        g.key,
        siblings.length > 1
          ? `Page ${p}${String.fromCharCode(97 + siblings.indexOf(g.key))}`
          : `Page ${p}`
      );
    }
    return labels;
  }, [imageGroups]);

  const effectiveKey =
    currentKey != null && imageGroups.some((g) => g.key === currentKey)
      ? currentKey
      : (imageGroups[0]?.key ?? null);
  const currentGroup = imageGroups.find((g) => g.key === effectiveKey);

  // Selecting a line elsewhere (the table) pulls its page into view.
  const selectedKey = lines.find((l) => l.id === selectedId)?.readImageKey;
  useEffect(() => {
    if (selectedKey != null) setCurrentKey(selectedKey);
  }, [selectedKey]);

  const imageUrl = useQuery({
    queryKey: ["read-image", takeoffId, effectiveKey],
    queryFn: () =>
      apiGet<{ url: string }>(
        `/takeoffs/${takeoffId}/reads/${readSlug(effectiveKey!)}/image`
      ),
    enabled: effectiveKey != null,
    staleTime: 10 * 60 * 1000,
  });

  if (effectiveKey == null) return null;

  const overlayBoxes: OverlayBox[] = (currentGroup?.lines ?? [])
    .filter((l): l is PanelLine & { bbox: BBox } => l.bbox != null)
    .map((l) => ({
      id: l.id,
      bbox: l.bbox,
      category: l.category,
      label: l.tag ?? l.category,
    }));

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap gap-1">
          {imageGroups.length > 1 ? (
            imageGroups.map((g) => (
              <button
                key={g.key}
                className={`rounded-md border px-2 py-1 text-xs ${
                  g.key === effectiveKey
                    ? "border-blue-500 bg-blue-50 text-blue-700"
                    : "border-zinc-300 bg-white text-zinc-600 hover:bg-zinc-50"
                }`}
                onClick={() => setCurrentKey(g.key)}
              >
                {labelByKey.get(g.key)} ({g.lines.length})
              </button>
            ))
          ) : (
            <span className="text-sm font-semibold text-zinc-500">
              {labelByKey.get(effectiveKey)}
            </span>
          )}
        </div>
        {editable && (
          <Button
            variant={drawMode ? "primary" : "default"}
            onClick={() => {
              setDrawMode((d) => !d);
              setPendingBox(null);
            }}
          >
            {drawMode ? "Drawing… (drag on image)" : "+ Draw new box"}
          </Button>
        )}
      </div>

      {pendingBox && (
        <NewLineForm
          onCancel={() => setPendingBox(null)}
          onSave={(fields) => {
            onCreate({
              ...fields,
              bbox: pendingBox,
              read_image_key: effectiveKey,
              source_page:
                currentGroup?.lines[0]?.sourcePage ?? pageFromSlug(effectiveKey),
            });
            setPendingBox(null);
            setDrawMode(false);
          }}
        />
      )}

      {imageUrl.data?.url ? (
        <BoxOverlay
          src={imageUrl.data.url}
          boxes={overlayBoxes}
          selectedId={selectedId}
          drawMode={editable && drawMode && pendingBox == null}
          onSelect={onSelect}
          onChange={(id, bbox) => {
            if (editable) onPatchBbox(id, bbox);
          }}
          onCreate={(bbox) => setPendingBox(bbox)}
        />
      ) : (
        <p className="text-sm text-zinc-400">Loading read image…</p>
      )}
    </div>
  );
}

function NewLineForm({
  onSave,
  onCancel,
}: {
  onSave: (fields: Record<string, unknown>) => void;
  onCancel: () => void;
}) {
  const [fields, setFields] = useState({
    tag: "",
    category: "casework_base",
    qty: "1",
    width_in: "",
    height_in: "",
    depth_in: "",
  });
  const num = (s: string) => (s.trim() === "" ? null : Number(s));
  return (
    <Card className="mb-2 border-blue-300">
      <h2 className="mb-2 text-sm font-semibold text-blue-800">
        New cabinet for the drawn box
      </h2>
      <div className="flex flex-wrap items-end gap-2 text-sm">
        <label className="flex flex-col text-xs text-zinc-500">
          Tag
          <Input
            className="w-32"
            autoFocus
            value={fields.tag}
            onChange={(e) => setFields({ ...fields, tag: e.target.value })}
          />
        </label>
        <label className="flex flex-col text-xs text-zinc-500">
          Category
          <select
            className="rounded-md border border-zinc-300 bg-white px-2 py-1 text-sm"
            value={fields.category}
            onChange={(e) => setFields({ ...fields, category: e.target.value })}
          >
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col text-xs text-zinc-500">
          Qty
          <Input
            className="w-12"
            value={fields.qty}
            onChange={(e) => setFields({ ...fields, qty: e.target.value })}
          />
        </label>
        {(["width_in", "height_in", "depth_in"] as const).map((f) => (
          <label key={f} className="flex flex-col text-xs text-zinc-500">
            {f === "width_in" ? "W" : f === "height_in" ? "H" : "D"} (in)
            <Input
              className="w-14"
              value={fields[f]}
              onChange={(e) => setFields({ ...fields, [f]: e.target.value })}
            />
          </label>
        ))}
        <Button
          variant="primary"
          onClick={() =>
            onSave({
              tag: fields.tag.trim() || null,
              category: fields.category,
              qty: Number(fields.qty) > 0 ? Number(fields.qty) : 1,
              width_in: num(fields.width_in),
              height_in: num(fields.height_in),
              depth_in: num(fields.depth_in),
            })
          }
        >
          Add line
        </Button>
        <Button variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </Card>
  );
}
