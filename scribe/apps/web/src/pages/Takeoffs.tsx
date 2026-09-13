import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { apiUpload, apiGet, formatUsd } from "../api";
import {
  Card,
  EmptyState,
  errorMessage,
  PageTitle,
  SkeletonRows,
  StatusPill,
  useToast,
} from "../ui";
import { UploadZone } from "../components/UploadZone";
import type { Progress } from "../components/ReadingProgress";

// One row per job: the takeoff plus its latest quote (GET /jobs).
export interface Job {
  id: string;
  sourceFilename: string | null;
  sourceKind: string;
  status: string;
  pageCount: number | null;
  selectedPageCount: number | null;
  docConfidence: number | null;
  progress: Progress | null;
  error: string | null;
  createdAt: string;
  updatedAt: string;
  quote: {
    id: string;
    name: string | null;
    status: string;
    totalCents: number;
    createdAt: string;
  } | null;
}

// Kept for the upload response shape (POST /takeoffs returns the takeoff row).
interface Takeoff {
  id: string;
  sourceKind: string;
}

type Filter = "all" | "attention" | "progress" | "quoted";

const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "attention", label: "Needs attention" },
  { key: "progress", label: "In progress" },
  { key: "quoted", label: "Quoted" },
];

// Which step a job is on, for the list. Quote state wins once one exists.
function stepOf(j: Job): { status: string; detail: string | null } {
  if (j.quote) return { status: j.quote.status, detail: null };
  if (j.status === "processing") {
    return { status: "processing", detail: j.progress?.message ?? null };
  }
  if (j.status === "approved") return { status: "approved", detail: "Ready to quote" };
  return { status: j.status, detail: null };
}

function matches(j: Job, f: Filter): boolean {
  const step = stepOf(j).status;
  switch (f) {
    case "attention":
      return ["awaiting_pages", "awaiting_boxes", "review", "extracted", "approved", "failed", "draft"].includes(step);
    case "progress":
      return step === "processing";
    case "quoted":
      return ["sent", "won", "lost", "expired"].includes(step);
    default:
      return true;
  }
}

// Where clicking a job should land, given its state.
function jobHref(j: Job): { to: string; params: Record<string, string> } {
  if (j.quote) return { to: "/quotes/$quoteId", params: { quoteId: j.quote.id } };
  if (j.status === "awaiting_pages")
    return { to: "/takeoffs/$takeoffId/pages", params: { takeoffId: j.id } };
  if (j.status === "awaiting_boxes")
    return { to: "/takeoffs/$takeoffId/detect", params: { takeoffId: j.id } };
  return { to: "/takeoffs/$takeoffId", params: { takeoffId: j.id } };
}

