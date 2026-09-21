import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { adminRoute } from "../main";
import { apiGet, apiSend, apiUpload, formatUsd } from "../api";
import {
  Badge,
  type BadgeTone,
  Button,
  Card,
  errorMessage,
  Field,
  Input,
  NumberInput,
  PageTitle,
  SectionLabel,
  Select,
  SkeletonRows,
  StatusPill,
  Textarea,
  useToast,
} from "../ui";

// The admin control panel (product-plan.md §3.3): pricing, branding and
// terms, freight and extraction settings, export mappings, users. Crawler
// sources stay routable (?tab=sources) but off the sidebar with the
// prospector. Stages 2–3 add orgs, invites, usage and credits here.

type Tab = "pricing" | "branding" | "freight" | "templates" | "users" | "sources";

const TABS: { key: Tab; label: string; hint: string; hidden?: boolean }[] = [
  { key: "pricing", label: "Pricing", hint: "Rates, adders, lead times" },
  { key: "branding", label: "Branding & terms", hint: "Logo, quote terms, footer" },
  { key: "freight", label: "Freight & reading", hint: "Pallet rate, handling, cross-check" },
  { key: "templates", label: "Export mappings", hint: "Mozaik / KCD columns" },
  { key: "users", label: "Users", hint: "Invites and who can sign in" },
  { key: "sources", label: "Crawler sources", hint: "Prospector (hidden)", hidden: true },
];

