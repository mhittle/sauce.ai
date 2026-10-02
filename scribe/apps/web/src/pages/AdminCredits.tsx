import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { CreditSettings } from "@scribe/shared";
import { apiGet, apiSend } from "../api";
import { LedgerTable, type LedgerRow } from "../components/Credits";
import { TechnicalDetail } from "../components/TechnicalDetail";
import { CREDITS_LOAD_FAILED } from "../messages";
import {
  Button,
  Card,
  errorMessage,
  Field,
  Input,
  NumberInput,
  SectionLabel,
  SkeletonRows,
  useToast,
} from "../ui";

// Admin → Credits (accounts-plan.md §3.3): the pricing rules, every company's
// balance, and grants / corrections. 1 credit = 1 page read = $1.

interface OrgCredits {
  id: string;
  name: string;
  is_platform: boolean;
  credit_balance: number;
  jobs: number;
  pages_spent: number;
  pages_added: number;
  last_activity: string | null;
}

export function Credits() {
  const q = useQuery({
    queryKey: ["admin-credits"],
    queryFn: () => apiGet<{ settings: CreditSettings; orgs: OrgCredits[] }>("/admin/credits"),
  });
  if (q.isLoading) return <SkeletonRows rows={5} />;
  if (q.isError || !q.data) {
    return (
      <div className="text-bad">
        {CREDITS_LOAD_FAILED}
        <TechnicalDetail details={String(q.error)} />
      </div>
    );
  }
  return (
    <div className="space-y-6">
      <Rules settings={q.data.settings} />
      <Balances orgs={q.data.orgs} />
    </div>
  );
}

function Rules({ settings }: { settings: CreditSettings }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [draft, setDraft] = useState(settings);
  useEffect(() => setDraft(settings), [settings]);
  const save = useMutation({
    mutationFn: () => apiSend("PATCH", "/admin/credit-settings", draft),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-credits"] });
      qc.invalidateQueries({ queryKey: ["credits"] });
      toast.success("Credit rules saved");
    },
    onError: (e) => toast.error("Not saved", errorMessage(e)),
  });
  const dirty = JSON.stringify(draft) !== JSON.stringify(settings);
  return (
    <Card>
      <SectionLabel>Rules</SectionLabel>
      <div className="flex flex-wrap items-end gap-4">
        <Field label="Minimum pages per job" hint="1 = no minimum">
          <NumberInput
            value={draft.minPagesPerJob}
            min={1}
            max={100}
            className="w-24"
            onChange={(e) => setDraft({ ...draft, minPagesPerJob: Math.max(1, Number(e.target.value)) })}
          />
        </Field>
        <label className="flex items-center gap-2 pb-2 text-sm">
          <input
            type="checkbox"
            checked={draft.firstJobFree}
            onChange={(e) => setDraft({ ...draft, firstJobFree: e.target.checked })}
          />
          First job free
        </label>
        <label className="flex items-center gap-2 pb-2 text-sm">
          <input
            type="checkbox"
            checked={draft.creditsEnforced}
            onChange={(e) => setDraft({ ...draft, creditsEnforced: e.target.checked })}
          />
          Block jobs the balance can't cover
        </label>
        <Button variant="primary" disabled={!dirty} loading={save.isPending} onClick={() => save.mutate()}>
          Save
        </Button>
      </div>
      <p className="mt-2 text-xs text-muted">
        While blocking is off, jobs are recorded and the balance can go below zero. Leave it off
        until customers can buy pages.
      </p>
    </Card>
  );
}

function Balances({ orgs }: { orgs: OrgCredits[] }) {
  const [open, setOpen] = useState<string | null>(null);
  return (
    <section>
      <SectionLabel>Companies</SectionLabel>
      <Card className="overflow-x-auto p-0">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-rule text-left font-mono text-[11px] uppercase tracking-wider text-muted">
              <th className="px-4 py-2">Company</th>
              <th className="px-3 py-2 text-right">Balance</th>
              <th className="px-3 py-2 text-right">Jobs</th>
              <th className="px-3 py-2 text-right">Pages used</th>
              <th className="px-3 py-2 text-right">Pages added</th>
              <th className="px-3 py-2">Last activity</th>
              <th className="px-3 py-2" />
            </tr>
          </thead>
          <tbody>
            {orgs.map((o) => (
              <OrgRow key={o.id} org={o} open={open === o.id} onToggle={() => setOpen(open === o.id ? null : o.id)} />
            ))}
          </tbody>
        </table>
      </Card>
    </section>
  );
}

function OrgRow({ org, open, onToggle }: { org: OrgCredits; open: boolean; onToggle: () => void }) {
  return (
    <>
      <tr className="border-b border-rule-soft">
        <td className="px-4 py-2 font-medium">
          {org.name}
          {org.is_platform && <span className="ml-2 text-xs text-faint">platform</span>}
        </td>
        <td className={`px-3 py-2 text-right font-mono tabular-nums ${org.credit_balance < 0 ? "text-bad" : ""}`}>
          {org.credit_balance}
        </td>
        <td className="px-3 py-2 text-right font-mono tabular-nums">{org.jobs}</td>
        <td className="px-3 py-2 text-right font-mono tabular-nums">{org.pages_spent}</td>
        <td className="px-3 py-2 text-right font-mono tabular-nums">{org.pages_added}</td>
        <td className="px-3 py-2 text-muted">
          {org.last_activity ? new Date(org.last_activity).toLocaleDateString() : "—"}
        </td>
        <td className="px-3 py-2 text-right">
          <Button size="sm" variant="quiet" onClick={onToggle}>
            {open ? "Close" : "Ledger · adjust"}
          </Button>
        </td>
      </tr>
      {open && (
        <tr className="border-b border-rule-soft bg-bg">
          <td colSpan={7} className="p-0">
            <OrgLedger orgId={org.id} />
          </td>
        </tr>
      )}
    </>
  );
}

function OrgLedger({ orgId }: { orgId: string }) {
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({
    queryKey: ["admin-credits", orgId],
    queryFn: () => apiGet<LedgerRow[]>(`/admin/credits/${orgId}/ledger`),
  });
  const [delta, setDelta] = useState(0);
  const [note, setNote] = useState("");
  const adjust = useMutation({
    mutationFn: () => apiSend("POST", "/admin/credits/adjust", { orgId, delta, note }),
    onSuccess: () => {
      setDelta(0);
      setNote("");
      qc.invalidateQueries({ queryKey: ["admin-credits"] });
      qc.invalidateQueries({ queryKey: ["credits"] });
      toast.success(delta > 0 ? `Added ${delta} pages` : `Removed ${-delta} pages`);
    },
    onError: (e) => toast.error("Not adjusted", errorMessage(e)),
  });
  return (
    <div className="space-y-3 p-4">
      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          adjust.mutate();
        }}
      >
        <Field label="Pages (+ add, − remove)">
          <NumberInput value={delta} className="w-28" onChange={(e) => setDelta(Math.trunc(Number(e.target.value)))} />
        </Field>
        <Field label="Reason (shown to the customer)" className="min-w-64 flex-1">
          <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="beta pilot pages" />
        </Field>
        <Button type="submit" variant="primary" disabled={delta === 0 || !note.trim()} loading={adjust.isPending}>
          Apply
        </Button>
      </form>
      <Card className="p-0">
        {q.data ? <LedgerTable rows={q.data} /> : <SkeletonRows rows={3} />}
      </Card>
    </div>
  );
}
