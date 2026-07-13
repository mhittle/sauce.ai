import { useEffect, useState } from "react";
import {
  fetchIngestableSources,
  fetchSolicitation,
  fetchSolicitations,
  fetchSolicitationSources,
  triggerSolicitationIngest,
  type IngestableSource,
  type Solicitation,
  type SolicitationDetail,
  type SourceCount,
} from "./api";
import SolicitationsTable from "./SolicitationsTable";
import SolicitationDrawer from "./SolicitationDrawer";
import type { SortState } from "./ProjectsTable";

const PAGE = 50;

export default function SolicitationsView() {
  const [items, setItems] = useState<Solicitation[]>([]);
  const [total, setTotal] = useState(0);
  const [sort, setSort] = useState<SortState>({ col: "cabinet_score", dir: "desc" });
  const [offset, setOffset] = useState(0);
  const [hasDocs, setHasDocs] = useState(false);
  const [cabinetOnly, setCabinetOnly] = useState(false);
  const [openOnly, setOpenOnly] = useState(true);
  const [stateFilter, setStateFilter] = useState("");
  const [sourceFilter, setSourceFilter] = useState("");
  const [sources, setSources] = useState<SourceCount[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<SolicitationDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const [ingesting, setIngesting] = useState(false);
  const [ingestMsg, setIngestMsg] = useState<string | null>(null);
  const [reloadTick, setReloadTick] = useState(0);
  const [ingestables, setIngestables] = useState<IngestableSource[]>([]);
  const [ingestSource, setIngestSource] = useState("bonfire");

  useEffect(() => {
    fetchSolicitationSources().then(setSources).catch(() => setSources([]));
  }, [reloadTick]);

  useEffect(() => {
    fetchIngestableSources().then(setIngestables).catch(() => setIngestables([]));
  }, []);

  async function fetchBids() {
    setIngesting(true);
    setIngestMsg(null);
    try {
      const r = await triggerSolicitationIngest(ingestSource);
      setIngestMsg(
        r.status === "ok"
          ? `Fetched ${r.upserted} from ${ingestSource}.`
          : `Ingest ${r.status} (fetched ${r.fetched}).`);
      setOffset(0);
      setSourceFilter(ingestSource);  // focus the table on what was fetched
      setReloadTick((t) => t + 1);   // refresh the list + source counts
    } catch (e) {
      setIngestMsg(e instanceof Error ? e.message : "fetch failed");
    } finally {
      setIngesting(false);
    }
  }

  useEffect(() => {
    // Stale-response guard: filters can change faster than requests resolve;
    // without this an older, slower response lands last and overwrites the
    // table with the wrong source's rows.
    let stale = false;
    setLoading(true);
    fetchSolicitations({
      has_docs: hasDocs,
      cabinet: cabinetOnly,
      open_only: openOnly,
      state: stateFilter.trim().toUpperCase() || undefined,
      source_type: sourceFilter || undefined,
      sort: sort.col,
      dir: sort.dir,
      limit: PAGE,
      offset,
    })
      .then((r) => {
        if (stale) return;
        setItems(r.items);
        setTotal(r.total);
        setError(null);
      })
      .catch((e) => { if (!stale) setError(String(e)); })
      .finally(() => { if (!stale) setLoading(false); });
    return () => { stale = true; };
  }, [hasDocs, cabinetOnly, openOnly, stateFilter, sourceFilter, sort, offset, reloadTick]);

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
          <label className="flex items-center gap-2 text-sm cursor-pointer mb-2 font-medium text-amber-800">
            <input type="checkbox" checked={cabinetOnly}
              onChange={() => { setOffset(0); setCabinetOnly((v) => !v); }} />
            Cabinetry only
          </label>
          <label className="flex items-center gap-2 text-sm cursor-pointer mb-2">
            <input type="checkbox" checked={hasDocs}
              onChange={() => { setOffset(0); setHasDocs((v) => !v); }} />
            Has plans / documents
          </label>
          <label className="flex items-center gap-2 text-sm cursor-pointer mb-2">
            <input type="checkbox" checked={openOnly}
              onChange={() => { setOffset(0); setOpenOnly((v) => !v); }} />
            Hide past-due
          </label>
          <label className="block text-sm">
            <span className="text-slate-500">State</span>
            <input value={stateFilter}
              onChange={(e) => { setOffset(0); setStateFilter(e.target.value); }}
              placeholder="GA" maxLength={2}
              className="mt-1 w-full border rounded px-2 py-1 uppercase" />
          </label>
          <label className="block text-sm mt-2">
            <span className="text-slate-500">Source</span>
            <select value={sourceFilter}
              onChange={(e) => { setOffset(0); setSourceFilter(e.target.value); }}
              className="mt-1 w-full border rounded px-2 py-1">
              <option value="">All sources</option>
              {[...sources]
                .sort((a, b) => a.source_type.localeCompare(b.source_type))
                .map((s) => (
                  <option key={s.source_type} value={s.source_type}>
                    {s.source_type} ({s.count})
                  </option>
                ))}
            </select>
          </label>
        </div>
      </aside>

      <main className="flex-1 p-4">
        {error && (
          <div className="mb-3 rounded bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>
        )}
        <div className="mb-2 flex items-center justify-between text-sm text-slate-500">
          <span className="flex items-center gap-2">
            <span>{loading ? "Loading…" : `${from}–${to} of ${total} solicitations`}</span>
            <select value={ingestSource}
              onChange={(e) => setIngestSource(e.target.value)}
              title="Pick a source to scrape on demand"
              className="border rounded px-1 py-1 text-xs max-w-[16rem]">
              {ingestables.map((s) => (
                <option key={s.slug} value={s.slug}>
                  {s.platform === "api"
                    ? s.name
                    : `${s.name ?? s.slug}${s.state ? ` [${s.state}]` : ""}`}
                </option>
              ))}
            </select>
            <button onClick={fetchBids} disabled={ingesting}
              title="Scrape this source's current open bids now"
              className="px-2 py-1 rounded bg-amber-700 text-white text-xs disabled:opacity-50">
              {ingesting ? "Fetching…" : "↻ Fetch"}
            </button>
            {ingestMsg && <span className="text-xs text-slate-500">{ingestMsg}</span>}
          </span>
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
