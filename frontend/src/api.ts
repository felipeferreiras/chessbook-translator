// Cliente da API local (backend/app/api/main.py).

export interface Version {
  version: number;
  kind: "machine" | "edit" | "revert";
  text: string;
  warnings: string[];
  author: string;
  created_at: string;
  provider: string;
  model: string;
}

export interface Segment {
  id: string;
  page: number;
  ordinal: number;
  section: string;
  source: string;
  status: string;
  approved: boolean;
  current: Version | null;
  machine_problems: string[];
  needs_attention: boolean;
}

export interface PageSummary {
  page: number;
  segments: number;
  approved: number;
}

export interface Project {
  id: string;
  name: string;
  pages: number;
  sha256: string;
  original_ok: boolean;
  pages_with_segments: PageSummary[];
  attention: string[];
  approved: number;
  segments: number;
  has_translated_pdf: boolean;
}

export interface GlossaryEntry {
  term: string;
  preferred: string;
  alternatives: string[];
  avoid: string[];
  context: string;
  category: string;
  case_sensitive: boolean;
  check: boolean;
  source: "padrão" | "projeto";
}

export interface EngineEstimate {
  engine: string;
  label: string;
  model: string;
  status: string;
  note: string;
  price_in_per_million: number;
  price_out_per_million: number;
  segments_to_send: number;
  cached: number;
  calls: number;
  input_tokens: number;
  output_tokens: number;
  cost: number;
  cost_low: number;
  cost_high: number;
  minutes: number;
  price_source: string;
  notes: string[];
}

export interface EstimateResponse {
  pages: number;
  segments: number;
  already_translated: number;
  notation_only: number;
  pending: number;
  estimates: EngineEstimate[];
}

export interface Job {
  id: number;
  engine: string;
  model: string;
  pages: string;
  state: string;
  total: number;
  done: number;
  tokens_in: number;
  tokens_out: number;
  cost: number;
  estimate: number | null;
  budget: number;
  counts: Record<string, number>;
  error: string | null;
  author: string;
  created_at: string;
  finished_at: string | null;
}

/** Erro da API com os motivos que o backend devolveu (ex.: notação alterada). */
export class ApiError extends Error {
  constructor(message: string, public problems: string[] = []) {
    super(message);
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    let detail: unknown = res.statusText;
    try {
      detail = (await res.json()).detail;
    } catch {
      /* resposta sem JSON */
    }
    if (detail && typeof detail === "object" && "problems" in detail) {
      const d = detail as { message: string; problems: string[] };
      throw new ApiError(d.message, d.problems);
    }
    throw new ApiError(String(detail));
  }
  return res.json() as Promise<T>;
}

const p = (id: string) => `/projects/${encodeURIComponent(id)}`;

export const api = {
  projects: () => call<{ id: string; name: string; pages: number }[]>("/projects"),
  project: (id: string) => call<Project>(p(id)),
  segments: (id: string, page: number) => call<Segment[]>(`${p(id)}/pages/${page}/segments`),
  history: (id: string, seg: string) => call<Version[]>(`${p(id)}/segments/${seg}/history`),
  edit: (id: string, seg: string, text: string, author: string) =>
    call<Segment>(`${p(id)}/segments/${seg}`, { method: "PUT", body: JSON.stringify({ text, author }) }),
  revert: (id: string, seg: string, version: number, author: string) =>
    call<Segment>(`${p(id)}/segments/${seg}/revert`, { method: "POST", body: JSON.stringify({ version, author }) }),
  approve: (id: string, seg: string, approved: boolean, author: string) =>
    call<Segment>(`${p(id)}/segments/${seg}/approve`, {
      method: "POST",
      body: JSON.stringify({ approved, author }),
    }),
  glossary: (id: string) => call<GlossaryEntry[]>(`${p(id)}/glossary`),
  setGlossary: (id: string, entry: Omit<GlossaryEntry, "source">, author: string) =>
    call<{ ok: boolean }>(`${p(id)}/glossary`, { method: "PUT", body: JSON.stringify({ ...entry, author }) }),
  estimate: (id: string, pages: string) =>
    call<EstimateResponse>(`${p(id)}/estimate`, { method: "POST", body: JSON.stringify({ pages }) }),
  jobs: (id: string) => call<Job[]>(`${p(id)}/jobs`),
  startJob: (id: string, engine: string, pages: string, budget: number, author: string) =>
    call<Job>(`${p(id)}/jobs`, { method: "POST", body: JSON.stringify({ engine, pages, budget, author }) }),
  cancelJob: (id: string, job: number) => call<Job>(`${p(id)}/jobs/${job}/cancel`, { method: "POST" }),
  pageImage: (id: string, page: number, which: "original" | "translated") =>
    `/api${p(id)}/pages/${page}/image?which=${which}`,
};
