import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { betaDetectRoute } from "../main";
import { apiGet, apiSend } from "../api";
import { Badge, Button, Card, PageTitle } from "../ui";
import {
  BoxOverlay,
  categoryColor,
  type BBox,
  type OverlayBox,
} from "../components/BoxOverlay";

// Beta detect wizard (4 steps):
//   1 Pages  — choose the relevant pages
//   2 Draw   — drag boxes over cabinet areas (stored, nothing sent)
//   3 Detect — send all drawn boxes; model counts/labels cabinets, no dims
//   4 Build  — one whole-input measurements pass → priced takeoff (replaces
//              existing lines, confirmed)
// Steps are navigation, not hard gates — move back and forth freely.

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
  error: string | null;
}

interface DetectionItem {
  label: string;
  category: string;
  confidence: number;
  bbox_2d: BBox | null;
}

interface Detection {
  id: string;
  page: number;
  rect: BBox;
  status: "drawn" | "queued" | "running" | "done" | "error";
  items: DetectionItem[] | null;
  error: string | null;
}

const RELEVANT_CLASSES = new Set([
  "floor_plan",
  "kitchen_or_millwork_elevation",
  "cabinet_schedule_table",
]);

const CLASS_SHORT: Record<string, string> = {
  floor_plan: "plan",
  kitchen_or_millwork_elevation: "elevation",
  cabinet_schedule_table: "schedule",
  finish_schedule: "finishes",
  cover_index: "cover",
  spec_text: "spec",
};

const STEPS = ["Pages", "Draw", "Detect", "Build"] as const;

