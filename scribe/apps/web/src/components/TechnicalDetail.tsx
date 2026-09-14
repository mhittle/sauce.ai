import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../api";

// The raw pipeline text behind a customer-facing message, shown only to
// admins (the developer reading a customer's screen). Same ["me"] query as
// the shell, so it costs nothing extra.
export function useIsAdmin(): boolean {
  const me = useQuery({
    queryKey: ["me"],
    queryFn: () => apiGet<{ role: string }>("/auth/me"),
    staleTime: 10 * 60 * 1000,
  });
  return me.data?.role === "admin";
}

export function TechnicalDetail({
  details,
  className = "",
}: {
  details: string | string[];
  className?: string;
}) {
  const isAdmin = useIsAdmin();
  const list = Array.isArray(details) ? details : [details];
  if (!isAdmin || list.length === 0) return null;
  return (
    <details className={`mt-1 text-xs text-muted ${className}`}>
      <summary className="cursor-pointer select-none text-faint">Technical details (admin)</summary>
      {list.map((d, i) => (
        <pre key={i} className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap break-all rounded bg-rule-soft/60 p-2 font-mono text-[11px] leading-snug text-muted">
          {d}
        </pre>
      ))}
    </details>
  );
}
