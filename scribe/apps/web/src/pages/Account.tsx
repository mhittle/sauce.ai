import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiSend, apiUpload } from "../api";
import {
  Badge,
  Button,
  Card,
  errorMessage,
  Field,
  Input,
  PageTitle,
  SectionLabel,
  SkeletonRows,
  useToast,
} from "../components/ui";

interface Account {
  me: { id: string; email: string; name: string | null; phone: string | null };
  org: { id: string; name: string; logo_url: string | null };
  orgRole: "owner" | "member";
  members: {
    id: string;
    email: string;
    name: string | null;
    orgRole: "owner" | "member";
    lastSignInAt: string | null;
  }[];
  invites: { id: string; email: string; name: string | null; expiresAt: string }[];
}

export function AccountPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({ queryKey: ["account"], queryFn: () => apiGet<Account>("/account") });
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["account"] });
    qc.invalidateQueries({ queryKey: ["me"] });
  };

  if (q.isLoading || !q.data) {
    return (
      <div className="mx-auto max-w-3xl">
        <PageTitle>Account</PageTitle>
        <SkeletonRows rows={6} />
      </div>
    );
  }
  const a = q.data;
  const owner = a.orgRole === "owner";

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <PageTitle>Account</PageTitle>
      <Profile me={a.me} onSaved={refresh} />
      <Org org={a.org} owner={owner} onSaved={refresh} />
      <Members account={a} owner={owner} onChanged={refresh} toast={toast} />
    </div>
  );
}

function Profile({ me, onSaved }: { me: Account["me"]; onSaved: () => void }) {
  const toast = useToast();
  const [name, setName] = useState(me.name ?? "");
  const [phone, setPhone] = useState(me.phone ?? "");
  const save = useMutation({
    mutationFn: () => apiSend("PATCH", "/me", { name: name.trim(), phone: phone.trim() || null }),
    onSuccess: () => {
      toast.success("Profile saved");
      onSaved();
    },
    onError: (e) => toast.error("Not saved", errorMessage(e)),
  });
  const dirty = name.trim() !== (me.name ?? "") || phone.trim() !== (me.phone ?? "");
  return (
    <Card>
      <SectionLabel>You</SectionLabel>
      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          if (name.trim()) save.mutate();
        }}
      >
        <Field label="Email" className="min-w-56">
          <Input value={me.email} readOnly disabled />
        </Field>
        <Field label="Name" className="min-w-48">
          <Input value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" />
        </Field>
        <Field label="Phone" className="min-w-40">
          <Input type="tel" value={phone} onChange={(e) => setPhone(e.target.value)} autoComplete="tel" />
        </Field>
        <Button type="submit" variant="primary" disabled={!dirty || !name.trim()} loading={save.isPending} className="mb-4">
          Save
        </Button>
      </form>
    </Card>
  );
}

function Org({ org, owner, onSaved }: { org: Account["org"]; owner: boolean; onSaved: () => void }) {
  const toast = useToast();
  const [name, setName] = useState(org.name);
  const save = useMutation({
    mutationFn: () => apiSend("PATCH", "/account/org", { name: name.trim() }),
    onSuccess: () => {
      toast.success("Company saved");
      onSaved();
    },
    onError: (e) => toast.error("Not saved", errorMessage(e)),
  });
  const upload = useMutation({
    mutationFn: (f: File) => apiUpload("/account/org/logo", f),
    onSuccess: () => {
      toast.success("Logo updated");
      onSaved();
    },
    onError: (e) => toast.error("Logo not uploaded", errorMessage(e)),
  });
  return (
    <Card>
      <SectionLabel>Company</SectionLabel>
      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          if (name.trim()) save.mutate();
        }}
      >
        <Field label="Company name" className="min-w-64 flex-1" hint={owner ? "Shown on your quotes" : "Only an owner can change this"}>
          <Input value={name} onChange={(e) => setName(e.target.value)} disabled={!owner} />
        </Field>
        {owner && (
          <Button type="submit" variant="primary" disabled={name.trim() === org.name || !name.trim()} loading={save.isPending} className="mb-4">
            Save
          </Button>
        )}
      </form>
      <div className="mt-3 flex items-center gap-4">
        {org.logo_url ? (
          <img src={org.logo_url} alt="Company logo" className="h-14 rounded border border-rule bg-white p-1" />
        ) : (
          <div className="flex h-14 w-28 items-center justify-center rounded border border-dashed border-rule text-xs text-faint">
            no logo
          </div>
        )}
        {owner && (
          <label className="text-sm">
            <span className="sr-only">Upload logo</span>
            <input
              type="file"
              accept=".png,.jpg,.jpeg"
              className="text-xs text-muted file:mr-3 file:rounded-md file:border file:border-rule file:bg-paper file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-ink hover:file:bg-rule-soft"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) upload.mutate(f);
                e.target.value = "";
              }}
            />
            <span className="ml-2 text-xs text-faint">PNG or JPEG · goes on your quote PDFs</span>
          </label>
        )}
      </div>
    </Card>
  );
}

