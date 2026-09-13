import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { betaDetectRoute } from "../main";
import { apiGet, apiSend } from "../api";
import {
  Badge,
  Button,
  Card,
  errorMessage,
  PageTitle,
  StatusPill,
  Stepper,
  useToast,
} from "../ui";
import { categoryLabel } from "../labels";
import {
  BoxOverlay,
  categoryColor,
  type BBox,
  type OverlayBox,
} from "../components/BoxOverlay";
import { ReadingProgress, type Progress } from "../components/ReadingProgress";

// The wizard — the one reading flow for PDFs (2026-09-14):
//   1 Draw   — the drawings Scribe located arrive as boxes; adjust, add, remove
//   2 Detect — the model counts and labels the cabinets inside each box
//   3 Build  — one measuring pass sizes everything → priced takeoff → review
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
  selectedPages: { page: number; class?: string }[] | null;
  progress: Progress | null;
  updatedAt: string;
  error: string | null;
  lines?: unknown[];
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
  kind: string | null;
  status: "drawn" | "queued" | "running" | "done" | "error";
  items: DetectionItem[] | null;
  error: string | null;
}

const RELEVANT_CLASSES = new Set([
  "floor_plan",
  "kitchen_or_millwork_elevation",
  "cabinet_schedule_table",
]);

const STEPS = [
  { key: "draw", label: "Mark", hint: "Boxes over every cabinet area" },
  { key: "detect", label: "Find", hint: "The model labels what's inside" },
  { key: "build", label: "Build", hint: "Measure, price, review" },
];

