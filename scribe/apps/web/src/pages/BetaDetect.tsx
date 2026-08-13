import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { betaDetectRoute } from "../main";
import { apiGet, apiSend } from "../api";
import { Badge, Button, Card, PageTitle } from "../ui";
import {
  BoxOverlay,
  categoryColor,
  type BBox,
  type OverlayBox,
} from "../components/BoxOverlay";

// Beta drag-to-detect view: pick a page, drag a rectangle over the drawing,
// and the model scans that region for cabinets and draws a labeled box over
// each one. Read-only with respect to the real takeoff — detections live in
// their own table and never touch takeoff_lines or takeoff status.

interface PageClassification {
  page: number;
  class: string;
  confidence: number;
}

interface TakeoffDetail {
  id: string;
  sourceFilename: string | null;
  sourceKind: string;
  status: string;
  pageCount: number | null;
  classifiedPages: PageClassification[] | null;
}

interface DetectionItem {
  label: string;
  category: string;
  width_in: number | null;
  height_in: number | null;
  confidence: number;
  bbox_2d: BBox | null;
}

interface Detection {
  id: string;
  page: number;
  rect: BBox;
  status: "queued" | "running" | "done" | "error";
  items: DetectionItem[] | null;
  error: string | null;
}

const CLASS_SHORT: Record<string, string> = {
  floor_plan: "plan",
  kitchen_or_millwork_elevation: "elevation",
  cabinet_schedule_table: "schedule",
  finish_schedule: "finishes",
  cover_index: "cover",
  spec_text: "spec",
};

