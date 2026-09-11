import type { ReactNode } from "react";
import { labelFor, toneFor, type Tone } from "../../labels";

// Old tone names stay accepted so existing call sites keep compiling.
type LegacyTone = "zinc" | "green" | "amber" | "red";
export type BadgeTone = Tone | LegacyTone;

const TONE: Record<Tone, string> = {
  neutral: "bg-rule-soft text-muted",
  blue: "bg-blue-soft text-blue",
  good: "bg-good-soft text-good",
  warn: "bg-warn-soft text-warn",
  bad: "bg-bad-soft text-bad",
};

function normalize(t: BadgeTone): Tone {
  switch (t) {
    case "zinc":
      return "neutral";
    case "green":
      return "good";
    case "amber":
      return "warn";
    case "red":
      return "bad";
    default:
      return t;
  }
}

export function Badge({
  children,
  tone = "neutral",
  className = "",
}: {
  children: ReactNode;
  tone?: BadgeTone;
  className?: string;
}) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${TONE[normalize(tone)]} ${className}`}
    >
      {children}
    </span>
  );
}

// A status enum rendered with its human label and semantic tone.
export function StatusPill({
  status,
  className = "",
}: {
  status: string;
  className?: string;
}) {
  return (
    <Badge tone={toneFor(status)} className={className}>
      {labelFor(status)}
    </Badge>
  );
}
