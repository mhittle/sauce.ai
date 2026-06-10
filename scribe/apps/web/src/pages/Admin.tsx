import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { API_URL, apiGet, apiSend, formatUsd } from "../api";
import { Badge, Button, Card, Input, PageTitle } from "../ui";

type Tab = "pricing" | "org" | "templates" | "sources" | "users";

export function AdminPage() {
  const [tab, setTab] = useState<Tab>("pricing");
  return (
    <div>
      <PageTitle>Admin</PageTitle>
      <div className="mb-4 flex gap-1">
        {(
          [
            ["pricing", "Pricing Editor"],
            ["org", "Branding & Freight"],
            ["templates", "CSV Export Mappings"],
            ["sources", "Crawler Sources"],
            ["users", "Users"],
          ] as [Tab, string][]
        ).map(([t, label]) => (
          <Button
            key={t}
            variant={tab === t ? "primary" : "default"}
            onClick={() => setTab(t)}
          >
            {label}
          </Button>
        ))}
      </div>
      {tab === "pricing" && <PricingEditor />}
      {tab === "org" && <OrgSettings />}
      {tab === "templates" && <ExportTemplates />}
      {tab === "sources" && <Sources />}
      {tab === "users" && <Users />}
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

function PricingEditor() {
  const qc = useQueryClient();
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
    mutationFn: () =>
      apiSend("PUT", "/admin/pricing", { product_lines: draft }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-pricing"] });
      setDraft(null);
    },
  });

  if (q.isLoading || !draft) return <div className="text-zinc-500">Loading…</div>;

  const update = (i: number, patch: Partial<ProductLine>) => {
    setDraft(draft.map((p, j) => (j === i ? { ...p, ...patch } : p)));
  };

  return (
    <div className="space-y-4">
      <Card className="flex items-center justify-between">
        <span className="text-sm text-zinc-500">
          Latest config: v{q.data!.versions[0]?.version ?? "—"}. Saving creates
          a new immutable version; existing quotes keep their pinned version.
        </span>
        <Button
          variant="primary"
          disabled={save.isPending}
          onClick={() => save.mutate()}
        >
          Save all (new version)
        </Button>
      </Card>
      {save.isError && (
        <p className="text-sm text-red-600">{String(save.error)}</p>
      )}

      {draft.map((pl, i) => (
        <Card key={pl.id}>
          <div className="mb-2 flex items-center gap-3">
            <h2 className="font-semibold">{pl.name}</h2>
            <Badge>{pl.size_measure}</Badge>
            <label className="ml-auto flex items-center gap-1 text-sm">
              Lead time (days)
              <Input
                type="number"
                className="w-16"
                value={pl.lead_time_days}
                onChange={(e) =>
                  update(i, { lead_time_days: Number(e.target.value) })
                }
              />
            </label>
            <label className="flex items-center gap-1 text-sm">
              <input
                type="checkbox"
                checked={pl.active}
                onChange={(e) => update(i, { active: e.target.checked })}
              />
              Active
            </label>
          </div>

          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <div>
              <h3 className="mb-1 text-xs font-semibold uppercase text-zinc-400">
                Material rates ($/{pl.size_measure})
              </h3>
              {Object.entries(pl.material_rates).map(([mat, rate]) => (
                <div key={mat} className="flex items-center gap-2 py-0.5 text-sm">
                  <span className="w-28">{mat}</span>
                  <Input
                    type="number"
                    step="0.01"
                    className="w-24"
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
                  {rate.needs_review && <Badge tone="red">NEEDS REVIEW</Badge>}
                </div>
              ))}
            </div>
            <div>
              <h3 className="mb-1 text-xs font-semibold uppercase text-zinc-400">
                Finish adders
              </h3>
              {Object.entries(pl.finish_adders).map(([finish, adder]) => (
                <div key={finish} className="flex items-center gap-2 py-0.5 text-sm">
                  <span className="w-28">{finish}</span>
                  <Input
                    type="number"
                    step="0.01"
                    className="w-24"
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
                  <span className="text-zinc-400">
                    {adder.kind === "flat" ? "$" : "%"}
                  </span>
                </div>
              ))}
              {pl.assembly_adder && (
                <div className="mt-2 flex items-center gap-2 text-sm">
                  <span className="w-28 font-medium">assembly</span>
                  <Input
                    type="number"
                    step="0.01"
                    className="w-24"
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
                  <span className="text-zinc-400">
                    {pl.assembly_adder.kind === "flat" ? "$" : "%"}
                  </span>
                </div>
              )}
            </div>
          </div>
        </Card>
      ))}

      <TestCalculator productLines={draft} />
    </div>
  );
}

