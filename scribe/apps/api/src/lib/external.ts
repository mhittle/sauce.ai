import { z } from "zod";

// External takeoffs (migrations/0022): a trusted service caller (CabinetHub)
// tags an upload with where it came from and where to push the approved
// lines. Carried on the query string of POST /takeoffs because multipart text
// fields are only visible when they precede the file part.
export const ExternalLinkQuery = z
  .object({
    external_source: z
      .string()
      .min(1)
      .max(40)
      .regex(/^[a-z0-9_-]+$/)
      .optional(),
    external_ref: z.string().min(1).max(200).optional(),
    callback_url: z.string().url().max(2000).optional(),
  })
  .refine((q) => !q.callback_url || (q.external_source && q.external_ref), {
    message: "callback_url needs external_source and external_ref",
  });

export interface ExternalLink {
  externalSource: string | null;
  externalRef: string | null;
  callbackUrl: string | null;
}

// A callback is only honoured for the service user: a signed-in user must
// not be able to point Scribe's worker at an arbitrary URL.
export function parseExternalLink(
  query: unknown,
  opts: { isService: boolean; production: boolean }
): ExternalLink | { error: string } {
  const parsed = ExternalLinkQuery.safeParse(query ?? {});
  if (!parsed.success) {
    return { error: parsed.error.issues[0]?.message ?? "invalid external link" };
  }
  const q = parsed.data;
  if (q.callback_url) {
    if (!opts.isService) return { error: "callback_url requires service auth" };
    if (opts.production && !q.callback_url.startsWith("https://")) {
      return { error: "callback_url must be https" };
    }
  }
  return {
    externalSource: q.external_source ?? null,
    externalRef: q.external_ref ?? null,
    callbackUrl: q.callback_url ?? null,
  };
}
