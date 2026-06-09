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

export interface Permit {
  permit_id: string;
  permit_type: string | null;
  work_description: string | null;
  valuation: number | null;
  status: string | null;
  issue_date: string | null;
  expiration_date: string | null;
  contractor_name: string | null;
  source_url: string | null;
}

export interface WhyRow {
  signal: string;
  value: unknown;
  contribution: number;
}

export interface ProjectDetail extends Project {
  permits: Permit[];
  signals: Record<string, unknown>;
  why_flagged: WhyRow[];
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

export interface ProjectQuery {
  signals: string[];
  q?: string;
  sort: string;
  dir: "asc" | "desc";
  limit: number;
  offset: number;
}

export async function fetchProjects(p: ProjectQuery): Promise<ProjectList> {
  const qs = new URLSearchParams();
  p.signals.forEach((s) => qs.append("signal", s));
  if (p.q) qs.set("q", p.q);
  qs.set("sort", p.sort);
  qs.set("dir", p.dir);
  qs.set("limit", String(p.limit));
  qs.set("offset", String(p.offset));
  const res = await fetch(`${BASE}/api/projects?${qs.toString()}`);
  if (!res.ok) throw new Error(`projects ${res.status}`);
  return res.json();
}

export async function fetchProject(id: number): Promise<ProjectDetail> {
  const res = await fetch(`${BASE}/api/projects/${id}`);
  if (!res.ok) throw new Error(`project ${id}: ${res.status}`);
  return res.json();
}

export async function fetchFacets(): Promise<SignalDef[]> {
  const res = await fetch(`${BASE}/api/signals?facets_only=true`);
  if (!res.ok) throw new Error(`signals ${res.status}`);
  return res.json();
}
