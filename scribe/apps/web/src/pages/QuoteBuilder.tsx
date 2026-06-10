import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { quoteBuilderRoute } from "../main";
import { apiGet, apiSend, formatUsd } from "../api";
import { Badge, Button, Card, Input, PageTitle, statusTone } from "../ui";

interface Me {
  role: string;
}

interface QuoteDetail {
  id: string;
  status: string;
  markupPct: number;
  handlingCents: number;
  freightCents: number;
  freightPallets: number;
  freightVerified: boolean;
  validUntil: string | null;
  maxLeadTimeDays: number | null;
  pdfS3Key: string | null;
  pricing_config_version: number;
  pricing: {
    priced: {
      takeoff_line_id: string;
      product_line_id: string;
      unit_cents: number;
      total_cents: number;
      lead_time_days: number;
      needs_review: boolean;
    }[];
    unpriced: { takeoff_line_id: string; reason: string }[];
    totals: {
      subtotal_cents: number;
      markup_cents: number;
      handling_cents: number;
      freight_cents: number;
      total_cents: number;
      max_lead_time_days: number;
      mixed_lead_times: boolean;
      any_needs_review: boolean;
    };
    freight_verification_required: boolean;
  };
}

export function QuoteBuilderPage() {
  const { quoteId } = quoteBuilderRoute.useParams();
  const qc = useQueryClient();
  const [error, setError] = useState<string | null>(null);

  const me = useQuery({ queryKey: ["me"], queryFn: () => apiGet<Me>("/auth/me") });
  const q = useQuery({
    queryKey: ["quote", quoteId],
    queryFn: () => apiGet<QuoteDetail>(`/quotes/${quoteId}`),
  });

  const patch = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      apiSend("PATCH", `/quotes/${quoteId}`, body),
    onSuccess: () => {
      setError(null);
      qc.invalidateQueries({ queryKey: ["quote", quoteId] });
      qc.invalidateQueries({ queryKey: ["quotes"] });
    },
    onError: (e) => setError(e.message),
  });

  const verifyFreight = useMutation({
    mutationFn: () => apiSend("POST", `/quotes/${quoteId}/verify-freight`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["quote", quoteId] }),
  });

  const generatePdf = useMutation({
    mutationFn: () =>
      apiSend<{ url: string }>("POST", `/quotes/${quoteId}/pdf`),
    onSuccess: (r) => window.open(r.url, "_blank"),
    onError: (e) => setError(e.message),
  });

  if (q.isLoading) return <div className="text-zinc-500">Loading…</div>;
  if (q.isError) return <div className="text-red-600">{String(q.error)}</div>;
  const quote = q.data!;
  const totals = quote.pricing.totals;
  const isAdmin = me.data?.role === "admin" || me.data?.role === "sales";

  return (
    <div>
      <PageTitle
        actions={
          <div className="flex items-center gap-2">
            <Button
              disabled={generatePdf.isPending}
              onClick={() => generatePdf.mutate()}
            >
              {generatePdf.isPending ? "Rendering…" : "Generate PDF"}
            </Button>
            <a
              href={`mailto:?from=hank@cabinetnow.com&subject=${encodeURIComponent(
                `CabinetNow quote #${quote.id.slice(0, 8).toUpperCase()}`
              )}&body=${encodeURIComponent(
                "Quote attached. Please verify all measurements and quantities. Pricing valid 10 days.\n\n(Attach the generated PDF before sending.)"
              )}`}
            >
              <Button
                variant="primary"
                disabled={quote.status === "sent"}
                onClick={(e) => {
                  // Draft the email, then mark sent only if gates pass.
                  patch.mutate({ status: "sent" });
                  if (
                    (quote.pricing.freight_verification_required &&
                      !quote.freightVerified) ||
                    totals.any_needs_review ||
                    quote.pricing.unpriced.length > 0
                  ) {
                    e.preventDefault();
                  }
                }}
              >
                Send (draft email)
              </Button>
            </a>
          </div>
        }
      >
        Quote #{quote.id.slice(0, 8).toUpperCase()}{" "}
        <Badge tone={statusTone(quote.status)}>{quote.status}</Badge>
      </PageTitle>

      {error && <p className="mb-3 text-sm text-red-600">{error}</p>}

      {totals.any_needs_review && (
        <Card className="mb-4 border-red-300 bg-red-50">
          <p className="text-sm text-red-700">
            This quote prices against seeded NEEDS REVIEW rates. An admin must
            enter real rates in the Pricing Editor before it can be sent.
          </p>
        </Card>
      )}

      {totals.mixed_lead_times && (
        <Card className="mb-4 border-amber-300 bg-amber-50">
          <p className="text-sm text-amber-800">
            Lines have mixed lead times (max {totals.max_lead_time_days} days)
            — consider a split shipment.
          </p>
        </Card>
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <h2 className="mb-2 text-sm font-semibold text-zinc-500">
            Priced lines (pricing config v{quote.pricing_config_version})
          </h2>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-zinc-500">
                <th className="py-1">Product line</th>
                <th>Unit</th>
                <th>Total</th>
                <th>Lead</th>
              </tr>
            </thead>
            <tbody>
              {quote.pricing.priced.map((l) => (
                <tr key={l.takeoff_line_id} className="border-t border-zinc-100">
                  <td className="py-1">
                    {l.product_line_id}
                    {l.needs_review && (
                      <Badge tone="red">NEEDS REVIEW rate</Badge>
                    )}
                  </td>
                  <td>{formatUsd(l.unit_cents)}</td>
                  <td>{formatUsd(l.total_cents)}</td>
                  <td>{l.lead_time_days}d</td>
                </tr>
              ))}
            </tbody>
          </table>
          {quote.pricing.unpriced.length > 0 && (
            <div className="mt-3 rounded-md bg-red-50 p-2 text-sm text-red-700">
              {quote.pricing.unpriced.length} unpriced line(s) — resolve them
              in the takeoff review screen.
            </div>
          )}
        </Card>

        <div className="space-y-4">
          <Card>
            <h2 className="mb-2 text-sm font-semibold text-zinc-500">
              Adjustments
            </h2>
            <label className="mb-2 block text-sm">
              Markup / discount %
              <Input
                type="number"
                step="0.5"
                className="ml-2 w-24"
                defaultValue={quote.markupPct}
                onBlur={(e) =>
                  patch.mutate({ markup_pct: Number(e.target.value) })
                }
              />
            </label>
            <label className="block text-sm">
              Handling $
              <Input
                type="number"
                step="1"
                className="ml-2 w-24"
                defaultValue={quote.handlingCents / 100}
                onBlur={(e) =>
                  patch.mutate({
                    handling_cents: Math.round(Number(e.target.value) * 100),
                  })
                }
              />
            </label>
            {isAdmin && (
              <p className="mt-2 text-xs text-zinc-500">
                Margin: {formatUsd(totals.markup_cents)} on{" "}
                {formatUsd(totals.subtotal_cents)}
              </p>
            )}
          </Card>

          <Card
            className={
              quote.pricing.freight_verification_required &&
              !quote.freightVerified
                ? "border-amber-400"
                : ""
            }
          >
            <h2 className="mb-2 text-sm font-semibold text-zinc-500">
              Freight
            </h2>
            <p className="text-sm">
              {quote.freightPallets} pallet(s) ·{" "}
              {formatUsd(totals.freight_cents)}
            </p>
            <label className="mt-2 block text-sm">
              Override $
              <Input
                type="number"
                className="ml-2 w-28"
                defaultValue={quote.freightCents / 100}
                onBlur={(e) =>
                  patch.mutate({
                    freight_cents: Math.round(Number(e.target.value) * 100),
                  })
                }
              />
            </label>
            <label className="mt-3 flex items-center gap-2 text-sm font-medium">
              <input
                type="checkbox"
                checked={quote.freightVerified}
                disabled={quote.freightVerified}
                onChange={() => verifyFreight.mutate()}
              />
              Freight verified
              {quote.pricing.freight_verification_required && (
                <Badge tone="amber">required before send</Badge>
              )}
            </label>
          </Card>

          <Card>
            <h2 className="mb-2 text-sm font-semibold text-zinc-500">Totals</h2>
            <Row label="Subtotal" value={formatUsd(totals.subtotal_cents)} />
            <Row label="Markup" value={formatUsd(totals.markup_cents)} />
            <Row label="Handling" value={formatUsd(totals.handling_cents)} />
            <Row label="Freight" value={formatUsd(totals.freight_cents)} />
            <div className="mt-1 border-t border-zinc-200 pt-1">
              <Row label="Total" value={formatUsd(totals.total_cents)} bold />
            </div>
            <p className="mt-2 text-xs text-zinc-400">
              Valid until {quote.validUntil ?? "—"} (10-day price lock).
              Customer must verify all measurements and quantities.
            </p>
          </Card>
        </div>
      </div>
    </div>
  );
}

function Row({
  label,
  value,
  bold,
}: {
  label: string;
  value: string;
  bold?: boolean;
}) {
  return (
    <div
      className={`flex justify-between py-0.5 text-sm ${bold ? "font-semibold" : ""}`}
    >
      <span>{label}</span>
      <span>{value}</span>
    </div>
  );
}
