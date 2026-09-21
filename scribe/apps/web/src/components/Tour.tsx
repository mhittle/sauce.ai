import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiSend } from "../api";
import { Coachmark } from "./ui/Coachmark";

// First-run walkthrough (accounts-plan.md §2): one short sequence per
// screen, shown until the user finishes or skips it; progress lives on
// users.onboarding so it follows them across devices. "Show me around" in
// the account menu clears it.

export type Screen = "jobs" | "pages" | "mark" | "review" | "quote";

export interface TourStep {
  anchor: string;
  title: string;
  body: string;
}

interface Onboarding {
  seen?: Partial<Record<Screen, boolean>>;
  dismissed?: boolean;
}

export const TOURS: Record<Screen, TourStep[]> = {
  jobs: [
    {
      anchor: "jobs-upload",
      title: "Start with a plan set",
      body: "Drop a PDF here (an image or a cabinet spreadsheet works too). Scribe reads the drawings and builds the cabinet list.",
    },
    {
      anchor: "jobs-sample",
      title: "A finished example",
      body: "We read a sample job for you. Open it to see what a takeoff looks like before you upload your own.",
    },
  ],
  pages: [
    {
      anchor: "pages-continue",
      title: "Pick the sheets",
      body: "Tick the pages with cabinets — floor plans and elevations. Skip covers, schedules and details. Then find the drawings.",
    },
  ],
  mark: [
    {
      anchor: "mark-actions",
      title: "Mark, find, build",
      body: "Draw a box around each cabinet drawing on the page. Find lists the cabinets in each box; Build measures and prices them.",
    },
  ],
  review: [
    {
      anchor: "review-accept",
      title: "Check the draft",
      body: "Every line is an AI draft. Fix a wrong size by typing over it; accept the confident ones in one click.",
    },
    {
      anchor: "review-bar",
      title: "The estimate follows your edits",
      body: "The number updates as you correct lines. When it looks right, build the quote.",
    },
  ],
  quote: [
    {
      anchor: "quote-tiers",
      title: "Pick a price level",
      body: "Low, upgraded or premium — the totals and the PDF follow your pick.",
    },
    {
      anchor: "quote-send",
      title: "Send it",
      body: "Download the PDF or send the quote. Sending stays locked until freight and every price are verified.",
    },
  ],
};

export function Tour({ screen, ready = true }: { screen: Screen; ready?: boolean }) {
  const qc = useQueryClient();
  const me = useQuery({
    queryKey: ["me"],
    queryFn: () => apiGet<{ onboarding?: Onboarding }>("/auth/me"),
    retry: false,
  });
  const [i, setI] = useState(0);
  const save = useMutation({
    mutationFn: (onboarding: Onboarding) => apiSend("PATCH", "/me", { onboarding }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["me"] }),
  });

  const onboarding = me.data?.onboarding ?? {};
  const active = ready && me.data !== undefined && !onboarding.dismissed && !onboarding.seen?.[screen];

  // Steps whose anchor is not on this page (no sample job, approved takeoff) are skipped.
  const steps = TOURS[screen].filter((s) => document.querySelector(`[data-tour="${s.anchor}"]`));
  useEffect(() => setI(0), [screen]);

  if (!active || steps.length === 0) return null;
  const step = steps[Math.min(i, steps.length - 1)];
  const last = i >= steps.length - 1;
  const finish = () => save.mutate({ ...onboarding, seen: { ...onboarding.seen, [screen]: true } });
  return (
    <Coachmark
      anchor={step.anchor}
      title={step.title}
      step={Math.min(i, steps.length - 1) + 1}
      total={steps.length}
      last={last}
      onNext={() => (last ? finish() : setI(i + 1))}
      onSkip={() => save.mutate({ ...onboarding, dismissed: true })}
    >
      {step.body}
    </Coachmark>
  );
}
