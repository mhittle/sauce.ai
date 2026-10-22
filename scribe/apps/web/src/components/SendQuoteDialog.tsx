import { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { apiSend } from "../api";
import { quoteEmailDefaults, quoteSendErrorText, SEND_QUOTE_HINT } from "../messages";
import { Button, Dialog, errorMessage, Field, Input, Textarea, useToast } from "../ui";

// Send quote (owner, 2026-10-22): the server emails the quote with its PDF
// attached — a mailto link can't carry an attachment. Replies go to the
// sender, who gets a copy unless they untick it.
export function SendQuoteDialog({
  open,
  quoteId,
  quoteName,
  senderEmail,
  onClose,
  onSent,
}: {
  open: boolean;
  quoteId: string;
  quoteName: string;
  senderEmail: string | null;
  onClose: () => void;
  onSent: (to: string[]) => void;
}) {
  const toast = useToast();
  const defaults = quoteEmailDefaults(quoteName);
  const [to, setTo] = useState("");
  const [subject, setSubject] = useState(defaults.subject);
  const [message, setMessage] = useState(defaults.message);
  const [copyMe, setCopyMe] = useState(true);
  useEffect(() => {
    if (open) {
      setSubject(defaults.subject);
      setMessage(defaults.message);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, quoteName]);

  const recipients = to
    .split(/[,;\s]+/)
    .map((s) => s.trim())
    .filter(Boolean);
  const valid = recipients.length > 0 && recipients.every((r) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(r));

  const send = useMutation({
    mutationFn: () =>
      apiSend<{ sent: boolean; to: string[] }>("POST", `/quotes/${quoteId}/send`, {
        to: recipients,
        subject,
        message,
        copy_me: copyMe,
      }),
    onSuccess: (r) => {
      setTo("");
      onSent(r.to);
    },
    onError: (e) => toast.error("Quote not sent", quoteSendErrorText(e) ?? errorMessage(e)),
  });

  return (
    <Dialog
      open={open}
      title="Send quote"
      onClose={onClose}
      actions={
        <>
          <Button variant="quiet" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" disabled={!valid || !subject.trim()} loading={send.isPending} onClick={() => send.mutate()}>
            Send with PDF attached
          </Button>
        </>
      }
    >
      <div className="space-y-3 text-ink">
        <Field label="To" hint="Separate several addresses with commas">
          <Input type="email" multiple value={to} onChange={(e) => setTo(e.target.value)} placeholder="customer@company.com" autoFocus />
        </Field>
        <Field label="Subject">
          <Input value={subject} onChange={(e) => setSubject(e.target.value)} />
        </Field>
        <Field label="Message">
          <Textarea rows={6} value={message} onChange={(e) => setMessage(e.target.value)} />
        </Field>
        {senderEmail && (
          <label className="flex items-center gap-2 text-xs text-muted">
            <input type="checkbox" checked={copyMe} onChange={(e) => setCopyMe(e.target.checked)} />
            Send me a copy ({senderEmail})
          </label>
        )}
        <p className="text-xs text-faint">{SEND_QUOTE_HINT}</p>
      </div>
    </Dialog>
  );
}
