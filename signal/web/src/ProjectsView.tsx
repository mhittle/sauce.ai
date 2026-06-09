import { useEffect, useState } from "react";
import {
  fetchFacets,
  fetchProject,
  fetchProjects,
  type Project,
  type ProjectDetail,
  type SignalDef,
} from "./api";
import ProjectsTable, { type SortState } from "./ProjectsTable";
import ProjectDrawer from "./ProjectDrawer";

const PAGE = 50;

export default function ProjectsView() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [total, setTotal] = useState(0);
  const [facets, setFacets] = useState<SignalDef[]>([]);
  const [active, setActive] = useState<Set<string>>(new Set());
  const [sort, setSort] = useState<SortState>({ col: "lead_score", dir: "desc" });
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<ProjectDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  useEffect(() => {
    fetchFacets().then(setFacets).catch(() => setFacets([]));
  }, []);

  useEffect(() => {
    setLoading(true);
    fetchProjects({ signals: [...active], sort: sort.col, dir: sort.dir, limit: PAGE, offset })
      .then((r) => {
        setProjects(r.items);
        setTotal(r.total);
        setError(null);
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [active, sort, offset]);

  const toggleFacet = (id: string) => {
    setOffset(0);
    setActive((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const onSort = (col: string) => {
    setOffset(0);
    setSort((prev) =>
      prev.col === col ? { col, dir: prev.dir === "asc" ? "desc" : "asc" } : { col, dir: "desc" },
    );
  };

  const openProject = (id: number) => {
    setSelectedId(id);
    setDetail(null);
    setDetailLoading(true);
    fetchProject(id)
      .then(setDetail)
      .catch((e) => setError(String(e)))
      .finally(() => setDetailLoading(false));
  };

  const distressFacets = facets.filter((f) => f.id.startsWith("distress_"));
  const otherFacets = facets.filter((f) => !f.id.startsWith("distress_"));
  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + PAGE, total);

  return (
    <div className="flex">
      <aside className="w-64 shrink-0 border-r p-4 space-y-4">
        <FacetGroup title="Distress" facets={distressFacets} active={active} onToggle={toggleFacet} />
        <FacetGroup title="Filters" facets={otherFacets} active={active} onToggle={toggleFacet} />
      </aside>

      <main className="flex-1 p-4">
        {error && (
          <div className="mb-3 rounded bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>
        )}
        <div className="mb-2 flex items-center justify-between text-sm text-slate-500">
          <span>{loading ? "Loading…" : `${from}–${to} of ${total} projects`}</span>
          <span className="flex gap-2">
            <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}
              className="px-2 py-1 border rounded disabled:opacity-40">Prev</button>
            <button disabled={to >= total} onClick={() => setOffset(offset + PAGE)}
              className="px-2 py-1 border rounded disabled:opacity-40">Next</button>
          </span>
        </div>
        <ProjectsTable data={projects} sort={sort} onSort={onSort} onRowClick={openProject} selectedId={selectedId} />
      </main>

      {selectedId !== null && (
        <ProjectDrawer detail={detail} loading={detailLoading}
          onClose={() => { setSelectedId(null); setDetail(null); }} />
      )}
    </div>
  );
}

function FacetGroup({
  title, facets, active, onToggle,
}: {
  title: string;
  facets: SignalDef[];
  active: Set<string>;
  onToggle: (id: string) => void;
}) {
  if (facets.length === 0) return null;
  return (
    <div>
      <h2 className="text-xs font-semibold uppercase text-slate-400 mb-1">{title}</h2>
      <ul className="space-y-1">
        {facets.map((f) => (
          <li key={f.id}>
            <label className="flex items-center gap-2 text-sm cursor-pointer">
              <input type="checkbox" checked={active.has(f.id)} onChange={() => onToggle(f.id)} />
              {f.label}
            </label>
          </li>
        ))}
      </ul>
    </div>
  );
}