function TestCalculator({ productLines }: { productLines: ProductLine[] }) {
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
  });

  return (
    <Card className="border-blue-200">
      <h2 className="mb-2 text-sm font-semibold text-blue-700">
        Test calculator — prices against the DRAFT config above (before saving)
      </h2>
      <div className="flex flex-wrap items-end gap-3 text-sm">
        <label>
          Line
          <select
            className="ml-1 rounded-md border border-zinc-300 px-2 py-1"
            value={plId}
            onChange={(e) => setPlId(e.target.value)}
          >
            {productLines.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
        {(["qty", "width_in", "height_in", "depth_in"] as const).map((f) => (
          <label key={f}>
            {f.replace("_in", '"')}
            <Input
              className="ml-1 w-16"
              value={form[f]}
              onChange={(e) => setForm({ ...form, [f]: e.target.value })}
            />
          </label>
        ))}
        <label>
          Material
          <select
            className="ml-1 rounded-md border border-zinc-300 px-2 py-1"
            value={form.material}
            onChange={(e) => setForm({ ...form, material: e.target.value })}
          >
            <option value="">(first)</option>
            {Object.keys(pl?.material_rates ?? {}).map((m) => (
              <option key={m}>{m}</option>
            ))}
          </select>
        </label>
        <label>
          Finish
          <select
            className="ml-1 rounded-md border border-zinc-300 px-2 py-1"
            value={form.finish}
            onChange={(e) => setForm({ ...form, finish: e.target.value })}
          >
            <option value="">(none)</option>
            {Object.keys(pl?.finish_adders ?? {}).map((f) => (
              <option key={f}>{f}</option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-1">
          <input
            type="checkbox"
            checked={form.assembled}
            onChange={(e) => setForm({ ...form, assembled: e.target.checked })}
          />
          Assembled
        </label>
        <Button variant="primary" onClick={() => calc.mutate()}>
          Calculate
        </Button>
      </div>
      {result && (
        <div className="mt-3 rounded-md bg-zinc-50 p-2 text-sm">
          {result.ok ? (
            <span>
              Unit {formatUsd(result.unit_cents as number)} · Total{" "}
              <strong>{formatUsd(result.total_cents as number)}</strong> · lead{" "}
              {String(result.lead_time_days)}d
              {Boolean(result.needs_review) && (
                <Badge tone="red">NEEDS REVIEW rate</Badge>
              )}
            </span>
          ) : (
            <span className="text-red-600">{String(result.detail)}</span>
          )}
        </div>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Org settings: branding, terms, freight (PRD §7.1, §6.5)
// ---------------------------------------------------------------------------

interface OrgSettingsData {
  quoteTermsMd: string;
  quoteFooterMd: string;
  defaultHandlingCents: number;
  palletRateCents: number;
  freightProvider: string;
  logo_url: string | null;
}

function OrgSettings() {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["org-settings"],
    queryFn: () => apiGet<OrgSettingsData>("/admin/org-settings"),
  });
  const [terms, setTerms] = useState<string | null>(null);
  const [footer, setFooter] = useState<string | null>(null);

  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      apiSend("PUT", "/admin/org-settings", body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["org-settings"] }),
  });

  if (q.isLoading) return <div className="text-zinc-500">Loading…</div>;
  const s = q.data!;

  return (
    <div className="space-y-4">
      <Card>
        <h2 className="mb-2 text-sm font-semibold text-zinc-500">Logo</h2>
        {s.logo_url && (
          <img src={s.logo_url} alt="logo" className="mb-2 h-16" />
        )}
        <input
          type="file"
          accept=".png,.svg,.jpg,.jpeg"
          onChange={async (e) => {
            const f = e.target.files?.[0];
            if (!f) return;
            const form = new FormData();
            form.append("file", f);
            await fetch(`${API_URL}/admin/org-settings/logo`, {
              method: "POST",
              credentials: "include",
              body: form,
            });
            qc.invalidateQueries({ queryKey: ["org-settings"] });
          }}
        />
      </Card>

      <Card>
        <h2 className="mb-2 text-sm font-semibold text-zinc-500">
          Quote terms (markdown)
        </h2>
        <textarea
          className="h-32 w-full rounded-md border border-zinc-300 p-2 text-sm"
          value={terms ?? s.quoteTermsMd}
          onChange={(e) => setTerms(e.target.value)}
        />
        <h2 className="mb-2 mt-3 text-sm font-semibold text-zinc-500">
          Quote footer (markdown)
        </h2>
        <textarea
          className="h-16 w-full rounded-md border border-zinc-300 p-2 text-sm"
          value={footer ?? s.quoteFooterMd}
          onChange={(e) => setFooter(e.target.value)}
        />
        <Button
          variant="primary"
          className="mt-2"
          onClick={() =>
            save.mutate({
              quote_terms_md: terms ?? s.quoteTermsMd,
              quote_footer_md: footer ?? s.quoteFooterMd,
            })
          }
        >
          Save terms
        </Button>
      </Card>

      <Card>
        <h2 className="mb-2 text-sm font-semibold text-zinc-500">Freight</h2>
        <label className="block py-1 text-sm">
          Pallet rate $
          <Input
            type="number"
            className="ml-2 w-28"
            defaultValue={s.palletRateCents / 100}
            onBlur={(e) =>
              save.mutate({
                pallet_rate_cents: Math.round(Number(e.target.value) * 100),
              })
            }
          />
          <span className="ml-2 text-zinc-400">
            flat per pallet ({s.freightProvider} provider; Uber Freight in v1.1)
          </span>
        </label>
        <label className="block py-1 text-sm">
          Default handling $
          <Input
            type="number"
            className="ml-2 w-28"
            defaultValue={s.defaultHandlingCents / 100}
            onBlur={(e) =>
              save.mutate({
                default_handling_cents: Math.round(Number(e.target.value) * 100),
              })
            }
          />
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
    onSuccess: () => qc.invalidateQueries({ queryKey: ["export-templates"] }),
  });

  if (q.isLoading) return <div className="text-zinc-500">Loading…</div>;

  return (
    <div className="space-y-4">
      <p className="text-sm text-zinc-500">
        Columns map takeoff-line fields → CSV headers. Edit the JSON to match
        your Mozaik/KCD import dialog (fields: tag, room, qty, category,
        width_in, height_in, depth_in, door_style, material, finish, assembled,
        notes, source_page, or literal:&lt;value&gt;).
      </p>
      {(q.data ?? []).map((t) => (
        <Card key={t.name}>
          <div className="mb-2 flex items-center gap-2">
            <h2 className="font-semibold">{t.name}</h2>
            <Badge>{t.target}</Badge>
            <Button
              className="ml-auto"
              variant="primary"
              onClick={() => save.mutate(t)}
            >
              Save mapping
            </Button>
          </div>
          <textarea
            className="h-40 w-full rounded-md border border-zinc-300 p-2 font-mono text-xs"
            value={drafts[t.name] ?? JSON.stringify(t.columns, null, 2)}
            onChange={(e) =>
              setDrafts({ ...drafts, [t.name]: e.target.value })
            }
          />
        </Card>
      ))}
      {save.isError && (
        <p className="text-sm text-red-600">{String(save.error)}</p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Crawler sources (PRD §5)
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
  const q = useQuery({
    queryKey: ["sources"],
    queryFn: () => apiGet<SourceRow[]>("/admin/sources"),
  });
  const run = useMutation({
    mutationFn: (id: string) => apiSend("POST", `/admin/sources/${id}/run`),
  });
  const patch = useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) =>
      apiSend("PATCH", `/admin/sources/${id}`, { status }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sources"] }),
  });

  if (q.isLoading) return <div className="text-zinc-500">Loading…</div>;

  return (
    <Card className="p-0">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-zinc-200 text-left text-zinc-500">
            <th className="px-3 py-2">Source</th>
            <th className="px-3 py-2">Type</th>
            <th className="px-3 py-2">Status</th>
            <th className="px-3 py-2">Last run</th>
            <th className="px-3 py-2">Last error</th>
            <th className="px-3 py-2"></th>
          </tr>
        </thead>
        <tbody>
          {(q.data ?? []).map((s) => (
            <tr key={s.id} className="border-b border-zinc-100">
              <td className="px-3 py-2 font-medium">{s.name}</td>
              <td className="px-3 py-2">{s.type}</td>
              <td className="px-3 py-2">
                <Badge tone={s.status === "active" ? "green" : "amber"}>
                  {s.status}
                </Badge>
              </td>
              <td className="px-3 py-2 text-zinc-500">
                {s.lastRunAt ? new Date(s.lastRunAt).toLocaleString() : "never"}
              </td>
              <td className="max-w-xs truncate px-3 py-2 text-red-600" title={s.lastError ?? ""}>
                {s.lastError ?? ""}
              </td>
              <td className="space-x-1 whitespace-nowrap px-3 py-2">
                <Button onClick={() => run.mutate(s.id)}>Run now</Button>
                <Button
                  variant="ghost"
                  onClick={() =>
                    patch.mutate({
                      id: s.id,
                      status: s.status === "active" ? "paused" : "active",
                    })
                  }
                >
                  {s.status === "active" ? "Pause" : "Resume"}
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Users (no self-signup)
// ---------------------------------------------------------------------------

interface UserRow {
  id: string;
  email: string;
  name: string | null;
  role: string;
}

function Users() {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["users"],
    queryFn: () => apiGet<UserRow[]>("/admin/users"),
  });
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("estimator");
  const add = useMutation({
    mutationFn: () => apiSend("POST", "/admin/users", { email, role }),
    onSuccess: () => {
      setEmail("");
      qc.invalidateQueries({ queryKey: ["users"] });
    },
  });

  return (
    <div className="space-y-4">
      <Card className="flex items-end gap-3">
        <label className="text-sm">
          Email
          <Input
            className="ml-2 w-64"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="rep@cabinetnow.com"
          />
        </label>
        <label className="text-sm">
          Role
          <select
            className="ml-2 rounded-md border border-zinc-300 px-2 py-1 text-sm"
            value={role}
            onChange={(e) => setRole(e.target.value)}
          >
            <option value="estimator">estimator</option>
            <option value="sales">sales</option>
            <option value="admin">admin</option>
          </select>
        </label>
        <Button variant="primary" disabled={!email} onClick={() => add.mutate()}>
          Add user
        </Button>
      </Card>
      <Card className="p-0">
        <table className="w-full text-sm">
          <tbody>
            {(q.data ?? []).map((u) => (
              <tr key={u.id} className="border-b border-zinc-100">
                <td className="px-3 py-2 font-medium">{u.email}</td>
                <td className="px-3 py-2">{u.name}</td>
                <td className="px-3 py-2">
                  <Badge>{u.role}</Badge>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}