export function BetaDetectPage() {
  const { takeoffId } = betaDetectRoute.useParams();
  const qc = useQueryClient();
  const [page, setPage] = useState(1);
  const [selectedBoxId, setSelectedBoxId] = useState<string | null>(null);

  const takeoffQ = useQuery({
    queryKey: ["takeoff", takeoffId],
    queryFn: () => apiGet<TakeoffDetail>(`/takeoffs/${takeoffId}`),
  });

  // The display render is produced on demand: {url: null} means the worker is
  // still rasterizing — keep polling.
  const imageQ = useQuery({
    queryKey: ["beta-page", takeoffId, page],
    queryFn: () =>
      apiGet<{ url: string | null }>(
        `/takeoffs/${takeoffId}/beta/pages/${page}/image`
      ),
    refetchInterval: (query) => (query.state.data?.url == null ? 2000 : false),
    staleTime: 10 * 60 * 1000,
  });

  const detectionsQ = useQuery({
    queryKey: ["detections", takeoffId, page],
    queryFn: () =>
      apiGet<Detection[]>(`/takeoffs/${takeoffId}/detections?page=${page}`),
    refetchInterval: (query) =>
      (query.state.data ?? []).some(
        (d) => d.status === "queued" || d.status === "running"
      )
        ? 2000
        : false,
  });
  const detections = useMemo(() => detectionsQ.data ?? [], [detectionsQ.data]);

  const scan = useMutation({
    mutationFn: (rect: BBox) =>
      apiSend<Detection>("POST", `/takeoffs/${takeoffId}/detections`, {
        page,
        rect,
      }),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["detections", takeoffId, page] }),
  });

  const remove = useMutation({
    mutationFn: (detectionId: string) =>
      apiSend("DELETE", `/takeoffs/${takeoffId}/detections/${detectionId}`),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["detections", takeoffId, page] }),
  });

  // Flatten every done detection's items into overlay boxes; the scanned rects
  // themselves render as faint dashed outlines underneath.
  const { boxes, rows } = useMemo(() => {
    const boxes: OverlayBox[] = [];
    const rows: {
      boxId: string | null;
      detectionId: string;
      item: DetectionItem;
    }[] = [];
    for (const d of detections) {
      if (d.status !== "done") continue;
      (d.items ?? []).forEach((item, i) => {
        const boxId = item.bbox_2d ? `${d.id}:${i}` : null;
        if (item.bbox_2d) {
          boxes.push({
            id: boxId!,
            bbox: item.bbox_2d,
            category: item.category,
            label: item.label,
          });
        }
        rows.push({ boxId, detectionId: d.id, item });
      });
    }
    return { boxes, rows };
  }, [detections]);

  const scanning =
    scan.isPending ||
    detections.some((d) => d.status === "queued" || d.status === "running");

  if (takeoffQ.isLoading) return <div className="text-zinc-500">Loading…</div>;
  if (takeoffQ.isError)
    return <div className="text-red-600">{String(takeoffQ.error)}</div>;
  const takeoff = takeoffQ.data!;
  const pageCount = takeoff.pageCount ?? 0;
  const classByPage = new Map(
    (takeoff.classifiedPages ?? []).map((c) => [c.page, c.class])
  );

  if (takeoff.sourceKind !== "pdf") {
    return (
      <Card>
        <p className="text-sm text-zinc-500">
          The detect view only works on PDF plan sets.
        </p>
      </Card>
    );
  }

  return (
    <div>
      <PageTitle
        actions={
          <Link to="/takeoffs/$takeoffId" params={{ takeoffId }}>
            <Button>← Back to takeoff</Button>
          </Link>
        }
      >
        Detect: {takeoff.sourceFilename ?? takeoffId.slice(0, 8)}{" "}
        <Badge tone="blue">beta</Badge>
      </PageTitle>

      <p className="mb-3 text-sm text-zinc-500">
        Pick a page, then drag a rectangle over the drawing — the model scans
        that region and draws a box over every cabinet it finds.
      </p>

      {(scan.isError || remove.isError) && (
        <p className="mb-2 text-sm text-red-600">
          {String(scan.error ?? remove.error)}
        </p>
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[9rem_1fr]">
        {/* Page rail */}
        <div className="flex max-h-[80vh] flex-row gap-2 overflow-auto lg:flex-col">
          {Array.from({ length: pageCount }, (_, i) => i + 1).map((p) => (
            <div
              key={p}
              className={`w-28 shrink-0 cursor-pointer rounded-lg border bg-white p-1 shadow-sm transition-colors lg:w-auto ${
                p === page
                  ? "border-blue-500 ring-2 ring-blue-200"
                  : "border-zinc-200 hover:border-zinc-400"
              }`}
              onClick={() => {
                setPage(p);
                setSelectedBoxId(null);
              }}
            >
              <PageThumb takeoffId={takeoffId} page={p} />
              <div className="mt-0.5 flex items-center justify-between px-0.5">
                <span className="text-xs font-medium text-zinc-600">p{p}</span>
                <span className="truncate text-[10px] text-zinc-400">
                  {CLASS_SHORT[classByPage.get(p) ?? ""] ?? ""}
                </span>
              </div>
            </div>
          ))}
          {pageCount === 0 && (
            <p className="text-sm text-zinc-400">
              No pages yet — the upload is still being prepared.
            </p>
          )}
        </div>

        {/* Canvas + results */}
        <div className="min-w-0">
          <Card className="relative">
            {imageQ.data?.url ? (
              <div className="max-h-[75vh] overflow-auto">
                <BoxOverlay
                  src={imageQ.data.url}
                  boxes={boxes}
                  underlays={detections
                    .filter((d) => d.status === "done")
                    .map((d) => d.rect)}
                  selectedId={selectedBoxId}
                  drawMode
                  onSelect={setSelectedBoxId}
                  onChange={() => {}}
                  onCreate={(bbox) => scan.mutate(bbox)}
                />
              </div>
            ) : (
              <div className="flex h-96 items-center justify-center">
                <p className="animate-pulse text-sm text-zinc-500">
                  Rendering page {page} at high resolution…
                </p>
              </div>
            )}
            {scanning && (
              <div className="absolute bottom-3 right-3 flex items-center gap-2 rounded-full border border-blue-200 bg-white px-3 py-1.5 shadow-md">
                <span className="h-3 w-3 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
                <span className="text-sm font-medium text-blue-700">
                  Finding cabinets…
                </span>
              </div>
            )}
          </Card>

          <Card className="mt-4">
            <h2 className="mb-2 text-sm font-semibold text-zinc-500">
              Detected cabinets — page {page}
            </h2>
            {rows.length === 0 && !scanning ? (
              <p className="text-sm text-zinc-400">
                Nothing detected yet. Drag over a kitchen elevation or plan
                region to scan it.
              </p>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-zinc-200 text-left text-xs text-zinc-500">
                    <th className="py-1 pr-2">Label</th>
                    <th className="py-1 pr-2">Category</th>
                    <th className="py-1 pr-2">Size (in)</th>
                    <th className="py-1 pr-2">Confidence</th>
                    <th className="py-1" />
                  </tr>
                </thead>
                <tbody>
                  {rows.map(({ boxId, detectionId, item }, i) => (
                    <tr
                      key={boxId ?? `${detectionId}-nobox-${i}`}
                      className={`cursor-pointer border-b border-zinc-100 ${
                        boxId != null && boxId === selectedBoxId
                          ? "bg-blue-50"
                          : "hover:bg-zinc-50"
                      }`}
                      onClick={() => setSelectedBoxId(boxId)}
                    >
                      <td className="py-1 pr-2 font-medium">
                        <span
                          className="mr-1.5 inline-block h-2.5 w-2.5 rounded-sm"
                          style={{ backgroundColor: categoryColor(item.category) }}
                        />
                        {item.label || "—"}
                      </td>
                      <td className="py-1 pr-2 text-zinc-600">
                        {item.category}
                      </td>
                      <td className="py-1 pr-2 text-zinc-600">
                        {item.width_in != null && item.height_in != null
                          ? `${item.width_in} × ${item.height_in}`
                          : "—"}
                      </td>
                      <td className="py-1 pr-2 text-zinc-600">
                        {Math.round(item.confidence * 100)}%
                      </td>
                      <td className="py-1 text-right">
                        <Button
                          variant="ghost"
                          className="text-xs text-red-600"
                          onClick={(e) => {
                            e.stopPropagation();
                            remove.mutate(detectionId);
                          }}
                          title="Delete this scan (removes all its boxes)"
                        >
                          ✕
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {detections.some((d) => d.status === "error") && (
              <p className="mt-2 text-xs text-red-600">
                {detections
                  .filter((d) => d.status === "error")
                  .map((d) => `Scan failed: ${d.error ?? "unknown error"}`)
                  .join(" · ")}
              </p>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}

// Same lazy thumbnail fetcher as the page picker's (kept local — the picker
// doesn't export it).
function PageThumb({ takeoffId, page }: { takeoffId: string; page: number }) {
  const q = useQuery({
    queryKey: ["thumb", takeoffId, page],
    queryFn: () =>
      apiGet<{ url: string }>(`/takeoffs/${takeoffId}/thumbs/${page}/image`),
    staleTime: 10 * 60 * 1000,
  });
  if (!q.data?.url) {
    return <div className="aspect-[3/4] w-full animate-pulse rounded bg-zinc-100" />;
  }
  return (
    <img
      src={q.data.url}
      alt={`page ${page}`}
      loading="lazy"
      className="w-full rounded border border-zinc-100 object-contain"
    />
  );
}
