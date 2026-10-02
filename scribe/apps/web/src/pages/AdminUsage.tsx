import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../api";
import { TechnicalDetail } from "../components/TechnicalDetail";
import { USAGE_LOAD_FAILED } from "../messages";
import { Card, Field, Input, SectionLabel, Select, SkeletonRows } from "../ui";

// Admin → Usage (accounts-plan.md §3.3): what each job, stage and page costs
// us in model calls. Read-only; nothing here charges anyone.

// Postgres bigints arrive as strings.
type Num = number | string | null;

interface UsageReport {
  from: string;
  to: string;
  summary: {
    jobs: number;
    pages: number;
    cost: Num;
    median_job: Num;
    p90_job: Num;
    median_page: Num;
    p90_page: Num;
  };
  by_takeoff: {
    takeoff_id: string;
    source_filename: string | null;
    source_kind: string;
    status: string;
    org_name: string;
    pages: number;
    pages_read: number;
    calls: number;
    input_tokens: Num;
    output_tokens: Num;
    cost: Num;
    cost_per_page: Num;
    by_stage: Record<string, Num>;
    first_call: string;
  }[];
  by_stage: {
    stage: string;
    model: string;
    calls: number;
    input_tokens: Num;
    output_tokens: Num;
    images: number;
    cost: Num;
  }[];
  by_page_kind: {
    page_kind: string;
    pages: number;
    cost: Num;
    median_cost: Num;
    p90_cost: Num;
  }[];
  orgs: { id: string; name: string }[];
}

const STAGES = ["classify", "locate", "extract", "detect", "measure", "spreadsheet", "cross_validate"];

// Microcents (cents × 1e6) → dollars; sub-dollar amounts keep 4 decimals so a
// fraction of a cent still shows.
function usd(micro: Num): string {
  if (micro == null) return "—";
  const dollars = Number(micro) / 1e8;
  return `$${dollars.toFixed(Math.abs(dollars) < 1 ? 4 : 2)}`;
}

function tokens(n: Num): string {
  if (n == null) return "—";
  const v = Number(n);
  return v >= 10_000 ? `${Math.round(v / 1000)}k` : v.toLocaleString();
}

const isoDay = (d: Date) => d.toISOString().slice(0, 10);