export function BetaDetectPage() {
  const { takeoffId } = betaDetectRoute.useParams();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const toast = useToast();
  const [step, setStep] = useState(1);
  const [page, setPage] = useState<number | null>(null);
  const [selectedBoxId, setSelectedBoxId] = useState<string | null>(null);
  const [building, setBuilding] = useState(false);

  const takeoffQ = useQuery({
    queryKey: ["takeoff", takeoffId],
    queryFn: () => apiGet<TakeoffDetail>(`/takeoffs/${takeoffId}`),
    refetchInterval: (query) =>
      query.state.data?.status === "processing" ? 3000 : false,
  });
  const status = takeoffQ.data?.status;

  // This screen owns awaiting_boxes (and re-marking a reviewed takeoff);
  // anything upstream goes back to its own gate.
  useEffect(() => {
    if (status === "awaiting_pages") {
      navigate({ to: "/takeoffs/$takeoffId/pages", params: { takeoffId } });
    }
  }, [status, navigate, takeoffId]);

  // All detections for the takeoff; poll while any are in flight.
  const detectionsQ = useQuery({
    queryKey: ["detections", takeoffId],
    queryFn: () => apiGet<Detection[]>(`/takeoffs/${takeoffId}/detections`),
    enabled: status != null && status !== "processing" && status !== "awaiting_pages",
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

  // The pages in play: what the human picked at the page step (or, for a
  // re-mark from review, whatever already has boxes or looks relevant).
  const pagesInPlay = useMemo(() => {
    const t = takeoffQ.data;
    if (!t) return [] as number[];
    const picked = (t.selectedPages ?? []).map((p) => p.page);
    const withDetections = detections.map((d) => d.page);
    const relevant = (t.classifiedPages ?? [])
      .filter((c) => RELEVANT_CLASSES.has(c.class))
      .map((c) => c.page);
    const set = new Set([...picked, ...withDetections]);
    if (set.size === 0) for (const p of relevant) set.add(p);
    return [...set].sort((a, b) => a - b);
  }, [takeoffQ.data, detections]);

  useEffect(() => {
    if (page == null && pagesInPlay.length > 0) setPage(pagesInPlay[0]);
    if (page != null && pagesInPlay.length > 0 && !pagesInPlay.includes(page))
      setPage(pagesInPlay[0]);
  }, [pagesInPlay, page]);

  // Land on the right step for the state of the boxes.
  useEffect(() => {
    if (detections.length === 0) return;
    if (detections.some((d) => d.status === "done") && step === 1) setStep(2);
  }, [detections, step]);

  const imageQ = useQuery({
    queryKey: ["beta-page", takeoffId, page],
    enabled: page != null && status !== "processing",
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
    onError: (e) => toast.error("Box not added", errorMessage(e)),
  });

  const runDetect = useMutation({
    mutationFn: () =>
      apiSend<{ queued: number }>(
        "POST",
        `/takeoffs/${takeoffId}/detections/run`
      ),
    onSuccess: invalidate,
    onError: (e) => toast.error("Couldn't start finding cabinets", errorMessage(e)),
  });

  const removeItem = useMutation({
    mutationFn: ({ detectionId, index }: { detectionId: string; index: number }) =>
      apiSend(
        "DELETE",
        `/takeoffs/${takeoffId}/detections/${detectionId}/items/${index}`
      ),
    onSuccess: invalidate,
    onError: (e) => toast.error("Not removed", errorMessage(e)),
  });

  const removeDetection = useMutation({
    mutationFn: (detectionId: string) =>
      apiSend("DELETE", `/takeoffs/${takeoffId}/detections/${detectionId}`),
    onSuccess: invalidate,
    onError: (e) => toast.error("Box not removed", errorMessage(e)),
  });

  const build = useMutation({
    mutationFn: () => apiSend("POST", `/takeoffs/${takeoffId}/build-takeoff`),
    onSuccess: () => {
      setBuilding(false);
      qc.invalidateQueries({ queryKey: ["takeoff", takeoffId] });
      navigate({ to: "/takeoffs/$takeoffId", params: { takeoffId } });
    },
    onError: (e) => {
      setBuilding(false);
      toast.error("Couldn't build the takeoff", errorMessage(e));
    },
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
          boxes.push({ id: boxId!, bbox: item.bbox_2d, category: item.category, label: item.label });
        }
        rows.push({ boxId, detectionId: d.id, itemIndex: i, item });
      });
    }
    return { boxes, rows };
  }, [pageDetections]);

  const drawnCount = detections.filter((d) => d.status === "drawn").length;
  const inFlight = detections.some((d) => d.status === "queued" || d.status === "running");
  const detectedCount = detections.reduce(
    (n, d) => n + (d.status === "done" ? (d.items?.length ?? 0) : 0),
    0
  );
  const failedCount = detections.filter((d) => d.status === "error").length;

  if (takeoffQ.isLoading) return <div className="text-muted">Loading…</div>;
  if (takeoffQ.isError) return <div className="text-bad">{String(takeoffQ.error)}</div>;
  const takeoff = takeoffQ.data!;

  if (takeoff.sourceKind !== "pdf") {
    return (
      <Card>
        <p className="text-sm text-muted">Marking cabinet areas only applies to PDF plan sets.</p>
      </Card>
    );
  }

  if (takeoff.status === "processing") {
    return (
      <div>
        <PageTitle eyebrow="Reading">{takeoff.sourceFilename ?? takeoffId.slice(0, 8)}</PageTitle>
        <ReadingProgress
          title={building || build.isPending ? "Building your takeoff" : "Finding the drawings"}
          progress={takeoff.progress}
          sourceKind={takeoff.sourceKind}
          pageCount={takeoff.pageCount}
          fallbackStartedAt={takeoff.updatedAt}
        />
      </div>
    );
  }

  const hasLines = (takeoff.lines?.length ?? 0) > 0 && takeoff.status !== "awaiting_boxes";

  const stepAction = (() => {
    switch (step) {
      case 1:
        return (
          <Button
            variant="primary"
            disabled={drawnCount === 0 || runDetect.isPending}
            loading={runDetect.isPending}
            onClick={() => {
              runDetect.mutate();
              setStep(2);
            }}
          >
            Find cabinets in {drawnCount} box{drawnCount === 1 ? "" : "es"} →
          </Button>
        );
      case 2:
        return (
          <div className="flex items-center gap-2">
            {drawnCount > 0 && (
              <Button loading={runDetect.isPending} onClick={() => runDetect.mutate()}>
                Find in {drawnCount} new box{drawnCount === 1 ? "" : "es"}
              </Button>
            )}
            <Button
              variant="primary"
              disabled={detectedCount === 0 || inFlight}
              onClick={() => setStep(3)}
            >
              Check {detectedCount} cabinets →
            </Button>
          </div>
        );
      default:
        return (
          <Button
            variant="primary"
            disabled={detectedCount === 0 || inFlight || build.isPending || building}
            loading={building || build.isPending}
            onClick={() => {
              if (
                hasLines &&
                !window.confirm(
                  `Build the takeoff from ${detectedCount} cabinets? This replaces the current breakdown.`
                )
              )
                return;
              setBuilding(true);
              build.mutate();
            }}
          >
            Build takeoff ({detectedCount} cabinets)
          </Button>
        );
    }
  })();

  return (
    <div>
      <PageTitle
        eyebrow="Mark the cabinet areas"
        actions={
          <div className="flex items-center gap-2">
            <StatusPill status={takeoff.status} />
            <Link to="/takeoffs/$takeoffId/pages" params={{ takeoffId }}>
              <Button variant="quiet">← Pages</Button>
            </Link>
            {stepAction}
          </div>
        }
      >
        {takeoff.sourceFilename ?? takeoffId.slice(0, 8)}
      </PageTitle>

      <div className="mb-4">
        <Stepper steps={STEPS} current={step - 1} onSelect={(i) => setStep(i + 1)} />
      </div>

      {takeoff.error && <p className="mb-2 text-sm text-bad">{takeoff.error}</p>}

      <p className="mb-3 text-sm text-muted">
        {step === 1 &&
          (detections.length > 0
            ? `Scribe found ${detections.length} drawing${detections.length === 1 ? "" : "s"} on your pages and boxed them. Move or resize a box, drag to add one over anything it missed, or clear a page. Zoom with ⌘/ctrl + scroll; hold space to pan.`
            : "Drag boxes over every area that contains cabinets. Zoom with ⌘/ctrl + scroll; hold space to pan.")}
        {step === 2 &&
          "Each cabinet the model found is a colored dot — hover one to see its label and box, ✕ removes a wrong one. Draw more boxes any time and find again."}
        {step === 3 &&
          "Check the counts, then build: one measuring pass sizes every cabinet from the printed dimensions where they exist, and you can fix anything on the review screen."}
      </p>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[9rem_1fr]">
        {/* Page rail */}
        <div className="flex max-h-[80vh] flex-row gap-2 overflow-auto lg:flex-col">
          {pagesInPlay.map((p) => {
            const count = detections
              .filter((d) => d.page === p)
              .reduce(
                (n, d) =>
                  n + (d.status === "done" ? (d.items?.length ?? 0) : d.status === "drawn" ? 1 : 0),
                0
              );
            return (
              <div
                key={p}
                className={`w-28 shrink-0 cursor-pointer rounded-lg border bg-paper p-1 transition-colors lg:w-auto ${
                  p === page ? "border-accent ring-2 ring-accent-soft" : "border-rule hover:border-muted"
                }`}
                onClick={() => {
                  setPage(p);
                  setSelectedBoxId(null);
                }}
              >
                <PageThumb takeoffId={takeoffId} page={p} />
                <div className="mt-0.5 flex items-center justify-between px-0.5">
                  <span className="font-mono text-xs text-muted">p{p}</span>
                  {count > 0 && <Badge tone="blue">{count}</Badge>}
                </div>
              </div>
            );
          })}
          {pagesInPlay.length === 0 && (
            <p className="text-sm text-faint">No pages selected — go back to Pages.</p>
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
                <p className="animate-pulse text-sm text-muted">
                  {page == null ? "Select a page." : `Rendering page ${page} at high resolution…`}
                </p>
              </div>
            )}
            {(inFlight || building || build.isPending) && (
              <div className="absolute bottom-3 right-3 flex items-center gap-2 rounded-full border border-blue bg-paper px-3 py-1.5 shadow-md">
                <span className="size-3 animate-spin rounded-full border-2 border-blue border-t-transparent" />
                <span className="text-sm font-medium text-blue">
                  {inFlight ? "Finding cabinets…" : "Building takeoff…"}
                </span>
              </div>
            )}
          </Card>

          <Card className="mt-4">
            <div className="mb-2 flex items-center justify-between">
              <h2 className="text-sm font-semibold text-muted">
                Page {page ?? "—"}: {pageDetections.filter((d) => d.status === "drawn").length} box
                {pageDetections.filter((d) => d.status === "drawn").length === 1 ? "" : "es"} to scan · {rows.length} cabinet{rows.length === 1 ? "" : "s"} found
              </h2>
              {pageDetections.length > 0 && (
                <Button
                  variant="quiet"
                  size="sm"
                  className="text-bad"
                  onClick={() => pageDetections.forEach((d) => removeDetection.mutate(d.id))}
                >
                  Clear page
                </Button>
              )}
            </div>
            {rows.length === 0 ? (
              <p className="text-sm text-faint">
                {pageDetections.some((d) => d.status === "drawn")
                  ? "Boxes are ready — find the cabinets inside them (the button top right)."
                  : "Drag over the drawing to mark a cabinet area."}
              </p>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-rule text-left font-mono text-[11px] uppercase tracking-wider text-muted">
                    <th className="py-1 pr-2">Label</th>
                    <th className="py-1 pr-2">Type</th>
                    <th className="py-1 pr-2">Conf</th>
                    <th className="py-1" />
                  </tr>
                </thead>
                <tbody>
                  {rows.map(({ boxId, detectionId, itemIndex, item }) => (
                    <tr
                      key={boxId ?? `${detectionId}-${itemIndex}`}
                      className={`cursor-pointer border-b border-rule-soft ${
                        boxId != null && boxId === selectedBoxId ? "bg-accent-soft" : "hover:bg-rule-soft"
                      }`}
                      onClick={() => setSelectedBoxId(boxId)}
                    >
                      <td className="py-1 pr-2 font-medium">
                        <span
                          className="mr-1.5 inline-block size-2.5 rounded-sm"
                          style={{ backgroundColor: categoryColor(item.category) }}
                        />
                        {item.label || "—"}
                      </td>
                      <td className="py-1 pr-2 text-muted">{categoryLabel(item.category)}</td>
                      <td className="py-1 pr-2 font-mono tabular-nums text-muted">
                        {Math.round(item.confidence * 100)}%
                      </td>
                      <td className="py-1 text-right">
                        <Button
                          variant="quiet"
                          size="sm"
                          className="text-bad"
                          title="Remove this cabinet"
                          onClick={(e) => {
                            e.stopPropagation();
                            removeItem.mutate({ detectionId, index: itemIndex });
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
            {failedCount > 0 && (
              <p className="mt-2 text-xs text-bad">
                {pageDetections
                  .filter((d) => d.status === "error")
                  .map((d) => `A box couldn't be scanned: ${d.error ?? "unknown"}`)
                  .join(" · ")}
              </p>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}

function PageThumb({ takeoffId, page }: { takeoffId: string; page: number }) {
  const q = useQuery({
    queryKey: ["thumb", takeoffId, page],
    queryFn: () => apiGet<{ url: string }>(`/takeoffs/${takeoffId}/thumbs/${page}/image`),
    staleTime: 10 * 60 * 1000,
  });
  if (!q.data?.url) {
    return <div className="aspect-[3/4] w-full animate-pulse rounded bg-rule-soft" />;
  }
  return (
    <img src={q.data.url} alt={`page ${page}`} loading="lazy" className="w-full rounded border border-rule-soft object-contain" />
  );
}
