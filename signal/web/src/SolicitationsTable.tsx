import type { ReactNode } from "react";
import type { Solicitation } from "./api";
import type { SortState } from "./ProjectsTable";

interface Column {
  key: string;
  label: string;
  sortable: boolean;          // server supports due_date / posted_date / estimated_value
  render?: (s: Solicitation) => ReactNode;
}

const dash = <span className="text-slate-300">—</span>;

const COLUMNS: Column[] = [
  { key: "cabinet_score", label: "Cabinetry", sortable: true,
    render: (s) => (s.cabinet_flag
      ? <span className="rounded bg-amber-200 text-amber-900 px-1.5 py-0.5 text-xs font-semibold">
          ✓{s.cabinet_score != null ? ` ${Number(s.cabinet_score).toFixed(2)}` : ""}
        </span>
      : (s.cabinet_score != null
          ? <span className="text-xs text-slate-400">{Number(s.cabinet_score).toFixed(2)}</span>
          : dash)) },
  { key: "due_date", label: "Bid due", sortable: true,
    render: (s) => s.due_date ?? dash },
  { key: "source_type", label: "Source", sortable: false,
    render: (s) => <span className="text-xs text-slate-500">{s.source_type}</span> },
  { key: "title", label: "Title", sortable: false,
    render: (s) => s.title ?? dash },
  { key: "agency", label: "Agency", sortable: false,
    render: (s) => s.agency ?? dash },
  { key: "state", label: "State", sortable: false, render: (s) => s.state ?? dash },
  { key: "estimated_value", label: "Value", sortable: true,
    render: (s) => (s.estimated_value != null
      ? `$${Number(s.estimated_value).toLocaleString()}` : dash) },
  { key: "doc_count", label: "Docs", sortable: false,
    render: (s) => (s.doc_count > 0
      ? <span className="font-semibold text-amber-700">{s.doc_count}</span> : "0") },
];

export default function SolicitationsTable({
  data, sort, onSort, onRowClick, selectedId,
}: {
  data: Solicitation[];
  sort: SortState;
  onSort: (col: string) => void;
  onRowClick: (id: number) => void;
  selectedId: number | null;
}) {
  return (
    <table className="w-full text-sm border-collapse">
      <thead className="bg-slate-100 text-left">
        <tr>
          {COLUMNS.map((c) => (
            <th key={c.key} onClick={() => c.sortable && onSort(c.key)}
              className={`px-3 py-2 font-medium select-none ${
                c.sortable ? "cursor-pointer hover:bg-slate-200" : ""}`}>
              {c.label}
              {sort.col === c.key ? (sort.dir === "asc" ? " ▲" : " ▼") : ""}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {data.map((s) => (
          <tr key={s.id} onClick={() => onRowClick(s.id)}
            className={`border-b cursor-pointer hover:bg-amber-50 ${
              selectedId === s.id ? "bg-amber-100" : ""}`}>
            {COLUMNS.map((c) => (
              <td key={c.key} className="px-3 py-2">{c.render ? c.render(s) : dash}</td>
            ))}
          </tr>
        ))}
        {data.length === 0 && (
          <tr>
            <td colSpan={COLUMNS.length} className="px-3 py-8 text-center text-slate-400">
              No solicitations — run jobs/ingest_solicitations.py.
            </td>
          </tr>
        )}
      </tbody>
    </table>
  );
}
