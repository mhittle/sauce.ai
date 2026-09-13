import { useEffect, useMemo, useRef, useState } from "react";
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
  type OverlayArea,
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
  builtAt: string | null;
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
  const [hoveredArea, setHoveredArea] = useState<string | null>(null);
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

  // Drawing → panel: a selected cabinet scrolls its row into view.
  useEffect(() => {
    if (!selectedBoxId) return;
    document
      .querySelector(`[data-box-id="${CSS.escape(selectedBoxId)}"]`)
      ?.scrollIntoView({ block: "nearest" });
  }, [selectedBoxId]);

  // A build this screen started has finished (processing → review): hand off
  // to the review. Also covers a build that had bounced here after a rollback.
  const sawProcessing = useRef(false);
  useEffect(() => {
    if (status === "processing") sawProcessing.current = true;
    if (status === "review" && sawProcessing.current) {
      sawProcessing.current = false;
      navigate({ to: "/takeoffs/$takeoffId", params: { takeoffId } });
    }
  }, [status, navigate, takeoffId]);

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
    onError: (e) => toast.error("Area not added", errorMessage(e)),
  });

  // Marking the same drawing twice finds the same cabinets twice. A new box
  // that mostly covers (or is mostly covered by) an existing area is refused
  // with a pointer at the area, instead of silently doubling the count.
  function tryDraw(rect: BBox) {
    const existing = detections.filter((d) => d.page === page);
    for (const [i, d] of existing.entries()) {
      const frac = overlapFraction(rect, d.rect);
      if (frac >= 0.5) {
        toast.error(
          `That overlaps Area ${areaNumber(d, existing, i)} by ${Math.round(frac * 100)}%`,
          "The same cabinets would be found twice. Adjust the new box, or remove the existing area first (its × button)."
        );
        setHoveredArea(d.id);
        window.setTimeout(() => setHoveredArea(null), 2500);
        return;
      }
    }
    draw.mutate(rect);
  }

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

  const moveArea = useMutation({
    mutationFn: ({ detectionId, rect }: { detectionId: string; rect: BBox }) =>
      apiSend<{ removed_lines: number }>("PATCH", `/takeoffs/${takeoffId}/detections/${detectionId}`, { rect }),
    onSuccess: (r) => {
      invalidate();
      qc.invalidateQueries({ queryKey: ["takeoff", takeoffId] });
      if (r.removed_lines > 0)
        toast.info(`Area changed — its ${r.removed_lines} cabinet${r.removed_lines === 1 ? "" : "s"} were removed from the takeoff. Find and build it again.`);
    },
    onError: (e) => toast.error("Area not changed", errorMessage(e)),
  });

  const setKind = useMutation({
    mutationFn: ({ detectionId, kind }: { detectionId: string; kind: "plan" | "elevation" }) =>
      apiSend("PATCH", `/takeoffs/${takeoffId}/detections/${detectionId}`, { kind }),
    onSuccess: invalidate,
    onError: (e) => toast.error("Not changed", errorMessage(e)),
  });

  // Removing an area removes the cabinets it found (approved decision).
  function confirmRemove(id: string) {
    const d = detections.find((x) => x.id === id);
    const n = d?.status === "done" ? (d.items?.length ?? 0) : 0;
    if (
      d?.builtAt &&
      !window.confirm(`Remove this area and the ${n} cabinet${n === 1 ? "" : "s"} it put in the takeoff?`)
    )
      return;
    removeDetection.mutate(id);
  }

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

  // Marked areas on the current page, numbered in creation order.
  const areas: OverlayArea[] = useMemo(
    () =>
      pageDetections.map((d, i) => ({
        id: d.id,
        bbox: d.rect,
        label: `Area ${i + 1}`,
        note:
          d.status === "done"
            ? `${d.items?.length ?? 0} found${d.builtAt ? " · in takeoff" : ""}`
            : d.status === "error"
              ? "failed"
              : d.status === "drawn"
                ? "not scanned"
                : "scanning…",
        highlighted: d.id === hoveredArea,
      })),
    [pageDetections, hoveredArea]
  );

  const unbuilt = detections.filter((d) => d.status === "done" && !d.builtAt);
  const unbuiltCabinets = unbuilt.reduce((n, d) => n + (d.items?.length ?? 0), 0);
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
          progress={takeoff.progress}
          sourceKind={takeoff.sourceKind}
          pageCount={takeoff.pageCount}
          fallbackStartedAt={takeoff.updatedAt}
        />
      </div>
    );
  }

  const hasLines = (takeoff.lines?.length ?? 0) > 0 && takeoff.status !== "awaiting_boxes";
  const locked = takeoff.status === "approved";

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
        if (unbuilt.length === 0 && (hasLines || takeoff.status === "review") && !inFlight) {
          return (
            <Link to="/takeoffs/$takeoffId" params={{ takeoffId }}>
              <Button variant="primary">Open the review →</Button>
            </Link>
          );
        }
        return (
          <Button
            variant="primary"
            disabled={unbuilt.length === 0 || inFlight || build.isPending || building || locked}
            loading={building || build.isPending}
            title={
              unbuilt.length === 0
                ? "Every scanned area is already in the takeoff — change or add an area first"
                : undefined
            }
            onClick={() => {
              setBuilding(true);
              build.mutate();
            }}
          >
            {hasLines
              ? `Update ${unbuilt.length} area${unbuilt.length === 1 ? "" : "s"} (${unbuiltCabinets} cabinets)`
              : `Build takeoff (${unbuiltCabinets} cabinets)`}
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
      {locked && (
        <div className="mb-3 flex items-center gap-3 rounded-lg border border-warn bg-warn-soft px-4 py-2 text-sm text-warn">
          This takeoff is approved, so its areas are locked. Reopen it from the review screen to make changes.
          <Link to="/takeoffs/$takeoffId" params={{ takeoffId }} className="ml-auto underline">
            Open the review
          </Link>
        </div>
      )}

      <p className="mb-3 text-sm text-muted">
        {step === 1 &&
          "Drag a box over each drawing that contains cabinets — one area per elevation or plan view. Each area is scanned once, so don't mark the same drawing twice. × removes an area; the plan / elevation toggle sets how it's read. Zoom with ⌘/ctrl + scroll; hold space to pan."}
        {step === 2 &&
          "Each cabinet the model found is a colored dot — hover one to see its label and box, ✕ removes a wrong one. Draw more boxes any time and find again."}
        {step === 3 &&
          (hasLines
            ? "Only new or changed areas are rebuilt — cabinets from untouched areas keep every edit you made on the review screen."
            : "Check the counts, then build: one measuring pass sizes every cabinet from the printed dimensions where they exist, and you can fix anything on the review screen.")}
      </p>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[9rem_minmax(0,1fr)_22rem]">
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

        {/* Canvas */}
        <div className="min-w-0">
          <Card className="relative">
            {page != null && imageQ.data?.url ? (
              <BoxOverlay
                src={imageQ.data.url}
                boxes={boxes}
                areas={areas}
                selectedId={selectedBoxId}
                drawMode
                maxHeight="72vh"
                onSelect={setSelectedBoxId}
                onChange={() => {}}
                onCreate={tryDraw}
                onAreaHover={setHoveredArea}
                onAreaRemove={(id) => confirmRemove(id)}
                onAreaChange={(id, rect) => {
                  const d = detections.find((x) => x.id === id);
                  if (
                    d?.builtAt &&
                    !window.confirm("Changing this area removes the cabinets it found from the takeoff until you find and build it again. Continue?")
                  ) {
                    invalidate();
                    return;
                  }
                  moveArea.mutate({ detectionId: id, rect });
                }}
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
        </div>

        {/* Side panel: areas, then the cabinets found — scrolls on its own */}
        <div className="min-w-0">
          <Card className="flex max-h-[80vh] flex-col overflow-hidden p-0">
            <div className="border-b border-rule px-3 py-2">
              <h2 className="text-sm font-semibold text-muted">
                Page {page ?? "—"}: {areas.length} marked area{areas.length === 1 ? "" : "s"} · {rows.length} cabinet{rows.length === 1 ? "" : "s"} found
              </h2>
            </div>
            <div className="min-h-0 flex-1 overflow-auto">
              <div className="border-b border-rule-soft px-3 py-2">
                <div className="mb-1 flex items-center justify-between">
                  <span className="font-mono text-[11px] uppercase tracking-wider text-muted">Areas</span>
                  {pageDetections.length > 0 && (
                    <Button
                      variant="quiet"
                      size="sm"
                      className="text-bad"
                      onClick={() => {
                        if (window.confirm(`Remove all ${pageDetections.length} area(s) on page ${page}?`))
                          pageDetections.forEach((d) => removeDetection.mutate(d.id));
                      }}
                    >
                      Clear page
                    </Button>
                  )}
                </div>
                {areas.length === 0 ? (
                  <p className="text-xs text-faint">Drag over the drawing to mark a cabinet area.</p>
                ) : (
                  <ul className="space-y-1" aria-label="Marked areas">
                    {areas.map((a) => {
                      const d = pageDetections.find((x) => x.id === a.id);
                      return (
                        <li
                          key={a.id}
                          onMouseEnter={() => setHoveredArea(a.id)}
                          onMouseLeave={() => setHoveredArea(null)}
                          className={`flex items-center gap-2 rounded-md border px-2 py-1 text-xs ${
                            a.highlighted ? "border-accent bg-accent-soft" : "border-rule bg-paper"
                          }`}
                        >
                          <span className="inline-block size-2 shrink-0 rounded-sm bg-accent" />
                          <span className="font-medium text-ink">{a.label}</span>
                          <span className="text-muted">{a.note}</span>
                          <select
                            aria-label={`${a.label} kind`}
                            title="How this area is read: an elevation is one cabinet per box, a plan is a run to split"
                            className="ml-auto rounded border border-rule bg-paper px-1 py-0.5 text-[11px] text-muted"
                            value={d?.kind === "plan" ? "plan" : "elevation"}
                            onChange={(e) =>
                              setKind.mutate({ detectionId: a.id, kind: e.target.value as "plan" | "elevation" })
                            }
                          >
                            <option value="elevation">elevation</option>
                            <option value="plan">plan</option>
                          </select>
                          <button
                            type="button"
                            aria-label={`Remove ${a.label}`}
                            title="Remove this area"
                            className="rounded px-1 text-muted hover:bg-bad-soft hover:text-bad"
                            onClick={() => confirmRemove(a.id)}
                          >
                            ×
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </div>
              {rows.length === 0 ? (
                <p className="px-3 py-3 text-sm text-faint">
                  {pageDetections.some((d) => d.status === "drawn")
                    ? "Areas are ready — find the cabinets inside them (the button top right)."
                    : "No cabinets found on this page yet."}
                </p>
              ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-rule text-left font-mono text-[11px] uppercase tracking-wider text-muted">
                    <th className="px-3 py-1">Cabinet</th>
                    <th className="py-1 pr-2">Type</th>
                    <th className="py-1 pr-2">Conf</th>
                    <th className="py-1 pr-2" />
                  </tr>
                </thead>
                <tbody>
                  {rows.map(({ boxId, detectionId, itemIndex, item }) => (
                    <tr
                      key={boxId ?? `${detectionId}-${itemIndex}`}
                      data-box-id={boxId ?? undefined}
                      className={`cursor-pointer border-b border-rule-soft ${
                        boxId != null && boxId === selectedBoxId ? "bg-accent-soft" : "hover:bg-rule-soft"
                      }`}
                      onClick={() => setSelectedBoxId(boxId)}
                    >
                      <td className="px-3 py-1 font-medium">
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
                <p className="px-3 py-2 text-xs text-bad">
                  {pageDetections
                    .filter((d) => d.status === "error")
                    .map((d) => `An area couldn't be scanned: ${d.error ?? "unknown"}`)
                    .join(" · ")}
                </p>
              )}
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}

// Fraction of the SMALLER box covered by the intersection (1 = one box sits
// entirely inside the other).
function overlapFraction(a: BBox, b: BBox): number {
  const ax0 = Math.min(a[0], a[2]), ax1 = Math.max(a[0], a[2]);
  const ay0 = Math.min(a[1], a[3]), ay1 = Math.max(a[1], a[3]);
  const bx0 = Math.min(b[0], b[2]), bx1 = Math.max(b[0], b[2]);
  const by0 = Math.min(b[1], b[3]), by1 = Math.max(b[1], b[3]);
  const iw = Math.max(0, Math.min(ax1, bx1) - Math.max(ax0, bx0));
  const ih = Math.max(0, Math.min(ay1, by1) - Math.max(ay0, by0));
  const inter = iw * ih;
  const smaller = Math.min((ax1 - ax0) * (ay1 - ay0), (bx1 - bx0) * (by1 - by0));
  return smaller > 0 ? inter / smaller : 0;
}

// Areas are numbered per page in creation order — the number the chip shows.
function areaNumber(d: { id: string }, pageDetections: { id: string }[], fallbackIndex: number): number {
  const i = pageDetections.findIndex((x) => x.id === d.id);
  return (i === -1 ? fallbackIndex : i) + 1;
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
