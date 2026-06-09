import type { ReactNode } from "react";
import type { Project } from "./api";

export interface SortState {
  col: string;
  dir: "asc" | "desc";
}

interface Column {
  key: string;
  label: string;
  sortable: boolean;
  render?: (p: Project) => ReactNode;
}

const COLUMNS: Column[] = [
  {
    key: "lead_score",
    label: "Score",
    sortable: true,
    render: (p) => <span className="font-semibold">{Number(p.lead_score).toFixed(1)}</span>,
  },
  { key: "primary_address", label: "Address", sortable: true,
    render: (p) => p.primary_address ?? <span className="text-slate-300">—</span> },
  { key: "jurisdiction", label: "City", sortable: true },
  { key: "category", label: "Category", sortable: true },
  { key: "value_tier", label: "Value", sortable: true },
  { key: "status", label: "Status", sortable: true },
];

export default function ProjectsTable({
  data,
  sort,
  onSort,
  onRowClick,
  selectedId,
}: {
  data: Project[];
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
            <th
              key={c.key}
              onClick={() => c.sortable && onSort(c.key)}
              className={`px-3 py-2 font-medium select-none ${
                c.sortable ? "cursor-pointer hover:bg-slate-200" : ""
              }`}
            >
              {c.label}
              {sort.col === c.key ? (sort.dir === "asc" ? " ▲" : " ▼") : ""}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {data.map((p) => (
          <tr
            key={p.id}
            onClick={() => onRowClick(p.id)}
            className={`border-b cursor-pointer hover:bg-amber-50 ${
              selectedId === p.id ? "bg-amber-100" : ""
            }`}
          >
            {COLUMNS.map((c) => {
              const raw = (p as unknown as Record<string, unknown>)[c.key];
              return (
                <td key={c.key} className="px-3 py-2">
                  {c.render
                    ? c.render(p)
                    : raw != null && raw !== ""
                      ? String(raw)
                      : <span className="text-slate-300">—</span>}
                </td>
              );
            })}
          </tr>
        ))}
        {data.length === 0 && (
          <tr>
            <td colSpan={COLUMNS.length} className="px-3 py-8 text-center text-slate-400">
              No projects match — adjust filters or run an ingest.
            </td>
          </tr>
        )}
      </tbody>
    </table>
  );
}
