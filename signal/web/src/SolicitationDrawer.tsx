import type { SolicitationDetail } from "./api";

export default function SolicitationDrawer({
  detail, loading, onClose,
}: {
  detail: SolicitationDetail | null;
  loading: boolean;
  onClose: () => void;
}) {
  return (
    <>
      <div className="fixed inset-0 bg-black/30 z-40" onClick={onClose} />
      <aside className="fixed right-0 top-0 h-full w-[34rem] max-w-[90vw] bg-white shadow-xl z-50 overflow-y-auto">
        <header className="flex items-center justify-between border-b px-4 py-3 sticky top-0 bg-white">
          <h2 className="font-semibold pr-4">
            {loading ? "Loading…" : detail?.title || `Solicitation #${detail?.id}`}
          </h2>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700 text-xl leading-none">×</button>
        </header>

        {detail && (
          <div className="p-4 space-y-5 text-sm">
            <section className="grid grid-cols-2 gap-2">
              <Field label="Agency" value={detail.agency ?? "—"} />
              <Field label="Source" value={detail.source_type} />
              <Field label="State / city" value={[detail.state, detail.place_city].filter(Boolean).join(" / ") || "—"} />
              <Field label="NAICS" value={detail.naics ?? "—"} />
              <Field label="Posted" value={detail.posted_date ?? "—"} />
              <Field label="Bid due" value={detail.due_date ?? "—"} strong />
              <Field label="Status" value={detail.status ?? "—"} />
              <Field label="Est. value" value={detail.estimated_value != null ? `$${Number(detail.estimated_value).toLocaleString()}` : "—"} />
            </section>

            {detail.description && (
              <section>
                <h3 className="font-semibold mb-1">Description</h3>
                <p className="text-slate-600 break-words">{detail.description}</p>
              </section>
            )}

            <section>
              <h3 className="font-semibold mb-1">Plans &amp; documents ({detail.documents.length})</h3>
              {detail.documents.length === 0 ? (
                <p className="text-slate-400">No attached documents.</p>
              ) : (
                <ul className="space-y-1">
                  {detail.documents.map((d, i) => (
                    <li key={i} className="border-b py-1">
                      <a href={d.url} target="_blank" rel="noreferrer"
                        className="text-amber-700 underline break-all">
                        {d.name || d.url}
                      </a>
                      <span className="text-slate-400 text-xs"> · {d.doc_type}</span>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            {detail.source_url && (
              <a href={detail.source_url} target="_blank" rel="noreferrer"
                className="inline-block text-amber-700 underline">
                open on source portal →
              </a>
            )}
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
