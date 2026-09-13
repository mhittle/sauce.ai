import { useEffect, useRef, useState } from "react";
import { Link, Outlet, useRouterState } from "@tanstack/react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { API_URL, apiGet, apiSend, ApiError, clearSession } from "../api";
import { Button } from "../components/ui";
import {
  applyTheme,
  nextThemePref,
  readThemePref,
  type ThemePref,
} from "../theme";

interface Me {
  id: string;
  email: string;
  role: string;
  name: string | null;
}

// Product nav (product-plan.md §3.2): Jobs is the app. Quotes stays until PR 2
// folds it into the Jobs list. Admin only for admins. Prospects and the
// pipeline dashboard are operator screens — reachable from the account menu.
const NAV = [
  { to: "/", label: "Jobs" },
  { to: "/quotes", label: "Quotes" },
];

// Screens that own the whole width (the review/drawing screens); everything
// else sits in a readable column.
const FULL_BLEED = /^\/takeoffs\/[^/]+(\/detect)?$/;

const NAV_LINK =
  "rounded-md px-2.5 py-1 text-sm text-muted hover:bg-rule-soft hover:text-ink [&.active]:bg-rule-soft [&.active]:font-medium [&.active]:text-ink";

export function Layout() {
  const me = useQuery({
    queryKey: ["me"],
    queryFn: () => apiGet<Me>("/auth/me"),
    retry: false,
  });
  const path = useRouterState({ select: (s) => s.location.pathname });

  if (me.isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-muted">
        Loading…
      </div>
    );
  }

  if (me.isError) {
    const err = me.error;
    const denied =
      err instanceof ApiError &&
      err.status === 401 &&
      new URLSearchParams(window.location.search).get("auth_error");
    return <SignIn denied={denied || null} />;
  }

  const user = me.data!;
  const wide = FULL_BLEED.test(path);

  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-40 border-b border-rule bg-paper">
        <div
          className={`mx-auto flex h-12 items-center gap-5 px-4 ${wide ? "" : "max-w-7xl"}`}
        >
          <Link to="/" className="flex items-baseline gap-2">
            <span className="wide font-display text-lg font-bold tracking-tight text-ink">
              Scribe
            </span>
            <span className="font-mono text-[10px] uppercase tracking-wider text-faint">
              takeoff
            </span>
          </Link>
          <nav className="flex gap-0.5" aria-label="Primary">
            {NAV.map((n) => (
              <Link
                key={n.to}
                to={n.to}
                className={NAV_LINK}
                activeOptions={{ exact: n.to === "/" }}
              >
                {n.label}
              </Link>
            ))}
            {user.role === "admin" && (
              <Link to="/admin" search={{ tab: undefined }} className={NAV_LINK}>
                Admin
              </Link>
            )}
          </nav>
          <div className="ml-auto flex items-center gap-1">
            <ThemeToggle />
            <AccountMenu user={user} />
          </div>
        </div>
      </header>
      <main
        className={`mx-auto w-full flex-1 px-4 py-5 ${wide ? "" : "max-w-7xl"}`}
      >
        <Outlet />
      </main>
    </div>
  );
}

function SignIn({ denied }: { denied: string | null }) {
  const reason =
    denied === "not_allowed"
      ? "That Google account isn't on the allowed list yet. Ask an admin to add it."
      : denied
        ? `Sign-in failed (${denied}). Try again.`
        : null;
  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-sm rounded-lg border border-rule bg-paper p-8">
        <div className="mb-6">
          <div className="wide font-display text-3xl font-bold leading-none text-ink">
            Scribe
          </div>
          <p className="mt-2 text-sm text-muted">
            Upload the drawings. Get the cabinet breakdown and a quote in
            minutes.
          </p>
        </div>
        {reason && (
          <p className="mb-4 rounded-md border border-bad bg-bad-soft px-3 py-2 text-sm text-bad">
            {reason}
          </p>
        )}
        <a href={`${API_URL}/auth/google`} className="block">
          <Button variant="primary" className="w-full">
            Continue with Google
          </Button>
        </a>
        <p className="mt-4 font-mono text-[11px] text-faint">sauce.ai / scribe</p>
      </div>
    </div>
  );
}

function ThemeToggle() {
  const [pref, setPref] = useState<ThemePref>(() => readThemePref());
  const label =
    pref === "system"
      ? "Theme: system"
      : pref === "light"
        ? "Theme: light"
        : "Theme: dark";
  const glyph = pref === "system" ? "◐" : pref === "light" ? "○" : "●";
  return (
    <button
      type="button"
      aria-label={`${label} — click to change`}
      title={label}
      className="rounded-md px-2 py-1 text-sm text-muted hover:bg-rule-soft hover:text-ink"
      onClick={() => {
        const next = nextThemePref(pref);
        applyTheme(next);
        setPref(next);
      }}
    >
      {glyph}
    </button>
  );
}

function AccountMenu({ user }: { user: Me }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const qc = useQueryClient();

  useEffect(() => {
    if (!open) return;
    function onDoc(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  async function signOut() {
    try {
      await apiSend("POST", "/auth/logout");
    } catch {
      // the local session is cleared regardless
    }
    clearSession();
    qc.clear();
    window.location.assign("/");
  }

  const initial = (user.name ?? user.email).slice(0, 1).toUpperCase();
  const item =
    "block w-full rounded px-2 py-1.5 text-left text-sm text-ink hover:bg-rule-soft";

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="Account"
        className="flex size-7 items-center justify-center rounded-full bg-ink font-mono text-xs font-medium text-paper hover:opacity-90"
        onClick={() => setOpen((o) => !o)}
      >
        {initial}
      </button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 mt-1 w-60 rounded-md border border-rule bg-paper p-1 shadow-md"
        >
          <div className="px-2 py-1.5">
            <div className="truncate text-sm font-medium text-ink">
              {user.name ?? user.email}
            </div>
            <div className="truncate text-xs text-muted">
              {user.email} · {user.role}
            </div>
          </div>
          {user.role === "admin" && (
            <>
              <div className="my-1 border-t border-rule-soft" />
              <div className="px-2 pb-1 pt-1 font-mono text-[10px] uppercase tracking-wider text-faint">
                Operator
              </div>
              <Link to="/dashboard" className={item} onClick={() => setOpen(false)}>
                Pipeline dashboard
              </Link>
              <Link to="/prospects" className={item} onClick={() => setOpen(false)}>
                Prospects
              </Link>
              <Link
                to="/admin"
                search={{ tab: "sources" }}
                className={item}
                onClick={() => setOpen(false)}
              >
                Crawler sources
              </Link>
            </>
          )}
          <div className="my-1 border-t border-rule-soft" />
          <button type="button" role="menuitem" className={item} onClick={signOut}>
            Sign out
          </button>
        </div>
      )}
    </div>
  );
}
