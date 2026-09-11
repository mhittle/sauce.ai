import { useRef, useState, type DragEvent } from "react";
import { Button } from "./ui";

const ACCEPT = ".pdf,.xlsx,.xls,.csv,.png,.jpg,.jpeg";
const ACCEPT_LABEL = "PDF plan sets · XLSX / CSV schedules · PNG / JPG photos";
const MAX_MB = 200;

export function UploadZone({
  onFile,
  busy,
  compact = false,
}: {
  onFile: (file: File) => void;
  busy: boolean;
  compact?: boolean;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  function accept(file: File | undefined) {
    if (!file) return;
    const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
    if (!ACCEPT.includes(`.${ext}`)) {
      setProblem(`.${ext} files aren't supported. ${ACCEPT_LABEL}.`);
      return;
    }
    if (file.size > MAX_MB * 1024 * 1024) {
      setProblem(`That file is over ${MAX_MB} MB. Split the set or compress the PDF.`);
      return;
    }
    setProblem(null);
    onFile(file);
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setOver(false);
    accept(e.dataTransfer.files?.[0]);
  }

  return (
    <div>
      <div
        role="button"
        tabIndex={0}
        aria-label="Upload drawings"
        onClick={() => inputRef.current?.click()}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            inputRef.current?.click();
          }
        }}
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={onDrop}
        className={`flex cursor-pointer items-center gap-4 rounded-lg border-2 border-dashed px-5 transition-colors ${
          compact ? "py-3" : "py-6"
        } ${
          over
            ? "border-accent bg-accent-soft"
            : "border-rule bg-paper hover:border-muted"
        }`}
      >
        <div className="min-w-0 flex-1">
          <div className="wide font-display text-base font-semibold text-ink">
            {busy ? "Uploading…" : "Drop a plan set here, or choose a file"}
          </div>
          <div className="mt-0.5 text-xs text-muted">{ACCEPT_LABEL}</div>
        </div>
        <Button
          variant="primary"
          loading={busy}
          onClick={(e) => {
            e.stopPropagation();
            inputRef.current?.click();
          }}
        >
          New job
        </Button>
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPT}
          className="hidden"
          onChange={(e) => {
            accept(e.target.files?.[0]);
            e.target.value = "";
          }}
        />
      </div>
      {problem && (
        <p role="alert" className="mt-2 text-sm text-bad">
          {problem}
        </p>
      )}
    </div>
  );
}
