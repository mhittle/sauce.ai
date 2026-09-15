import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { signupRoute } from "../main";
import { apiPublic, ApiError, setSession } from "../api";
import { Button, Field, Input } from "../components/ui";

type InviteState = "pending" | "used" | "revoked" | "expired";

interface InviteLookup {
  state: InviteState;
  email?: string;
  name?: string | null;
  orgName?: string | null;
  creditsGranted?: number;
  inviterName?: string;
  expiresAt?: string;
  termsUrl?: string | null;
  privacyUrl?: string | null;
}

const STATE_COPY: Record<Exclude<InviteState, "pending">, { title: string; body: string }> = {
  used: {
    title: "This invite was already used",
    body: "Your account exists — sign in instead.",
  },
  revoked: {
    title: "This invite was withdrawn",
    body: "Ask the person who invited you for a new link.",
  },
  expired: {
    title: "This invite has expired",
    body: "Invites last 14 days. Ask the person who invited you for a new link.",
  },
};

export function SignupPage() {
  const { token } = signupRoute.useSearch();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const lookup = useQuery({
    queryKey: ["signup", token],
    queryFn: () => apiPublic<InviteLookup>("GET", `/signup/${token}`),
    enabled: Boolean(token),
    retry: false,
  });
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [touched, setTouched] = useState(false);
  const invite = lookup.data;
  const displayName = touched ? name : name || invite?.name || "";

  const submit = useMutation({
    mutationFn: () =>
      apiPublic<{ session: string }>("POST", "/signup", {
        token,
        name: displayName.trim(),
        phone: phone.trim() || undefined,
      }),
    onSuccess: (r) => {
      setSession(r.session);
      qc.clear();
      navigate({ to: "/" });
    },
  });

  let content: React.ReactNode;
  if (!token || (lookup.isError && lookup.error instanceof ApiError && lookup.error.status === 404)) {
    content = (
      <Notice title="This sign-up link isn't valid" body="Check the link in your email, or ask the person who invited you for a new one." />
    );
  } else if (lookup.isLoading) {
    content = <p className="text-sm text-muted">Checking your invite…</p>;
  } else if (lookup.isError || !invite) {
    content = <Notice title="We couldn't check this invite" body="Please try again in a moment." />;
  } else if (invite.state !== "pending") {
    const c = STATE_COPY[invite.state];
    content = (
      <Notice title={c.title} body={c.body}>
        {invite.state === "used" && (
          <a href="/" className="mt-3 inline-block">
            <Button variant="primary">Go to sign in</Button>
          </a>
        )}
      </Notice>
    );
  } else {
    const submitError =
      submit.error instanceof ApiError
        ? submit.error.status === 409
          ? "This invite can't be used any more — it may already have been redeemed. Try signing in."
          : "We couldn't create your account. Please try again."
        : null;
    content = (
      <form
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault();
          if (displayName.trim()) submit.mutate();
        }}
      >
        <p className="text-sm text-muted">
          {invite.inviterName} invited you to Scribe
          {invite.orgName ? ` for ${invite.orgName}` : ""}.
          {invite.creditsGranted ? ` Your account starts with ${invite.creditsGranted} pages of reading included.` : ""}
        </p>
        <Field label="Email">
          <Input value={invite.email ?? ""} readOnly disabled />
        </Field>
        <Field label="Your name">
          <Input
            value={displayName}
            onChange={(e) => {
              setTouched(true);
              setName(e.target.value);
            }}
            placeholder="Pat Smith"
            autoComplete="name"
            autoFocus
          />
        </Field>
        <Field label="Phone (optional)">
          <Input
            type="tel"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            placeholder="(555) 555-0100"
            autoComplete="tel"
          />
        </Field>
        {submitError && (
          <p className="rounded-md border border-bad bg-bad-soft px-3 py-2 text-sm text-bad">{submitError}</p>
        )}
        <Button type="submit" variant="primary" className="w-full" disabled={!displayName.trim()} loading={submit.isPending}>
          Create my account
        </Button>
        <p className="text-xs text-faint">
          By continuing you agree to the{" "}
          <Legal href={invite.termsUrl}>Terms</Legal> and <Legal href={invite.privacyUrl}>Privacy Policy</Legal>.
        </p>
      </form>
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-sm rounded-lg border border-rule bg-paper p-8">
        <div className="mb-6">
          <div className="wide font-display text-3xl font-bold leading-none text-ink">Scribe</div>
          <p className="mt-2 text-sm text-muted">Upload the drawings. Get the cabinet breakdown and a quote in minutes.</p>
        </div>
        {content}
        <p className="mt-4 font-mono text-[11px] text-faint">sauce.ai / scribe</p>
      </div>
    </div>
  );
}

function Notice({ title, body, children }: { title: string; body: string; children?: React.ReactNode }) {
  return (
    <div>
      <h2 className="font-display text-lg font-semibold text-ink">{title}</h2>
      <p className="mt-1 text-sm text-muted">{body}</p>
      {children}
    </div>
  );
}

function Legal({ href, children }: { href: string | null | undefined; children: React.ReactNode }) {
  if (!href) return <span className="text-muted">{children}</span>;
  return (
    <a href={href} target="_blank" rel="noreferrer" className="text-ink underline">
      {children}
    </a>
  );
}
