import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { takeoffReviewRoute } from "../main";
import { API_URL, apiGet, apiSend, formatUsd } from "../api";
import {
  Button,
  Dialog,
  errorMessage,
  Input,
  Kbd,
  PageTitle,
  Select,
  StatusPill,
  useToast,
} from "../ui";
import { Tour } from "../components/Tour";
import { categoryDotClass, categoryLabel } from "../labels";
import { SourceBoxPanel } from "../components/SourceBoxPanel";
import { ReadingProgress, type Progress } from "../components/ReadingProgress";
import { TechnicalDetail, useIsAdmin } from "../components/TechnicalDetail";
import { friendlyError, friendlyNotes } from "../messages";

// The review screen is the product (PRD §7.2): the drawing on the left with
// one dot per cabinet, the breakdown on the right grouped by room, every cell
// editable in place, and the live Base estimate in the bar at the bottom so
// the reviewer sees what each correction does to the number.

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
  rawModelOutput: { expanded?: boolean; parent?: string } | null;
  updatedAt: string;
}

interface Tier {
  label: string;
  box_count: number;
  total_cents: number;
}

interface TakeoffDetail {
  id: string;
  sourceFilename: string | null;
  sourceKind: string;
  status: string;
  pageCount: number | null;
  progress: Progress | null;
  error: string | null;
  createdAt: string;
  updatedAt: string;
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
  quote_tiers: Record<"low" | "medium" | "high", Tier> | null;
}

interface ProductLineRow {
  id: string;
  name: string;
}

const LOW_CONFIDENCE = 0.8;
const UNDO_MS = 8000;
const NO_ROOM = "No room";

type Filter = "all" | "flagged" | "unmatched";

function isFace(l: Line): boolean {
  return l.rawModelOutput?.expanded === true;
}
function isFlagged(l: Line): boolean {
  return l.confidence < LOW_CONFIDENCE || l.productLineId == null;
}

