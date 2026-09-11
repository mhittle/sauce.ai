import { useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { apiUpload, apiGet } from "../api";
import { Button, Card, EmptyState, errorMessage, PageTitle, SkeletonRows, StatusPill, useToast } from "../ui";

export interface Takeoff {
  id: string;
  sourceFilename: string | null;
  sourceKind: string;
  status: string;
  pageCount: number | null;
  docConfidence: number | null;
  error: string | null;
  createdAt: string;
}

export function TakeoffsPage() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const fileRef = useRef<HTMLInputElement>(null);
  const toast = useToast();
  const q = useQuery({
    queryKey: ["takeoffs"],
    queryFn: () => apiGet<Takeoff[]>("/takeoffs"),
    // Poll only while a job is still being read.
    refetchInterval: (query) =>
      query.state.data?.some((t) => t.status === "processing") ? 4000 : false,
  });

  const upload = useMutation({
    mutationFn: (file: File) => apiUpload<Takeoff>("/takeoffs", file),
    onError: (e) => toast.error("Upload failed", errorMessage(e)),
    onSuccess: (t) => {
      qc.invalidateQueries({ queryKey: ["takeoffs"] });
      // PDFs stop at the page-picker gate first; everything else lands on the
      // takeoff page, which forwards to whichever gate the status demands.
      if (t.sourceKind === "pdf") {
        navigate({ to: "/takeoffs/$takeoffId/pages", params: { takeoffId: t.id } });
      } else {
        navigate({ to: "/takeoffs/$takeoffId", params: { takeoffId: t.id } });
      }
    },
  });

  return (
    <div>
      <PageTitle
        actions={
          <div>
            <input
              ref={fileRef}
              type="file"
              accept=".pdf,.xlsx,.xls,.csv,.png,.jpg,.jpeg"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) upload.mutate(f);
                e.target.value = "";
              }}
            />
            <Button
              variant="primary"
              loading={upload.isPending}
              onClick={() => fileRef.current?.click()}
            >
              {upload.isPending ? "Uploading…" : "New job"}
            </Button>
          </div>
        }
      >
        Jobs
      </PageTitle>


      <Card className="p-0">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-rule text-left font-mono text-[11px] uppercase tracking-wider text-muted">
              <th className="px-3 py-2">File</th>
              <th className="px-3 py-2">Kind</th>
              <th className="px-3 py-2">Pages</th>
              <th className="px-3 py-2">Confidence</th>
              <th className="px-3 py-2">Status</th>
              <th className="px-3 py-2">Started</th>
            </tr>
          </thead>
          <tbody>
            {(q.data ?? []).map((t) => (
              <tr key={t.id} className="border-b border-rule-soft hover:bg-rule-soft">
                <td className="px-3 py-2">
                  <Link
                    to="/takeoffs/$takeoffId"
                    params={{ takeoffId: t.id }}
                    className="font-medium text-blue hover:underline"
                  >
                    {t.sourceFilename ?? t.id.slice(0, 8)}
                  </Link>
                  {t.error && (
                    <div className="text-xs text-bad">{t.error}</div>
                  )}
                </td>
                <td className="px-3 py-2 uppercase">{t.sourceKind}</td>
                <td className="px-3 py-2">{t.pageCount ?? "—"}</td>
                <td className="px-3 py-2">
                  {t.docConfidence != null
                    ? `${Math.round(t.docConfidence * 100)}%`
                    : "—"}
                </td>
                <td className="px-3 py-2">
                  <StatusPill status={t.status} />
                </td>
                <td className="px-3 py-2 text-muted">
                  {new Date(t.createdAt).toLocaleString()}
                </td>
              </tr>
            ))}
            {q.isLoading && (
              <tr>
                <td colSpan={6} className="p-0">
                  <SkeletonRows rows={4} />
                </td>
              </tr>
            )}
            {!q.isLoading && (q.data ?? []).length === 0 && (
              <tr>
                <td colSpan={6} className="p-3">
                  <EmptyState
                    title="No jobs yet"
                    description="Upload a plan set PDF, a spreadsheet, or a photo of a cabinet schedule. Scribe reads it and drafts the cabinet breakdown for you to check."
                    action={
                      <Button variant="primary" onClick={() => fileRef.current?.click()}>
                        Upload the first drawings
                      </Button>
                    }
                  />
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </Card>
    </div>
  );
}
