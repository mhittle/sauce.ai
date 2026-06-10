import { useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { apiUpload, apiGet } from "../api";
import { Badge, Button, Card, PageTitle, statusTone } from "../ui";

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
  const fileRef = useRef<HTMLInputElement>(null);
  const q = useQuery({
    queryKey: ["takeoffs"],
    queryFn: () => apiGet<Takeoff[]>("/takeoffs"),
    refetchInterval: 5000,
  });

  const upload = useMutation({
    mutationFn: (file: File) => apiUpload<Takeoff>("/takeoffs", file),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["takeoffs"] }),
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
              disabled={upload.isPending}
              onClick={() => fileRef.current?.click()}
            >
              {upload.isPending ? "Uploading…" : "Upload plan / schedule"}
            </Button>
          </div>
        }
      >
        Takeoffs
      </PageTitle>

      {upload.isError && (
        <p className="mb-2 text-sm text-red-600">{String(upload.error)}</p>
      )}

      <Card className="p-0">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-zinc-200 text-left text-zinc-500">
              <th className="px-3 py-2">File</th>
              <th className="px-3 py-2">Kind</th>
              <th className="px-3 py-2">Pages</th>
              <th className="px-3 py-2">Confidence</th>
              <th className="px-3 py-2">Status</th>
              <th className="px-3 py-2">Created</th>
            </tr>
          </thead>
          <tbody>
            {(q.data ?? []).map((t) => (
              <tr key={t.id} className="border-b border-zinc-100 hover:bg-zinc-50">
                <td className="px-3 py-2">
                  <Link
                    to="/takeoffs/$takeoffId"
                    params={{ takeoffId: t.id }}
                    className="font-medium text-blue-700 hover:underline"
                  >
                    {t.sourceFilename ?? t.id.slice(0, 8)}
                  </Link>
                  {t.error && (
                    <div className="text-xs text-red-600">{t.error}</div>
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
                  <Badge tone={statusTone(t.status)}>{t.status}</Badge>
                </td>
                <td className="px-3 py-2 text-zinc-500">
                  {new Date(t.createdAt).toLocaleString()}
                </td>
              </tr>
            ))}
            {(q.data ?? []).length === 0 && (
              <tr>
                <td colSpan={6} className="px-3 py-6 text-center text-zinc-400">
                  Upload a plan set PDF, spreadsheet, or schedule photo to run
                  your first takeoff.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </Card>
    </div>
  );
}
