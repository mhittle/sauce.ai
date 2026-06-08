import { useEffect, useState } from "react";
import { fetchFacets, fetchProjects, type Project, type SignalDef } from "./api";
import ProjectsTable from "./ProjectsTable";

export default function App() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [facets, setFacets] = useState<SignalDef[]>([]);
  const [active, setActive] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    fetchFacets().then(setFacets).catch(() => setFacets([]));
  }, []);

  useEffect(() => {
    setLoading(true);
    fetchProjects({ signals: [...active] })
      .then((r) => {
        setProjects(r.items);
        setError(null);
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [active]);

  const toggle = (id: string) =>
    setActive((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  const distressFacets = facets.filter((f) => f.id.startsWith("distress_"));
  const otherFacets = facets.filter((f) => !f.id.startsWith("distress_"));

  return (
    <div className="min-h-screen bg-white text-slate-800">
      <header className="border-b px-6 py-4">
        <h1 className="text-xl font-bold">
          sauce.ai<span className="text-amber-600">/signal</span>
        </h1>
        <p className="text-sm text-slate-500">
          Permit intelligence & distressed-project triage
        </p>
      </header>

      <div className="flex">
        <aside className="w-64 shrink-0 border-r p-4 space-y-4">
          <FacetGroup title="Distress" facets={distressFacets} active={active} onToggle={toggle} />
          <FacetGroup title="Filters" facets={otherFacets} active={active} onToggle={toggle} />
        </aside>

        <main className="flex-1 p-4">
          {error && (
            <div className="mb-3 rounded bg-red-50 px-3 py-2 text-sm text-red-700">
              {error}
            </div>
          )}
          <div className="mb-2 text-sm text-slate-500">
            {loading ? "Loading…" : `${projects.length} projects`}
          </div>
          <ProjectsTable data={projects} />
        </main>
      </div>
    </div>
  );
}

function FacetGroup({
  title,
  facets,
  active,
  onToggle,
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
              <input
                type="checkbox"
                checked={active.has(f.id)}
                onChange={() => onToggle(f.id)}
              />
              {f.label}
            </label>
          </li>
        ))}
      </ul>
    </div>
  );
}
