// Compatibility shim: pages import primitives from "../ui". The library now
// lives in components/ui; new code should import from there.
export * from "./components/ui";
import { toneFor, type Tone } from "./labels";

// Legacy helper kept for call sites that pair it with <Badge tone=…>.
export function statusTone(status: string): Tone {
  return toneFor(status);
}