export function BetaDetectPage() {
  const { takeoffId } = betaDetectRoute.useParams();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [step, setStep] = useState(1);
  const [selectedPages, setSelectedPages] = useState<number[]>([]);
  const [page, setPage] = useState<number | null>(null);
  const [selectedBoxId, setSelectedBoxId] = useState<string | null>(null);
  const [building, setBuilding] = useState(false);

  const takeoffQ = useQuery({
    queryKey: ["takeoff", takeoffId],
    queryFn: () => apiGet<TakeoffDetail>(`/takeoffs/${takeoffId}`),
  });

  // All detections for the takeoff; poll while any are in flight.
  const detectionsQ = useQuery({
    queryKey: ["detections", takeoffId],
    queryFn: () => apiGet<Detection[]>(`/takeoffs/${takeoffId}/detections`),
    refetchInterval: (query) =>
      (query.state.data ?? []).some(
        (d) => d.status === "queued" || d.status === "running"
      )
        ? 2000
        : false,
  });
  const detections = useMemo(() => detectionsQ.data ?? [], [detectionsQ.data]);
  const invalidate = () =>
    qc.invalidateQueries({ queryKey: ["detections", takeoffId] });

  // Pre-select pages that already have detections or look relevant.
  useEffect(() => {
    if (selectedPages.length > 0 || !takeoffQ.data) return;
    const withDetections = new Set(detections.map((d) => d.page));
    const relevant = (takeoffQ.data.classifiedPages ?? [])
      .filter((c) => RELEVANT_CLASSES.has(c.class))
      .map((c) => c.page);
    const pre = [...new Set([...withDetections, ...relevant])].sort(
      (a, b) => a - b
    );
    if (pre.length > 0) setSelectedPages(pre);
    if (withDetections.size > 0) setStep(2);
  }, [takeoffQ.data, detections, selectedPages.length]);

  useEffect(() => {
    if (page == null && selectedPages.length > 0) setPage(selectedPages[0]);
    if (page != null && !selectedPages.includes(page))
      setPage(selectedPages[0] ?? null);
  }, [selectedPages, page]);

  const imageQ = useQuery({
    queryKey: ["beta-page", takeoffId, page],
    enabled: page != null,
    queryFn: () =>
      apiGet<{ url: string | null }>(
        `/takeoffs/${takeoffId}/beta/pages/${page}/image`
      ),
    refetchInterval: (query) => (query.state.data?.url == null ? 2000 : false),
    staleTime: 10 * 60 * 1000,
  });

  const draw = useMutation({
    mutationFn: (rect: BBox) =>
      apiSend<Detection>("POST", `/takeoffs/${takeoffId}/detections`, {
        page,
        rect,
      }),
    onSuccess: invalidate,
  });

  const runDetect = useMutation({
    mutationFn: () =>
      apiSend<{ queued: number }>(
        "POST",
        `/takeoffs/${takeoffId}/detections/run`
      ),
    onSuccess: invalidate,
  });

  const removeItem = useMutation({
    mutationFn: ({
      detectionId,
      index,
    }: {
      detectionId: string;
      index: number;
    }) =>
      apiSend(
        "DELETE",
        `/takeoffs/${takeoffId}/detections/${detectionId}/items/${index}`
      ),
    onSuccess: invalidate,
  });

  const removeDetection = useMutation({
    mutationFn: (detectionId: string) =>
      apiSend("DELETE", `/takeoffs/${takeoffId}/detections/${detectionId}`),
    onSuccess: invalidate,
  });

  const build = useMutation({
    mutationFn: () =>
      apiSend("POST", `/takeoffs/${takeoffId}/build-takeoff`),
    onSuccess: () => {
      setBuilding(false);
      navigate({ to: "/takeoffs/$takeoffId", params: { takeoffId } });
    },
    onError: () => setBuilding(false),
  });

  const pageDetections = useMemo(
    () => detections.filter((d) => d.page === page),
    [detections, page]
  );

  // Overlay boxes: detected items for the current page.
  const { boxes, rows } = useMemo(() => {
    const boxes: OverlayBox[] = [];
    const rows: {
      boxId: string | null;
      detectionId: string;
      itemIndex: number;
      item: DetectionItem;
    }[] = [];
    for (const d of pageDetections) {
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
        rows.push({ boxId, detectionId: d.id, itemIndex: i, item });
      });
    }
    return { boxes, rows };
  }, [pageDetections]);

  const drawnCount = detections.filter((d) => d.status === "drawn").length;
  const inFlight = detections.some(
    (d) => d.status === "queued" || d.status === "running"
  );
  const detectedCount = detections.reduce(
    (n, d) => n + (d.status === "done" ? (d.items?.length ?? 0) : 0),
    0
  );

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

  const anyError = draw.error ?? runDetect.error ?? removeItem.error ??
    removeDetection.error ?? build.error;

  const stepAction = (() => {
    switch (step) {
      case 1:
        return (
          <Button
            variant="primary"
            disabled={selectedPages.length === 0}
            onClick={() => setStep(2)}
          >
            Draw boxes on {selectedPages.length} page
            {selectedPages.length === 1 ? "" : "s"} →
          </Button>
        );
      case 2:
        return (
          <Button
            variant="primary"
            disabled={drawnCount === 0}
            onClick={() => {
              runDetect.mutate();
              setStep(3);
            }}
          >
            Detect cabinets in {drawnCount} box{drawnCount === 1 ? "" : "es"} →
          </Button>
        );
      case 3:
        return (
          <div className="flex items-center gap-2">
            {drawnCount > 0 && (
              <Button disabled={runDetect.isPending} onClick={() => runDetect.mutate()}>
                Detect {drawnCount} new box{drawnCount === 1 ? "" : "es"}
              </Button>
            )}
            <Button
              variant="primary"
              disabled={detectedCount === 0 || inFlight}
              onClick={() => setStep(4)}
            >
              Review {detectedCount} cabinets →
            </Button>
          </div>
        );
      default:
        return (
          <Button
            variant="primary"
            disabled={detectedCount === 0 || inFlight || build.isPending || building}
            onClick={() => {
              if (
                window.confirm(
                  `Build the takeoff from ${detectedCount} detected cabinets? This REPLACES the takeoff's current line items.`
                )
              ) {
                setBuilding(true);
                build.mutate();
              }
            }}
          >
            {building || build.isPending
              ? "Building…"
              : `Build takeoff (${detectedCount} cabinets)`}
          </Button>
        );
    }
  })();

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

      {/* Stepper */}
      <div className="mb-4 flex items-center gap-1">
        {STEPS.map((label, i) => {
          const n = i + 1;
          return (
            <button
              key={label}
              onClick={() => setStep(n)}
              className={`flex items-center gap-1.5 rounded-full px-3 py-1 text-sm font-medium transition-colors ${
                step === n
                  ? "bg-zinc-900 text-white"
                  : "text-zinc-500 hover:bg-zinc-100"
              }`}
            >
              <span
                className={`flex h-5 w-5 items-center justify-center rounded-full text-xs ${
                  step === n ? "bg-white text-zinc-900" : "bg-zinc-200"
                }`}
              >
                {n}
              </span>
              {label}
            </button>
          );
        })}
        <div className="ml-auto">{stepAction}</div>
      </div>

      {anyError && (
        <p className="mb-2 text-sm text-red-600">{String(anyError)}</p>
      )}
      {takeoff.error && (
        <p className="mb-2 text-sm text-red-600">{takeoff.error}</p>
      )}

      {step === 1 ? (
        <>
          <p className="mb-3 text-sm text-zinc-500">
            Select the pages that show cabinets (plans, elevations, schedules).
          </p>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
            {Array.from({ length: pageCount }, (_, i) => i + 1).map((p) => {
              const selected = selectedPages.includes(p);
              return (
                <div
                  key={p}
                  className={`cursor-pointer rounded-lg border bg-white p-2 shadow-sm transition-colors ${
                    selected
                      ? "border-blue-500 ring-2 ring-blue-200"
                      : "border-zinc-200 hover:border-zinc-400"
                  }`}
                  onClick={() =>
                    setSelectedPages((prev) =>
                      selected
                        ? prev.filter((x) => x !== p)
                        : [...prev, p].sort((a, b) => a - b)
                    )
                  }
                >
                  <div className="relative">
                    <PageThumb takeoffId={takeoffId} page={p} />
                    {selected && (
                      <span className="absolute right-1 top-1 flex h-6 w-6 items-center justify-center rounded-full bg-blue-600 text-sm font-bold text-white">
                        ✓
                      </span>
                    )}
                  </div>
                  <div className="mt-1 flex items-center justify-between">
                    <span className="text-xs font-medium text-zinc-600">
                      p{p}
                    </span>
                    <span className="truncate text-xs text-zinc-400">
                      {CLASS_SHORT[classByPage.get(p) ?? ""] ?? ""}
                    </span>
                  </div>
                </div>
              );
            })}
            {pageCount === 0 && (
              <Card className="col-span-full">
                <p className="text-sm text-zinc-400">
                  No pages yet — the upload is still being prepared.
                </p>
              </Card>
            )}
          </div>
        </>
      ) : (
        <>
          <p className="mb-3 text-sm text-zinc-500">
            {step === 2 &&
              "Drag boxes over every area that contains cabinets. Nothing is sent yet. Zoom with ⌘/ctrl + scroll (or the buttons); hold space to drag the sheet around."}
            {step === 3 &&
              "Detected cabinets appear as colored dots — hover one to see its label and box, ✕ removes a wrong one. Draw more boxes any time."}
            {step === 4 &&
              "Check the counts below, then build the takeoff — one measurements pass sizes every cabinet (printed dims where available, standard sizes otherwise)."}
          </p>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-[9rem_1fr]">
            {/* Page rail (selected pages only) */}
            <div className="flex max-h-[80vh] flex-row gap-2 overflow-auto lg:flex-col">
              {selectedPages.map((p) => {
                const count = detections
                  .filter((d) => d.page === p)
                  .reduce(
                    (n, d) =>
                      n +
                      (d.status === "done"
                        ? (d.items?.length ?? 0)
                        : d.status === "drawn"
                          ? 1
                          : 0),
                    0
                  );
                return (
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
                      <span className="text-xs font-medium text-zinc-600">
                        p{p}
                      </span>
                      {count > 0 && <Badge tone="blue">{count}</Badge>}
                    </div>
                  </div>
                );
              })}
              {selectedPages.length === 0 && (
                <p className="text-sm text-zinc-400">
                  No pages selected — go back to step 1.
                </p>
              )}
            </div>

            {/* Canvas + results */}
            <div className="min-w-0">
              <Card className="relative">
                {page != null && imageQ.data?.url ? (
                  <BoxOverlay
                    src={imageQ.data.url}
                    boxes={boxes}
                    underlays={pageDetections.map((d) => d.rect)}
                    selectedId={selectedBoxId}
                    drawMode
                    maxHeight="72vh"
                    onSelect={setSelectedBoxId}
                    onChange={() => {}}
                    onCreate={(bbox) => draw.mutate(bbox)}
                  />
                ) : (
                  <div className="flex h-96 items-center justify-center">
                    <p className="animate-pulse text-sm text-zinc-500">
                      {page == null
                        ? "Select a page."
                        : `Rendering page ${page} at high resolution…`}
                    </p>
                  </div>
                )}
                {(inFlight || building || build.isPending) && (
                  <div className="absolute bottom-3 right-3 flex items-center gap-2 rounded-full border border-blue-200 bg-white px-3 py-1.5 shadow-md">
                    <span className="h-3 w-3 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
                    <span className="text-sm font-medium text-blue-700">
                      {inFlight ? "Finding cabinets…" : "Building takeoff…"}
                    </span>
                  </div>
                )}
              </Card>

              <Card className="mt-4">
                <div className="mb-2 flex items-center justify-between">
                  <h2 className="text-sm font-semibold text-zinc-500">
                    Page {page ?? "—"}:{" "}
                    {pageDetections.filter((d) => d.status === "drawn").length}{" "}
                    drawn · {rows.length} detected
                  </h2>
                  {pageDetections.length > 0 && (
                    <Button
                      variant="ghost"
                      className="text-xs text-red-600"
                      onClick={() =>
                        pageDetections.forEach((d) =>
                          removeDetection.mutate(d.id)
                        )
                      }
                    >
                      Clear page
                    </Button>
                  )}
                </div>
                {rows.length === 0 ? (
                  <p className="text-sm text-zinc-400">
                    {pageDetections.some((d) => d.status === "drawn")
                      ? "Boxes drawn — run detection (step 3) to find the cabinets inside them."
                      : "Drag over the drawing to mark cabinet areas."}
                  </p>
                ) : (
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-zinc-200 text-left text-xs text-zinc-500">
                        <th className="py-1 pr-2">Label</th>
                        <th className="py-1 pr-2">Category</th>
                        <th className="py-1 pr-2">Confidence</th>
                        <th className="py-1" />
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map(({ boxId, detectionId, itemIndex, item }) => (
                        <tr
                          key={boxId ?? `${detectionId}-${itemIndex}`}
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
                              style={{
                                backgroundColor: categoryColor(item.category),
                              }}
                            />
                            {item.label || "—"}
                          </td>
                          <td className="py-1 pr-2 text-zinc-600">
                            {item.category}
                          </td>
                          <td className="py-1 pr-2 text-zinc-600">
                            {Math.round(item.confidence * 100)}%
                          </td>
                          <td className="py-1 text-right">
                            <Button
                              variant="ghost"
                              className="text-xs text-red-600"
                              title="Remove this cabinet"
                              onClick={(e) => {
                                e.stopPropagation();
                                removeItem.mutate({
                                  detectionId,
                                  index: itemIndex,
                                });
                              }}
                            >
                              ✕
                            </Button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
                {pageDetections.some((d) => d.status === "error") && (
                  <p className="mt-2 text-xs text-red-600">
                    {pageDetections
                      .filter((d) => d.status === "error")
                      .map((d) => `Scan failed: ${d.error ?? "unknown"}`)
                      .join(" · ")}
                  </p>
                )}
              </Card>
            </div>
          </div>
        </>
      )}
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