export function AdminPage() {
  const { tab: tabParam } = adminRoute.useSearch();
  const tab: Tab = TABS.some((t) => t.key === tabParam) ? (tabParam as Tab) : "pricing";
  const current = TABS.find((t) => t.key === tab)!;
  return (
    <div>
      <PageTitle eyebrow="Admin">{current.label}</PageTitle>
      <div className="grid grid-cols-1 gap-6 md:grid-cols-[13rem_minmax(0,1fr)]">
        <nav aria-label="Admin sections" className="md:sticky md:top-16 md:self-start">
          <ul className="flex gap-1 overflow-x-auto md:flex-col">
            {TABS.filter((t) => !t.hidden || t.key === tab).map((t) => (
              <li key={t.key}>
                <Link
                  to="/admin"
                  search={{ tab: t.key }}
                  className={`block rounded-md px-3 py-2 ${
                    t.key === tab ? "bg-ink text-paper" : "text-ink hover:bg-rule-soft"
                  }`}
                >
                  <div className="text-sm font-medium">{t.label}</div>
                  <div className={`text-[11px] ${t.key === tab ? "text-paper/70" : "text-muted"}`}>
                    {t.hint}
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        </nav>
        <div className="min-w-0">
          {tab === "pricing" && <PricingEditor />}
          {tab === "branding" && <Branding />}
          {tab === "freight" && <FreightAndReading />}
          {tab === "templates" && <ExportTemplates />}
          {tab === "users" && (<><Invites /><SampleJob /><Users /></>)}
          {tab === "sources" && <Sources />}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Pricing Editor (PRD §6.4)
// ---------------------------------------------------------------------------

interface Adder {
  kind: "flat" | "pct";
  cents?: number;
  pct?: number;
}

interface ProductLine {
  id: string;
  name: string;
  categories: string[];
  size_measure: "lf" | "sqft" | "unit";
  material_rates: Record<string, { rate_cents: number; needs_review: boolean }>;
  finish_adders: Record<string, Adder>;
  assembly_adder: Adder | null;
  dim_bounds: Record<string, unknown>;
  lead_time_days: number;
  active: boolean;
}

interface PricingResponse {
  product_lines: {
    id: string;
    name: string;
    categories: string[];
    sizeMeasure: "lf" | "sqft" | "unit";
    materialRates: ProductLine["material_rates"];
    finishAdders: ProductLine["finish_adders"];
    assemblyAdder: Adder | null;
    dimBounds: Record<string, unknown>;
    leadTimeDays: number;
    active: boolean;
  }[];
  versions: { version: number; createdAt: string }[];
}

const MEASURE_LABEL: Record<ProductLine["size_measure"], string> = {
  lf: "per linear foot",
  sqft: "per square foot",
  unit: "per unit",
};

function PricingEditor() {
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({
    queryKey: ["admin-pricing"],
    queryFn: () => apiGet<PricingResponse>("/admin/pricing"),
  });
  const [draft, setDraft] = useState<ProductLine[] | null>(null);

  useEffect(() => {
    if (q.data && !draft) {
      setDraft(
        q.data.product_lines.map((p) => ({
          id: p.id,
          name: p.name,
          categories: p.categories,
          size_measure: p.sizeMeasure,
          material_rates: p.materialRates,
          finish_adders: p.finishAdders,
          assembly_adder: p.assemblyAdder,
          dim_bounds: p.dimBounds,
          lead_time_days: p.leadTimeDays,
          active: p.active,
        }))
      );
    }
  }, [q.data, draft]);

  const save = useMutation({
    mutationFn: () => apiSend("PUT", "/admin/pricing", { product_lines: draft }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-pricing"] });
      setDraft(null);
      toast.success("Pricing saved as a new version");
    },
    onError: (e) => toast.error("Pricing not saved", errorMessage(e)),
  });

  if (q.isLoading || !draft) return <SkeletonRows rows={6} />;

  const update = (i: number, patch: Partial<ProductLine>) => {
    setDraft(draft.map((p, j) => (j === i ? { ...p, ...patch } : p)));
  };
  const placeholders = draft.reduce(
    (n, pl) => n + Object.values(pl.material_rates).filter((r) => r.needs_review).length,
    0
  );

  return (
    <div className="space-y-4">
      <div className="sticky top-14 z-20 flex flex-wrap items-center gap-3 rounded-lg border border-rule bg-paper px-4 py-2">
        <div className="text-sm text-muted">
          Latest config <span className="font-mono text-ink">v{q.data!.versions[0]?.version ?? "—"}</span>.
          Saving creates a new version; existing quotes keep theirs.
        </div>
        {placeholders > 0 && (
          <span className="rounded bg-bad-soft px-2 py-0.5 text-xs text-bad">
            {placeholders} placeholder rate{placeholders === 1 ? "" : "s"} block sending
          </span>
        )}
        <Button className="ml-auto" variant="primary" loading={save.isPending} onClick={() => save.mutate()}>
          Save as new version
        </Button>
      </div>

      {draft.map((pl, i) => (
        <Card key={pl.id}>
          <div className="mb-3 flex flex-wrap items-center gap-3">
            <h2 className="wide font-display text-base font-semibold text-ink">{pl.name}</h2>
            <Badge>{MEASURE_LABEL[pl.size_measure]}</Badge>
            <span className="text-xs text-muted">{pl.categories.map((c) => c.replace(/_/g, " ")).join(", ")}</span>
            <label className="ml-auto flex items-center gap-2 text-xs text-muted">
              Lead time (days)
              <NumberInput
                className="w-16"
                value={pl.lead_time_days}
                onChange={(e) => update(i, { lead_time_days: Number(e.target.value) })}
              />
            </label>
            <label className="flex items-center gap-1.5 text-sm">
              <input
                type="checkbox"
                checked={pl.active}
                onChange={(e) => update(i, { active: e.target.checked })}
              />
              Active
            </label>
          </div>

          <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
            <div>
              <SectionLabel>Material rates ($ {MEASURE_LABEL[pl.size_measure]})</SectionLabel>
              <div className="space-y-1">
                {Object.entries(pl.material_rates).map(([mat, rate]) => (
                  <div key={mat} className="flex items-center gap-2 text-sm">
                    <span className="w-32 truncate text-ink" title={mat}>{mat}</span>
                    <NumberInput
                      step="0.01"
                      className={`w-28 ${rate.needs_review ? "border-bad" : ""}`}
                      value={rate.rate_cents / 100}
                      onChange={(e) =>
                        update(i, {
                          material_rates: {
                            ...pl.material_rates,
                            [mat]: {
                              ...rate,
                              rate_cents: Math.round(Number(e.target.value) * 100),
                              needs_review: false,
                            },
                          },
                        })
                      }
                    />
                    {rate.needs_review && (
                      <span className="rounded bg-bad-soft px-1.5 font-mono text-[10px] uppercase text-bad">
                        placeholder
                      </span>
                    )}
                  </div>
                ))}
              </div>
            </div>
            <div>
              <SectionLabel>Finish adders</SectionLabel>
              <div className="space-y-1">
                {Object.entries(pl.finish_adders).map(([finish, adder]) => (
                  <div key={finish} className="flex items-center gap-2 text-sm">
                    <span className="w-32 truncate text-ink" title={finish}>{finish}</span>
                    <NumberInput
                      step="0.01"
                      className="w-28"
                      value={adder.kind === "flat" ? (adder.cents ?? 0) / 100 : adder.pct}
                      onChange={(e) => {
                        const v = Number(e.target.value);
                        update(i, {
                          finish_adders: {
                            ...pl.finish_adders,
                            [finish]:
                              adder.kind === "flat"
                                ? { kind: "flat", cents: Math.round(v * 100) }
                                : { kind: "pct", pct: v },
                          },
                        });
                      }}
                    />
                    <span className="font-mono text-xs text-faint">{adder.kind === "flat" ? "$" : "%"}</span>
                  </div>
                ))}
                {pl.assembly_adder && (
                  <div className="mt-2 flex items-center gap-2 border-t border-rule-soft pt-2 text-sm">
                    <span className="w-32 font-medium text-ink">Assembled</span>
                    <NumberInput
                      step="0.01"
                      className="w-28"
                      value={
                        pl.assembly_adder.kind === "flat"
                          ? (pl.assembly_adder.cents ?? 0) / 100
                          : pl.assembly_adder.pct
                      }
                      onChange={(e) => {
                        const v = Number(e.target.value);
                        update(i, {
                          assembly_adder:
                            pl.assembly_adder!.kind === "flat"
                              ? { kind: "flat", cents: Math.round(v * 100) }
                              : { kind: "pct", pct: v },
                        });
                      }}
                    />
                    <span className="font-mono text-xs text-faint">{pl.assembly_adder.kind === "flat" ? "$" : "%"}</span>
                  </div>
                )}
              </div>
            </div>
          </div>
        </Card>
      ))}

      <TestCalculator productLines={draft} />
    </div>
  );
}

function TestCalculator({ productLines }: { productLines: ProductLine[] }) {
  const toast = useToast();
  const [plId, setPlId] = useState(productLines[0]?.id ?? "");
  const [form, setForm] = useState({
    qty: "1",
    width_in: "24",
    height_in: "34.5",
    depth_in: "24",
    material: "",
    finish: "",
    assembled: false,
  });
  const [result, setResult] = useState<Record<string, unknown> | null>(null);

  const pl = productLines.find((p) => p.id === plId);
  const calc = useMutation({
    mutationFn: () =>
      apiSend<Record<string, unknown>>("POST", "/admin/pricing/test-calc", {
        product_line: pl,
        params: {
          product_line_id: plId,
          qty: Number(form.qty),
          width_in: form.width_in ? Number(form.width_in) : null,
          height_in: form.height_in ? Number(form.height_in) : null,
          depth_in: form.depth_in ? Number(form.depth_in) : null,
          material: form.material || Object.keys(pl?.material_rates ?? {})[0],
          finish: form.finish || null,
          assembled: form.assembled,
        },
      }),
    onSuccess: setResult,
    onError: (e) => toast.error("Calculation failed", errorMessage(e)),
  });

  return (
    <Card className="border-blue">
      <SectionLabel className="text-blue">Test calculator — prices against the draft above, before saving</SectionLabel>
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Product line">
          <Select value={plId} onChange={(e) => setPlId(e.target.value)}>
            {productLines.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </Select>
        </Field>
        {(
          [
            ["qty", "Qty"],
            ["width_in", "W (in)"],
            ["height_in", "H (in)"],
            ["depth_in", "D (in)"],
          ] as const
        ).map(([f, label]) => (
          <Field key={f} label={label}>
            <NumberInput className="w-20" value={form[f]} onChange={(e) => setForm({ ...form, [f]: e.target.value })} />
          </Field>
        ))}
        <Field label="Material">
          <Select value={form.material} onChange={(e) => setForm({ ...form, material: e.target.value })}>
            <option value="">(first)</option>
            {Object.keys(pl?.material_rates ?? {}).map((m) => (
              <option key={m}>{m}</option>
            ))}
          </Select>
        </Field>
        <Field label="Finish">
          <Select value={form.finish} onChange={(e) => setForm({ ...form, finish: e.target.value })}>
            <option value="">(none)</option>
            {Object.keys(pl?.finish_adders ?? {}).map((f) => (
              <option key={f}>{f}</option>
            ))}
          </Select>
        </Field>
        <label className="flex items-center gap-1.5 pb-1.5 text-sm">
          <input
            type="checkbox"
            checked={form.assembled}
            onChange={(e) => setForm({ ...form, assembled: e.target.checked })}
          />
          Assembled
        </label>
        <Button variant="primary" loading={calc.isPending} onClick={() => calc.mutate()}>
          Calculate
        </Button>
      </div>
      {result && (
        <div className="mt-3 rounded-md bg-bg px-3 py-2 font-mono text-sm tabular-nums">
          {result.ok ? (
            <span>
              Unit {formatUsd(result.unit_cents as number)} · Total{" "}
              <strong>{formatUsd(result.total_cents as number)}</strong> · lead {String(result.lead_time_days)}d
              {Boolean(result.needs_review) && (
                <span className="ml-2 rounded bg-bad-soft px-1.5 text-[10px] uppercase text-bad">placeholder rate</span>
              )}
            </span>
          ) : (
            <span className="text-bad">{String(result.detail)}</span>
          )}
        </div>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Branding & terms · Freight & reading (org_settings, PRD §7.1 / §6.5)
// ---------------------------------------------------------------------------

interface OrgSettingsData {
  quoteTermsMd: string;
  quoteFooterMd: string;
  defaultHandlingCents: number;
  palletRateCents: number;
  freightProvider: string;
  crossValidationEnabled: boolean;
  logo_url: string | null;
}

function useOrgSettings() {
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({
    queryKey: ["org-settings"],
    queryFn: () => apiGet<OrgSettingsData>("/admin/org-settings"),
  });
  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) => apiSend("PUT", "/admin/org-settings", body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["org-settings"] });
      toast.success("Saved");
    },
    onError: (e) => toast.error("Not saved", errorMessage(e)),
  });
  return { q, save, qc, toast };
}

function Branding() {
  const { q, save, qc, toast } = useOrgSettings();
  const [terms, setTerms] = useState<string | null>(null);
  const [footer, setFooter] = useState<string | null>(null);
  const upload = useMutation({
    mutationFn: (f: File) => apiUpload("/admin/org-settings/logo", f),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["org-settings"] });
      toast.success("Logo updated");
    },
    onError: (e) => toast.error("Logo not uploaded", errorMessage(e)),
  });

  if (q.isLoading) return <SkeletonRows rows={4} />;
  const s = q.data!;
  const dirty = (terms != null && terms !== s.quoteTermsMd) || (footer != null && footer !== s.quoteFooterMd);

  return (
    <div className="space-y-4">
      <Card>
        <SectionLabel>Logo on the quote PDF</SectionLabel>
        <div className="flex items-center gap-4">
          {s.logo_url ? (
            <img src={s.logo_url} alt="Current logo" className="h-14 rounded border border-rule bg-white p-1" />
          ) : (
            <div className="flex h-14 w-28 items-center justify-center rounded border border-dashed border-rule text-xs text-faint">
              no logo
            </div>
          )}
          <label className="text-sm">
            <span className="sr-only">Upload logo</span>
            <input
              type="file"
              accept=".png,.svg,.jpg,.jpeg"
              className="text-xs text-muted file:mr-3 file:rounded-md file:border file:border-rule file:bg-paper file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-ink hover:file:bg-rule-soft"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) upload.mutate(f);
                e.target.value = "";
              }}
            />
          </label>
        </div>
      </Card>

      <Card>
        <SectionLabel>Quote terms (markdown)</SectionLabel>
        <Textarea
          className="h-36 w-full"
          value={terms ?? s.quoteTermsMd}
          onChange={(e) => setTerms(e.target.value)}
        />
        <SectionLabel className="mt-4">Quote footer (markdown)</SectionLabel>
        <Textarea
          className="h-20 w-full"
          value={footer ?? s.quoteFooterMd}
          onChange={(e) => setFooter(e.target.value)}
        />
        <div className="mt-3 flex justify-end">
          <Button
            variant="primary"
            disabled={!dirty}
            loading={save.isPending}
            onClick={() =>
              save.mutate({
                quote_terms_md: terms ?? s.quoteTermsMd,
                quote_footer_md: footer ?? s.quoteFooterMd,
              })
            }
          >
            Save terms
          </Button>
        </div>
      </Card>
    </div>
  );
}

