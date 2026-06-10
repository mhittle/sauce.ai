import { useQuery } from "@tanstack/react-query";
import { apiGet, formatUsd } from "../api";
import { Card, PageTitle } from "../ui";

interface DashboardData {
  quotes_by_status: { status: string; count: number; total_cents: number }[];
  weekly: {
    week: string;
    quotes: number;
    quoted_cents: number;
    won_cents: number;
  }[];
  avg_turnaround_minutes: string | null;
  freight_estimate_vs_actual: {
    orders: number;
    avg_estimated_cents: number;
    avg_actual_cents: number;
  } | null;
  prospects_by_status: { status: string; count: number }[];
}

export function DashboardPage() {
  const q = useQuery({
    queryKey: ["dashboard"],
    queryFn: () => apiGet<DashboardData>("/dashboard"),
  });

  if (q.isLoading) return <div className="text-zinc-500">Loading…</div>;
  if (q.isError) return <div className="text-red-600">{String(q.error)}</div>;
  const d = q.data!;

  return (
    <div>
      <PageTitle>Pipeline Dashboard</PageTitle>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <Card>
          <h2 className="mb-2 text-sm font-semibold text-zinc-500">
            Quotes by status
          </h2>
          {d.quotes_by_status.length === 0 && (
            <p className="text-sm text-zinc-400">No quotes yet.</p>
          )}
          {d.quotes_by_status.map((s) => (
            <div key={s.status} className="flex justify-between py-1 text-sm">
              <span className="capitalize">{s.status}</span>
              <span>
                {s.count} · {formatUsd(Number(s.total_cents))}
              </span>
            </div>
          ))}
        </Card>
        <Card>
          <h2 className="mb-2 text-sm font-semibold text-zinc-500">
            Turnaround & freight
          </h2>
          <div className="flex justify-between py-1 text-sm">
            <span>Avg takeoff → sent</span>
            <span>
              {d.avg_turnaround_minutes
                ? `${d.avg_turnaround_minutes} min`
                : "—"}
            </span>
          </div>
          <div className="flex justify-between py-1 text-sm">
            <span>Freight est vs actual</span>
            <span>
              {d.freight_estimate_vs_actual?.orders
                ? `${formatUsd(Number(d.freight_estimate_vs_actual.avg_estimated_cents))} / ${formatUsd(Number(d.freight_estimate_vs_actual.avg_actual_cents))}`
                : "no actuals yet"}
            </span>
          </div>
        </Card>
        <Card>
          <h2 className="mb-2 text-sm font-semibold text-zinc-500">
            Prospects
          </h2>
          {d.prospects_by_status.length === 0 && (
            <p className="text-sm text-zinc-400">
              Crawler hasn't found projects yet.
            </p>
          )}
          {d.prospects_by_status.map((s) => (
            <div key={s.status} className="flex justify-between py-1 text-sm">
              <span className="capitalize">{s.status}</span>
              <span>{s.count}</span>
            </div>
          ))}
        </Card>
      </div>

      <Card className="mt-4">
        <h2 className="mb-2 text-sm font-semibold text-zinc-500">
          $ quoted / won per week
        </h2>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-zinc-500">
              <th className="py-1">Week</th>
              <th>Quotes</th>
              <th>Quoted</th>
              <th>Won</th>
            </tr>
          </thead>
          <tbody>
            {d.weekly.map((w) => (
              <tr key={w.week} className="border-t border-zinc-100">
                <td className="py-1">{String(w.week).slice(0, 10)}</td>
                <td>{w.quotes}</td>
                <td>{formatUsd(Number(w.quoted_cents))}</td>
                <td>{formatUsd(Number(w.won_cents))}</td>
              </tr>
            ))}
            {d.weekly.length === 0 && (
              <tr>
                <td colSpan={4} className="py-2 text-zinc-400">
                  No activity yet — upload a takeoff to get started.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </Card>
    </div>
  );
}