function Members({
  account,
  owner,
  onChanged,
  toast,
}: {
  account: Account;
  owner: boolean;
  onChanged: () => void;
  toast: ReturnType<typeof useToast>;
}) {
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [lastLink, setLastLink] = useState<{ email: string; link: string; sent: boolean } | null>(null);
  const invite = useMutation({
    mutationFn: () =>
      apiSend<{ email: string; link: string; sent: boolean }>("POST", "/account/invites", {
        email,
        name: name || undefined,
      }),
    onSuccess: (r) => {
      setEmail("");
      setName("");
      setLastLink(r);
      toast.success(r.sent ? `Invite emailed to ${r.email}` : "Invite created — copy the link");
      onChanged();
    },
    onError: (e) => toast.error("Invite not sent", errorMessage(e)),
  });
  const revoke = useMutation({
    mutationFn: (id: string) => apiSend("DELETE", `/account/invites/${id}`),
    onSuccess: onChanged,
    onError: (e) => toast.error("Could not withdraw", errorMessage(e)),
  });
  const role = useMutation({
    mutationFn: (v: { id: string; org_role: "owner" | "member" }) =>
      apiSend("PATCH", `/account/members/${v.id}`, { org_role: v.org_role }),
    onSuccess: onChanged,
    onError: (e) => toast.error("Role not changed", errorMessage(e)),
  });

  return (
    <Card className="p-0">
      <div className="px-4 pt-4">
        <SectionLabel>Team</SectionLabel>
      </div>
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-rule text-left font-mono text-[11px] uppercase tracking-wider text-muted">
            <th className="px-4 py-2">Email</th>
            <th className="px-3 py-2">Name</th>
            <th className="px-3 py-2">Role</th>
            <th className="px-3 py-2">Last sign-in</th>
          </tr>
        </thead>
        <tbody>
          {account.members.map((m) => (
            <tr key={m.id} className="border-b border-rule-soft">
              <td className="px-4 py-2 font-medium">{m.email}</td>
              <td className="px-3 py-2 text-muted">{m.name ?? "—"}</td>
              <td className="px-3 py-2">
                {owner && m.id !== account.me.id ? (
                  <Button
                    size="sm"
                    variant="ghost"
                    loading={role.isPending && role.variables?.id === m.id}
                    onClick={() => role.mutate({ id: m.id, org_role: m.orgRole === "owner" ? "member" : "owner" })}
                  >
                    {m.orgRole} · make {m.orgRole === "owner" ? "member" : "owner"}
                  </Button>
                ) : (
                  <Badge>{m.orgRole}</Badge>
                )}
              </td>
              <td className="px-3 py-2 text-muted">
                {m.lastSignInAt ? new Date(m.lastSignInAt).toLocaleDateString() : "—"}
              </td>
            </tr>
          ))}
          {account.invites.map((i) => (
            <tr key={i.id} className="border-b border-rule-soft text-muted">
              <td className="px-4 py-2">{i.email}</td>
              <td className="px-3 py-2">{i.name ?? "—"}</td>
              <td className="px-3 py-2">
                <Badge tone="blue">invited</Badge>
              </td>
              <td className="px-3 py-2">
                until {new Date(i.expiresAt).toLocaleDateString()}
                {owner && (
                  <Button size="sm" variant="ghost" className="ml-2" onClick={() => revoke.mutate(i.id)}>
                    Withdraw
                  </Button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {owner && (
        <form
          className="flex flex-wrap items-end gap-3 border-t border-rule px-4 py-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (email) invite.mutate();
          }}
        >
          <Field label="Invite a teammate" className="min-w-56 flex-1">
            <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="name@company.com" />
          </Field>
          <Field label="Name (optional)" className="min-w-40">
            <Input value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <Button type="submit" variant="primary" disabled={!email} loading={invite.isPending} className="mb-4">
            Send invite
          </Button>
          {lastLink && !lastLink.sent && (
            <p className="w-full text-xs text-muted">
              Email isn't set up yet — send this link to {lastLink.email}:{" "}
              <code className="font-mono">{lastLink.link}</code>
            </p>
          )}
        </form>
      )}
    </Card>
  );
}