function relative(iso: string): string {
  const s = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function TakeoffsPage() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const toast = useToast();
  const [filter, setFilter] = useState<Filter>("all");

  const q = useQuery({
    queryKey: ["jobs"],
    queryFn: () => apiGet<Job[]>("/jobs"),
    // Poll only while a job is still being read.
    refetchInterval: (query) =>
      query.state.data?.some((j) => j.status === "processing") ? 4000 : false,
  });

  const upload = useMutation({
    mutationFn: (file: File) => apiUpload<Takeoff>("/takeoffs", file),
    onError: (e) => toast.error("Upload failed", errorMessage(e)),
    onSuccess: (t) => {
      qc.invalidateQueries({ queryKey: ["jobs"] });
      // PDFs stop at the page-picker gate first; everything else lands on the
      // takeoff page, which forwards to whichever gate the status demands.
      if (t.sourceKind === "pdf") {
        navigate({ to: "/takeoffs/$takeoffId/pages", params: { takeoffId: t.id } });
      } else {
        navigate({ to: "/takeoffs/$takeoffId", params: { takeoffId: t.id } });
      }
    },
  });

  const jobs = q.data ?? [];
  const visible = useMemo(() => jobs.filter((j) => matches(j, filter)), [jobs, filter]);
  const counts = useMemo(
    () =>
      Object.fromEntries(
        FILTERS.map((f) => [f.key, jobs.filter((j) => matches(j, f.key)).length])
      ) as Record<Filter, number>,
    [jobs]
  );

  return (
    <div>
      <PageTitle>Jobs</PageTitle>

      <div className="mb-5">
        <UploadZone
          onFile={(f) => upload.mutate(f)}
          busy={upload.isPending}
          compact={jobs.length > 0}
        />
      </div>

      {jobs.length > 0 && (
        <div className="mb-3 flex flex-wrap gap-1" role="tablist" aria-label="Filter jobs">
          {FILTERS.map((f) => (
            <button
              key={f.key}
              role="tab"
              aria-selected={filter === f.key}
              onClick={() => setFilter(f.key)}
              className={`rounded-md px-2.5 py-1 text-sm ${
                filter === f.key
                  ? "bg-ink text-paper"
                  : "text-muted hover:bg-rule-soft hover:text-ink"
              }`}
            >
              {f.label}
              <span className="ml-1.5 font-mono text-xs tabular-nums opacity-70">
                {counts[f.key]}
              </span>
            </button>
          ))}
        </div>
      )}

      <Card className="p-0">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-rule text-left font-mono text-[11px] uppercase tracking-wider text-muted">
              <th className="px-3 py-2">Job</th>
              <th className="px-3 py-2">Pages</th>
              <th className="px-3 py-2">Step</th>
              <th className="px-3 py-2 text-right">Quote</th>
              <th className="px-3 py-2 text-right">Updated</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((j) => {
              const step = stepOf(j);
              const href = jobHref(j);
              return (
                <tr
                  key={j.id}
                  className="border-b border-rule-soft hover:bg-rule-soft"
                >
                  <td className="px-3 py-2">
                    <Link
                      to={href.to}
                      params={href.params}
                      className="font-medium text-ink hover:text-accent"
                    >
                      {j.sourceFilename ?? j.id.slice(0, 8)}
                    </Link>
                    <span className="ml-2 font-mono text-[10px] uppercase tracking-wider text-faint">
                      {j.sourceKind}
                    </span>
                    {j.error && (
                      <div className="mt-0.5 text-xs text-bad">{j.error}</div>
                    )}
                  </td>
                  <td className="px-3 py-2 font-mono tabular-nums text-muted">
                    {j.pageCount ?? "—"}
                    {j.selectedPageCount != null && j.pageCount != null && j.selectedPageCount < j.pageCount
                      ? ` (${j.selectedPageCount} read)`
                      : ""}
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-2">
                      <StatusPill status={step.status} />
                      {step.detail && (
                        <span className="truncate text-xs text-muted">{step.detail}</span>
                      )}
                    </div>
                  </td>
                  <td className="px-3 py-2 text-right font-mono tabular-nums" title={j.quote?.name ?? undefined}>
                    {j.quote ? formatUsd(j.quote.totalCents) : <span className="text-faint">—</span>}
                  </td>
                  <td className="px-3 py-2 text-right text-muted" title={new Date(j.updatedAt).toLocaleString()}>
                    {relative(j.updatedAt)}
                  </td>
                </tr>
              );
            })}
            {q.isLoading && (
              <tr>
                <td colSpan={5} className="p-0">
                  <SkeletonRows rows={4} />
                </td>
              </tr>
            )}
            {!q.isLoading && jobs.length === 0 && (
              <tr>
                <td colSpan={5} className="p-3">
                  <EmptyState
                    title="No jobs yet"
                    description="Drop a plan set above. Scribe reads it and drafts the cabinet breakdown for you to check before it prices anything."
                  />
                </td>
              </tr>
            )}
            {!q.isLoading && jobs.length > 0 && visible.length === 0 && (
              <tr>
                <td colSpan={5} className="px-3 py-6 text-center text-sm text-muted">
                  Nothing under “{FILTERS.find((f) => f.key === filter)?.label}”.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </Card>
      {q.isError && (
        <p className="mt-2 text-sm text-bad">
          Couldn't load jobs: {errorMessage(q.error)}
        </p>
      )}
    </div>
  );
}
