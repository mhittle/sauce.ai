import { useEffect, useRef, type ReactNode } from "react";
import { Button } from "./Button";

export function Dialog({
  open,
  title,
  children,
  onClose,
  actions,
}: {
  open: boolean;
  title: string;
  children: ReactNode;
  onClose: () => void;
  actions?: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (open && !el.open) el.showModal();
    if (!open && el.open) el.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      onClick={(e) => {
        if (e.target === ref.current) onClose();
      }}
      className="w-full max-w-md rounded-lg border border-rule bg-paper p-0 text-ink shadow-lg backdrop:bg-ink/40"
    >
      <div className="p-5">
        <h2 className="wide mb-2 font-display text-lg font-semibold">{title}</h2>
        <div className="text-sm text-muted">{children}</div>
        <div className="mt-5 flex justify-end gap-2">
          {actions ?? <Button onClick={onClose}>Close</Button>}
        </div>
      </div>
    </dialog>
  );
}
