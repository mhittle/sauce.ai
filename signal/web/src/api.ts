export interface Project {
  id: number;
  primary_address: string | null;
  jurisdiction: string | null;
  category: string | null;
  value_tier: string | null;
  lead_score: number;
  status: string;
  latitude: number | null;
  longitude: number | null;
  crm_id: string | null;
  updated_at: string | null;
}

export interface ProjectList {
  total: number;
  items: Project[];
}

export interface SignalDef {
  id: string;
  label: string;
  tier: string;
  datatype: string;
  is_facet: boolean;
}

const BASE = import.meta.env.VITE_API_BASE ?? "";

export async function fetchProjects(params: {
  signals: string[];
  min_score?: number;
  q?: string;
}): Promise<ProjectList> {
  const qs = new URLSearchParams();
  params.signals.forEach((s) => qs.append("signal", s));
  if (params.min_score) qs.set("min_score", String(params.min_score));
  if (params.q) qs.set("q", params.q);
  const res = await fetch(`${BASE}/api/projects?${qs.toString()}`);
  if (!res.ok) throw new Error(`projects ${res.status}`);
  return res.json();
}

export async function fetchFacets(): Promise<SignalDef[]> {
  const res = await fetch(`${BASE}/api/signals?facets_only=true`);
  if (!res.ok) throw new Error(`signals ${res.status}`);
  return res.json();
}
