import { Link, Outlet } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { API_URL, apiGet, ApiError } from "../api";
import { Button } from "../ui";

interface Me {
  id: string;
  email: string;
  role: string;
  name: string | null;
}

const NAV = [
  { to: "/", label: "Dashboard" },
  { to: "/prospects", label: "Prospect Queue" },
  { to: "/takeoffs", label: "Takeoffs" },
  { to: "/quotes", label: "Quotes" },
  { to: "/admin", label: "Admin" },
];

export function Layout() {
  const me = useQuery({
    queryKey: ["me"],
    queryFn: () => apiGet<Me>("/auth/me"),
    retry: false,
  });

  if (me.isLoading) {
    return <div className="p-8 text-zinc-500">Loading…</div>;
  }

  if (me.isError) {
    const err = me.error;
    const denied =
      err instanceof ApiError &&
      err.status === 401 &&
      new URLSearchParams(window.location.search).get("auth_error");
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="w-96 rounded-lg border border-zinc-200 bg-white p-8 text-center shadow-sm">
          <h1 className="mb-1 text-2xl font-bold">Scribe</h1>
          <p className="mb-6 text-sm text-zinc-500">
            CabinetNow takeoff-to-quote pipeline
          </p>
          {denied && (
            <p className="mb-4 text-sm text-red-600">
              Sign-in failed ({denied}). Your email must be on the allowed
              list — ask an admin.
            </p>
          )}
          <a href={`${API_URL}/auth/google`}>
            <Button variant="primary" className="w-full">
              Sign in with Google
            </Button>
          </a>
        </div>
      </div>
    );
  }

  const user = me.data!;
  return (
    <div className="min-h-screen">
      <header className="border-b border-zinc-200 bg-white">
        <div className="mx-auto flex max-w-7xl items-center gap-6 px-4 py-3">
          <span className="text-lg font-bold">
            Scribe
            <span className="ml-2 text-xs font-normal text-zinc-400">
              sauce.ai
            </span>
          </span>
          <nav className="flex gap-1">
            {NAV.filter((n) => n.to !== "/admin" || user.role === "admin").map(
              (n) => (
                <Link
                  key={n.to}
                  to={n.to}
                  className="rounded-md px-3 py-1.5 text-sm text-zinc-600 hover:bg-zinc-100 [&.active]:bg-zinc-900 [&.active]:text-white"
                  activeOptions={{ exact: n.to === "/" }}
                >
                  {n.label}
                </Link>
              )
            )}
          </nav>
          <span className="ml-auto text-sm text-zinc-500">
            {user.email} · {user.role}
          </span>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-6">
        <Outlet />
      </main>
    </div>
  );
}
