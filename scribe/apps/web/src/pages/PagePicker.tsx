import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { pagePickerRoute } from "../main";
import { apiGet, apiSend } from "../api";
import {
  Button,
  Card,
  errorMessage,
  PageTitle,
  StatusPill,
  useToast,
} from "../ui";
import { ReadingProgress, type Progress } from "../components/ReadingProgress";

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
  progress: Progress | null;
  updatedAt: string;
  error: string | null;
}

// The page types the reader knows how to read, plus "other" (skipped). The
// tag tells the extractor HOW to read a page — the diagnosis showed the
// plan-vs-elevation call decides reading accuracy, so overriding it here is
// high-leverage.
const CLASS_OPTIONS: { value: string; label: string; short: string }[] = [
  { value: "floor_plan", label: "Floor plan", short: "Plan" },
  { value: "kitchen_or_millwork_elevation", label: "Elevation / millwork", short: "Elevation" },
  { value: "cabinet_schedule_table", label: "Cabinet schedule", short: "Schedule" },
  { value: "finish_schedule", label: "Finish schedule", short: "Finishes" },
  { value: "other", label: "Other (not read)", short: "Skip" },
];

const OPTION_VALUES = new Set(CLASS_OPTIONS.map((o) => o.value));
const READABLE = ["floor_plan", "kitchen_or_millwork_elevation", "cabinet_schedule_table"];

// Collapse classifier classes with no read path into "other" for the select.
function toOption(cls: string | undefined): string {
  return cls != null && OPTION_VALUES.has(cls) ? cls : "other";
}

function classLabel(cls: string): string {
  return CLASS_OPTIONS.find((o) => o.value === cls)?.label ?? cls;
}