export function Usage() {
  const today = new Date();
  const [from, setFrom] = useState(isoDay(new Date(today.getTime() - 29 * 86_400_000)));
  const [to, setTo] = useState(isoDay(today));
  const [org, setOrg] = useState("");
  const params = new URLSearchParams({ from, to, ...(org ? { org_id: org } : {}) });
  const q = useQuery({
    queryKey: ["admin-usage", from, to, org],
    queryFn: () => apiGet<UsageReport>(`/admin/usage?${params}`),
  });

  const r = q.data;
  const totalStageCost = (r?.by_stage ?? []).reduce((s, x) => s + Number(x.cost ?? 0), 0);

  return (
    <div className="space-y-6">
      <Card className="flex flex-wrap items-end gap-3">
        <Field label="From">
          <Input type="date" value={from} max={to} onChange={(e) => setFrom(e.target.value)} />
        </Field>
        <Field label="To">
          <Input type="date" value={to} min={from} onChange={(e) => setTo(e.target.value)} />
        </Field>
        <Field label="Company">
          <Select value={org} onChange={(e) => setOrg(e.target.value)}>
            <option value="">All companies</option>
            {(r?.orgs ?? []).map((o) => (
              <option key={o.id} value={o.id}>{o.name}</option>
            ))}
          </Select>
        </Field>
        <p className="text-xs text-faint">
          Our model cost at list price. Nothing on this page is charged to anyone.
        </p>
      </Card>

      {q.isLoading && <SkeletonRows rows={5} />}
      {q.isError && (
        <div className="text-bad">
          {USAGE_LOAD_FAILED}
          <TechnicalDetail details={String(q.error)} />
        </div>
      )}

      {r && (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Stat label="Jobs" value={String(r.summary.jobs)} sub={`${r.summary.pages} pages`} />
            <Stat label="Total cost" value={usd(r.summary.cost)} />
            <Stat label="Per job" value={usd(r.summary.median_job)} sub={`median · p90 ${usd(r.summary.p90_job)}`} />
            <Stat label="Per page" value={usd(r.summary.median_page)} sub={`median · p90 ${usd(r.summary.p90_page)}`} />
          </div>

          <section>
            <SectionLabel>By stage</SectionLabel>
            <Card className="overflow-x-auto p-0">
              <table className="w-full text-sm">
                <thead>
                  <Head cols={["Stage", "Model", "Calls", "Images", "In tokens", "Out tokens", "Cost", "Share"]} />
                </thead>
                <tbody>
                  {r.by_stage.map((s) => (
                    <tr key={`${s.stage}-${s.model}`} className="border-b border-rule-soft">
                      <td className="px-4 py-2 font-medium">{s.stage}</td>
                      <td className="px-3 py-2 font-mono text-xs text-muted">{s.model}</td>
                      <Numcell>{s.calls}</Numcell>
                      <Numcell>{s.images}</Numcell>
                      <Numcell>{tokens(s.input_tokens)}</Numcell>
                      <Numcell>{tokens(s.output_tokens)}</Numcell>
                      <Numcell>{usd(s.cost)}</Numcell>
                      <Numcell>
                        {totalStageCost > 0 ? `${Math.round((Number(s.cost) / totalStageCost) * 100)}%` : "—"}
                      </Numcell>
                    </tr>
                  ))}
                  {r.by_stage.length === 0 && <Empty cols={8} />}
                </tbody>
              </table>
            </Card>
          </section>

          <section>
            <SectionLabel>By page kind</SectionLabel>
            <Card className="overflow-x-auto p-0">
              <p className="border-b border-rule px-4 py-2 text-xs text-muted">
                Calls about a single page only. The measuring pass reads the whole job at once
                and shows under "measure" above, not here.
              </p>
              <table className="w-full text-sm">
                <thead>
                  <Head cols={["Page kind", "Pages", "Cost", "Median / page", "p90 / page"]} />
                </thead>
                <tbody>
                  {r.by_page_kind.map((k) => (
                    <tr key={k.page_kind} className="border-b border-rule-soft">
                      <td className="px-4 py-2 font-medium">{k.page_kind}</td>
                      <Numcell>{k.pages}</Numcell>
                      <Numcell>{usd(k.cost)}</Numcell>
                      <Numcell>{usd(k.median_cost)}</Numcell>
                      <Numcell>{usd(k.p90_cost)}</Numcell>
                    </tr>
                  ))}
                  {r.by_page_kind.length === 0 && <Empty cols={5} />}
                </tbody>
              </table>
            </Card>
          </section>

          <section>
            <SectionLabel>By job</SectionLabel>
            <Card className="overflow-x-auto p-0">
              <table className="w-full text-sm">
                <thead>
                  <Head cols={["Job", "Company", "Pages", "Calls", "Cost", "Per page", ...STAGES]} />
                </thead>
                <tbody>
                  {r.by_takeoff.map((t) => (
                    <tr key={t.takeoff_id} className="border-b border-rule-soft">
                      <td className="max-w-[16rem] truncate px-4 py-2">
                        <span className="font-medium" title={t.takeoff_id}>
                          {t.source_filename ?? t.takeoff_id.slice(0, 8)}
                        </span>
                        <div className="text-[11px] text-faint">
                          {new Date(t.first_call).toLocaleDateString()} · {t.status}
                        </div>
                      </td>
                      <td className="px-3 py-2 text-muted">{t.org_name}</td>
                      <Numcell>{t.pages}</Numcell>
                      <Numcell>{t.calls}</Numcell>
                      <Numcell>{usd(t.cost)}</Numcell>
                      <Numcell>{usd(t.cost_per_page)}</Numcell>
                      {STAGES.map((s) => (
                        <Numcell key={s}>{t.by_stage?.[s] != null ? usd(t.by_stage[s]) : ""}</Numcell>
                      ))}
                    </tr>
                  ))}
                  {r.by_takeoff.length === 0 && <Empty cols={6 + STAGES.length} />}
                </tbody>
              </table>
            </Card>
          </section>
        </>
      )}
    </div>
  );
}

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <Card>
      <div className="font-mono text-[11px] uppercase tracking-wider text-muted">{label}</div>
      <div className="mt-1 font-mono text-xl tabular-nums">{value}</div>
      {sub && <div className="text-xs text-faint">{sub}</div>}
    </Card>
  );
}

function Head({ cols }: { cols: string[] }) {
  return (
    <tr className="border-b border-rule text-left font-mono text-[11px] uppercase tracking-wider text-muted">
      {cols.map((c, i) => (
        <th key={c} className={`${i === 0 ? "px-4" : "px-3"} py-2 ${i >= 2 ? "text-right" : ""}`}>
          {c}
        </th>
      ))}
    </tr>
  );
}

function Numcell({ children }: { children: React.ReactNode }) {
  return <td className="px-3 py-2 text-right font-mono tabular-nums">{children}</td>;
}

function Empty({ cols }: { cols: number }) {
  return (
    <tr>
      <td colSpan={cols} className="px-4 py-6 text-center text-faint">
        No model calls in this range.
      </td>
    </tr>
  );
}
