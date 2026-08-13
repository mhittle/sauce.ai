import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { pagePickerRoute } from "../main";
import { apiGet, apiSend } from "../api";
import { Badge, Button, Card, PageTitle, statusTone } from "../ui";

interface PageClassification {
  page: number;
  class: string;
  confidence: number;
}

interface TakeoffDetail {
  id: string;
  sourceFilename: string | null;
  status: string;
  pageCount: number | null;
  classifiedPages: PageClassification[] | null;
  error: string | null;
}

// The page types the reader knows how to read, plus "other" (skipped). The
// tag tells the extractor HOW to read a page — the diagnosis showed the
// plan-vs-elevation call decides reading accuracy, so overriding it here is
// high-leverage.
const CLASS_OPTIONS: { value: string; label: string }[] = [
  { value: "floor_plan", label: "Floor plan" },
  { value: "kitchen_or_millwork_elevation", label: "Elevation / millwork" },
  { value: "cabinet_schedule_table", label: "Cabinet schedule" },
  { value: "finish_schedule", label: "Finish schedule" },
  { value: "other", label: "Other (not read)" },
];

const OPTION_VALUES = new Set(CLASS_OPTIONS.map((o) => o.value));

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
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["takeoff", takeoffId] });
      navigate({ to: "/takeoffs/$takeoffId", params: { takeoffId } });
    },
  });

  if (q.isLoading) return <div className="text-zinc-500">Loading…</div>;
  if (q.isError) return <div className="text-red-600">{String(q.error)}</div>;
  const takeoff = q.data!;
  const pageCount = takeoff.pageCount ?? 0;
  const selectedCount = Object.keys(picked).length;

  return (
    <div>
      <PageTitle
        actions={
          <div className="flex items-center gap-2">
            <Link to="/takeoffs/$takeoffId/detect" params={{ takeoffId }}>
              <Button>
                Detect <Badge tone="blue">beta</Badge>
              </Button>
            </Link>
            <Button
              variant="primary"
              disabled={selectedCount === 0 || submit.isPending}
              onClick={() => submit.mutate()}
            >
              {submit.isPending
                ? "Starting…"
                : `Process ${selectedCount} page${selectedCount === 1 ? "" : "s"} →`}
            </Button>
          </div>
        }
      >
        Select pages: {takeoff.sourceFilename ?? takeoffId.slice(0, 8)}{" "}
        <Badge tone={statusTone(takeoff.status)}>{takeoff.status}</Badge>
      </PageTitle>

      {submit.isError && (
        <p className="mb-2 text-sm text-red-600">{String(submit.error)}</p>
      )}

      {takeoff.status === "processing" ? (
        <Card>
          <p className="text-sm text-zinc-500">
            Preparing page thumbnails… this page refreshes automatically.
          </p>
        </Card>
      ) : (
        <>
          <p className="mb-3 text-sm text-zinc-500">
            Click the pages the takeoff should read, and correct the suggested
            page type where it's wrong — the type decides how a page is read.
            Pages tagged “Other” are skipped.
          </p>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
            {Array.from({ length: pageCount }, (_, i) => i + 1).map((page) => {
              const suggested = toOption(classByPage.get(page)?.class);
              const selected = page in picked;
              return (
                <div
                  key={page}
                  className={`cursor-pointer rounded-lg border bg-white p-2 shadow-sm transition-colors ${
                    selected
                      ? "border-blue-500 ring-2 ring-blue-200"
                      : "border-zinc-200 hover:border-zinc-400"
                  }`}
                  onClick={() =>
                    setPicked((prev) => {
                      const next = { ...prev };
                      if (page in next) delete next[page];
                      else next[page] = suggested;
                      return next;
                    })
                  }
                >
                  <div className="relative">
                    <PageThumb takeoffId={takeoffId} page={page} />
                    {selected && (
                      <span className="absolute right-1 top-1 flex h-6 w-6 items-center justify-center rounded-full bg-blue-600 text-sm font-bold text-white">
                        ✓
                      </span>
                    )}
                  </div>
                  <div className="mt-1 flex items-center justify-between gap-1">
                    <span className="text-xs font-medium text-zinc-600">
                      p{page}
                    </span>
                    {selected ? (
                      <select
                        className="min-w-0 flex-1 rounded-md border border-zinc-300 px-1 py-0.5 text-xs"
                        value={picked[page]}
                        onClick={(e) => e.stopPropagation()}
                        onChange={(e) =>
                          setPicked((prev) => ({ ...prev, [page]: e.target.value }))
                        }
                      >
                        {CLASS_OPTIONS.map((o) => (
                          <option key={o.value} value={o.value}>
                            {o.label}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <span className="truncate text-xs text-zinc-400">
                        {classLabel(suggested)}
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
            {pageCount === 0 && (
              <Card className="col-span-full">
                <p className="text-sm text-zinc-400">No pages found.</p>
              </Card>
            )}
          </div>
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
