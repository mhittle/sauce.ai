import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { apiGet, apiSend, formatUsd } from "../api";
import { Badge, Button, Card, PageTitle, statusTone } from "../ui";

interface ProjectDoc {
  id: string;
  docClass: string;
}

interface Project {
  id: string;
  canonicalAddress: string | null;
  jurisdiction: string | null;
  permitNumber: string | null;
  projectType: string | null;
  valuationCents: number | null;
  estCabinetScopeUsd: number | null;
  description: string | null;
  status: string;
  cabinetRelevanceScore: number | null;
  scoreRationale: string | null;
  documents: ProjectDoc[];
}

export function ProspectQueuePage() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const q = useQuery({
    queryKey: ["projects"],
    queryFn: () => apiGet<Project[]>("/projects"),
  });

  const patch = useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) =>
      apiSend("PATCH", `/projects/${id}`, { status }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["projects"] }),
  });

  const runTakeoff = useMutation({
    mutationFn: (docId: string) =>
      apiSend<{ id: string }>("POST", "/takeoffs", {
        project_document_id: docId,
      }),
    onSuccess: (t) =>
      navigate({ to: "/takeoffs/$takeoffId", params: { takeoffId: t.id } }),
  });

  if (q.isLoading) return <div className="text-zinc-500">Loading…</div>;
  if (q.isError) return <div className="text-red-600">{String(q.error)}</div>;

  const projects = q.data!;
  const aboveFold = projects.filter(
    (p) => (p.estCabinetScopeUsd ?? 0) >= 35000
  );
  const belowFold = projects.filter(
    (p) => (p.estCabinetScopeUsd ?? 0) < 35000
  );

  return (
    <div>
      <PageTitle>Prospect Queue</PageTitle>
      {projects.length === 0 && (
        <Card>
          <p className="text-sm text-zinc-500">
            No prospected projects yet. The crawler runs every 6 hours; an
            admin can trigger a source manually from the Admin screen.
          </p>
        </Card>
      )}
      <ProjectTable
        projects={aboveFold}
        onView={(id) => navigate({ to: "/prospects/$projectId", params: { projectId: id } })}
        onIgnore={(id) => patch.mutate({ id, status: "ignored" })}
        onTriage={(id) => patch.mutate({ id, status: "triaged" })}
        onRunTakeoff={(docId) => runTakeoff.mutate(docId)}
      />
      {belowFold.length > 0 && (
        <>
          <h2 className="mb-2 mt-6 text-sm font-semibold text-zinc-400">
            Below the fold (est. scope &lt; $35k)
          </h2>
          <ProjectTable
            projects={belowFold}
            onView={(id) => navigate({ to: "/prospects/$projectId", params: { projectId: id } })}
            onIgnore={(id) => patch.mutate({ id, status: "ignored" })}
            onTriage={(id) => patch.mutate({ id, status: "triaged" })}
            onRunTakeoff={(docId) => runTakeoff.mutate(docId)}
          />
        </>
      )}
    </div>
  );
}

function ProjectTable({
  projects,
  onView,
  onIgnore,
  onTriage,
  onRunTakeoff,
}: {
  projects: Project[];
  onView: (id: string) => void;
  onIgnore: (id: string) => void;
  onTriage: (id: string) => void;
  onRunTakeoff: (docId: string) => void;
}) {
  if (projects.length === 0) return null;
  return (
    <Card className="overflow-x-auto p-0">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-zinc-200 text-left text-zinc-500">
            <th className="px-3 py-2">Score</th>
            <th className="px-3 py-2">Est. scope</th>
            <th className="px-3 py-2">Project</th>
            <th className="px-3 py-2">Jurisdiction</th>
            <th className="px-3 py-2">Plans</th>
            <th className="px-3 py-2">Status</th>
            <th className="px-3 py-2"></th>
          </tr>
        </thead>
        <tbody>
          {projects.map((p) => {
            const planDoc = p.documents.find((d) => d.docClass === "plan_set");
            return (
              <tr key={p.id} className="border-b border-zinc-100 align-top">
                <td className="px-3 py-2 font-semibold">
                  {p.cabinetRelevanceScore != null
                    ? Math.round(p.cabinetRelevanceScore)
                    : "—"}
                </td>
                <td className="px-3 py-2">
                  {p.estCabinetScopeUsd != null
                    ? `$${Math.round(p.estCabinetScopeUsd).toLocaleString()}`
                    : "—"}
                </td>
                <td className="max-w-md px-3 py-2">
                  <div className="font-medium">
                    {p.canonicalAddress ?? p.permitNumber ?? "Unknown"}
                  </div>
                  <div
                    className="truncate text-xs text-zinc-500"
                    title={p.description ?? undefined}
                  >
                    {p.description}
                  </div>
                  <div className="text-xs text-zinc-400">
                    {p.scoreRationale} ·{" "}
                    {p.valuationCents != null
                      ? `valuation ${formatUsd(p.valuationCents)}`
                      : "no valuation"}
                  </div>
                </td>
                <td className="px-3 py-2">{p.jurisdiction}</td>
                <td className="px-3 py-2">
                  {p.documents.length > 0 ? (
                    <Badge tone={planDoc ? "green" : "zinc"}>
                      {p.documents.length} doc
                      {p.documents.length === 1 ? "" : "s"}
                    </Badge>
                  ) : (
                    <span className="text-zinc-300">—</span>
                  )}
                </td>
                <td className="px-3 py-2">
                  <Badge tone={statusTone(p.status)}>{p.status}</Badge>
                </td>
                <td className="space-x-1 whitespace-nowrap px-3 py-2">
                  <Button onClick={() => onView(p.id)}>View</Button>
                  {planDoc && (
                    <Button
                      variant="primary"
                      onClick={() => onRunTakeoff(planDoc.id)}
                    >
                      Run Takeoff
                    </Button>
                  )}
                  <Button onClick={() => onTriage(p.id)}>Triage</Button>
                  <Button variant="ghost" onClick={() => onIgnore(p.id)}>
                    Ignore
                  </Button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </Card>
  );
}
