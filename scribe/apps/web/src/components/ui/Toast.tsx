import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

type ToastTone = "neutral" | "good" | "bad";

interface ToastItem {
  id: number;
  title: string;
  description?: string;
  tone: ToastTone;
}

interface ToastApi {
  push: (t: Omit<ToastItem, "id">) => void;
  success: (title: string, description?: string) => void;
  error: (title: string, description?: string) => void;
  info: (title: string, description?: string) => void;
}

const ToastContext = createContext<ToastApi | null>(null);
const TTL_MS = 5000;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const seq = useRef(0);

  const dismiss = useCallback((id: number) => {
    setItems((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const push = useCallback(
    (t: Omit<ToastItem, "id">) => {
      const id = ++seq.current;
      setItems((prev) => [...prev.slice(-3), { ...t, id }]);
      window.setTimeout(() => dismiss(id), TTL_MS);
    },
    [dismiss]
  );

  const api = useMemo<ToastApi>(
    () => ({
      push,
      success: (title, description) => push({ title, description, tone: "good" }),
      error: (title, description) => push({ title, description, tone: "bad" }),
      info: (title, description) => push({ title, description, tone: "neutral" }),
    }),
    [push]
  );

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div
        aria-live="polite"
        aria-relevant="additions"
        className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-80 max-w-[calc(100vw-2rem)] flex-col gap-2"
      >
        {items.map((t) => (
          <div
            key={t.id}
            role="status"
            className={`pointer-events-auto rounded-md border bg-paper px-3 py-2 text-sm shadow-md ${
              t.tone === "bad"
                ? "border-bad border-l-4"
                : t.tone === "good"
                  ? "border-good border-l-4"
                  : "border-rule border-l-4 border-l-blue"
            }`}
          >
            <div className="flex items-start gap-2">
              <div className="min-w-0 flex-1">
                <div className="font-medium text-ink">{t.title}</div>
                {t.description && (
                  <div className="mt-0.5 break-words text-xs text-muted">
                    {t.description}
                  </div>
                )}
              </div>
              <button
                aria-label="Dismiss"
                className="-mr-1 -mt-0.5 rounded px-1 text-muted hover:bg-rule-soft hover:text-ink"
                onClick={() => dismiss(t.id)}
              >
                ×
              </button>
            </div>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used inside <ToastProvider>");
  return ctx;
}

// Turn any thrown value into a readable toast line.
export function errorMessage(err: unknown): string {
  if (err instanceof Error) return err.message;
  return String(err);
}
