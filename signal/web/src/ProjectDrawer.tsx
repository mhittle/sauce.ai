import type { ProjectDetail } from "./api";

function fmtVal(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "boolean") return v ? "yes" : "no";
  return String(v);
}

export default function ProjectDrawer({
  detail,
  loading,
  onClose,
}: {
  detail: ProjectDetail | null;
  loading: boolean;
  onClose: () => void;
}) {
  return (
    <>
      <div className="fixed inset-0 bg-black/30 z-40" onClick={onClose} />
      <aside className="fixed right-0 top-0 h-full w-[34rem] max-w-[90vw] bg-white shadow-xl z-50 overflow-y-auto">
        <header className="flex items-center justify-between border-b px-4 py-3 sticky top-0 bg-white">
          <h2 className="font-semibold">
            {loading ? "Loading…" : detail?.primary_address || `Project #${detail?.id}`}
          </h2>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700 text-xl leading-none">
            ×
          </button>
        </header>

        {detail && (
          <div className="p-4 space-y-5 text-sm">
            <section className="grid grid-cols-2 gap-2">
              <Field label="Lead score" value={Number(detail.lead_score).toFixed(1)} strong />
              <Field label="City" value={detail.jurisdiction ?? "—"} />
              <Field label="Category" value={detail.category ?? "—"} />
              <Field label="Value tier" value={detail.value_tier ?? "—"} />
              <Field label="Status" value={detail.status} />
              <Field label="In CRM" value={detail.crm_id ? "yes" : "no"} />
            </section>

            <section>
              <h3 className="font-semibold mb-1">Why flagged</h3>
              {detail.why_flagged.length === 0 ? (
                <p className="text-slate-400">No scoring contributions.</p>
              ) : (
                <ul className="space-y-1">
                  {detail.why_flagged.map((w) => (
                    <li key={w.signal} className="flex justify-between border-b py-1">
                      <span>
                        <span className="font-medium">{w.signal}</span>{" "}
                        <span className="text-slate-500">= {fmtVal(w.value)}</span>
                      </span>
                      <span className="text-emerald-700 font-medium">+{w.contribution}</span>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section>
              <h3 className="font-semibold mb-1">Signals</h3>
              <div className="grid grid-cols-2 gap-x-4 gap-y-1">
                {Object.entries(detail.signals).map(([k, v]) => (
                  <div key={k} className="flex justify-between border-b py-0.5">
                    <span className="text-slate-500">{k}</span>
                    <span>{fmtVal(v)}</span>
                  </div>
                ))}
              </div>
            </section>

            <section>
              <h3 className="font-semibold mb-1">Permits ({detail.permits.length})</h3>
              <ul className="space-y-2">
                {detail.permits.map((p) => (
                  <li key={p.permit_id} className="border rounded p-2">
                    <div className="flex justify-between">
                      <span className="font-medium">{p.permit_type ?? "permit"}</span>
                      <span className="text-slate-500">{p.status ?? ""}</span>
                    </div>
                    {p.work_description && (
                      <div className="text-slate-600">{p.work_description}</div>
                    )}
                    <div className="text-slate-500 text-xs mt-1">
                      {p.issue_date ? `issued ${p.issue_date}` : ""}
                      {p.valuation != null ? ` · $${Number(p.valuation).toLocaleString()}` : ""}
                      {p.contractor_name ? ` · ${p.contractor_name}` : ""}
                    </div>
                    {p.source_url && (
                      <a href={p.source_url} target="_blank" rel="noreferrer"
                         className="text-amber-700 underline text-xs">
                        source record →
                      </a>
                    )}
                  </li>
                ))}
              </ul>
            </section>
          </div>
        )}
      </aside>
    </>
  );
}

function Field({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return (
    <div>
      <div className="text-xs uppercase text-slate-400">{label}</div>
      <div className={strong ? "font-semibold" : ""}>{value}</div>
    </div>
  );
}