export function PagePickerPage() {
  const { takeoffId } = pagePickerRoute.useParams();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const toast = useToast();
  // page -> chosen class; presence in the map = selected.
  const [picked, setPicked] = useState<Record<number, string>>({});

  const q = useQuery({
    queryKey: ["takeoff", takeoffId],
    queryFn: () => apiGet<TakeoffDetail>(`/takeoffs/${takeoffId}`),
    refetchInterval: (query) =>
      query.state.data?.status === "processing" ? 3000 : false,
  });
  const status = q.data?.status;

  // This page owns only the awaiting_pages state; route anywhere else back to
  // the takeoff page, which forwards to whichever gate the status demands.
  useEffect(() => {
    if (status == null || status === "processing" || status === "awaiting_pages")
      return;
    navigate({ to: "/takeoffs/$takeoffId", params: { takeoffId } });
  }, [status, navigate, takeoffId]);

  const classByPage = useMemo(() => {
    const m = new Map<number, PageClassification>();
    for (const c of q.data?.classifiedPages ?? []) m.set(c.page, c);
    return m;
  }, [q.data?.classifiedPages]);

  const pageCount = q.data?.pageCount ?? 0;
  const allPages = useMemo(
    () => Array.from({ length: pageCount }, (_, i) => i + 1),
    [pageCount]
  );

  // Pre-select what the classifier thinks is readable — the common case is
  // "looks right, go", and the tiles are there to correct the exceptions.
  useEffect(() => {
    if (status !== "awaiting_pages" || pageCount === 0) return;
    setPicked((prev) => {
      if (Object.keys(prev).length > 0) return prev;
      const next: Record<number, string> = {};
      for (const p of allPages) {
        const cls = toOption(classByPage.get(p)?.class);
        if (READABLE.includes(cls)) next[p] = cls;
      }
      return next;
    });
  }, [status, pageCount, allPages, classByPage]);

  const submit = useMutation({
    mutationFn: () =>
      apiSend("POST", `/takeoffs/${takeoffId}/pages`, {
        pages: Object.entries(picked)
          .map(([page, cls]) => {
            const suggested = toOption(classByPage.get(Number(page))?.class);
            // Send the class only when the user changed the suggestion — an
            // untouched pre-fill keeps the classifier's call.
            return cls !== suggested
              ? { page: Number(page), class: cls }
              : { page: Number(page) };
          })
          .sort((a, b) => a.page - b.page),
      }),
    onError: (e) => toast.error("Couldn't start reading", errorMessage(e)),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["takeoff", takeoffId] });
      navigate({ to: "/takeoffs/$takeoffId", params: { takeoffId } });
    },
  });

  // Counts per suggested type, for the "all elevations" shortcuts.
  const byType = useMemo(() => {
    const m = new Map<string, number[]>();
    for (const p of allPages) {
      const cls = toOption(classByPage.get(p)?.class);
      m.set(cls, [...(m.get(cls) ?? []), p]);
    }
    return m;
  }, [allPages, classByPage]);

  function selectType(cls: string) {
    setPicked((prev) => {
      const next = { ...prev };
      for (const p of byType.get(cls) ?? []) next[p] = cls;
      return next;
    });
  }

  if (q.isLoading) return <div className="text-muted">Loading…</div>;
  if (q.isError) return <div className="text-bad">{String(q.error)}</div>;
  const takeoff = q.data!;
  const selectedPages = Object.keys(picked)
    .map(Number)
    .sort((a, b) => a - b);
  const selectedCount = selectedPages.length;
  const readableCount = selectedPages.filter((p) => READABLE.includes(picked[p])).length;

  return (
    <div>
      <PageTitle
        eyebrow="Choose pages"
        actions={
          <div className="flex items-center gap-2">
            <StatusPill status={takeoff.status} />
            <Button
              variant="primary"
              loading={submit.isPending}
              disabled={readableCount === 0}
              onClick={() => submit.mutate()}
            >
              {`Read ${readableCount} page${readableCount === 1 ? "" : "s"} →`}
            </Button>
          </div>
        }
      >
        {takeoff.sourceFilename ?? takeoffId.slice(0, 8)}
      </PageTitle>

      {takeoff.status === "processing" ? (
        <ReadingProgress
          title="Preparing your pages"
          progress={takeoff.progress}
          sourceKind={takeoff.sourceKind}
          pageCount={takeoff.pageCount}
          fallbackStartedAt={takeoff.updatedAt}
        />
      ) : (
        <>
          <p className="mb-3 max-w-3xl text-sm text-muted">
            The pages that look like cabinet drawings are already selected. Click
            a page to add or remove it, and correct its type where the guess is
            wrong — the type decides how a page is read. Pages marked “Skip” are
            not read.
          </p>

          <div className="mb-4 flex flex-wrap items-center gap-1.5">
            {READABLE.map((cls) => {
              const n = byType.get(cls)?.length ?? 0;
              if (n === 0) return null;
              const o = CLASS_OPTIONS.find((x) => x.value === cls)!;
              return (
                <Button key={cls} size="sm" onClick={() => selectType(cls)}>
                  All {o.short.toLowerCase()}s
                  <span className="font-mono text-[11px] text-muted">{n}</span>
                </Button>
              );
            })}
            <Button size="sm" onClick={() => setPicked(Object.fromEntries(allPages.map((p) => [p, toOption(classByPage.get(p)?.class)])))}>
              Every page
            </Button>
            <Button size="sm" variant="quiet" onClick={() => setPicked({})}>
              Clear
            </Button>
            <span className="ml-auto font-mono text-xs tabular-nums text-muted">
              {selectedCount} of {pageCount} selected
            </span>
          </div>

          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 2xl:grid-cols-5">
            {allPages.map((page) => {
              const suggested = toOption(classByPage.get(page)?.class);
              const selected = page in picked;
              const cls = selected ? picked[page] : suggested;
              return (
                <div
                  key={page}
                  className={`rounded-lg border bg-paper p-2 transition-colors ${
                    selected
                      ? "border-accent ring-2 ring-accent-soft"
                      : "border-rule hover:border-muted"
                  }`}
                >
                  <div
                    role="checkbox"
                    aria-checked={selected}
                    aria-label={`Page ${page}, ${classLabel(cls)}`}
                    tabIndex={0}
                    className="relative cursor-pointer"
                    onClick={() =>
                      setPicked((prev) => {
                        const next = { ...prev };
                        if (page in next) delete next[page];
                        else next[page] = suggested;
                        return next;
                      })
                    }
                    onKeyDown={(e) => {
                      if (e.key === " " || e.key === "Enter") {
                        e.preventDefault();
                        (e.currentTarget as HTMLElement).click();
                      }
                    }}
                  >
                    <PageThumb takeoffId={takeoffId} page={page} />
                    <span className="absolute left-1 top-1 rounded bg-paper/90 px-1.5 font-mono text-[11px] text-ink">
                      p{page}
                    </span>
                    {selected && (
                      <span className="absolute right-1 top-1 flex h-6 w-6 items-center justify-center rounded-full bg-accent text-sm font-bold text-white">
                        ✓
                      </span>
                    )}
                  </div>
                  <div className="mt-1.5 flex flex-wrap gap-1" role="radiogroup" aria-label={`Page ${page} type`}>
                    {CLASS_OPTIONS.map((o) => {
                      const on = cls === o.value;
                      return (
                        <button
                          key={o.value}
                          type="button"
                          role="radio"
                          aria-checked={on}
                          title={o.label}
                          className={`rounded px-1.5 py-0.5 text-[11px] leading-tight ${
                            on
                              ? selected
                                ? "bg-ink text-paper"
                                : "bg-rule-soft text-ink"
                              : "text-muted hover:bg-rule-soft"
                          }`}
                          onClick={() =>
                            setPicked((prev) => {
                              const next = { ...prev };
                              if (o.value === "other") delete next[page];
                              else next[page] = o.value;
                              return next;
                            })
                          }
                        >
                          {o.short}
                        </button>
                      );
                    })}
                  </div>
                </div>
              );
            })}
            {pageCount === 0 && (
              <Card className="col-span-full">
                <p className="text-sm text-faint">No pages found.</p>
              </Card>
            )}
          </div>

          <details className="mt-6 max-w-3xl rounded-lg border border-rule bg-paper">
            <summary className="cursor-pointer px-4 py-3 text-sm font-medium text-ink">
              Draw the regions yourself
              <span className="ml-2 text-xs font-normal text-muted">
                advanced — when the automatic read keeps missing a sheet
              </span>
            </summary>
            <div className="border-t border-rule-soft px-4 py-3 text-sm text-muted">
              <p className="mb-3">
                Instead of letting Scribe find the drawings, you drag boxes over
                every cabinet area on the selected pages. The model then labels
                what's inside each box and one measuring pass sizes everything.
                Slower, but you control exactly what gets read.
              </p>
              <Link
                to="/takeoffs/$takeoffId/detect"
                params={{ takeoffId }}
                search={{ pages: selectedPages.join(",") || undefined }}
              >
                <Button disabled={selectedCount === 0}>
                  Draw on {selectedCount} page{selectedCount === 1 ? "" : "s"} →
                </Button>
              </Link>
            </div>
          </details>
        </>
      )}
    </div>
  );
}

function PageThumb({ takeoffId, page }: { takeoffId: string; page: number }) {
  const q = useQuery({
    queryKey: ["thumb", takeoffId, page],
    queryFn: () =>
      apiGet<{ url: string }>(`/takeoffs/${takeoffId}/thumbs/${page}/image`),
    staleTime: 10 * 60 * 1000,
  });
  if (!q.data?.url) {
    return <div className="aspect-[3/4] w-full animate-pulse rounded bg-rule-soft" />;
  }
  return (
    <img
      src={q.data.url}
      alt={`page ${page}`}
      loading="lazy"
      className="w-full rounded border border-rule-soft object-contain"
    />
  );
}
