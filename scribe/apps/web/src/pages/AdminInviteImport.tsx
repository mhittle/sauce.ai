import { useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { INVITE_CSV_TEMPLATE, parseInviteCsv, type InviteCsvResult } from "@scribe/shared";
import { apiSend } from "../api";
import {
  importErrorsLine,
  importPreviewLine,
  importResultLine,
  INVITE_IMPORT_HINT,
  INVITE_STATUS_LABEL,
} from "../messages";
import { Button, Card, errorMessage, SectionLabel, useToast } from "../ui";

// Admin › Users › Import CSV: invite many people at once. The file is checked
// here for a preview, then sent whole; the API parses it again and reports
// every row (sent, created without email, skipped and why).

interface ImportResult {
  emailConfigured: boolean;
  results: { line: number; email: string; status: "sent" | "created" | "skipped"; reason?: string; link?: string }[];
  errors: { line: number; message: string }[];
}

function downloadTemplate() {
  const url = URL.createObjectURL(new Blob([INVITE_CSV_TEMPLATE], { type: "text/csv" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = "scribe-invites-template.csv";
  a.click();
  URL.revokeObjectURL(url);
}

export function InviteImport() {
  const qc = useQueryClient();
  const toast = useToast();
  const fileRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<{ name: string; text: string; parsed: InviteCsvResult } | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);

  const send = useMutation({
    mutationFn: () => apiSend<ImportResult>("POST", "/admin/invites/import", { csv: file!.text }),
    onSuccess: (r) => {
      setResult(r);
      setFile(null);
      qc.invalidateQueries({ queryKey: ["invites"] });
      toast.success(importResultLine(r.results));
    },
    onError: (e) => toast.error("Invites not imported", errorMessage(e)),
  });

  const onPick = async (f: File | undefined) => {
    if (!f) return;
    const text = await f.text();
    setResult(null);
    setFile({ name: f.name, text, parsed: parseInviteCsv(text) });
    if (fileRef.current) fileRef.current.value = "";
  };

  return (
    <Card>
      <div className="flex flex-wrap items-center gap-2">
        <SectionLabel>Invite from a CSV</SectionLabel>
        <div className="ml-auto flex items-center gap-2">
          <Button size="sm" variant="quiet" onClick={downloadTemplate}>
            Download template
          </Button>
          <Button size="sm" onClick={() => fileRef.current?.click()}>
            Import CSV
          </Button>
          <input
            ref={fileRef}
            type="file"
            accept=".csv,text/csv"
            className="hidden"
            aria-label="CSV file of people to invite"
            onChange={(e) => onPick(e.target.files?.[0])}
          />
        </div>
      </div>
      <p className="text-xs text-muted">{INVITE_IMPORT_HINT}</p>

      {file && (
        <div className="mt-3 space-y-2 rounded-md border border-rule bg-rule-soft px-3 py-2 text-sm">
          <div>
            <span className="font-medium">{file.name}</span> — {importPreviewLine(file.parsed.rows.length)}
          </div>
          {file.parsed.rows.length > 0 && (
            <ul className="max-h-40 overflow-auto text-xs text-muted">
              {file.parsed.rows.map((r) => (
                <li key={r.line}>
                  {r.email}
                  {r.name ? ` · ${r.name}` : ""}
                  {r.company ? ` · ${r.company}` : ""}
                  {r.pagesIncluded ? ` · ${r.pagesIncluded} pages` : ""}
                </li>
              ))}
            </ul>
          )}
          {file.parsed.errors.length > 0 && (
            <div className="text-xs text-bad">
              {importErrorsLine(file.parsed.errors.length)}
              <ul>
                {file.parsed.errors.map((e) => (
                  <li key={e.line}>
                    Row {e.line}: {e.message}
                  </li>
                ))}
              </ul>
            </div>
          )}
          <div className="flex gap-2">
            <Button
              size="sm"
              variant="primary"
              disabled={file.parsed.rows.length === 0}
              loading={send.isPending}
              onClick={() => send.mutate()}
            >
              Send {file.parsed.rows.length} invite{file.parsed.rows.length === 1 ? "" : "s"}
            </Button>
            <Button size="sm" variant="quiet" onClick={() => setFile(null)}>
              Cancel
            </Button>
          </div>
        </div>
      )}

      {result && (
        <table className="mt-3 w-full text-xs">
          <thead>
            <tr className="border-b border-rule text-left font-mono text-[10px] uppercase tracking-wider text-muted">
              <th className="py-1 pr-2">Row</th>
              <th className="py-1 pr-2">Email</th>
              <th className="py-1 pr-2">Result</th>
              <th className="py-1" />
            </tr>
          </thead>
          <tbody>
            {result.results.map((r) => (
              <tr key={r.line} className="border-b border-rule-soft">
                <td className="py-1 pr-2 font-mono text-muted">{r.line}</td>
                <td className="py-1 pr-2">{r.email}</td>
                <td className={`py-1 pr-2 ${r.status === "skipped" ? "text-warn" : ""}`}>
                  {INVITE_STATUS_LABEL[r.status]}
                  {r.reason ? ` — ${r.reason}` : ""}
                </td>
                <td className="py-1 text-right">
                  {r.link && r.status === "created" && (
                    <Button
                      size="sm"
                      variant="quiet"
                      onClick={() =>
                        navigator.clipboard.writeText(r.link!).then(
                          () => toast.success("Link copied"),
                          () => toast.error("Copy failed", "Select the link and copy it by hand")
                        )
                      }
                    >
                      Copy link
                    </Button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}
