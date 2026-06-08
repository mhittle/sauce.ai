import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
  type SortingState,
} from "@tanstack/react-table";
import { useState } from "react";
import type { Project } from "./api";

const col = createColumnHelper<Project>();

const columns = [
  col.accessor("lead_score", {
    header: "Score",
    cell: (c) => <span className="font-semibold">{Number(c.getValue()).toFixed(1)}</span>,
  }),
  col.accessor("primary_address", { header: "Address" }),
  col.accessor("jurisdiction", { header: "Jurisdiction" }),
  col.accessor("category", { header: "Category" }),
  col.accessor("value_tier", { header: "Value" }),
  col.accessor("status", { header: "Status" }),
];

export default function ProjectsTable({ data }: { data: Project[] }) {
  // Default sort by lead_score desc (PRD §10 default sort).
  const [sorting, setSorting] = useState<SortingState>([
    { id: "lead_score", desc: true },
  ]);
  const table = useReactTable({
    data,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  return (
    <table className="w-full text-sm border-collapse">
      <thead className="bg-slate-100 text-left">
        {table.getHeaderGroups().map((hg) => (
          <tr key={hg.id}>
            {hg.headers.map((h) => (
              <th
                key={h.id}
                onClick={h.column.getToggleSortingHandler()}
                className="px-3 py-2 cursor-pointer select-none font-medium"
              >
                {flexRender(h.column.columnDef.header, h.getContext())}
                {{ asc: " ▲", desc: " ▼" }[h.column.getIsSorted() as string] ?? ""}
              </th>
            ))}
          </tr>
        ))}
      </thead>
      <tbody>
        {table.getRowModel().rows.map((row) => (
          <tr key={row.id} className="border-b hover:bg-amber-50">
            {row.getVisibleCells().map((cell) => (
              <td key={cell.id} className="px-3 py-2">
                {flexRender(cell.column.columnDef.cell, cell.getContext())}
              </td>
            ))}
          </tr>
        ))}
        {data.length === 0 && (
          <tr>
            <td colSpan={columns.length} className="px-3 py-8 text-center text-slate-400">
              No projects yet — run an ingest (jobs/daily_ingest.py).
            </td>
          </tr>
        )}
      </tbody>
    </table>
  );
}