function FreightAndReading() {
  const { q, save } = useOrgSettings();
  if (q.isLoading) return <SkeletonRows rows={4} />;
  const s = q.data!;
  return (
    <div className="space-y-4">
      <Card>
        <SectionLabel>Freight</SectionLabel>
        <div className="grid max-w-md grid-cols-2 gap-3">
          <Field label="Pallet rate $" hint={`Flat per pallet · ${s.freightProvider} provider`}>
            <NumberInput
              defaultValue={s.palletRateCents / 100}
              onBlur={(e) => {
                const c = Math.round(Number(e.target.value) * 100);
                if (c !== s.palletRateCents) save.mutate({ pallet_rate_cents: c });
              }}
            />
          </Field>
          <Field label="Default handling $" hint="Applied to every new quote">
            <NumberInput
              defaultValue={s.defaultHandlingCents / 100}
              onBlur={(e) => {
                const c = Math.round(Number(e.target.value) * 100);
                if (c !== s.defaultHandlingCents) save.mutate({ default_handling_cents: c });
              }}
            />
          </Field>
        </div>
      </Card>
      <Card>
        <SectionLabel>Reading</SectionLabel>
        <label className="flex items-start gap-2 text-sm">
          <input
            type="checkbox"
            className="mt-0.5"
            checked={s.crossValidationEnabled}
            disabled={save.isPending}
            onChange={(e) => save.mutate({ cross_validation_enabled: e.target.checked })}
          />
          <span>
            <span className="font-medium text-ink">Second-opinion cross-check</span>
            <span className="block text-xs text-muted">
              Every page is also read by a second vision model; lines the two models
              disagree on drop below the review threshold so they surface as flagged.
              Needs OPENAI_API_KEY on the workers service.
            </span>
          </span>
        </label>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
// CSV export mapping editor (PRD §7.3)
// ---------------------------------------------------------------------------

interface TemplateRow {
  name: string;
  target: string;
  delimiter: string;
  unitFormat: string;
  columns: { header: string; field: string }[];
}

function ExportTemplates() {
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({
    queryKey: ["export-templates"],
    queryFn: () => apiGet<TemplateRow[]>("/admin/export-templates"),
  });
  const [drafts, setDrafts] = useState<Record<string, string>>({});

  const save = useMutation({
    mutationFn: (t: TemplateRow) =>
      apiSend("PUT", "/admin/export-templates", {
        templates: [
          {
            name: t.name,
            target: t.target,
            delimiter: t.delimiter,
            unit_format: t.unitFormat,
            columns: JSON.parse(drafts[t.name] ?? JSON.stringify(t.columns)),
          },
        ],
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["export-templates"] });
      toast.success("Mapping saved");
    },
    onError: (e) => toast.error("Mapping not saved", errorMessage(e)),
  });

  if (q.isLoading) return <SkeletonRows rows={4} />;

  return (
    <div className="space-y-4">
      <p className="max-w-2xl text-sm text-muted">
        Columns map takeoff-line fields to CSV headers. Edit the JSON to match your
        Mozaik or KCD import dialog. Fields: <code>tag</code>, <code>room</code>,{" "}
        <code>qty</code>, <code>category</code>, <code>width_in</code>,{" "}
        <code>height_in</code>, <code>depth_in</code>, <code>door_style</code>,{" "}
        <code>material</code>, <code>finish</code>, <code>assembled</code>,{" "}
        <code>notes</code>, <code>source_page</code>, or <code>literal:&lt;value&gt;</code>.
      </p>
      {(q.data ?? []).map((t) => (
        <Card key={t.name}>
          <div className="mb-2 flex items-center gap-2">
            <h2 className="wide font-display text-base font-semibold text-ink">{t.name}</h2>
            <Badge>{t.target}</Badge>
            <span className="font-mono text-xs text-faint">delimiter "{t.delimiter}" · {t.unitFormat}</span>
            <Button className="ml-auto" variant="primary" loading={save.isPending} onClick={() => save.mutate(t)}>
              Save mapping
            </Button>
          </div>
          <Textarea
            className="h-40 w-full font-mono text-xs"
            value={drafts[t.name] ?? JSON.stringify(t.columns, null, 2)}
            onChange={(e) => setDrafts({ ...drafts, [t.name]: e.target.value })}
          />
        </Card>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Crawler sources (PRD §5) — hidden with the prospector, still routable
// ---------------------------------------------------------------------------

interface SourceRow {
  id: string;
  name: string;
  type: string;
  baseUrl: string;
  status: string;
  lastRunAt: string | null;
  lastError: string | null;
}

function Sources() {
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({
    queryKey: ["sources"],
    queryFn: () => apiGet<SourceRow[]>("/admin/sources"),
  });
  const run = useMutation({
    mutationFn: (id: string) => apiSend("POST", `/admin/sources/${id}/run`),
    onSuccess: () => toast.success("Crawl queued"),
    onError: (e) => toast.error("Crawl not queued", errorMessage(e)),
  });
  const patch = useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) =>
      apiSend("PATCH", `/admin/sources/${id}`, { status }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sources"] }),
    onError: (e) => toast.error("Not updated", errorMessage(e)),
  });

  if (q.isLoading) return <SkeletonRows rows={3} />;

  return (
    <Card className="p-0">
      <p className="border-b border-rule px-4 py-2 text-xs text-muted">
        The prospector is parked (product-plan.md §7). Sources stay here so nothing is lost.
      </p>
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-rule text-left font-mono text-[11px] uppercase tracking-wider text-muted">
            <th className="px-4 py-2">Source</th>
            <th className="px-3 py-2">Type</th>
            <th className="px-3 py-2">Status</th>
            <th className="px-3 py-2">Last run</th>
            <th className="px-3 py-2">Last error</th>
            <th className="px-3 py-2" />
          </tr>
        </thead>
        <tbody>
          {(q.data ?? []).map((s) => (
            <tr key={s.id} className="border-b border-rule-soft">
              <td className="px-4 py-2 font-medium">{s.name}</td>
              <td className="px-3 py-2 text-muted">{s.type}</td>
              <td className="px-3 py-2"><StatusPill status={s.status} /></td>
              <td className="px-3 py-2 text-muted">
                {s.lastRunAt ? new Date(s.lastRunAt).toLocaleString() : "never"}
              </td>
              <td className="max-w-xs truncate px-3 py-2 text-bad" title={s.lastError ?? ""}>
                {s.lastError ?? ""}
              </td>
              <td className="space-x-1 whitespace-nowrap px-3 py-2 text-right">
                <Button size="sm" onClick={() => run.mutate(s.id)}>Run now</Button>
                <Button
                  size="sm"
                  variant="quiet"
                  onClick={() =>
                    patch.mutate({ id: s.id, status: s.status === "active" ? "paused" : "active" })
                  }
                >
                  {s.status === "active" ? "Pause" : "Resume"}
                </Button>
              </td>
            </tr>
          ))}
          {(q.data ?? []).length === 0 && (
            <tr><td colSpan={6} className="px-4 py-6 text-center text-faint">No sources configured.</td></tr>
          )}
        </tbody>
      </table>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Invites (accounts-plan.md §1): a single-use sign-up link emailed to a
// prospect. The link is shown once so it can be pasted when email is not
// configured on the API yet.
// ---------------------------------------------------------------------------

interface InviteRow {
  id: string;
  email: string;
  name: string | null;
  orgName: string | null;
  creditsGranted: number;
  note: string | null;
  expiresAt: string;
  usedAt: string | null;
  revokedAt: string | null;
  lastSentAt: string | null;
  createdAt: string;
  state: "pending" | "used" | "revoked" | "expired";
}

interface InviteList {
  emailConfigured: boolean;
  invites: InviteRow[];
}

const INVITE_TONE: Record<InviteRow["state"], BadgeTone> = {
  pending: "blue",
  used: "good",
  revoked: "neutral",
  expired: "warn",
};

function Invites() {
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({
    queryKey: ["invites"],
    queryFn: () => apiGet<InviteList>("/admin/invites"),
  });
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [orgName, setOrgName] = useState("");
  const [credits, setCredits] = useState(20);
  const [note, setNote] = useState("");
  const [lastLink, setLastLink] = useState<{ email: string; link: string; sent: boolean } | null>(null);
  const [showAll, setShowAll] = useState(false);

  const create = useMutation({
    mutationFn: () =>
      apiSend<InviteRow & { sent: boolean; link: string }>("POST", "/admin/invites", {
        email,
        name: name || undefined,
        orgName: orgName || undefined,
        creditsGranted: credits,
        note: note || undefined,
      }),
    onSuccess: (r) => {
      setEmail("");
      setName("");
      setOrgName("");
      setNote("");
      setLastLink({ email: r.email, link: r.link, sent: r.sent });
      qc.invalidateQueries({ queryKey: ["invites"] });
      toast.success(r.sent ? `Invite emailed to ${r.email}` : `Invite created — email not configured, copy the link`);
    },
    onError: (e) => toast.error("Invite not created", errorMessage(e)),
  });
  const resend = useMutation({
    mutationFn: (id: string) =>
      apiSend<InviteRow & { sent: boolean; link: string }>("POST", `/admin/invites/${id}/resend`),
    onSuccess: (r) => {
      setLastLink({ email: r.email, link: r.link, sent: r.sent });
      qc.invalidateQueries({ queryKey: ["invites"] });
      toast.success(r.sent ? `New link emailed to ${r.email}` : "New link ready — copy it below");
    },
    onError: (e) => toast.error("Could not resend", errorMessage(e)),
  });
  const revoke = useMutation({
    mutationFn: (id: string) => apiSend<InviteRow>("DELETE", `/admin/invites/${id}`),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["invites"] });
      toast.info(`Invite for ${r.email} withdrawn`);
    },
    onError: (e) => toast.error("Could not revoke", errorMessage(e)),
  });

  const rows = (q.data?.invites ?? []).filter((i) => showAll || i.state === "pending");
  const hidden = (q.data?.invites.length ?? 0) - rows.length;

  return (
    <div className="space-y-4">
      <Card>
        <SectionLabel>Invite someone</SectionLabel>
        <form
          className="flex flex-wrap items-end gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (email) create.mutate();
          }}
        >
          <Field label="Email" className="min-w-56 flex-1">
            <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="name@company.com" />
          </Field>
          <Field label="Name (optional)" className="min-w-40">
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Pat" />
          </Field>
          <Field label="Company (optional)" className="min-w-40">
            <Input value={orgName} onChange={(e) => setOrgName(e.target.value)} placeholder="Pat's Cabinets" />
          </Field>
          <Field label="Pages included" hint="Credits granted at sign-up">
            <NumberInput value={credits} onChange={(e) => setCredits(Number(e.target.value))} min={0} max={10000} className="w-24" />
          </Field>
          <Field label="Note (admins only)" className="min-w-48 flex-1">
            <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="met at KBIS" />
          </Field>
          <Button type="submit" variant="primary" disabled={!email} loading={create.isPending} className="mb-4">
            Send invite
          </Button>
        </form>
        {q.data && !q.data.emailConfigured && (
          <p className="text-xs text-warn">
            Email is not configured on the API (RESEND_API_KEY / EMAIL_FROM), so invites are not sent — copy the link after creating one.
          </p>
        )}
        {lastLink && (
          <div className="mt-3 flex flex-wrap items-center gap-2 rounded-md border border-rule bg-rule-soft px-3 py-2 text-xs">
            <span className="text-muted">
              {lastLink.sent ? "Emailed to" : "Link for"} <span className="font-medium text-ink">{lastLink.email}</span>:
            </span>
            <code className="min-w-0 flex-1 truncate font-mono">{lastLink.link}</code>
            <Button
              size="sm"
              onClick={() => {
                navigator.clipboard.writeText(lastLink.link).then(
                  () => toast.success("Link copied"),
                  () => toast.error("Copy failed", "Select the link and copy it by hand")
                );
              }}
            >
              Copy
            </Button>
          </div>
        )}
      </Card>
      <Card className="p-0">
        <div className="flex items-center justify-between px-4 py-2">
          <SectionLabel>Invites</SectionLabel>
          {hidden > 0 || showAll ? (
            <button type="button" className="text-xs text-muted underline" onClick={() => setShowAll((v) => !v)}>
              {showAll ? "Pending only" : `Show ${hidden} used / expired / revoked`}
            </button>
          ) : null}
        </div>
        {q.isLoading ? (
          <SkeletonRows rows={3} />
        ) : rows.length === 0 ? (
          <p className="px-4 pb-4 text-sm text-muted">No pending invites.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-rule text-left font-mono text-[11px] uppercase tracking-wider text-muted">
                <th className="px-4 py-2">Email</th>
                <th className="px-3 py-2">Name</th>
                <th className="px-3 py-2">Pages</th>
                <th className="px-3 py-2">State</th>
                <th className="px-3 py-2">Expires</th>
                <th className="px-3 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((i) => (
                <tr key={i.id} className="border-b border-rule-soft">
                  <td className="px-4 py-2 font-medium">
                    {i.email}
                    {i.note && <div className="text-xs text-faint">{i.note}</div>}
                  </td>
                  <td className="px-3 py-2 text-muted">
                    {i.name ?? "—"}
                    {i.orgName && <div className="text-xs text-faint">{i.orgName}</div>}
                  </td>
                  <td className="px-3 py-2 text-muted">{i.creditsGranted}</td>
                  <td className="px-3 py-2"><Badge tone={INVITE_TONE[i.state]}>{i.state}</Badge></td>
                  <td className="px-3 py-2 text-muted">{new Date(i.expiresAt).toLocaleDateString()}</td>
                  <td className="px-3 py-2 text-right">
                    {(i.state === "pending" || i.state === "expired") && (
                      <span className="inline-flex gap-1">
                        <Button size="sm" loading={resend.isPending && resend.variables === i.id} onClick={() => resend.mutate(i.id)}>
                          Resend
                        </Button>
                        {i.state === "pending" && (
                          <Button size="sm" variant="ghost" loading={revoke.isPending && revoke.variables === i.id} onClick={() => revoke.mutate(i.id)}>
                            Revoke
                          </Button>
                        )}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tutorial sample job: one finished takeoff, cloned into every new org.
// ---------------------------------------------------------------------------

function SampleJob() {
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({
    queryKey: ["sample-takeoff"],
    queryFn: () => apiGet<{ takeoff: { id: string; sourceFilename: string | null; status: string } | null }>("/admin/sample-takeoff"),
  });
  const [id, setId] = useState("");
  const save = useMutation({
    mutationFn: (takeoff_id: string | null) => apiSend("PUT", "/admin/sample-takeoff", { takeoff_id }),
    onSuccess: () => {
      setId("");
      qc.invalidateQueries({ queryKey: ["sample-takeoff"] });
      toast.success("Sample job saved");
    },
    onError: (e) => toast.error("Not saved", errorMessage(e)),
  });
  const t = q.data?.takeoff ?? null;
  return (
    <Card>
      <SectionLabel>Sample job for new accounts</SectionLabel>
      <p className="mb-3 text-sm text-muted">
        {t ? (
          <>
            Currently <span className="font-medium text-ink">{t.sourceFilename ?? t.id}</span> ({t.status}). New sign-ups get a copy on their Jobs list.
          </>
        ) : (
          "None set — new sign-ups start with an empty Jobs list. Paste the id of a finished (reviewed or approved) takeoff from the URL of its review screen."
        )}
      </p>
      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          if (id.trim()) save.mutate(id.trim());
        }}
      >
        <Field label="Takeoff id" className="min-w-80 flex-1">
          <Input value={id} onChange={(e) => setId(e.target.value)} placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" className="font-mono" />
        </Field>
        <Button type="submit" variant="primary" disabled={!id.trim()} loading={save.isPending} className="mb-4">
          Use as sample
        </Button>
        {t && (
          <Button variant="quiet" onClick={() => save.mutate(null)} className="mb-4">
            Clear
          </Button>
        )}
      </form>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Users (allow-list until self-signup lands in Stage 2)
// ---------------------------------------------------------------------------

interface UserRow {
  id: string;
  email: string;
  name: string | null;
  role: string;
  orgName: string | null;
  orgRole: "owner" | "member";
  isPlatformAdmin: boolean;
  lastSignInAt: string | null;
}

const ROLE_HINT: Record<string, string> = {
  estimator: "Runs takeoffs and quotes",
  sales: "Same, plus margin visibility",
  admin: "Everything, including this panel",
};

function Users() {
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({
    queryKey: ["users"],
    queryFn: () => apiGet<UserRow[]>("/admin/users"),
  });
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("estimator");
  const add = useMutation({
    mutationFn: () => apiSend<UserRow | { error: string }>("POST", "/admin/users", { email, role }),
    onSuccess: (r) => {
      if ("error" in r) {
        toast.info(r.error);
        return;
      }
      setEmail("");
      qc.invalidateQueries({ queryKey: ["users"] });
      toast.success(`${r.email} can now sign in`);
    },
    onError: (e) => toast.error("User not added", errorMessage(e)),
  });
  const patch = useMutation({
    mutationFn: (v: { id: string; role?: string; is_platform_admin?: boolean }) =>
      apiSend<UserRow>("PATCH", `/admin/users/${v.id}`, { role: v.role, is_platform_admin: v.is_platform_admin }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }),
    onError: (e) => toast.error("User not changed", errorMessage(e)),
  });

  return (
    <div className="space-y-4">
      <Card>
        <SectionLabel>Allow a staff Google account to sign in</SectionLabel>
        <form
          className="flex flex-wrap items-end gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (email) add.mutate();
          }}
        >
          <Field label="Google account email" className="min-w-64 flex-1">
            <Input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="name@company.com"
            />
          </Field>
          <Field label="Role" hint={ROLE_HINT[role]}>
            <Select value={role} onChange={(e) => setRole(e.target.value)}>
              <option value="estimator">Estimator</option>
              <option value="sales">Sales</option>
              <option value="admin">Admin</option>
            </Select>
          </Field>
          <Button type="submit" variant="primary" disabled={!email} loading={add.isPending} className="mb-4">
            Add user
          </Button>
        </form>
        <p className="text-xs text-faint">
          Adds a CabinetNow staff account directly (no email); customers arrive through invites above.
          Platform admins see every org's jobs and this panel.
        </p>
      </Card>
      <Card className="p-0">
        {q.isLoading ? (
          <SkeletonRows rows={3} />
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-rule text-left font-mono text-[11px] uppercase tracking-wider text-muted">
                <th className="px-4 py-2">Email</th>
                <th className="px-3 py-2">Name</th>
                <th className="px-3 py-2">Org</th>
                <th className="px-3 py-2">Role</th>
                <th className="px-3 py-2">Platform admin</th>
                <th className="px-3 py-2">Last sign-in</th>
              </tr>
            </thead>
            <tbody>
              {(q.data ?? []).map((u) => (
                <tr key={u.id} className="border-b border-rule-soft">
                  <td className="px-4 py-2 font-medium">{u.email}</td>
                  <td className="px-3 py-2 text-muted">{u.name ?? "—"}</td>
                  <td className="px-3 py-2 text-muted">
                    {u.orgName ?? "—"} <span className="text-faint">· {u.orgRole}</span>
                  </td>
                  <td className="px-3 py-2">
                    <Select
                      value={u.role}
                      onChange={(e) => patch.mutate({ id: u.id, role: e.target.value })}
                      className="w-32"
                    >
                      <option value="estimator">Estimator</option>
                      <option value="sales">Sales</option>
                      <option value="admin">Admin</option>
                    </Select>
                  </td>
                  <td className="px-3 py-2">
                    <input
                      type="checkbox"
                      checked={u.isPlatformAdmin}
                      onChange={(e) => patch.mutate({ id: u.id, is_platform_admin: e.target.checked })}
                    />
                  </td>
                  <td className="px-3 py-2 text-muted">
                    {u.lastSignInAt ? new Date(u.lastSignInAt).toLocaleDateString() : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}
