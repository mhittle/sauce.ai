import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { takeoffReviewRoute } from "../main";
import { API_URL, apiGet, apiSend } from "../api";
import { Badge, Button, Card, Input, PageTitle, statusTone } from "../ui";
import { BoxReviewSection } from "./BoxReview";
import { SourceBoxPanel } from "../components/SourceBoxPanel";

interface Line {
  id: string;
  sourcePage: number | null;
  tag: string | null;
  room: string | null;
  qty: number;
  category: string;
  widthIn: number | null;
  heightIn: number | null;
  depthIn: number | null;
  material: string | null;
  finish: string | null;
  assembled: boolean | null;
  notes: string | null;
  confidence: number;
  productLineId: string | null;
  matchConfidence: number | null;
  unmatchedReason: string | null;
  reviewerEdited: boolean;
  bbox: [number, number, number, number] | null;
  readImageKey: string | null;
  updatedAt: string;
}

interface TakeoffDetail {
  id: string;
  sourceFilename: string | null;
  sourceKind: string;
  status: string;
  pageCount: number | null;
  docSummary: {
    uncertainties?: string[];
    unreadable_pages?: number[];
    warnings?: string[];
  } | null;
  lines: Line[];
  material_stats: {
    box_count: number;
    carcass_sqft: number;
    carcass_sheets: number;
    door_count: number;
    door_sqft: number;
    drawer_front_count: number;
    front_sqft: number;
    face_sheets: number;
    skipped_no_dims: number;
    waste_pct: number;
    sheet_area_sqft: number;
  } | null;
}

interface ProductLineRow {
  id: string;
  name: string;
}

const LOW_CONFIDENCE = 0.8;

