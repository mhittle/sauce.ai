import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiSend } from "../api";
import { Badge, Button, Card, Input, PageTitle, statusTone } from "../ui";
import {
  BoxOverlay,
  categoryColor,
  type BBox,
  type OverlayBox,
} from "../components/BoxOverlay";

// Box-review gate (status awaiting_boxes). Not a route of its own: the
// takeoff screen (/takeoffs/$takeoffId) renders this section while the
// takeoff waits at the gate, so review is one page whose content follows the
// status. Read images are tabbed by PAGE ("Page 1", "Page 2", …); clicking a
// line in the list switches to its image.

export interface BoxReviewLine {
  id: string;
  sourcePage: number | null;
  tag: string | null;
  room: string | null;
  qty: number;
  category: string;
  widthIn: number | null;
  heightIn: number | null;
  depthIn: number | null;
  notes: string | null;
  confidence: number;
  bbox: BBox | null;
  readImageKey: string | null;
  updatedAt: string;
}

export interface BoxReviewTakeoff {
  id: string;
  sourceFilename: string | null;
  status: string;
  lines: BoxReviewLine[];
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

interface Group {
  key: string | null;
  lines: BoxReviewLine[];
}

export function BoxReviewSection({ takeoff }: { takeoff: BoxReviewTakeoff }) {
  const takeoffId = takeoff.id;
  const qc = useQueryClient();
  const [currentKey, setCurrentKey] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [drawMode, setDrawMode] = useState(false);
  // The box the reviewer just drew, waiting for its line details.
  const [pendingBox, setPendingBox] = useState<BBox | null>(null);
  const rowRefs = useRef(new Map<string, HTMLTableRowElement>());

  const lines = takeoff.lines;

  // Group lines by the exact image they were read from; null = no drawing
  // (text-layer schedule reads) — those get a list-only review.
  const groups = useMemo<Group[]>(() => {
    const keys: (string | null)[] = [];
    const byKey = new Map<string | null, BoxReviewLine[]>();
    for (const l of lines) {
      const k = l.readImageKey;
      if (!byKey.has(k)) {
        byKey.set(k, []);
        keys.push(k);
      }
      byKey.get(k)!.push(l);
    }
    return keys.map((k) => ({ key: k, lines: byKey.get(k)! }));
  }, [lines]);

  const imageGroups = groups.filter(
    (g): g is Group & { key: string } => g.key != null
  );

  // Human tab labels: "Page 1", "Page 2", … — with an a/b suffix only when a
  // page was read as several crops (rare). Falls back to the raw slug when the
  // key doesn't carry a page number.
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

  const groupLabel = (key: string | null): string =>
    key == null ? "No drawing (text schedule)" : (labelByKey.get(key) ?? readSlug(key));

  const effectiveKey =
    currentKey != null && imageGroups.some((g) => g.key === currentKey)
      ? currentKey
      : (imageGroups[0]?.key ?? null);
  const currentGroup = groups.find((g) => g.key === effectiveKey);

  const imageUrl = useQuery({
    queryKey: ["read-image", takeoffId, effectiveKey],
    queryFn: () =>
      apiGet<{ url: string }>(
        `/takeoffs/${takeoffId}/reads/${readSlug(effectiveKey!)}/image`
      ),
    enabled: effectiveKey != null,
    staleTime: 10 * 60 * 1000,
  });

  const patchLine = useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: Record<string, unknown> }) =>
      apiSend("PATCH", `/takeoff-lines/${id}`, patch),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["takeoff", takeoffId] }),
  });

  const deleteLine = useMutation({
    mutationFn: (id: string) => apiSend("DELETE", `/takeoff-lines/${id}`),
    onSuccess: () => {
      setSelectedId(null);
      qc.invalidateQueries({ queryKey: ["takeoff", takeoffId] });
    },
  });

  const createLine = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      apiSend<BoxReviewLine>("POST", "/takeoff-lines", body),
    onSuccess: (line) => {
      setPendingBox(null);
      setDrawMode(false);
      setSelectedId(line.id);
      qc.invalidateQueries({ queryKey: ["takeoff", takeoffId] });
    },
  });

  const finalize = useMutation({
    mutationFn: () => apiSend("POST", `/takeoffs/${takeoffId}/finalize-boxes`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["takeoff", takeoffId] }),
  });

  // Delete key removes the selected box + line (box and line are one thing).
  useEffect(() => {
    function onKey(ev: KeyboardEvent) {
      if (ev.key !== "Delete" && ev.key !== "Backspace") return;
      const target = ev.target as HTMLElement;
      if (["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return;
      if (selectedId != null && !deleteLine.isPending) {
        deleteLine.mutate(selectedId);
        ev.preventDefault();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selectedId, deleteLine]);

  const selectFromOverlay = (id: string | null) => {
    setSelectedId(id);
    if (id != null) {
      rowRefs.current
        .get(id)
        ?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  };

  const selectFromList = (line: BoxReviewLine) => {
    setSelectedId(line.id);
    if (line.readImageKey != null) setCurrentKey(line.readImageKey);
  };

  const boxCount = lines.reduce((s, l) => s + l.qty, 0);

  const overlayBoxes: OverlayBox[] = (currentGroup?.lines ?? [])
    .filter((l): l is BoxReviewLine & { bbox: BBox } => l.bbox != null)
    .map((l) => ({
      id: l.id,
      bbox: l.bbox,
      category: l.category,
      label: l.tag ?? l.category,
    }));

  return (
    <div>
      <PageTitle
        actions={
          <div className="flex items-center gap-2">
            <span className="text-sm text-zinc-500">
              {boxCount} cabinet{boxCount === 1 ? "" : "s"}
            </span>
            <Button
              variant="primary"
              disabled={finalize.isPending || takeoff.status !== "awaiting_boxes"}
              onClick={() => finalize.mutate()}
            >
              {finalize.isPending ? "Finalizing…" : "Finalize boxes →"}
            </Button>
          </div>
        }
      >
        Review boxes: {takeoff.sourceFilename ?? takeoffId.slice(0, 8)}{" "}
        <Badge tone={statusTone(takeoff.status)}>{takeoff.status}</Badge>
      </PageTitle>

      {(finalize.isError || createLine.isError) && (
        <p className="mb-2 text-sm text-red-600">
          {String(finalize.error ?? createLine.error)}
        </p>
      )}

      <p className="mb-3 text-xs text-zinc-400">
        Boxes are the model's own (loose) anchors — drag to move, corner handles
        to resize, Delete removes box + line. Box edits are visual only; the
        inch fields drive pricing. Finalizing prices the list and opens the
        quote review.
      </p>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div>
          {imageGroups.length > 1 && (
            <div className="mb-2 flex flex-wrap gap-1">
              {imageGroups.map((g) => (
                <button
                  key={g.key}
                  className={`rounded-md border px-2 py-1 text-xs ${
                    g.key === effectiveKey
                      ? "border-blue-500 bg-blue-50 text-blue-700"
                      : "border-zinc-300 bg-white text-zinc-600 hover:bg-zinc-50"
                  }`}
                  onClick={() => setCurrentKey(g.key)}
                >
                  {groupLabel(g.key)} ({g.lines.length})
                </button>
              ))}
            </div>
          )}
          <Card className="max-h-[75vh] overflow-auto">
            {effectiveKey == null ? (
              <p className="text-sm text-zinc-400">
                No drawing for these lines (read from the document's text
                schedule) — review the list on the right.
              </p>
            ) : imageUrl.data?.url ? (
              <>
                <div className="mb-2 flex items-center justify-between">
                  <span className="text-sm font-semibold text-zinc-500">
                    {groupLabel(effectiveKey)}
                  </span>
                  <Button
                    variant={drawMode ? "primary" : "default"}
                    onClick={() => {
                      setDrawMode((d) => !d);
                      setPendingBox(null);
                    }}
                  >
                    {drawMode ? "Drawing… (drag on image)" : "+ Draw new box"}
                  </Button>
                </div>
                <BoxOverlay
                  src={imageUrl.data.url}
                  boxes={overlayBoxes}
                  selectedId={selectedId}
                  drawMode={drawMode && pendingBox == null}
                  onSelect={selectFromOverlay}
                  onChange={(id, bbox) => patchLine.mutate({ id, patch: { bbox } })}
                  onCreate={(bbox) => setPendingBox(bbox)}
                />
              </>
            ) : (
              <p className="text-sm text-zinc-400">Loading read image…</p>
            )}
          </Card>
        </div>

        <div>
          {pendingBox && (
            <NewLineForm
              pending={createLine.isPending}
              onCancel={() => setPendingBox(null)}
              onSave={(fields) =>
                createLine.mutate({
                  takeoff_id: takeoffId,
                  ...fields,
                  bbox: pendingBox,
                  read_image_key: effectiveKey,
                  source_page:
                    currentGroup?.lines[0]?.sourcePage ??
                    (effectiveKey != null ? pageFromSlug(effectiveKey) : null),
                })
              }
            />
          )}
          <Card className="max-h-[75vh] overflow-auto p-0">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-white">
                <tr className="border-b border-zinc-200 text-left text-zinc-500">
                  <th className="px-2 py-2">Tag</th>
                  <th className="px-2 py-2">Category</th>
                  <th className="px-2 py-2">Qty</th>
                  <th className="px-2 py-2">W×H×D (in)</th>
                  <th className="px-2 py-2"></th>
                </tr>
              </thead>
              <tbody>
                {groups.map((g) => (
                  <LineGroup
                    key={g.key ?? "none"}
                    group={g}
                    label={groupLabel(g.key)}
                    current={g.key === effectiveKey}
                    selectedId={selectedId}
                    rowRefs={rowRefs.current}
                    onSelect={selectFromList}
                    onPatch={(id, patch) => patchLine.mutate({ id, patch })}
                    onDelete={(id) => deleteLine.mutate(id)}
                  />
                ))}
                {lines.length === 0 && (
                  <tr>
                    <td colSpan={5} className="px-3 py-6 text-center text-zinc-400">
                      No cabinets extracted — draw boxes to add them, or
                      finalize with an empty list.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </Card>
        </div>
      </div>
    </div>
  );
}

function LineGroup({
  group,
  label,
  current,
  selectedId,
  rowRefs,
  onSelect,
  onPatch,
  onDelete,
}: {
  group: Group;
  label: string;
  current: boolean;
  selectedId: string | null;
  rowRefs: Map<string, HTMLTableRowElement>;
  onSelect: (line: BoxReviewLine) => void;
  onPatch: (id: string, patch: Record<string, unknown>) => void;
  onDelete: (id: string) => void;
}) {
  return (
    <>
      <tr className={current ? "bg-blue-50/50" : "bg-zinc-50"}>
        <td colSpan={5} className="px-2 py-1 text-xs font-semibold text-zinc-500">
          {label} — {group.lines.length} line{group.lines.length === 1 ? "" : "s"}
        </td>
      </tr>
      {group.lines.map((l) => (
        <BoxLineRow
          key={`${l.id}:${l.updatedAt}`}
          line={l}
          selected={l.id === selectedId}
          rowRef={(el) => {
            if (el) rowRefs.set(l.id, el);
            else rowRefs.delete(l.id);
          }}
          onSelect={() => onSelect(l)}
          onPatch={(patch) => onPatch(l.id, patch)}
          onDelete={() => onDelete(l.id)}
        />
      ))}
    </>
  );
}

// Always-editable row (no edit mode): inputs commit on blur, the category
// select commits on change. Deleting the row deletes its box.
function BoxLineRow({
  line,
  selected,
  rowRef,
  onSelect,
  onPatch,
  onDelete,
}: {
  line: BoxReviewLine;
  selected: boolean;
  rowRef: (el: HTMLTableRowElement | null) => void;
  onSelect: () => void;
  onPatch: (patch: Record<string, unknown>) => void;
  onDelete: () => void;
}) {
  const numBlur =
    (field: string, prev: number | null, positive = true) =>
    (e: React.FocusEvent<HTMLInputElement>) => {
      const raw = e.target.value.trim();
      const val = raw === "" ? null : Number(raw);
      if (val !== null && (!Number.isFinite(val) || (positive && val <= 0))) {
        e.target.value = prev == null ? "" : String(prev);
        return;
      }
      if (val !== prev) onPatch({ [field]: val });
    };

  return (
    <tr
      ref={rowRef}
      onClick={onSelect}
      className={`cursor-pointer border-b border-zinc-100 ${
        selected ? "bg-blue-50" : ""
      }`}
    >
      <td className="px-2 py-1">
        <span
          className="mr-1 inline-block h-2.5 w-2.5 rounded-sm"
          style={{ backgroundColor: categoryColor(line.category) }}
        />
        <Input
          className="w-40"
          defaultValue={line.tag ?? ""}
          onBlur={(e) => {
            const v = e.target.value.trim() || null;
            if (v !== line.tag) onPatch({ tag: v });
          }}
        />
      </td>
      <td className="px-2 py-1">
        <select
          className="rounded-md border border-zinc-300 bg-white px-1 py-1 text-sm"
          value={line.category}
          onChange={(e) => onPatch({ category: e.target.value })}
          onClick={(e) => e.stopPropagation()}
        >
          {CATEGORIES.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      </td>
      <td className="px-2 py-1">
        <Input
          className="w-12"
          defaultValue={String(line.qty)}
          onBlur={(e) => {
            const v = Number(e.target.value);
            if (Number.isFinite(v) && v > 0 && v !== line.qty)
              onPatch({ qty: v });
            else e.target.value = String(line.qty);
          }}
        />
      </td>
      <td className="whitespace-nowrap px-2 py-1">
        <Input
          className="w-14"
          defaultValue={line.widthIn != null ? String(line.widthIn) : ""}
          onBlur={numBlur("width_in", line.widthIn)}
        />{" "}
        <Input
          className="w-14"
          defaultValue={line.heightIn != null ? String(line.heightIn) : ""}
          onBlur={numBlur("height_in", line.heightIn)}
        />{" "}
        <Input
          className="w-14"
          defaultValue={line.depthIn != null ? String(line.depthIn) : ""}
          onBlur={numBlur("depth_in", line.depthIn)}
        />
      </td>
      <td className="px-2 py-1 text-right">
        <Button
          variant="ghost"
          className="text-red-600"
          onClick={(e) => {
            e.stopPropagation();
            onDelete();
          }}
        >
          ✕
        </Button>
      </td>
    </tr>
  );
}

function NewLineForm({
  pending,
  onSave,
  onCancel,
}: {
  pending: boolean;
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
    <Card className="mb-3 border-blue-300">
      <h2 className="mb-2 text-sm font-semibold text-blue-800">
        New cabinet for the drawn box
      </h2>
      <div className="flex flex-wrap items-end gap-2 text-sm">
        <label className="flex flex-col text-xs text-zinc-500">
          Tag
          <Input
            className="w-36"
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
            className="w-14"
            value={fields.qty}
            onChange={(e) => setFields({ ...fields, qty: e.target.value })}
          />
        </label>
        {(["width_in", "height_in", "depth_in"] as const).map((f) => (
          <label key={f} className="flex flex-col text-xs text-zinc-500">
            {f === "width_in" ? "W" : f === "height_in" ? "H" : "D"} (in)
            <Input
              className="w-16"
              value={fields[f]}
              onChange={(e) => setFields({ ...fields, [f]: e.target.value })}
            />
          </label>
        ))}
        <Button
          variant="primary"
          disabled={pending}
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
