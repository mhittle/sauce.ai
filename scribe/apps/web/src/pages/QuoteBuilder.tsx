import { useMemo } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { quoteBuilderRoute } from "../main";
import { API_URL, apiGet, apiSend, formatUsd } from "../api";
import {
  Button,
  Card,
  errorMessage,
  NumberInput,
  PageTitle,
  SectionLabel,
  StatusPill,
  useToast,
} from "../ui";
import { categoryLabel, quoteRef } from "../labels";

// The quote step (product-plan.md §3.3): pick a tier, set markup and
// freight, confirm shipping, download or send. Operator-only concepts
// (pricing-config versions, product-line ids, NEEDS REVIEW rates) render for
// admins only. Once sent, the screen locks and becomes the Done state.

interface Me {
  role: string;
}

type TierName = "low" | "medium" | "high";

interface QuoteDetail {
  id: string;
  takeoffId: string;
  sourceFilename: string | null;
  status: string;
  pricingTier: TierName;
  markupPct: number;
  handlingCents: number;
  freightCents: number;
  freightPallets: number;
  freightVerified: boolean;
  validUntil: string | null;
  maxLeadTimeDays: number | null;
  pdfS3Key: string | null;
  sentAt: string | null;
  createdAt: string;
  pricing_config_version: number;
  pricing: {
    priced: {
      takeoff_line_id: string;
      product_line_id: string;
      tag: string | null;
      category: string;
      qty: number;
      width_in: number | null;
      height_in: number | null;
      depth_in: number | null;
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
  quote_tiers: Record<
    TierName,
    {
      label: string;
      box_count: number;
      box_cents: number;
      door_cents: number;
      front_cents: number;
      drawer_box_count: number;
      hardware_cents: number;
      total_cents: number;
    }
  >;
}

const TIER_HINT: Record<TierName, string> = {
  low: "Shaker doors at the real CabinetNow rate",
  medium: "Estimated mid-range door styles",
  high: "Estimated premium door styles",
};

const LOCKED = new Set(["sent", "won", "lost", "expired"]);

export function QuoteBuilderPage() {
  const { quoteId } = quoteBuilderRoute.useParams();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const toast = useToast();

  const me = useQuery({ queryKey: ["me"], queryFn: () => apiGet<Me>("/auth/me") });
  const q = useQuery({
    queryKey: ["quote", quoteId],
    queryFn: () => apiGet<QuoteDetail>(`/quotes/${quoteId}`),
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["quote", quoteId] });
    qc.invalidateQueries({ queryKey: ["quotes"] });
    qc.invalidateQueries({ queryKey: ["jobs"] });
  };

  const patch = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      apiSend("PATCH", `/quotes/${quoteId}`, body),
    onSuccess: invalidate,
    onError: (e) => toast.error("Quote not saved", errorMessage(e)),
  });

  const verifyFreight = useMutation({
    mutationFn: () => apiSend("POST", `/quotes/${quoteId}/verify-freight`),
    onSuccess: invalidate,
    onError: (e) => toast.error("Freight not confirmed", errorMessage(e)),
  });

  const generatePdf = useMutation({
    mutationFn: () =>
      apiSend<{ url: string }>("POST", `/quotes/${quoteId}/pdf?tier=${q.data?.pricingTier ?? "medium"}`),
    onSuccess: (r) => window.open(r.url, "_blank"),
    onError: (e) => toast.error("PDF not generated", errorMessage(e)),
  });

  // Send: the server enforces the gates (freight confirmed, no placeholder
  // rates, nothing unpriced). On success, open a drafted email — attaching
  // the PDF stays manual until the email provider lands (Stage 2).
  const send = useMutation({
    mutationFn: () => apiSend("PATCH", `/quotes/${quoteId}`, { status: "sent" }),
    onSuccess: () => {
      invalidate();
      toast.success("Quote marked as sent", "Attach the PDF to the email that just opened.");
      const quote = q.data!;
      window.location.href = `mailto:?subject=${encodeURIComponent(
        `CabinetNow quote — ${quote.sourceFilename ?? quoteRef(quote.id)}`
      )}&body=${encodeURIComponent(
        "Quote attached. Please verify all measurements and quantities. Pricing valid 10 days."
      )}`;
    },
    onError: (e) => toast.error("Couldn't send", errorMessage(e)),
  });

  const quote = q.data;
  const isAdmin = me.data?.role === "admin";
  const showMargin = me.data?.role === "admin" || me.data?.role === "sales";
  const locked = quote ? LOCKED.has(quote.status) : false;
  const tier = quote?.pricingTier ?? "medium";

  const blockers = useMemo(() => {
    if (!quote) return [];
    const out: string[] = [];
    if (quote.pricing.freight_verification_required && !quote.freightVerified) {
      out.push("Confirm the shipping cost");
    }
    if (quote.pricing.unpriced.length > 0) {
      out.push(
        `${quote.pricing.unpriced.length} line${quote.pricing.unpriced.length === 1 ? "" : "s"} still unpriced — fix them in the takeoff`
      );
    }
    if (quote.pricing.totals.any_needs_review) {
      out.push(
        isAdmin
          ? "Placeholder rates in use — enter real rates in Admin › Pricing"
          : "Pricing for this quote isn't finalized yet — ask an admin"
      );
    }
    return out;
  }, [quote, isAdmin]);

  if (q.isLoading) return <div className="text-muted">Loading…</div>;
  if (q.isError) return <div className="text-bad">{String(q.error)}</div>;
  if (!quote) return null;
  const totals = quote.pricing.totals;

  const subtotal = quote.quote_tiers[tier].total_cents;
  const markup = Math.round((subtotal * quote.markupPct) / 100);
  const grand = subtotal + markup + quote.handlingCents + totals.freight_cents;

  return (
    <div className="flex flex-col gap-4">
      <PageTitle
        eyebrow={
          <span>
            Quote {quoteRef(quote.id)}
            {isAdmin && (
              <span className="ml-2 normal-case tracking-normal text-faint">
                pricing config v{quote.pricing_config_version}
              </span>
            )}
          </span>
        }
        actions={
          <div className="flex items-center gap-2">
            <StatusPill status={quote.status} />
            <Link to="/takeoffs/$takeoffId" params={{ takeoffId: quote.takeoffId }}>
              <Button variant="quiet">Open the takeoff</Button>
            </Link>
            <details className="relative">
              <summary className="list-none">
                <Button variant="quiet" aria-haspopup="menu">
                  More ▾
                </Button>
              </summary>
              <div
                role="menu"
                className="absolute right-0 z-30 mt-1 w-60 rounded-md border border-rule bg-paper p-1 shadow-md"
              >
                <a
                  role="menuitem"
                  className="block rounded px-2 py-1.5 text-sm text-ink hover:bg-rule-soft"
                  href={`${API_URL}/takeoffs/${quote.takeoffId}/export.csv?template=${encodeURIComponent("Mozaik (default)")}`}
                >
                  Export for Mozaik (CSV)
                </a>
                <a
                  role="menuitem"
                  className="block rounded px-2 py-1.5 text-sm text-ink hover:bg-rule-soft"
                  href={`${API_URL}/takeoffs/${quote.takeoffId}/export.csv?template=${encodeURIComponent("KCD (default)")}`}
                >
                  Export for KCD (CSV)
                </a>
                {quote.status === "sent" && (
                  <>
                    <div className="my-1 border-t border-rule-soft" />
                    <button
                      role="menuitem"
                      className="block w-full rounded px-2 py-1.5 text-left text-sm text-ink hover:bg-rule-soft"
                      onClick={() => patch.mutate({ status: "won" })}
                    >
                      Mark as won
                    </button>
                    <button
                      role="menuitem"
                      className="block w-full rounded px-2 py-1.5 text-left text-sm text-ink hover:bg-rule-soft"
                      onClick={() => patch.mutate({ status: "lost" })}
                    >
                      Mark as lost
                    </button>
                  </>
                )}
              </div>
            </details>
          </div>
        }
      >
        {quote.sourceFilename ?? "Untitled job"}
      </PageTitle>

      {locked && (
        <div className="flex flex-wrap items-center gap-3 rounded-lg border border-good bg-good-soft px-4 py-3 text-sm text-good">
          <span className="font-medium">
            {quote.status === "sent"
              ? `Sent ${quote.sentAt ? new Date(quote.sentAt).toLocaleString() : ""}`
              : quote.status === "won"
                ? "Won"
                : quote.status === "lost"
                  ? "Lost"
                  : "Expired"}
            . This quote is locked.
          </span>
          <span className="text-good/80">
            Valid until {quote.validUntil ?? "—"} · lead time up to{" "}
            {quote.maxLeadTimeDays ?? totals.max_lead_time_days} days.
          </span>
          <Button className="ml-auto" onClick={() => navigate({ to: "/" })}>
            Start another job
          </Button>
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <div className="flex flex-col gap-4">
          {/* Tier cards */}
          <div>
            <SectionLabel>Pick a price level</SectionLabel>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3" role="radiogroup" aria-label="Price level">
              {(["low", "medium", "high"] as const).map((t) => {
                const qt = quote.quote_tiers[t];
                const on = tier === t;
                return (
                  <button
                    key={t}
                    type="button"
                    role="radio"
                    aria-checked={on}
                    disabled={locked || patch.isPending}
                    onClick={() => patch.mutate({ pricing_tier: t })}
                    className={`rounded-lg border p-3 text-left transition-colors disabled:cursor-default ${
                      on
                        ? "border-accent bg-accent-soft shadow-[inset_0_3px_0_var(--accent)]"
                        : "border-rule bg-paper hover:border-muted"
                    }`}
                  >
                    <div className="flex items-baseline justify-between gap-2">
                      <span className="wide font-display text-sm font-semibold text-ink">
                        {qt.label}
                      </span>
                      {on && (
                        <span className="font-mono text-[10px] uppercase tracking-wider text-accent">
                          selected
                        </span>
                      )}
                    </div>
                    <div className="mt-1 font-mono text-xl tabular-nums text-ink">
                      {formatUsd(qt.total_cents)}
                    </div>
                    <div className="mt-1 text-xs text-muted">{TIER_HINT[t]}</div>
                    <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-2 text-[11px] text-muted">
                      <dt>Boxes ({qt.box_count})</dt>
                      <dd className="text-right font-mono tabular-nums">{formatUsd(qt.box_cents)}</dd>
                      <dt>Doors &amp; fronts</dt>
                      <dd className="text-right font-mono tabular-nums">{formatUsd(qt.door_cents + qt.front_cents)}</dd>
                      <dt>Drawer boxes ({qt.drawer_box_count})</dt>
                      <dd className="text-right font-mono tabular-nums">{formatUsd(qt.hardware_cents)}</dd>
                    </dl>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Line items */}
          <Card className="p-0">
            <div className="flex items-center justify-between px-4 pt-3">
              <SectionLabel className="mb-0">Line items</SectionLabel>
              {totals.mixed_lead_times && (
                <span className="text-xs text-warn">
                  Mixed lead times (up to {totals.max_lead_time_days} days) — consider a split shipment
                </span>
              )}
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-rule text-left font-mono text-[11px] uppercase tracking-wider text-muted">
                    <th className="px-4 py-2">Item</th>
                    <th className="px-2 py-2 text-right">Qty</th>
                    <th className="px-2 py-2 text-right">Unit</th>
                    <th className="px-2 py-2 text-right">Total</th>
                    <th className="px-4 py-2 text-right">Lead</th>
                  </tr>
                </thead>
                <tbody>
                  {quote.pricing.priced.map((l) => {
                    const dims = [l.width_in, l.height_in, l.depth_in]
                      .map((d) => (d == null ? "—" : `${d}"`))
                      .join(" × ");
                    return (
                      <tr key={l.takeoff_line_id} className="border-b border-rule-soft">
                        <td className="px-4 py-1.5">
                          <span className="font-medium text-ink">
                            {l.tag ?? categoryLabel(l.category)}
                          </span>
                          <span className="ml-2 font-mono text-xs tabular-nums text-muted">{dims}</span>
                          {isAdmin && (
                            <span className="ml-2 font-mono text-[10px] text-faint">{l.product_line_id}</span>
                          )}
                          {isAdmin && l.needs_review && (
                            <span className="ml-2 rounded bg-bad-soft px-1.5 font-mono text-[10px] uppercase text-bad">
                              placeholder rate
                            </span>
                          )}
                        </td>
                        <td className="px-2 py-1.5 text-right font-mono tabular-nums">{l.qty}</td>
                        <td className="px-2 py-1.5 text-right font-mono tabular-nums text-muted">{formatUsd(l.unit_cents)}</td>
                        <td className="px-2 py-1.5 text-right font-mono tabular-nums">{formatUsd(l.total_cents)}</td>
                        <td className="px-4 py-1.5 text-right font-mono tabular-nums text-muted">{l.lead_time_days}d</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {quote.pricing.unpriced.length > 0 && (
              <div className="border-t border-rule px-4 py-2 text-sm text-bad">
                {quote.pricing.unpriced.length} line{quote.pricing.unpriced.length === 1 ? "" : "s"} could not be priced and{" "}
                {quote.pricing.unpriced.length === 1 ? "is" : "are"} left off this quote.{" "}
                <Link
                  to="/takeoffs/$takeoffId"
                  params={{ takeoffId: quote.takeoffId }}
                  className="underline"
                >
                  Fix them in the takeoff
                </Link>
                .
              </div>
            )}
            <p className="px-4 py-2 text-xs text-faint">
              The line items above are the itemized audit; the price levels use the
              CabinetNow box + door/front + drawer-box model. Glides, shelf pins and
              toe kick are not yet included.
            </p>
          </Card>
        </div>

        <div className="flex flex-col gap-4">
          <Card>
            <SectionLabel>Adjustments</SectionLabel>
            <div className="grid grid-cols-2 gap-3">
              <label className="flex flex-col gap-1 text-xs text-muted">
                Markup / discount %
                <NumberInput
                  step="0.5"
                  disabled={locked}
                  defaultValue={quote.markupPct}
                  onBlur={(e) => {
                    const v = Number(e.target.value);
                    if (v !== quote.markupPct) patch.mutate({ markup_pct: v });
                  }}
                />
              </label>
              <label className="flex flex-col gap-1 text-xs text-muted">
                Handling $
                <NumberInput
                  step="1"
                  disabled={locked}
                  defaultValue={quote.handlingCents / 100}
                  onBlur={(e) => {
                    const c = Math.round(Number(e.target.value) * 100);
                    if (c !== quote.handlingCents) patch.mutate({ handling_cents: c });
                  }}
                />
              </label>
            </div>
            {showMargin && (
              <p className="mt-2 text-xs text-muted">
                Margin {formatUsd(markup)} on {formatUsd(subtotal)}
              </p>
            )}
          </Card>

          <Card className={quote.pricing.freight_verification_required && !quote.freightVerified ? "border-warn" : ""}>
            <SectionLabel>Shipping</SectionLabel>
            <p className="text-sm text-ink">
              <span className="font-mono tabular-nums">{quote.freightPallets}</span> pallet
              {quote.freightPallets === 1 ? "" : "s"} ·{" "}
              <span className="font-mono tabular-nums">{formatUsd(totals.freight_cents)}</span>
            </p>
            <label className="mt-2 flex flex-col gap-1 text-xs text-muted">
              Override $
              <NumberInput
                disabled={locked}
                defaultValue={quote.freightCents / 100}
                onBlur={(e) => {
                  const c = Math.round(Number(e.target.value) * 100);
                  if (c !== quote.freightCents) patch.mutate({ freight_cents: c });
                }}
              />
            </label>
            <label className="mt-3 flex items-start gap-2 text-sm">
              <input
                type="checkbox"
                className="mt-0.5"
                checked={quote.freightVerified}
                disabled={quote.freightVerified || locked || verifyFreight.isPending}
                onChange={() => verifyFreight.mutate()}
              />
              <span>
                <span className="font-medium text-ink">I've confirmed the shipping cost</span>
                {quote.pricing.freight_verification_required && (
                  <span className="block text-xs text-warn">
                    Required before sending — shipping is the most common quoting error.
                  </span>
                )}
              </span>
            </label>
          </Card>

          <Card>
            <SectionLabel>Total</SectionLabel>
            <dl className="text-sm">
              <Row label={`${quote.quote_tiers[tier].label} subtotal`} value={formatUsd(subtotal)} />
              <Row label={`Markup ${quote.markupPct}%`} value={formatUsd(markup)} />
              <Row label="Handling" value={formatUsd(quote.handlingCents)} />
              <Row label="Shipping" value={formatUsd(totals.freight_cents)} />
              <div className="mt-1 border-t border-rule pt-1">
                <Row label="Total" value={formatUsd(grand)} bold />
              </div>
            </dl>
            <p className="mt-2 text-xs text-muted">
              Valid until {quote.validUntil ?? "—"} (10-day price lock) · lead time up to{" "}
              {totals.max_lead_time_days} days.
            </p>
          </Card>
        </div>
      </div>

      {/* Sticky bar: the number, and the way out. */}
      <div className="sticky bottom-3 flex flex-wrap items-center gap-x-5 gap-y-2 rounded-lg border border-rule bg-paper px-4 py-2 shadow-md">
        <div>
          <div className="font-mono text-[10px] uppercase tracking-wider text-muted">
            {quote.quote_tiers[tier].label} · total
          </div>
          <div className="font-mono text-xl font-medium tabular-nums text-ink">{formatUsd(grand)}</div>
        </div>
        {!locked && blockers.length > 0 && (
          <ul className="text-xs text-warn">
            {blockers.map((b) => (
              <li key={b}>· {b}</li>
            ))}
          </ul>
        )}
        <div className="ml-auto flex items-center gap-2">
          <Button loading={generatePdf.isPending} onClick={() => generatePdf.mutate()}>
            Download PDF
          </Button>
          {!locked && (
            <Button
              variant="primary"
              loading={send.isPending}
              disabled={blockers.length > 0}
              title={blockers.length > 0 ? blockers.join(" · ") : undefined}
              onClick={() => send.mutate()}
            >
              Send quote
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

function Row({ label, value, bold }: { label: string; value: string; bold?: boolean }) {
  return (
    <div className={`flex justify-between py-0.5 ${bold ? "font-semibold text-ink" : "text-muted"}`}>
      <dt>{label}</dt>
      <dd className="font-mono tabular-nums">{value}</dd>
    </div>
  );
}
