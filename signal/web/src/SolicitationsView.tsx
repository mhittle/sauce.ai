import { useEffect, useState } from "react";
import {
  fetchSolicitation,
  fetchSolicitations,
  type Solicitation,
  type SolicitationDetail,
} from "./api";
import SolicitationsTable from "./SolicitationsTable";
import SolicitationDrawer from "./SolicitationDrawer";
import type { SortState } from "./ProjectsTable";

const PAGE = 50;

export default function SolicitationsView() {
  const [items, setItems] = useState<Solicitation[]>([]);
  const [total, setTotal] = useState(0);
  const [sort, setSort] = useState<SortState>({ col: "due_date", dir: "asc" });
  const [offset, setOffset] = useState(0);
  const [hasDocs, setHasDocs] = useState(false);
  const [stateFilter, setStateFilter] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<SolicitationDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  useEffect(() => {
    setLoading(true);
    fetchSolicitations({
      has_docs: hasDocs,
      state: stateFilter.trim().toUpperCase() || undefined,
      sort: sort.col,
      dir: sort.dir,
      limit: PAGE,
      offset,
    })
      .then((r) => {
        setItems(r.items);
        setTotal(r.total);
        setError(null);
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [hasDocs, stateFilter, sort, offset]);

  const onSort = (col: string) => {
    setOffset(0);
    setSort((prev) =>
      prev.col === col ? { col, dir: prev.dir === "asc" ? "desc" : "asc" } : { col, dir: "asc" },
    );
  };

  const open = (id: number) => {
    setSelectedId(id);
    setDetail(null);
    setDetailLoading(true);
    fetchSolicitation(id)
      .then(setDetail)
      .catch((e) => setError(String(e)))
      .finally(() => setDetailLoading(false));
  };

  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + PAGE, total);

  return (
    <div className="flex">
      <aside className="w-64 shrink-0 border-r p-4 space-y-4">
        <div>
          <h2 className="text-xs font-semibold uppercase text-slate-400 mb-1">Filters</h2>
          <label className="flex items-center gap-2 text-sm cursor-pointer mb-2">
            <input type="checkbox" checked={hasDocs}
              onChange={() => { setOffset(0); setHasDocs((v) => !v); }} />
            Has plans / documents
          </label>
          <label className="block text-sm">
            <span className="text-slate-500">State</span>
            <input value={stateFilter}
              onChange={(e) => { setOffset(0); setStateFilter(e.target.value); }}
              placeholder="GA" maxLength={2}
              className="mt-1 w-full border rounded px-2 py-1 uppercase" />
          </label>
        </div>
      </aside>

      <main className="flex-1 p-4">
        {error && (
          <div className="mb-3 rounded bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>
        )}
        <div className="mb-2 flex items-center justify-between text-sm text-slate-500">
          <span>{loading ? "Loading…" : `${from}–${to} of ${total} solicitations`}</span>
          <span className="flex gap-2">
            <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}
              className="px-2 py-1 border rounded disabled:opacity-40">Prev</button>
            <button disabled={to >= total} onClick={() => setOffset(offset + PAGE)}
              className="px-2 py-1 border rounded disabled:opacity-40">Next</button>
          </span>
        </div>
        <SolicitationsTable data={items} sort={sort} onSort={onSort} onRowClick={open} selectedId={selectedId} />
      </main>

      {selectedId !== null && (
        <SolicitationDrawer detail={detail} loading={detailLoading}
          onClose={() => { setSelectedId(null); setDetail(null); }} />
      )}
    </div>
  );
}