export function TakeoffReviewPage() {
  const { takeoffId } = takeoffReviewRoute.useParams();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [selected, setSelected] = useState(0);
  const [editing, setEditing] = useState(false);

  const q = useQuery({
    queryKey: ["takeoff", takeoffId],
    queryFn: () => apiGet<TakeoffDetail>(`/takeoffs/${takeoffId}`),
    refetchInterval: (query) =>
      query.state.data?.status === "processing" ? 3000 : false,
  });
  const status = q.data?.status;

  // Two-gate flow: the page-picker gate has its own screen (a different
  // interaction entirely); the box gate renders INSIDE this page below.
  useEffect(() => {
    if (status === "awaiting_pages") {
      navigate({ to: "/takeoffs/$takeoffId/pages", params: { takeoffId } });
    }
  }, [status, navigate, takeoffId]);

  const productLines = useQuery({
    queryKey: ["product-lines"],
    queryFn: () => apiGet<ProductLineRow[]>("/product-lines"),
  });

  const patchLine = useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: Record<string, unknown> }) =>
      apiSend("PATCH", `/takeoff-lines/${id}`, patch),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["takeoff", takeoffId] }),
  });

  const deleteLine = useMutation({
    mutationFn: (id: string) => apiSend("DELETE", `/takeoff-lines/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["takeoff", takeoffId] }),
  });

  const createLine = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      apiSend("POST", "/takeoff-lines", { takeoff_id: takeoffId, ...body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["takeoff", takeoffId] }),
  });

  const approve = useMutation({
    mutationFn: () => apiSend("POST", `/takeoffs/${takeoffId}/approve`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["takeoff", takeoffId] }),
  });

  const createQuote = useMutation({
    mutationFn: () =>
      apiSend<{ id: string }>("POST", "/quotes", { takeoff_id: takeoffId }),
    onSuccess: (quote) =>
      navigate({ to: "/quotes/$quoteId", params: { quoteId: quote.id } }),
  });

  const lines = q.data?.lines ?? [];
  const selectedLine = lines[selected];

  const pageImage = useQuery({
    queryKey: ["page-image", takeoffId, selectedLine?.sourcePage],
    queryFn: () =>
      apiGet<{ url: string }>(
        `/takeoffs/${takeoffId}/pages/${selectedLine!.sourcePage}/image`
      ),
    enabled: selectedLine?.sourcePage != null,
    staleTime: 10 * 60 * 1000,
  });

  // Keystroke-optimized review (PRD §7.2): arrows navigate, e edits,
  // enter accepts the line.
  useEffect(() => {
    function onKey(ev: KeyboardEvent) {
      if (editing) return;
      const target = ev.target as HTMLElement;
      if (["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return;
      if (ev.key === "ArrowDown" || ev.key === "j") {
        setSelected((s) => Math.min(s + 1, lines.length - 1));
        ev.preventDefault();
      } else if (ev.key === "ArrowUp" || ev.key === "k") {
        setSelected((s) => Math.max(s - 1, 0));
        ev.preventDefault();
      } else if (ev.key === "e") {
        setEditing(true);
        ev.preventDefault();
      } else if (ev.key === "Enter" && lines[selected]) {
        patchLine.mutate({
          id: lines[selected].id,
          patch: { confidence: 1 },
        });
        setSelected((s) => Math.min(s + 1, lines.length - 1));
        ev.preventDefault();
      } else if (
        (ev.key === "Delete" || ev.key === "Backspace") &&
        lines[selected] &&
        !deleteLine.isPending
      ) {
        deleteLine.mutate(lines[selected].id);
        setSelected((s) => Math.max(0, Math.min(s, lines.length - 2)));
        ev.preventDefault();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [editing, lines, selected, patchLine, deleteLine]);

  const unmatched = useMemo(
    () => lines.filter((l) => !l.productLineId),
    [lines]
  );

  if (q.isLoading) return <div className="text-zinc-500">Loading…</div>;
  if (q.isError) return <div className="text-red-600">{String(q.error)}</div>;
  const takeoff = q.data!;

  // Box-review gate: same page, different content — the priced review table
  // takes over once "Finalize boxes" has run.
  if (takeoff.status === "awaiting_boxes") {
    return <BoxReviewSection takeoff={takeoff} />;
  }

  return (
    <div>
      <PageTitle
        actions={
          <div className="flex items-center gap-2">
            {takeoff.sourceKind === "pdf" && (
              <Link to="/takeoffs/$takeoffId/detect" params={{ takeoffId }}>
                <Button>
                  Detect <Badge tone="blue">beta</Badge>
                </Button>
              </Link>
            )}
            <a
              href={`${API_URL}/takeoffs/${takeoffId}/export.csv?template=${encodeURIComponent("Mozaik (default)")}`}
            >
              <Button>Export Mozaik CSV</Button>
            </a>
            <a
              href={`${API_URL}/takeoffs/${takeoffId}/export.csv?template=${encodeURIComponent("KCD (default)")}`}
            >
              <Button>Export KCD CSV</Button>
            </a>
            <Button
              onClick={() => {
                for (const l of lines) {
                  if (l.confidence >= LOW_CONFIDENCE && l.confidence < 1) {
                    patchLine.mutate({ id: l.id, patch: { confidence: 1 } });
                  }
                }
              }}
            >
              Batch-accept high-confidence
            </Button>
            {takeoff.status === "approved" ? (
              <Button
                variant="primary"
                disabled={createQuote.isPending}
                onClick={() => createQuote.mutate()}
              >
                Build Quote →
              </Button>
            ) : (
              <Button
                variant="primary"
                disabled={
                  approve.isPending ||
                  !["extracted", "review"].includes(takeoff.status)
                }
                onClick={() => approve.mutate()}
              >
                Approve takeoff
              </Button>
            )}
          </div>
        }
      >
        Review: {takeoff.sourceFilename ?? takeoffId.slice(0, 8)}{" "}
        <Badge tone={statusTone(takeoff.status)}>{takeoff.status}</Badge>
      </PageTitle>

      <p className="mb-3 text-xs text-zinc-400">
        Keyboard: ↑/↓ navigate · e edit · enter accept line · del delete line.
        Click a box on the drawing to jump to its line; box edits are visual
        anchors — the inch fields drive pricing.
      </p>

      {takeoff.status === "processing" && (
        <Card>
          <p className="text-sm text-zinc-500">
            Processing (extraction or pricing)… this page refreshes
            automatically.
          </p>
        </Card>
      )}

      {((takeoff.docSummary?.uncertainties?.length ?? 0) > 0 ||
        (takeoff.docSummary?.warnings?.length ?? 0) > 0) && (
        <Card className="mb-4 border-amber-300 bg-amber-50">
          <h2 className="mb-1 text-sm font-semibold text-amber-800">
            Flagged for review
          </h2>
          <ul className="list-inside list-disc text-sm text-amber-800">
            {[...(takeoff.docSummary?.uncertainties ?? []), ...(takeoff.docSummary?.warnings ?? [])].map(
              (u, i) => (
                <li key={i}>{u}</li>
              )
            )}
          </ul>
        </Card>
      )}

      {takeoff.material_stats &&
        takeoff.material_stats.box_count > 0 &&
        ["review", "approved"].includes(takeoff.status) && (
          <Card className="mb-4">
            <h2 className="mb-2 text-sm font-semibold text-zinc-500">
              Materials
            </h2>
            <div className="flex flex-wrap gap-x-8 gap-y-2">
              <div>
                <div className="text-lg font-semibold">
                  {takeoff.material_stats.box_count}
                </div>
                <div className="text-xs text-zinc-500">Cabinet boxes</div>
              </div>
              <div>
                <div className="text-lg font-semibold">
                  {takeoff.material_stats.carcass_sqft} ft²
                  <span className="ml-1 text-sm font-normal text-zinc-500">
                    → ~{takeoff.material_stats.carcass_sheets} sheets
                  </span>
                </div>
                <div className="text-xs text-zinc-500">
                  Carcass material (4×8 @ {takeoff.material_stats.waste_pct}%
                  waste)
                </div>
              </div>
              <div>
                <div className="text-lg font-semibold">
                  {takeoff.material_stats.door_count} doors ·{" "}
                  {takeoff.material_stats.door_sqft} ft²
                </div>
                <div className="text-xs text-zinc-500">Door fronts</div>
              </div>
              <div>
                <div className="text-lg font-semibold">
                  {takeoff.material_stats.drawer_front_count} fronts ·{" "}
                  {takeoff.material_stats.front_sqft} ft²
                </div>
                <div className="text-xs text-zinc-500">Drawer fronts</div>
              </div>
              <div>
                <div className="text-lg font-semibold">
                  ~{takeoff.material_stats.face_sheets} sheets
                </div>
                <div className="text-xs text-zinc-500">
                  Door/front material (4×8 @{" "}
                  {takeoff.material_stats.waste_pct}% waste)
                </div>
              </div>
            </div>
            {takeoff.material_stats.skipped_no_dims > 0 && (
              <p className="mt-2 text-xs text-amber-700">
                {takeoff.material_stats.skipped_no_dims} box(es) missing
                dimensions — not counted above.
              </p>
            )}
          </Card>
        )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card className="max-h-[75vh] overflow-auto">
          {lines.some((l) => l.readImageKey != null) ? (
            <SourceBoxPanel
              takeoffId={takeoffId}
              lines={lines}
              selectedId={selectedLine?.id ?? null}
              editable={takeoff.status !== "approved"}
              onSelect={(id) => {
                if (id == null) return;
                const idx = lines.findIndex((l) => l.id === id);
                if (idx !== -1) setSelected(idx);
              }}
              onPatchBbox={(id, bbox) => patchLine.mutate({ id, patch: { bbox } })}
              onCreate={(body) => createLine.mutate(body)}
            />
          ) : (
            <>
              <h2 className="mb-2 text-sm font-semibold text-zinc-500">
                Source
                {selectedLine?.sourcePage
                  ? ` — page ${selectedLine.sourcePage}`
                  : ""}
              </h2>
              {pageImage.data?.url ? (
                <img
                  src={pageImage.data.url}
                  alt="source page"
                  className="w-full border border-zinc-200"
                />
              ) : (
                <p className="text-sm text-zinc-400">
                  {selectedLine?.sourcePage
                    ? "Loading page image…"
                    : "No page image for this line (spreadsheet/manual source)."}
                </p>
              )}
            </>
          )}
        </Card>

        <Card className="max-h-[75vh] overflow-auto p-0">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-white">
              <tr className="border-b border-zinc-200 text-left text-zinc-500">
                <th className="px-2 py-2">Tag</th>
                <th className="px-2 py-2">Qty</th>
                <th className="px-2 py-2">W×H×D</th>
                <th className="px-2 py-2">Material / Finish</th>
                <th className="px-2 py-2">Conf</th>
                <th className="px-2 py-2">Match</th>
                <th className="px-2 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {lines.map((l, i) => (
                <LineRow
                  key={l.id}
                  line={l}
                  selected={i === selected}
                  editing={editing && i === selected}
                  onSelect={() => setSelected(i)}
                  onEdit={() => {
                    setSelected(i);
                    setEditing(true);
                  }}
                  onSave={(patch) => {
                    patchLine.mutate({ id: l.id, patch });
                    setEditing(false);
                  }}
                  onCancel={() => setEditing(false)}
                  onDelete={() => deleteLine.mutate(l.id)}
                />
              ))}
              {lines.length === 0 && takeoff.status !== "processing" && (
                <tr>
                  <td colSpan={7} className="px-3 py-6 text-center text-zinc-400">
                    No lines extracted.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </Card>
      </div>

      {unmatched.length > 0 && (
        <Card className="mt-4 border-red-200">
          <h2 className="mb-2 text-sm font-semibold text-red-700">
            Unmatched bucket ({unmatched.length}) — assign a product line
          </h2>
          {unmatched.map((l) => (
            <div
              key={l.id}
              className="flex items-center gap-3 border-t border-zinc-100 py-2 text-sm"
            >
              <span className="w-24 font-medium">{l.tag ?? l.category}</span>
              <span className="flex-1 text-zinc-500">{l.unmatchedReason}</span>
              <select
                className="rounded-md border border-zinc-300 px-2 py-1 text-sm"
                defaultValue=""
                onChange={(e) => {
                  if (!e.target.value) return;
                  patchLine.mutate({
                    id: l.id,
                    patch: {
                      product_line_id: e.target.value,
                      resolved_params: {
                        product_line_id: e.target.value,
                        qty: l.qty,
                        width_in: l.widthIn,
                        height_in: l.heightIn,
                        depth_in: l.depthIn,
                        material: l.material ?? "",
                        finish: l.finish,
                        assembled: l.assembled ?? false,
                      },
                    },
                  });
                }}
              >
                <option value="">Pick product line…</option>
                {(productLines.data ?? []).map((pl) => (
                  <option key={pl.id} value={pl.id}>
                    {pl.name}
                  </option>
                ))}
              </select>
            </div>
          ))}
        </Card>
      )}
    </div>
  );
}

function LineRow({
  line,
  selected,
  editing,
  onSelect,
  onEdit,
  onSave,
  onCancel,
  onDelete,
}: {
  line: Line;
  selected: boolean;
  editing: boolean;
  onSelect: () => void;
  onEdit: () => void;
  onSave: (patch: Record<string, unknown>) => void;
  onCancel: () => void;
  onDelete: () => void;
}) {
  const [draft, setDraft] = useState<Record<string, string>>({});

  useEffect(() => {
    if (editing) {
      setDraft({
        tag: line.tag ?? "",
        qty: String(line.qty),
        width_in: line.widthIn != null ? String(line.widthIn) : "",
        height_in: line.heightIn != null ? String(line.heightIn) : "",
        depth_in: line.depthIn != null ? String(line.depthIn) : "",
        material: line.material ?? "",
        finish: line.finish ?? "",
      });
    }
  }, [editing, line]);

  const lowConfidence = line.confidence < LOW_CONFIDENCE;

  if (editing) {
    const num = (s: string) => (s.trim() === "" ? null : Number(s));
    return (
      <tr className="border-b border-zinc-100 bg-blue-50">
        <td className="px-2 py-1">
          <Input
            className="w-20"
            value={draft.tag ?? ""}
            autoFocus
            onChange={(e) => setDraft({ ...draft, tag: e.target.value })}
          />
        </td>
        <td className="px-2 py-1">
          <Input
            className="w-14"
            value={draft.qty ?? ""}
            onChange={(e) => setDraft({ ...draft, qty: e.target.value })}
          />
        </td>
        <td className="space-x-1 whitespace-nowrap px-2 py-1">
          {(["width_in", "height_in", "depth_in"] as const).map((f) => (
            <Input
              key={f}
              className="w-14"
              value={draft[f] ?? ""}
              onChange={(e) => setDraft({ ...draft, [f]: e.target.value })}
            />
          ))}
        </td>
        <td className="space-x-1 whitespace-nowrap px-2 py-1">
          <Input
            className="w-20"
            value={draft.material ?? ""}
            onChange={(e) => setDraft({ ...draft, material: e.target.value })}
          />
          <Input
            className="w-20"
            value={draft.finish ?? ""}
            onChange={(e) => setDraft({ ...draft, finish: e.target.value })}
          />
        </td>
        <td colSpan={3} className="space-x-1 whitespace-nowrap px-2 py-1">
          <Button
            variant="primary"
            onClick={() =>
              onSave({
                tag: draft.tag || null,
                qty: Number(draft.qty) || line.qty,
                width_in: num(draft.width_in),
                height_in: num(draft.height_in),
                depth_in: num(draft.depth_in),
                material: draft.material || null,
                finish: draft.finish || null,
                confidence: 1,
              })
            }
          >
            Save
          </Button>
          <Button variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
        </td>
      </tr>
    );
  }

  return (
    <tr
      onClick={onSelect}
      onDoubleClick={onEdit}
      className={`cursor-pointer border-b border-zinc-100 ${
        selected ? "bg-blue-50" : lowConfidence ? "bg-amber-50" : ""
      }`}
    >
      <td className="px-2 py-1.5 font-medium">
        {line.tag ?? "—"}
        {line.room && <span className="ml-1 text-xs text-zinc-400">{line.room}</span>}
      </td>
      <td className="px-2 py-1.5">{line.qty}</td>
      <td className="whitespace-nowrap px-2 py-1.5">
        {[line.widthIn, line.heightIn, line.depthIn]
          .map((d) => (d == null ? "—" : d))
          .join(" × ")}
      </td>
      <td className="px-2 py-1.5">
        {line.material ?? "—"}
        {line.finish ? ` / ${line.finish}` : ""}
      </td>
      <td className="px-2 py-1.5">
        <Badge tone={lowConfidence ? "amber" : "green"}>
          {Math.round(line.confidence * 100)}%
        </Badge>
      </td>
      <td className="px-2 py-1.5">
        {line.productLineId ? (
          <Badge tone="green">{line.productLineId}</Badge>
        ) : (
          <Badge tone="red">unmatched</Badge>
        )}
      </td>
      <td className="px-2 py-1.5 text-right">
        <Button
          variant="ghost"
          className="px-1.5 py-0.5 text-red-600"
          title="Delete line (and its box)"
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
