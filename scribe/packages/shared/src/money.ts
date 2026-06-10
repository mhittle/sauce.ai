// Money is integer cents everywhere internally (PRD §7.2).

export function formatUsd(cents: number): string {
  const sign = cents < 0 ? "-" : "";
  const abs = Math.abs(cents);
  const dollars = Math.floor(abs / 100);
  const rem = abs % 100;
  return `${sign}$${dollars.toLocaleString("en-US")}.${rem
    .toString()
    .padStart(2, "0")}`;
}

export function roundCents(value: number): number {
  return Math.round(value);
}
