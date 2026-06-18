import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "@tanstack/react-router";
import { apiGet, apiSend, formatUsd } from "../api";
import { Badge, Button, Card, PageTitle, statusTone } from "../ui";

interface ProjectDoc {
  id: string;
  docClass: string;
  pageCount: number | null;
  fetchedFromUrl: string;
}

interface ProjectDetail {
  id: string;
  canonicalAddress: string | null;
  jurisdiction: string | null;
  permitNumber: string | null;
  parcel: string | null;
  projectType: string | null;
  valuationCents: number | null;
  estCabinetScopeUsd: number | null;
  description: string | null;
  gcName: string | null;
  gcContact: unknown;
  status: string;
  cabinetRelevanceScore: number | null;
  scoreRationale: string | null;
  sourceRefs: SourceRef[];
  createdAt: string;
  documents: ProjectDoc[];
}

interface SourceRef {
  source_id?: string;
  external_id?: string;
  url?: string;
}

function docTone(docClass: string): "green" | "blue" | "zinc" {
  if (docClass === "plan_set") return "green";
  if (docClass === "spec_book") return "blue";
  return "zinc";
}

export function ProspectDetailPage() {
  const { projectId } = useParams({ from: "/prospects/$projectId" });
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [previewDocId, setPreviewDocId] = useState<string | null>(null);

  const q = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => apiGet<ProjectDetail>(`/projects/${projectId}`),
  });

  const patch = useMutation({
    mutationFn: (status: string) =>
      apiSend("PATCH", `/projects/${projectId}`, { status }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["project", projectId] });
      qc.invalidateQueries({ queryKey: ["projects"] });
    },
  });

  const runTakeoff = useMutation({
    mutationFn: (docId: string) =>
      apiSend<{ id: string }>("POST", "/takeoffs", {
        project_document_id: docId,
      }),
    onSuccess: (t) =>
      navigate({ to: "/takeoffs/$takeoffId", params: { takeoffId: t.id } }),
  });

  const preview = useQuery({
    queryKey: ["project-doc-url", previewDocId],
    queryFn: () =>
      apiGet<{ url: string }>(`/project-documents/${previewDocId}/url`),
    enabled: previewDocId != null,
    staleTime: 10 * 60 * 1000,
  });

  if (q.isLoading) return <div className="text-zinc-500">Loading…</div>;
  if (q.isError) return <div className="text-red-600">{String(q.error)}</div>;

  const p = q.data!;
  const title = p.canonicalAddress ?? p.permitNumber ?? "Unknown project";

  return (
    <div>
      <PageTitle
        actions={
          <div className="space-x-1">
            <Link to="/prospects">
              <Button variant="ghost">← Back to queue</Button>
            </Link>
            <Button onClick={() => patch.mutate("triaged")}>Triage</Button>
            <Button variant="ghost" onClick={() => patch.mutate("ignored")}>
              Ignore
            </Button>
          </div>
        }
      >
        {title}
      </PageTitle>

      <div className="mb-4 flex items-center gap-3">
        <Badge tone={statusTone(p.status)}>{p.status}</Badge>
        {p.cabinetRelevanceScore != null && (
          <span className="text-sm text-zinc-500">
            Relevance score{" "}
            <span className="font-semibold text-zinc-800">
              {Math.round(p.cabinetRelevanceScore)}
            </span>
          </span>
        )}
        {p.estCabinetScopeUsd != null && (
          <span className="text-sm text-zinc-500">
            Est. cabinet scope{" "}
            <span className="font-semibold text-zinc-800">
              ${Math.round(p.estCabinetScopeUsd).toLocaleString()}
            </span>
          </span>
        )}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <h2 className="mb-3 text-sm font-semibold text-zinc-700">Details</h2>
          <dl className="space-y-2 text-sm">
            <Field label="Address" value={p.canonicalAddress} />
            <Field label="Jurisdiction" value={p.jurisdiction} />
            <Field label="Permit #" value={p.permitNumber} />
            <Field label="Parcel" value={p.parcel} />
            <Field label="Project type" value={p.projectType} />
            <Field
              label="Valuation"
              value={
                p.valuationCents != null ? formatUsd(p.valuationCents) : null
              }
            />
            <Field label="GC" value={p.gcName} />
            <Field label="Score rationale" value={p.scoreRationale} />
            {(Array.isArray(p.sourceRefs) ? p.sourceRefs : []).some(
              (r) => r.url
            ) && (
              <div>
                <dt className="text-zinc-500">Source</dt>
                <dd className="space-y-1">
                  {(Array.isArray(p.sourceRefs) ? p.sourceRefs : [])
                    .filter((r) => r.url)
                    .map((r, i) => (
                      <a
                        key={r.url ?? i}
                        href={r.url}
                        target="_blank"
                        rel="noreferrer"
                        className="block truncate text-blue-600 hover:underline"
                        title={r.url}
                      >
                        {r.external_id
                          ? `${r.external_id} ↗`
                          : `${r.url} ↗`}
                      </a>
                    ))}
                </dd>
              </div>
            )}
            {p.description && (
              <div>
                <dt className="text-zinc-500">Description</dt>
                <dd className="whitespace-pre-wrap text-zinc-800">
                  {p.description}
                </dd>
              </div>
            )}
          </dl>
        </Card>

        <Card>
          <h2 className="mb-3 text-sm font-semibold text-zinc-700">
            Documents &amp; plans
          </h2>
          {p.documents.length === 0 ? (
            <p className="text-sm text-zinc-500">
              No documents discovered for this prospect.
            </p>
          ) : (
            <ul className="space-y-3">
              {p.documents.map((d) => (
                <li
                  key={d.id}
                  className="rounded-md border border-zinc-200 p-3"
                >
                  <div className="mb-2 flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <Badge tone={docTone(d.docClass)}>
                        {d.docClass.replace(/_/g, " ")}
                      </Badge>
                      {d.pageCount != null && (
                        <span className="text-xs text-zinc-400">
                          {d.pageCount} pp
                        </span>
                      )}
                    </div>
                    <div className="space-x-1 whitespace-nowrap">
                      <Button
                        onClick={() =>
                          setPreviewDocId((cur) =>
                            cur === d.id ? null : d.id
                          )
                        }
                      >
                        {previewDocId === d.id ? "Hide" : "View"}
                      </Button>
                      <Button
                        variant="primary"
                        disabled={runTakeoff.isPending}
                        onClick={() => runTakeoff.mutate(d.id)}
                      >
                        Send to Takeoff
                      </Button>
                    </div>
                  </div>
                  <div
                    className="truncate text-xs text-zinc-400"
                    title={d.fetchedFromUrl}
                  >
                    {d.fetchedFromUrl}
                  </div>
                  {previewDocId === d.id && (
                    <div className="mt-3">
                      {preview.isLoading && (
                        <div className="text-xs text-zinc-500">
                          Loading preview…
                        </div>
                      )}
                      {preview.isError && (
                        <div className="text-xs text-red-600">
                          Could not load preview.
                        </div>
                      )}
                      {preview.data?.url && (
                        <>
                          <iframe
                            src={preview.data.url}
                            title="Plan preview"
                            className="h-[28rem] w-full rounded border border-zinc-200"
                          />
                          <a
                            href={preview.data.url}
                            target="_blank"
                            rel="noreferrer"
                            className="mt-1 inline-block text-xs text-blue-600 hover:underline"
                          >
                            Open in new tab ↗
                          </a>
                        </>
                      )}
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}

function Field({
  label,
  value,
}: {
  label: string;
  value: string | null | undefined;
}) {
  if (!value) return null;
  return (
    <div className="flex justify-between gap-4">
      <dt className="text-zinc-500">{label}</dt>
      <dd className="text-right text-zinc-800">{value}</dd>
    </div>
  );
}
