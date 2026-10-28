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
  source_flags: string[];
  needs_attention: boolean;
  kept_as_image: boolean;
  source_extracted: string | null;
  discarded: boolean;
}

export interface Reprocess {
  kind?: "sync" | "figurines" | "symbols" | "pieces";
  state: "none" | "running" | "done" | "failed" | "interrupted";
  progress?: { stage: string; done: number; total: number };
  result?: Record<string, number> | null;
  error?: string | null;
}

export interface DiagramInfo {
  id: string;
  page: number;
  index: number;
  placement: string | null;
  read: string | null;
  side_to_move: "w" | "b" | null;
  issues: string[];
  confirmed: boolean;
  needs_attention: boolean;
}

export interface FigurineGroup {
  id: number;
  count: number;
  auto: string;
  score?: number;
  margin?: number;
  ocr?: string[];
  read?: string[];
  black?: boolean;
  image: string;
}

export interface FigurineInfo {
  available: boolean;
  reason: string;
  labels: Record<string, string>;
  groups: FigurineGroup[];
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
  spent: number;
  spend_limit: number | null;
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
  mode: string;
  already_translated: number;
  notation_only: number;
  pending: number;
  selected: number;
  skipped: Record<string, number>;
  spent: number;
  spend_limit: number | null;
  remaining: number | null;
  estimates: EngineEstimate[];
}

/** O que traduzir: páginas e modo (ver ``MODES`` no backend). */
export interface Selection {
  pages: string;
  mode: string;
  segment_ids?: string[];
  fresh?: boolean;
  resume_of?: number;
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
  mode: string;
  segment_ids: string[] | null;
  fresh: boolean;
  heartbeat_at: string | null;
  resumed_from: number | null;
}

export interface QualityPage {
  page: number;
  ok: boolean;
  blocks: number;
  reduced: number;
  min_scale: number;
  issues: Record<string, (string | number)[]>;
}

export interface Quality {
  summary: Record<string, unknown>;
  pages_ok: number;
  pages_total: number;
  pages: QualityPage[];
  assembled_at: string;
}

export interface Assembly {
  id: number;
  state: "running" | "done" | "failed" | "cancelled" | "interrupted";
  author: string;
  created_at: string;
  finished_at: string | null;
  error: string | null;
  summary: { blocks: number; blocks_placed: number; chunks: number; chunks_reused: number; pages_ok: number;
             pages: number } | null;
  progress: { pages_total: number; pages_done: number; chunks_total: number; chunks_done: number;
              chunks_reused: number } | null;
  outdated: boolean;
}

export interface Audit {
  at: string;
  ok: boolean;
  complete: boolean;
  original_ok: boolean;
  extraction?: { ok: boolean; ocr_outdated?: boolean; segments_project: number; segments_extraction: number; missing_in_project: string[];
                 only_in_project: string[]; source_differs: string[] };
  segments: { total: number; by_state: Record<string, number>; unfinished: string[]; unfinished_count: number;
              notation_broken: { id: string; problems: string[] }[]; markers_left: string[] };
  assembly: null | { ok: boolean; outdated: boolean; pages_assembled: number; pages_in_pdf: number; pages_ok: number;
                     blocks: number; blocks_placed: number; missing_notation: number; diagrams_changed: number;
                     original_unchanged_during_assembly: boolean };
}

export interface Settings {
  storage: string;
  privacy_mode: string;
  remote_allowed: boolean;
  pollinations_key: boolean;
  workers: number;
  tesseract: boolean;
  max_upload_mb: number;
  max_pages: number;
}

export interface Creation {
  id: string;
  name: string;
  pages: number;
  ocr: string;
  state: "running" | "done" | "failed" | "interrupted";
  started_at: string;
  finished_at: string | null;
  error: string | null;
  progress?: { stage: string; done: number; total: number };
}