export function TakeoffReviewPage() {
  const { takeoffId } = takeoffReviewRoute.useParams();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const toast = useToast();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [showFaces, setShowFaces] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  // Soft delete: the row disappears now, the DELETE fires after UNDO_MS
  // unless the toast's Undo is clicked.
  const [hidden, setHidden] = useState<Set<string>>(() => new Set());
  const pendingDeletes = useRef(new Map<string, number>());

  const q = useQuery({
    queryKey: ["takeoff", takeoffId],
    queryFn: () => apiGet<TakeoffDetail>(`/takeoffs/${takeoffId}`),
    refetchInterval: (query) =>
      query.state.data?.status === "processing" ? 3000 : false,
  });
  const status = q.data?.status;

  // One flow: pages → mark cabinets (wizard) → review. Each gate owns its
  // own screen; this page forwards to whichever the status demands.
  useEffect(() => {
    if (status === "awaiting_pages") {
      navigate({ to: "/takeoffs/$takeoffId/pages", params: { takeoffId } });
    } else if (status === "awaiting_boxes") {
      navigate({ to: "/takeoffs/$takeoffId/detect", params: { takeoffId }, search: { pages: undefined } });
    }
  }, [status, navigate, takeoffId]);

  const productLines = useQuery({
    queryKey: ["product-lines"],
    queryFn: () => apiGet<ProductLineRow[]>("/product-lines"),
    staleTime: 10 * 60 * 1000,
  });
  const productName = useMemo(
    () => new Map((productLines.data ?? []).map((p) => [p.id, p.name])),
    [productLines.data]
  );

  const invalidate = useCallback(
    () => qc.invalidateQueries({ queryKey: ["takeoff", takeoffId] }),
    [qc, takeoffId]
  );

  const patchLine = useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: Record<string, unknown> }) =>
      apiSend("PATCH", `/takeoff-lines/${id}`, patch),
    onSuccess: invalidate,
    onError: (e) => toast.error("Line not saved", errorMessage(e)),
  });

  const deleteLine = useMutation({
    mutationFn: (id: string) => apiSend("DELETE", `/takeoff-lines/${id}`),
    onSuccess: invalidate,
    onError: (e, id) => {
      setHidden((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
      toast.error("Line not deleted", errorMessage(e));
    },
  });

  const createLine = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      apiSend<Line>("POST", "/takeoff-lines", { takeoff_id: takeoffId, ...body }),
    onSuccess: (line) => {
      invalidate();
      setSelectedId(line.id);
      toast.success("Cabinet added");
    },
    onError: (e) => toast.error("Cabinet not added", errorMessage(e)),
  });

  const acceptAll = useMutation({
    mutationFn: () =>
      apiSend<{ accepted: number }>("POST", `/takeoffs/${takeoffId}/accept-lines`, {}),
    onSuccess: (r) => {
      invalidate();
      toast.success(`${r.accepted} line${r.accepted === 1 ? "" : "s"} accepted`);
    },
    onError: (e) => toast.error("Couldn't accept lines", errorMessage(e)),
  });

  const approve = useMutation({
    mutationFn: () => apiSend("POST", `/takeoffs/${takeoffId}/approve`),
    onError: (e) => toast.error("Couldn't approve", errorMessage(e)),
  });

  const remeasure = useMutation({
    mutationFn: () => apiSend("POST", `/takeoffs/${takeoffId}/remeasure`),
    onSuccess: () => {
      invalidate();
      toast.info("Measuring again — this takes a minute or two");
    },
    onError: (e) => toast.error("Couldn't start measuring", errorMessage(e)),
  });

  const reopen = useMutation({
    mutationFn: () => apiSend("POST", `/takeoffs/${takeoffId}/reopen`),
    onSuccess: () => {
      invalidate();
      toast.success("Reopened — you can change areas and lines again");
    },
    onError: (e) => toast.error("Couldn't reopen", errorMessage(e)),
  });

  const createQuote = useMutation({
    mutationFn: (name: string) =>
      apiSend<{ id: string }>("POST", "/quotes", { takeoff_id: takeoffId, name }),
    onError: (e) => toast.error("Couldn't create the quote", errorMessage(e)),
  });

  // "Looks right → Quote": ask for a name, approve (if needed), open the quote.
  const [finishing, setFinishing] = useState(false);
  const [naming, setNaming] = useState(false);
  const [quoteName, setQuoteName] = useState("");
  function openNaming() {
    const file = q.data?.sourceFilename ?? "";
    setQuoteName(file.replace(/\.[a-z0-9]+$/i, "") || "Quote");
    setNaming(true);
  }
  async function finish(name: string) {
    setNaming(false);
    setFinishing(true);
    try {
      if (q.data?.status !== "approved") {
        await approve.mutateAsync();
        invalidate();
      }
      const quote = await createQuote.mutateAsync(name.trim() || "Quote");
      navigate({ to: "/quotes/$quoteId", params: { quoteId: quote.id } });
    } catch {
      // toasts already shown by the mutations
    } finally {
      setFinishing(false);
    }
  }

  // ---- derived data -------------------------------------------------------
  const allLines = useMemo(() => q.data?.lines ?? [], [q.data?.lines]);
  const cabinets = useMemo(
    () => allLines.filter((l) => !isFace(l) && !hidden.has(l.id)),
    [allLines, hidden]
  );
  const facesByParent = useMemo(() => {
    const m = new Map<string, Line[]>();
    for (const l of allLines) {
      if (!isFace(l)) continue;
      const parent = l.rawModelOutput?.parent ?? "";
      m.set(parent, [...(m.get(parent) ?? []), l]);
    }
    return m;
  }, [allLines]);
  const flagged = useMemo(() => cabinets.filter(isFlagged), [cabinets]);
  const unmatched = useMemo(() => cabinets.filter((l) => !l.productLineId), [cabinets]);
  const acceptable = useMemo(
    () => cabinets.filter((l) => l.confidence >= LOW_CONFIDENCE && l.confidence < 1),
    [cabinets]
  );
  const visible = useMemo(() => {
    switch (filter) {
      case "flagged":
        return flagged;
      case "unmatched":
        return unmatched;
      default:
        return cabinets;
    }
  }, [filter, cabinets, flagged, unmatched]);
  const groups = useMemo(() => {
    const order: string[] = [];
    const by = new Map<string, Line[]>();
    for (const l of visible) {
      const room = l.room?.trim() || NO_ROOM;
      if (!by.has(room)) {
        by.set(room, []);
        order.push(room);
      }
      by.get(room)!.push(l);
    }
    return order.map((room) => ({ room, lines: by.get(room)! }));
  }, [visible]);
  const categoryCounts = useMemo(() => {
    const m = new Map<string, number>();
    for (const l of cabinets) m.set(l.category, (m.get(l.category) ?? 0) + l.qty);
    return [...m.entries()].sort((a, b) => b[1] - a[1]);
  }, [cabinets]);
  // Customer-facing notes; developer-only notes show for admins with the
  // raw text behind a toggle (messages.ts).
  const isAdmin = useIsAdmin();
  const docFlags = useMemo(
    () =>
      friendlyNotes(
        [
          ...(q.data?.docSummary?.uncertainties ?? []),
          ...(q.data?.docSummary?.warnings ?? []),
        ],
        isAdmin
      ),
    [q.data?.docSummary, isAdmin]
  );

  const selectedLine = cabinets.find((l) => l.id === selectedId) ?? null;

  // ---- soft delete with undo -----------------------------------------------
  const requestDelete = useCallback(
    (id: string) => {
      if (pendingDeletes.current.has(id)) return;
      setHidden((prev) => new Set(prev).add(id));
      const timer = window.setTimeout(() => {
        pendingDeletes.current.delete(id);
        deleteLine.mutate(id);
      }, UNDO_MS);
      pendingDeletes.current.set(id, timer);
      const line = allLines.find((l) => l.id === id);
      toast.push({
        title: `Removed ${line?.tag ?? categoryLabel(line?.category ?? "")}`,
        tone: "neutral",
        ttlMs: UNDO_MS,
        action: {
          label: "Undo",
          onClick: () => {
            const t = pendingDeletes.current.get(id);
            if (t != null) window.clearTimeout(t);
            pendingDeletes.current.delete(id);
            setHidden((prev) => {
              const next = new Set(prev);
              next.delete(id);
              return next;
            });
          },
        },
      });
    },
    [allLines, deleteLine, toast]
  );
  // Leaving the page flushes pending deletes immediately.
  useEffect(() => {
    const pending = pendingDeletes.current;
    return () => {
      for (const [id, t] of pending) {
        window.clearTimeout(t);
        apiSend("DELETE", `/takeoff-lines/${id}`).catch(() => {});
      }
      pending.clear();
    };
  }, []);

  // ---- keyboard ------------------------------------------------------------
  const flatIds = useMemo(() => visible.map((l) => l.id), [visible]);
  useEffect(() => {
    function onKey(ev: KeyboardEvent) {
      const target = ev.target as HTMLElement;
      const inField = ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
      if (ev.key === "?" && !inField) {
        setHelpOpen((o) => !o);
        ev.preventDefault();
        return;
      }
      if (inField || helpOpen) return;
      const idx = selectedId ? flatIds.indexOf(selectedId) : -1;
      if (ev.key === "ArrowDown" || ev.key === "j") {
        setSelectedId(flatIds[Math.min(idx + 1, flatIds.length - 1)] ?? null);
        ev.preventDefault();
      } else if (ev.key === "ArrowUp" || ev.key === "k") {
        setSelectedId(flatIds[Math.max(idx - 1, 0)] ?? null);
        ev.preventDefault();
      } else if (ev.key === "Enter" && selectedLine) {
        if (selectedLine.confidence < 1) {
          patchLine.mutate({ id: selectedLine.id, patch: { confidence: 1 } });
        }
        setSelectedId(flatIds[Math.min(idx + 1, flatIds.length - 1)] ?? null);
        ev.preventDefault();
      } else if ((ev.key === "Delete" || ev.key === "Backspace") && selectedLine) {
        requestDelete(selectedLine.id);
        setSelectedId(flatIds[idx + 1] ?? flatIds[idx - 1] ?? null);
        ev.preventDefault();
      } else if (ev.key === "e" && selectedLine) {
        const input = document.querySelector<HTMLInputElement>(
          `[data-line-id="${selectedLine.id}"] input`
        );
        input?.focus();
        ev.preventDefault();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [flatIds, selectedId, selectedLine, helpOpen, patchLine, requestDelete]);

  // Keep the selected row in view when selection moves by keyboard.
  useEffect(() => {
    if (!selectedId) return;
    document
      .querySelector(`[data-line-id="${selectedId}"]`)
      ?.scrollIntoView({ block: "nearest" });
  }, [selectedId]);

  const pageImage = useQuery({
    queryKey: ["page-image", takeoffId, selectedLine?.sourcePage],
    queryFn: () =>
      apiGet<{ url: string }>(
        `/takeoffs/${takeoffId}/pages/${selectedLine!.sourcePage}/image`
      ),
    enabled: selectedLine?.sourcePage != null && !cabinets.some((l) => l.readImageKey),
    staleTime: 10 * 60 * 1000,
  });

  // ---- render --------------------------------------------------------------
  if (q.isLoading) return <div className="text-muted">Loading…</div>;
  if (q.isError) return <div className="text-bad">{String(q.error)}</div>;
  const takeoff = q.data!;

  if (takeoff.status === "processing") {
    return (
      <div>
        <PageTitle eyebrow="Reading">
          {takeoff.sourceFilename ?? takeoffId.slice(0, 8)}
        </PageTitle>
        <ReadingProgress
          progress={takeoff.progress}
          sourceKind={takeoff.sourceKind}
          pageCount={takeoff.pageCount}
          fallbackStartedAt={takeoff.updatedAt}
        />
      </div>
    );
  }

  if (takeoff.status === "failed") {
    return (
      <div>
        <PageTitle eyebrow="Failed" actions={<StatusPill status="failed" />}>
          {takeoff.sourceFilename ?? takeoffId.slice(0, 8)}
        </PageTitle>
        <div className="max-w-xl rounded-lg border border-bad bg-bad-soft p-4 text-sm text-bad">
          {takeoff.error
            ? friendlyError(takeoff.error).text
            : "The read failed. Upload the file again, or pick different pages."}
          <TechnicalDetail
            details={[takeoff.error, ...(takeoff.docSummary?.warnings ?? [])].filter(
              (d): d is string => !!d
            )}
          />
        </div>
      </div>
    );
  }

  const editable = takeoff.status !== "approved";
  const hasReadImages = cabinets.some((l) => l.readImageKey != null);
  const tiers = takeoff.quote_tiers;
  const base = tiers?.low ?? null;
  const flagCount = flagged.length + docFlags.length;

  return (
    <div className="flex h-[calc(100vh-5.5rem)] min-h-[32rem] flex-col">
      <Tour screen="review" />
      <PageTitle
        eyebrow={editable ? "Review the breakdown" : "Approved"}
        actions={
          <div className="flex items-center gap-2">
            <StatusPill status={takeoff.status} />
            <details className="relative">
              <summary className="list-none">
                <Button variant="quiet" aria-haspopup="menu">
                  More ▾
                </Button>
              </summary>
              <div
                role="menu"
                className="absolute right-0 z-30 mt-1 w-64 rounded-md border border-rule bg-paper p-1 shadow-md"
              >
                <a
                  role="menuitem"
                  className="block rounded px-2 py-1.5 text-sm text-ink hover:bg-rule-soft"
                  href={`${API_URL}/takeoffs/${takeoffId}/export.csv?template=${encodeURIComponent("Mozaik (default)")}`}
                >
                  Export for Mozaik (CSV)
                </a>
                <a
                  role="menuitem"
                  className="block rounded px-2 py-1.5 text-sm text-ink hover:bg-rule-soft"
                  href={`${API_URL}/takeoffs/${takeoffId}/export.csv?template=${encodeURIComponent("KCD (default)")}`}
                >
                  Export for KCD (CSV)
                </a>
                {takeoff.sourceKind === "pdf" && takeoff.status === "review" && (
                  <>
                    <div className="my-1 border-t border-rule-soft" />
                    <Link
                      role="menuitem"
                      to="/takeoffs/$takeoffId/detect"
                      params={{ takeoffId }}
                      search={{ pages: undefined }}
                      className="block rounded px-2 py-1.5 text-sm text-ink hover:bg-rule-soft"
                    >
                      Add or change areas…
                    </Link>
                  </>
                )}
                {takeoff.status === "approved" && (
                  <>
                    <div className="my-1 border-t border-rule-soft" />
                    <button
                      role="menuitem"
                      className="block w-full rounded px-2 py-1.5 text-left text-sm text-ink hover:bg-rule-soft"
                      onClick={() => reopen.mutate()}
                    >
                      Reopen for changes
                    </button>
                  </>
                )}
                {editable && takeoff.status === "review" && takeoff.sourceKind === "pdf" && (
                  <button
                    role="menuitem"
                    className="block w-full rounded px-2 py-1.5 text-left text-sm text-ink hover:bg-rule-soft"
                    title="Re-run the measuring and pricing pass on every scanned area. Replaces these cabinets' sizes; your edits on them are lost."
                    onClick={() => {
                      if (window.confirm("Measure every area again? Sizes and edits on these cabinets will be replaced."))
                        remeasure.mutate();
                    }}
                  >
                    Measure again…
                  </button>
                )}
                {editable && takeoff.status === "review" && (
                  <>
                    <div className="my-1 border-t border-rule-soft" />
                    <button
                      role="menuitem"
                      className="block w-full rounded px-2 py-1.5 text-left text-sm text-ink hover:bg-rule-soft"
                      onClick={() => approve.mutate(undefined, { onSuccess: invalidate })}
                    >
                      Approve without quoting
                    </button>
                  </>
                )}
              </div>
            </details>
            <Button
              variant="quiet"
              aria-label="Keyboard shortcuts"
              title="Keyboard shortcuts"
              onClick={() => setHelpOpen(true)}
            >
              ?
            </Button>
          </div>
        }
      >
        {takeoff.sourceFilename ?? takeoffId.slice(0, 8)}
      </PageTitle>

      {/* A failed "Measure again" or area update lands back here with the
          previous breakdown intact; the failure used to be invisible. */}
      {takeoff.status === "review" && takeoff.error && (
        <div
          role="alert"
          className="mb-3 flex flex-wrap items-center gap-3 rounded-lg border border-bad bg-bad-soft px-3 py-2 text-sm text-bad"
        >
          <span className="min-w-0 flex-1">
            The last measuring run didn't finish, so this breakdown is unchanged.{" "}
            {friendlyError(takeoff.error).text}
            <TechnicalDetail details={takeoff.error} />
          </span>
          {takeoff.sourceKind === "pdf" && (
            <Button
              variant="default"
              size="sm"
              loading={remeasure.isPending}
              onClick={() => remeasure.mutate()}
            >
              Measure again
            </Button>
          )}
        </div>
      )}

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        {/* Drawing */}
        <div className="flex min-h-0 flex-col gap-2">
          <div className="min-h-0 flex-1 overflow-hidden rounded-lg border border-rule bg-paper p-2">
            {hasReadImages ? (
              <SourceBoxPanel
                takeoffId={takeoffId}
                lines={cabinets}
                selectedId={selectedId}
                editable={editable}
                maxHeight="calc(100vh - 17rem)"
                onSelect={(id) => {
                  if (id != null) setSelectedId(id);
                }}
                onPatchBbox={(id, bbox) => patchLine.mutate({ id, patch: { bbox } })}
                onCreate={(body) => createLine.mutate(body)}
              />
            ) : pageImage.data?.url ? (
              <img
                src={pageImage.data.url}
                alt="source page"
                className="max-h-full w-full object-contain"
              />
            ) : (
              <div className="flex h-full items-center justify-center text-sm text-faint">
                {selectedLine?.sourcePage
                  ? "Loading page image…"
                  : "No drawing for this input — the breakdown came from the schedule."}
              </div>
            )}
          </div>
          {takeoff.material_stats && takeoff.material_stats.box_count > 0 && (
            <details className="rounded-lg border border-rule bg-paper px-3 py-2 text-sm">
              <summary className="cursor-pointer text-muted">
                <span className="font-medium text-ink">Materials</span>
                <span className="ml-2 font-mono text-xs tabular-nums">
                  {takeoff.material_stats.box_count} boxes ·{" "}
                  {takeoff.material_stats.carcass_sqft} ft² carcass (~
                  {takeoff.material_stats.carcass_sheets} sheets) ·{" "}
                  {takeoff.material_stats.door_count} doors ·{" "}
                  {takeoff.material_stats.drawer_front_count} fronts (~
                  {takeoff.material_stats.face_sheets} sheets)
                </span>
              </summary>
              <p className="mt-1 text-xs text-muted">
                4×8 sheets at {takeoff.material_stats.waste_pct}% waste.
                {takeoff.material_stats.skipped_no_dims > 0 &&
                  ` ${takeoff.material_stats.skipped_no_dims} box(es) missing dimensions are not counted.`}
              </p>
            </details>
          )}
        </div>

        {/* Breakdown */}
        <div className="flex min-h-0 flex-col overflow-hidden rounded-lg border border-rule bg-paper">
          <div className="border-b border-rule px-3 py-2">
            <div className="flex flex-wrap items-center gap-1" role="tablist" aria-label="Filter lines">
              <FilterTab active={filter === "all"} onClick={() => setFilter("all")} label="All" count={cabinets.length} />
              <FilterTab active={filter === "flagged"} onClick={() => setFilter("flagged")} label="Flagged" count={flagged.length} tone="warn" />
              <FilterTab active={filter === "unmatched"} onClick={() => setFilter("unmatched")} label="Unmatched" count={unmatched.length} tone="bad" />
              <label className="ml-auto flex items-center gap-1.5 text-xs text-muted">
                <input
                  type="checkbox"
                  checked={showFaces}
                  onChange={(e) => setShowFaces(e.target.checked)}
                />
                Show doors &amp; fronts
              </label>
            </div>
            {categoryCounts.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted">
                {categoryCounts.map(([cat, n]) => (
                  <span key={cat} className="inline-flex items-center gap-1">
                    <span className={`inline-block size-2 rounded-full ${categoryDotClass(cat)}`} />
                    {categoryLabel(cat)}
                    <span className="font-mono tabular-nums">{n}</span>
                  </span>
                ))}
              </div>
            )}
          </div>

          {docFlags.length > 0 && (
            <details className="border-b border-rule bg-warn-soft/60 px-3 py-2 text-sm" open={docFlags.length <= 2}>
              <summary className="cursor-pointer font-medium text-warn">
                {docFlags.length} note{docFlags.length === 1 ? "" : "s"} from the read
              </summary>
              <ul className="mt-1 list-inside list-disc text-xs text-warn">
                {docFlags.map((u, i) => (
                  <li key={i}>
                    {u.text}
                    <TechnicalDetail details={u.details} />
                  </li>
                ))}
              </ul>
            </details>
          )}

          <div className="min-h-0 flex-1 overflow-auto">
            {visible.length === 0 ? (
              <div className="p-6 text-center text-sm text-muted">
                {cabinets.length === 0
                  ? "No cabinets were read. Draw one on the drawing, or re-read with different pages."
                  : filter === "flagged"
                    ? "Nothing flagged — every line is confident and matched."
                    : "Every line is matched to a product."}
              </div>
            ) : (
              <table className="w-full text-sm">
                <thead className="sticky top-0 z-10 bg-paper">
                  <tr className="border-b border-rule text-left font-mono text-[11px] uppercase tracking-wider text-muted">
                    <th className="w-5 px-2 py-1.5" />
                    <th className="px-1 py-1.5">Cabinet</th>
                    <th className="w-10 px-1 py-1.5">Qty</th>
                    <th className="px-1 py-1.5">W × H × D</th>
                    <th className="w-12 px-1 py-1.5">Conf</th>
                    <th className="px-1 py-1.5">Product</th>
                    <th className="w-7 px-1 py-1.5" />
                  </tr>
                </thead>
                <tbody>
                  {groups.map((g) => (
                    <GroupRows
                      key={g.room}
                      room={g.room}
                      lines={g.lines}
                      selectedId={selectedId}
                      editable={editable}
                      showFaces={showFaces}
                      facesByParent={facesByParent}
                      productLines={productLines.data ?? []}
                      productName={productName}
                      onSelect={setSelectedId}
                      onPatch={(id, patch) => patchLine.mutate({ id, patch })}
                      onDelete={requestDelete}
                    />
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>

      {/* Sticky bar: the number, and the way out. */}
      <div
        className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-2 rounded-lg border border-rule bg-paper px-4 py-2"
        data-tour="review-bar"
      >
        <div>
          <div className="font-mono text-[10px] uppercase tracking-wider text-muted">
            Base estimate
          </div>
          <div className="font-mono text-xl font-medium tabular-nums text-ink">
            {base ? formatUsd(base.total_cents) : "—"}
          </div>
        </div>
        {tiers && (
          <div className="text-xs text-muted">
            <div>Upgraded {formatUsd(tiers.medium.total_cents)}</div>
            <div>Premium {formatUsd(tiers.high.total_cents)}</div>
          </div>
        )}
        <div className="text-xs text-muted">
          <div>
            <span className="font-mono tabular-nums text-ink">{cabinets.length}</span> cabinets
          </div>
          <button
            type="button"
            className={`${flagCount > 0 ? "text-warn" : "text-muted"} hover:underline`}
            onClick={() => setFilter(flagged.length > 0 ? "flagged" : "all")}
          >
            <span className="font-mono tabular-nums">{flagCount}</span> to check
          </button>
        </div>
        <div className="ml-auto flex items-center gap-2">
          {editable && acceptable.length > 0 && (
            <Button
              data-tour="review-accept"
              loading={acceptAll.isPending}
              onClick={() => acceptAll.mutate()}
              title={`Mark the ${acceptable.length} lines at or above ${Math.round(LOW_CONFIDENCE * 100)}% as checked`}
            >
              Accept {acceptable.length} confident
            </Button>
          )}
          {takeoff.status === "approved" ? (
            <Button variant="primary" loading={finishing} onClick={openNaming}>
              Build quote →
            </Button>
          ) : (
            <Button
              variant="primary"
              loading={finishing}
              disabled={cabinets.length === 0 || takeoff.status !== "review"}
              onClick={openNaming}
              title={unmatched.length > 0 ? `${unmatched.length} unmatched line(s) will be left off the quote` : undefined}
            >
              Looks right → Quote
            </Button>
          )}
        </div>
      </div>

      <Dialog
        open={naming}
        title="Name this quote"
        onClose={() => setNaming(false)}
        actions={
          <>
            <Button variant="quiet" onClick={() => setNaming(false)}>
              Cancel
            </Button>
            <Button variant="primary" onClick={() => finish(quoteName)}>
              Create quote →
            </Button>
          </>
        }
      >
        <form
          onSubmit={(e) => {
            e.preventDefault();
            finish(quoteName);
          }}
        >
          <label className="flex flex-col gap-1 text-xs text-muted">
            Quote name
            <Input
              autoFocus
              value={quoteName}
              maxLength={120}
              onChange={(e) => setQuoteName(e.target.value)}
              onFocus={(e) => e.currentTarget.select()}
            />
          </label>
          <p className="mt-2 text-xs text-muted">
            Shown on the Jobs and Quotes lists and in the email subject. You can rename it later on the quote.
          </p>
        </form>
      </Dialog>

      <Dialog open={helpOpen} title="Keyboard shortcuts" onClose={() => setHelpOpen(false)}>
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
          <dt><Kbd>↑</Kbd> <Kbd>↓</Kbd></dt><dd>Move between cabinets</dd>
          <dt><Kbd>Enter</Kbd></dt><dd>Accept the selected line and move on</dd>
          <dt><Kbd>e</Kbd></dt><dd>Edit the selected line (or click any cell)</dd>
          <dt><Kbd>Esc</Kbd></dt><dd>Cancel an edit</dd>
          <dt><Kbd>Del</Kbd></dt><dd>Remove the selected cabinet (undo for 8 s)</dd>
          <dt><Kbd>⌘</Kbd> + scroll</dt><dd>Zoom the drawing; drag to pan</dd>
          <dt><Kbd>?</Kbd></dt><dd>This list</dd>
        </dl>
      </Dialog>
    </div>
  );
}

function FilterTab({
  active,
  onClick,
  label,
  count,
  tone,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
  count: number;
  tone?: "warn" | "bad";
}) {
  const countClass =
    count > 0 && tone === "warn" ? "text-warn" : count > 0 && tone === "bad" ? "text-bad" : "text-muted";
  return (
    <button
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={`rounded-md px-2 py-1 text-sm ${
        active ? "bg-ink text-paper" : "text-muted hover:bg-rule-soft hover:text-ink"
      }`}
    >
      {label}
      <span className={`ml-1.5 font-mono text-xs tabular-nums ${active ? "opacity-70" : countClass}`}>
        {count}
      </span>
    </button>
  );
}

function GroupRows({
  room,
  lines,
  selectedId,
  editable,
  showFaces,
  facesByParent,
  productLines,
  productName,
  onSelect,
  onPatch,
  onDelete,
}: {
  room: string;
  lines: Line[];
  selectedId: string | null;
  editable: boolean;
  showFaces: boolean;
  facesByParent: Map<string, Line[]>;
  productLines: ProductLineRow[];
  productName: Map<string, string>;
  onSelect: (id: string) => void;
  onPatch: (id: string, patch: Record<string, unknown>) => void;
  onDelete: (id: string) => void;
}) {
  const qty = lines.reduce((n, l) => n + l.qty, 0);
  return (
    <>
      <tr className="bg-bg">
        <td colSpan={7} className="px-3 py-1 font-mono text-[11px] uppercase tracking-wider text-muted">
          {room}
          <span className="ml-2 tabular-nums">{qty}</span>
        </td>
      </tr>
      {lines.map((l) => (
        <CabinetRow
          key={l.id}
          line={l}
          faces={facesByParent.get(l.id) ?? []}
          showFaces={showFaces}
          selected={l.id === selectedId}
          editable={editable}
          productLines={productLines}
          productName={productName}
          onSelect={() => onSelect(l.id)}
          onPatch={(patch) => onPatch(l.id, patch)}
          onDelete={() => onDelete(l.id)}
        />
      ))}
    </>
  );
}

function CabinetRow({
  line,
  faces,
  showFaces,
  selected,
  editable,
  productLines,
  productName,
  onSelect,
  onPatch,
  onDelete,
}: {
  line: Line;
  faces: Line[];
  showFaces: boolean;
  selected: boolean;
  editable: boolean;
  productLines: ProductLineRow[];
  productName: Map<string, string>;
  onSelect: () => void;
  onPatch: (patch: Record<string, unknown>) => void;
  onDelete: () => void;
}) {
  const low = line.confidence < LOW_CONFIDENCE;
  const rowClass = selected
    ? "bg-accent-soft shadow-[inset_3px_0_0_var(--accent)]"
    : low || !line.productLineId
      ? "bg-warn-soft/40 hover:bg-warn-soft/70"
      : "hover:bg-rule-soft";
  const num = (v: number | null) => (v == null ? "" : String(v));
  const parseNum = (s: string) => (s.trim() === "" ? null : Number(s));
  const doors = faces.filter((f) => f.category === "door").reduce((n, f) => n + f.qty, 0);
  const fronts = faces.filter((f) => f.category === "drawer_front").reduce((n, f) => n + f.qty, 0);

  return (
    <>
      <tr
        data-line-id={line.id}
        onClick={onSelect}
        onFocusCapture={onSelect}
        className={`cursor-pointer border-b border-rule-soft ${rowClass}`}
      >
        <td className="px-2 py-1 align-top">
          <span
            className={`mt-2 inline-block size-2.5 rounded-full ${categoryDotClass(line.category)}`}
            title={categoryLabel(line.category)}
          />
        </td>
        <td className="px-1 py-1 align-top">
          <Cell
            value={line.tag ?? ""}
            placeholder={categoryLabel(line.category)}
            editable={editable}
            className="font-medium"
            ariaLabel="Tag"
            onCommit={(v) => onPatch({ tag: v.trim() || null })}
          />
          <div className="flex items-center gap-0.5 text-xs">
            <Cell
              value={line.material ?? ""}
              placeholder="material"
              editable={editable}
              className="w-16 text-muted"
              ariaLabel="Material"
              onCommit={(v) => onPatch({ material: v.trim() || null })}
            />
            <span className="text-faint">/</span>
            <Cell
              value={line.finish ?? ""}
              placeholder="finish"
              editable={editable}
              className="w-16 text-muted"
              ariaLabel="Finish"
              onCommit={(v) => onPatch({ finish: v.trim() || null })}
            />
            {(doors > 0 || fronts > 0) && !showFaces && (
              <span className="ml-1 whitespace-nowrap text-[11px] text-faint">
                {[doors > 0 && `${doors} door${doors === 1 ? "" : "s"}`, fronts > 0 && `${fronts} front${fronts === 1 ? "" : "s"}`]
                  .filter(Boolean)
                  .join(" · ")}
              </span>
            )}
          </div>
        </td>
        <td className="px-1 py-1 align-top">
          <Cell
            value={String(line.qty)}
            editable={editable}
            mono
            className="w-8 text-center"
            ariaLabel="Quantity"
            onCommit={(v) => {
              const n = Number(v);
              if (Number.isFinite(n) && n > 0 && n !== line.qty) onPatch({ qty: n });
            }}
          />
        </td>
        <td className="whitespace-nowrap px-1 py-1 align-top">
          <div className="flex items-center gap-0.5">
            {(
              [
                ["width_in", line.widthIn, "Width"],
                ["height_in", line.heightIn, "Height"],
                ["depth_in", line.depthIn, "Depth"],
              ] as const
            ).map(([field, value, label], i) => (
              <span key={field} className="flex items-center">
                {i > 0 && <span className="text-faint">×</span>}
                <Cell
                  value={num(value)}
                  placeholder="—"
                  editable={editable}
                  mono
                  className="w-10 px-0.5 text-center"
                  ariaLabel={label}
                  onCommit={(v) => {
                    const n = parseNum(v);
                    if (n !== value) onPatch({ [field]: n });
                  }}
                />
              </span>
            ))}
          </div>
        </td>
        <td className="px-1 py-1 align-top">
          <button
            type="button"
            disabled={!editable || line.confidence >= 1}
            title={line.confidence >= 1 ? "Checked" : "Mark as checked"}
            onClick={(e) => {
              e.stopPropagation();
              onPatch({ confidence: 1 });
            }}
            className={`mt-0.5 rounded-full px-2 py-0.5 font-mono text-[11px] tabular-nums ${
              line.confidence >= 1
                ? "bg-good-soft text-good"
                : low
                  ? "bg-warn-soft text-warn hover:bg-warn-soft/80"
                  : "bg-rule-soft text-muted hover:bg-good-soft hover:text-good"
            }`}
          >
            {line.confidence >= 1 ? "✓" : `${Math.round(line.confidence * 100)}%`}
          </button>
        </td>
        <td className="px-1 py-1 align-top">
          {line.productLineId ? (
            <span className="block max-w-[9rem] truncate px-1 text-xs text-muted" title={productName.get(line.productLineId) ?? line.productLineId}>
              {productName.get(line.productLineId) ?? line.productLineId}
            </span>
          ) : editable ? (
            <Select
              className="w-full py-0.5 text-xs"
              defaultValue=""
              title={line.unmatchedReason ?? undefined}
              aria-label="Assign a product"
              onClick={(e) => e.stopPropagation()}
              onChange={(e) => {
                if (!e.target.value) return;
                onPatch({
                  product_line_id: e.target.value,
                  resolved_params: {
                    product_line_id: e.target.value,
                    qty: line.qty,
                    width_in: line.widthIn,
                    height_in: line.heightIn,
                    depth_in: line.depthIn,
                    material: line.material ?? "",
                    finish: line.finish,
                    assembled: line.assembled ?? false,
                  },
                });
              }}
            >
              <option value="">Unmatched — pick…</option>
              {productLines.map((pl) => (
                <option key={pl.id} value={pl.id}>
                  {pl.name}
                </option>
              ))}
            </Select>
          ) : (
            <span className="px-1 text-xs text-bad">unmatched</span>
          )}
          {!line.productLineId && line.unmatchedReason && (
            <div className="px-1 text-[11px] text-faint">{line.unmatchedReason}</div>
          )}
        </td>
        <td className="px-1 py-1 text-right align-top">
          {editable && (
            <button
              type="button"
              aria-label="Remove cabinet"
              title="Remove (undo for 8 s)"
              className="rounded px-1.5 py-0.5 text-muted hover:bg-bad-soft hover:text-bad"
              onClick={(e) => {
                e.stopPropagation();
                onDelete();
              }}
            >
              ✕
            </button>
          )}
        </td>
      </tr>
      {showFaces &&
        faces.map((f) => (
          <tr key={f.id} className="border-b border-rule-soft text-xs text-muted">
            <td />
            <td className="px-2 py-0.5" colSpan={2}>
              ↳ {f.qty} × {categoryLabel(f.category)}
            </td>
            <td className="px-1 py-0.5 font-mono tabular-nums">
              {[f.widthIn, f.heightIn].map((d) => d ?? "—").join(" × ")}
            </td>
            <td colSpan={3} className="px-1 py-0.5">
              {f.material ?? ""}
              {f.finish ? ` / ${f.finish}` : ""}
            </td>
          </tr>
        ))}
    </>
  );
}

// A cell that reads as text and edits in place: click or tab in, Enter or
// blur commits, Esc restores.
function Cell({
  value,
  onCommit,
  editable,
  placeholder,
  mono,
  className = "",
  ariaLabel,
}: {
  value: string;
  onCommit: (v: string) => void;
  editable: boolean;
  placeholder?: string;
  mono?: boolean;
  className?: string;
  ariaLabel: string;
}) {
  const [draft, setDraft] = useState(value);
  const [focused, setFocused] = useState(false);
  useEffect(() => {
    if (!focused) setDraft(value);
  }, [value, focused]);
  if (!editable) {
    return (
      <span className={`block truncate px-1 py-0.5 ${mono ? "font-mono tabular-nums" : ""} ${className}`}>
        {value || <span className="text-faint">{placeholder ?? "—"}</span>}
      </span>
    );
  }
  return (
    <input
      aria-label={ariaLabel}
      value={draft}
      placeholder={placeholder}
      onFocus={(e) => {
        setFocused(true);
        e.currentTarget.select();
      }}
      onBlur={() => {
        setFocused(false);
        if (draft !== value) onCommit(draft);
      }}
      onChange={(e) => setDraft(e.target.value)}
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          (e.currentTarget as HTMLInputElement).blur();
        } else if (e.key === "Escape") {
          e.preventDefault();
          setDraft(value);
          (e.currentTarget as HTMLInputElement).blur();
        }
        e.stopPropagation();
      }}
      className={`min-w-0 rounded border border-transparent bg-transparent px-1 py-0.5 text-ink outline-none placeholder:text-faint hover:border-rule focus:border-accent focus:bg-paper ${
        mono ? "font-mono tabular-nums" : ""
      } ${className}`}
    />
  );
}
