import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { apiGet, formatUsd } from "../api";
import { Badge, Card, PageTitle, StatusPill } from "../ui";
import { quoteRef } from "../labels";

export interface QuoteRow {
  id: string;
  takeoffId: string;
  name: string | null;
  sourceFilename: string | null;
  status: string;
  subtotalCents: number;
  totalCents: number;
  markupPct: number;
  freightVerified: boolean;
  validUntil: string | null;
  maxLeadTimeDays: number | null;
  createdAt: string;
}

export function QuotesPage() {
  const q = useQuery({
    queryKey: ["quotes"],
    queryFn: () => apiGet<QuoteRow[]>("/quotes"),
  });

  return (
    <div>
      <PageTitle>Quotes</PageTitle>
      <Card className="p-0">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-rule text-left font-mono text-[11px] uppercase tracking-wider text-muted">
              <th className="px-3 py-2">Job</th>
              <th className="px-3 py-2">Total</th>
              <th className="px-3 py-2">Markup</th>
              <th className="px-3 py-2">Lead time</th>
              <th className="px-3 py-2">Valid until</th>
              <th className="px-3 py-2">Freight</th>
              <th className="px-3 py-2">Status</th>
            </tr>
          </thead>
          <tbody>
            {(q.data ?? []).map((quote) => (
              <tr key={quote.id} className="border-b border-rule-soft hover:bg-rule-soft">
                <td className="px-3 py-2">
                  <Link
                    to="/quotes/$quoteId"
                    params={{ quoteId: quote.id }}
                    className="font-medium text-ink hover:text-accent"
                  >
                    {quote.name ?? quote.sourceFilename ?? "Untitled quote"}
                  </Link>
                  {quote.name && quote.sourceFilename && (
                    <span className="ml-2 text-xs text-muted">{quote.sourceFilename}</span>
                  )}
                  <span className="ml-2 font-mono text-[10px] text-faint">
                    {quoteRef(quote.id)}
                  </span>
                </td>
                <td className="px-3 py-2">{formatUsd(quote.totalCents)}</td>
                <td className="px-3 py-2">{quote.markupPct}%</td>
                <td className="px-3 py-2">
                  {quote.maxLeadTimeDays != null
                    ? `${quote.maxLeadTimeDays}d`
                    : "—"}
                </td>
                <td className="px-3 py-2">{quote.validUntil ?? "—"}</td>
                <td className="px-3 py-2">
                  <Badge tone={quote.freightVerified ? "green" : "amber"}>
                    {quote.freightVerified ? "verified" : "unverified"}
                  </Badge>
                </td>
                <td className="px-3 py-2">
                  <StatusPill status={quote.status} />
                </td>
              </tr>
            ))}
            {(q.data ?? []).length === 0 && (
              <tr>
                <td colSpan={7} className="px-3 py-6 text-center text-faint">
                  No quotes yet — approve a takeoff, then build a quote from it.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </Card>
    </div>
  );
}