/** Erro da API com os motivos que o backend devolveu (ex.: notação alterada). */
export class ApiError extends Error {
  constructor(message: string, public problems: string[] = []) {
    super(message);
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const form = init?.body instanceof FormData;  // envio de arquivo: o navegador define o Content-Type
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: form ? (init?.headers ?? {}) : { "Content-Type": "application/json", ...(init?.headers ?? {}) },
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
  settings: () => call<Settings>("/settings"),
  createProject: (file: File, name: string, projectId: string, ocr: string) => {
    const body = new FormData();
    body.append("file", file);
    body.append("name", name);
    body.append("project_id", projectId);
    body.append("ocr", ocr);
    return call<Creation>("/projects", { method: "POST", body });
  },
  creations: () => call<Creation[]>("/creations"),
  restoreBackup: (file: File, projectId: string) => {
    const body = new FormData();
    body.append("file", file);
    body.append("project_id", projectId);
    return call<{ id: string; name: string }>("/backups/restore", { method: "POST", body });
  },
  sync: (id: string, author: string) =>
    call<Reprocess>(`${p(id)}/sync`, { method: "POST", body: JSON.stringify({ author }) }),
  reprocess: (id: string) => call<Reprocess>(`${p(id)}/reprocess`),
  figurines: (id: string) => call<FigurineInfo>(`${p(id)}/figurines`),
  symbols: (id: string) => call<FigurineInfo>(`${p(id)}/symbols`),
  pieces: (id: string) => call<FigurineInfo>(`${p(id)}/pieces`),
  setPieces: (id: string, labels: Record<string, string>, author: string) =>
    call<Reprocess>(`${p(id)}/pieces`, { method: "PUT", body: JSON.stringify({ labels, author }) }),
  diagrams: (id: string, page: number) => call<DiagramInfo[]>(`${p(id)}/pages/${page}/diagrams`),
  setDiagram: (id: string, page: number, index: number, placement: string | null, side: string | null,
               author: string) =>
    call<DiagramInfo>(`${p(id)}/pages/${page}/diagrams/${index}`, {
      method: "PUT", body: JSON.stringify({ placement, side, confirmed: true, author }),
    }),
  diagramImage: (id: string, page: number, index: number) => `/api${p(id)}/pages/${page}/diagrams/${index}/image`,
  setSymbols: (id: string, labels: Record<string, string>, author: string) =>
    call<Reprocess>(`${p(id)}/symbols`, { method: "PUT", body: JSON.stringify({ labels, author }) }),
  setFigurines: (id: string, labels: Record<string, string>, author: string) =>
    call<Reprocess>(`${p(id)}/figurines`, { method: "PUT", body: JSON.stringify({ labels, author }) }),
  backupUrl: (id: string) => `/api${p(id)}/backup`,
  downloadUrl: (id: string) => `/api${p(id)}/download`,
  projects: () => call<{ id: string; name: string; pages: number }[]>("/projects"),
  project: (id: string) => call<Project>(p(id)),
  segments: (id: string, page: number) => call<Segment[]>(`${p(id)}/pages/${page}/segments`),
  history: (id: string, seg: string) => call<Version[]>(`${p(id)}/segments/${seg}/history`),
  edit: (id: string, seg: string, text: string, author: string) =>
    call<Segment>(`${p(id)}/segments/${seg}`, { method: "PUT", body: JSON.stringify({ text, author }) }),
  revert: (id: string, seg: string, version: number, author: string) =>
    call<Segment>(`${p(id)}/segments/${seg}/revert`, { method: "POST", body: JSON.stringify({ version, author }) }),
  editSource: (id: string, seg: string, text: string, author: string) =>
    call<Segment>(`${p(id)}/segments/${seg}/source`, { method: "PUT", body: JSON.stringify({ text, author }) }),
  discard: (id: string, seg: string, discarded: boolean, author: string) =>
    call<Segment>(`${p(id)}/segments/${seg}/discard`, {
      method: "POST",
      body: JSON.stringify({ discarded, author }),
    }),
  approve: (id: string, seg: string, approved: boolean, author: string) =>
    call<Segment>(`${p(id)}/segments/${seg}/approve`, {
      method: "POST",
      body: JSON.stringify({ approved, author }),
    }),
  approvePage: (id: string, page: number, author: string) =>
    call<{ approved: string[]; skipped: string[] }>(`${p(id)}/pages/${page}/approve`, {
      method: "POST",
      body: JSON.stringify({ author }),
    }),
  glossary: (id: string) => call<GlossaryEntry[]>(`${p(id)}/glossary`),
  setGlossary: (id: string, entry: Omit<GlossaryEntry, "source">, author: string) =>
    call<{ ok: boolean }>(`${p(id)}/glossary`, { method: "PUT", body: JSON.stringify({ ...entry, author }) }),
  modes: () => call<Record<string, string>>("/modes"),
  estimate: (id: string, sel: Selection) =>
    call<EstimateResponse>(`${p(id)}/estimate`, { method: "POST", body: JSON.stringify(sel) }),
  jobs: (id: string) => call<Job[]>(`${p(id)}/jobs`),
  startJob: (id: string, engine: string, sel: Selection, budget: number, author: string) =>
    call<Job>(`${p(id)}/jobs`, { method: "POST", body: JSON.stringify({ ...sel, engine, budget, author }) }),
  resumeJob: (id: string, job: number, author: string, budget?: number) =>
    call<Job>(`${p(id)}/jobs/${job}/resume`, { method: "POST", body: JSON.stringify({ author, budget }) }),
  setLimit: (id: string, spend_limit: number | null, author: string) =>
    call<{ spent: number; spend_limit: number | null }>(`${p(id)}/limits`, {
      method: "PUT",
      body: JSON.stringify({ spend_limit, author }),
    }),
  cancelJob: (id: string, job: number) => call<Job>(`${p(id)}/jobs/${job}/cancel`, { method: "POST" }),
  quality: (id: string) => call<Quality>(`${p(id)}/quality`),
  audit: (id: string) => call<Audit | null>(`${p(id)}/audit`),
  runAudit: (id: string) => call<Audit>(`${p(id)}/audit`, { method: "POST" }),
  assembly: (id: string) => call<Assembly | null>(`${p(id)}/assembly`),
  assemble: (id: string, author: string) =>
    call<Assembly>(`${p(id)}/assembly`, { method: "POST", body: JSON.stringify({ author }) }),
  cancelAssembly: (id: string) => call<Assembly | null>(`${p(id)}/assembly/cancel`, { method: "POST" }),
  pageImage: (id: string, page: number, which: "original" | "translated") =>
    `/api${p(id)}/pages/${page}/image?which=${which}`,
};
