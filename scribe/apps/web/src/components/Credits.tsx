import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { chargeBlocked, type CreditSettings, jobCharge } from "@scribe/shared";
import { apiGet } from "../api";
import { creditCostLine, CREDIT_REASON_LABEL, creditsShort } from "../messages";

// Credits (accounts-plan.md §3): one page read = one credit. Balance in the
// top bar, cost preview where a job is submitted, the ledger on Account.

export interface LedgerRow {
  id: number;
  delta: number;
  reason: string;
  takeoffId: string | null;
  balanceAfter: number;
  note: string | null;
  createdAt: string;
}

export interface CreditsState {
  balance: number;
  settings: CreditSettings;
  firstJobFree: boolean;
  ledger: LedgerRow[];
}

export function useCredits() {
  return useQuery({
    queryKey: ["credits"],
    queryFn: () => apiGet<CreditsState>("/credits"),
    staleTime: 30_000,
  });
}

export function CreditBalance() {
  const q = useCredits();
  if (!q.data) return null;
  const { balance, firstJobFree } = q.data;
  return (
    <Link
      to="/account"
      title="Pages of reading left — each page Scribe reads takes one"
      className="rounded-md px-2 py-1 font-mono text-xs tabular-nums text-muted hover:bg-rule-soft"
    >
      {creditsShort(balance, firstJobFree)}
    </Link>
  );
}

// "Reading 3 pages uses 3 from your balance. 17 left…", or the free-first-job line.
// Returns whether the job is blocked (only ever true once credits are enforced).
export function useJobCost(pages: number): { line: string | null; blocked: boolean } {
  const q = useCredits();
  if (!q.data || pages === 0) return { line: null, blocked: false };
  const charge = jobCharge(pages, q.data.settings, q.data.firstJobFree);
  return {
    line: creditCostLine(charge, q.data.balance),
    blocked: chargeBlocked(charge, q.data.balance, q.data.settings),
  };
}

export function LedgerTable({ rows }: { rows: LedgerRow[] }) {
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="border-b border-rule text-left font-mono text-[11px] uppercase tracking-wider text-muted">
          <th className="px-4 py-2">When</th>
          <th className="px-3 py-2">What</th>
          <th className="px-3 py-2 text-right">Pages</th>
          <th className="px-3 py-2 text-right">Balance</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.id} className="border-b border-rule-soft">
            <td className="px-4 py-2 text-muted">{new Date(r.createdAt).toLocaleDateString()}</td>
            <td className="px-3 py-2">
              {CREDIT_REASON_LABEL[r.reason] ?? r.reason}
              {r.note && <span className="text-faint"> — {r.note}</span>}
            </td>
            <td className="px-3 py-2 text-right font-mono tabular-nums">
              {r.delta > 0 ? `+${r.delta}` : r.delta === 0 ? "—" : r.delta}
            </td>
            <td className="px-3 py-2 text-right font-mono tabular-nums">{r.balanceAfter}</td>
          </tr>
        ))}
        {rows.length === 0 && (
          <tr>
            <td colSpan={4} className="px-4 py-6 text-center text-faint">Nothing yet.</td>
          </tr>
        )}
      </tbody>
    </table>
  );
}
