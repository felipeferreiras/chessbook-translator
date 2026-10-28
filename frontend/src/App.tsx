import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, GlossaryEntry, Project, Segment, Selection, Settings, Version } from "./api";
import ProjectView from "./ProjectView";
import QualityView from "./QualityView";
import TranslateView from "./TranslateView";

// Preferências locais do revisor; o navegador pode recusar o armazenamento.
function loadPref(key: string, fallback: string): string {
  try {
    return localStorage.getItem(key) ?? fallback;
  } catch {
    return fallback;
  }
}
function savePref(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* sem armazenamento: só não lembra */
  }
}

const KIND: Record<string, string> = { machine: "máquina", edit: "editado", revert: "revertido" };
const STATUS: Record<string, string> = {
  translated: "traduzido",
  cached: "traduzido",
  not_needed: "só notação",
  needs_review: "recusado pela proteção",
  blocked: "bloqueado: lances desenhados (traduzir à mão)",
  failed: "falhou",
};

export default function App() {
  const [projects, setProjects] = useState<{ id: string; name: string }[]>([]);
  const [projectId, setProjectId] = useState(() => loadPref("project", ""));
  const [project, setProject] = useState<Project | null>(null);
  const [page, setPage] = useState<number | null>(null);
  const [tab, setTab] = useState<"project" | "pages" | "translate" | "quality" | "glossary">("pages");
  const [settings, setSettings] = useState<Settings | null>(null);
  const [author, setAuthor] = useState(() => loadPref("author", ""));
  const [onlyAttention, setOnlyAttention] = useState(false);
  const [retranslate, setRetranslate] = useState<Selection | null>(null);
  const [error, setError] = useState("");

  const loadProjects = useCallback((open?: string) => {
    api.projects().then((list) => {
      setProjects(list);
      if (open) setProjectId(open);
      else if (!list.some((p) => p.id === projectId)) {
        if (list.length) setProjectId(list[0].id);
        else setTab("project");  // primeiro uso: começa criando um projeto
      }
    }, (e) => setError(String(e)));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { loadProjects(); api.settings().then(setSettings); }, [loadProjects]);

  // Resposta atrasada de um projeto anterior não pode sobrescrever a do projeto escolhido agora.
  const current = useRef(projectId);
  current.current = projectId;
  const refreshProject = useCallback(() => {
    if (!projectId) return;
    api.project(projectId).then((p) => {
      if (p.id !== current.current) return;
      setProject(p);
      setPage((cur) => cur ?? p.pages_with_segments[0]?.page ?? null);
    }, (e) => setError(String(e)));
  }, [projectId]);

  useEffect(() => {
    savePref("project", projectId);
    setPage(null);
    setProject(null);
    refreshProject();
  }, [projectId, refreshProject]);

  useEffect(() => savePref("author", author), [author]);

  const attentionPages = new Set((project?.attention ?? []).map((id) => Number(id.slice(1).split("-")[0])));
  const nextAttention = [...attentionPages].sort((a, b) => a - b).find((pg) => pg > (page ?? 0))
    ?? [...attentionPages].sort((a, b) => a - b)[0];
  const pages = (project?.pages_with_segments ?? []).filter((p) => !onlyAttention || attentionPages.has(p.page));

  return (
    <div className="app">
      <header>
        <h1>Revisão da tradução</h1>
        <select value={projectId} onChange={(e) => setProjectId(e.target.value)} aria-label="Projeto">
          {projects.map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </select>
        {project && (
          <span className="progress">
            {project.approved}/{project.segments} aprovados · {project.attention.length} pedem atenção
            {!project.original_ok && <strong className="bad"> · original alterado!</strong>}
          </span>
        )}
        <label className="author">
          Revisor
          <input value={author} onChange={(e) => setAuthor(e.target.value)} placeholder="seu nome" />
        </label>
        <nav>
          <button className={tab === "project" ? "on" : ""} onClick={() => setTab("project")}>Projeto</button>
          <button className={tab === "pages" ? "on" : ""} onClick={() => setTab("pages")}>Páginas</button>
          <button className={tab === "translate" ? "on" : ""}
                  onClick={() => { setRetranslate(null); setTab("translate"); }}>Traduzir</button>
          <button className={tab === "quality" ? "on" : ""} onClick={() => setTab("quality")}>Qualidade</button>
          <button className={tab === "glossary" ? "on" : ""} onClick={() => setTab("glossary")}>Glossário</button>
        </nav>
      </header>
      {error && <p className="error" role="alert">{error}</p>}
      {tab === "project" && (
        <ProjectView project={project} author={author} settings={settings} onChange={refreshProject}
                     onOpen={(id) => { loadProjects(id); setTab("pages"); }} />
      )}
      {project && tab === "pages" && (
        <div className="layout">
          <aside>
            <label className="filter">
              <input type="checkbox" checked={onlyAttention} onChange={(e) => setOnlyAttention(e.target.checked)} />
              só o que pede atenção
            </label>
            {nextAttention !== undefined && (
              <button className="next" onClick={() => setPage(nextAttention)}
                      title="Vai para a próxima página com algo para revisar">
                Próxima pendência: p. {nextAttention}
              </button>
            )}
            <ul className="pages">
              {pages.map((p) => (
                <li key={p.page}>
                  <button className={p.page === page ? "on" : ""} onClick={() => setPage(p.page)}>
                    p. {p.page}
                    <small>{p.approved}/{p.segments}{attentionPages.has(p.page) ? " ⚠" : ""}</small>
                  </button>
                </li>
              ))}
            </ul>
          </aside>
          <main>
            {page !== null && (
              <PageView key={`${projectId}-${page}`} project={project} page={page} author={author}
                        onlyAttention={onlyAttention} onChange={refreshProject}
                        onRetranslate={(s) => {
                          setRetranslate({ pages: String(s.page), mode: "ids", segment_ids: [s.id], fresh: true });
                          setTab("translate");
                        }} />
            )}
          </main>
        </div>
      )}
      {project && tab === "translate" && (
        <TranslateView key={JSON.stringify(retranslate)} projectId={project.id} pages={project.pages} author={author}
                       spent={project.spent} spendLimit={project.spend_limit} initial={retranslate}
                       onChange={refreshProject} />
      )}
      {project && tab === "quality" && (
        <QualityView projectId={project.id} author={author} onAssembled={refreshProject}
                     onOpenPage={(pg) => { setPage(pg); setTab("pages"); }} />
      )}
      {project && tab === "glossary" && <GlossaryView projectId={project.id} author={author} />}
    </div>
  );
}

function PageView(props: { project: Project; page: number; author: string; onlyAttention: boolean;
                           onChange: () => void; onRetranslate: (s: Segment) => void }) {
  const { project, page } = props;
  const [segments, setSegments] = useState<Segment[]>([]);
  const [showImages, setShowImages] = useState(() => loadPref("images", "1") === "1");
  const [pageMessage, setPageMessage] = useState("");

  useEffect(() => {
    api.segments(project.id, page).then(setSegments);
  }, [project.id, page]);

  const approvePage = async () => {
    try {
      const r = await api.approvePage(project.id, page, props.author);
      setSegments(await api.segments(project.id, page));
      props.onChange();
      setPageMessage(`${r.approved.length} aprovados` + (r.skipped.length
        ? `; ${r.skipped.length} ficaram de fora (recusados pela proteção, com falha ou sem tradução)` : "."));
    } catch (e) {
      setPageMessage(String(e));
    }
  };
  const pending = segments.some((s) => !s.approved && (s.current || s.kept_as_image)
                                        && s.status !== "needs_review" && s.status !== "failed");

  const replace = (s: Segment) => {
    setSegments((list) => list.map((x) => (x.id === s.id ? s : x)));
    props.onChange();
  };
  const shown = segments.filter((s) => s.status !== "not_needed" && (!props.onlyAttention || s.needs_attention));

  return (
    <section>
      <div className="page-head">
        <h2>Página {page}</h2>
        <label>
          <input type="checkbox" checked={showImages}
                 onChange={(e) => { setShowImages(e.target.checked); savePref("images", e.target.checked ? "1" : "0"); }} />
          mostrar páginas
        </label>
        <button disabled={!pending || !props.author.trim()} onClick={approvePage}
                title="Aprova todos os parágrafos traduzidos desta página depois de conferi-los com a página original">
          Aprovar página
        </button>
        {pageMessage && <span className="muted" role="status">{pageMessage}</span>}
      </div>
      {showImages && (
        <div className="images">
          <figure>
            <img src={api.pageImage(project.id, page, "original")} alt={`Página ${page}, original`} />
            <figcaption>Original</figcaption>
          </figure>
          <figure>
            {project.has_translated_pdf ? (
              <TranslatedImage projectId={project.id} page={page} />
            ) : (
              <p className="muted">PDF traduzido ainda não montado (aba Qualidade → Montar PDF traduzido).</p>
            )}
            <figcaption>Tradução montada (pode estar desatualizada em relação às edições)</figcaption>
          </figure>
        </div>
      )}
      {shown.length === 0 && <p className="muted">Nada a revisar nesta página com o filtro atual.</p>}
      {shown.map((s) => (
        <SegmentCard key={s.id} projectId={project.id} segment={s} author={props.author} onSaved={replace}
                     onRetranslate={props.onRetranslate} />
      ))}
    </section>
  );
}

function TranslatedImage(props: { projectId: string; page: number }) {
  const [missing, setMissing] = useState(false);
  if (missing) return <p className="muted">Esta página não está no PDF montado (sem texto para traduzir).</p>;
  return <img src={api.pageImage(props.projectId, props.page, "translated")} onError={() => setMissing(true)}
              alt={`Página ${props.page}, tradução montada`} />;
}

function SegmentCard(props: { projectId: string; segment: Segment; author: string; onSaved: (s: Segment) => void;
                              onRetranslate: (s: Segment) => void }) {
  const { segment: s, projectId } = props;
  const [text, setText] = useState(s.current?.text ?? "");
  const [problems, setProblems] = useState<string[]>([]);
  const [message, setMessage] = useState("");
  const [history, setHistory] = useState<Version[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [sourceText, setSourceText] = useState<string | null>(null);  // corrigindo o original
  const dirty = text !== (s.current?.text ?? "");
  const canFixSource = s.source_flags.length > 0 || s.status === "blocked";
  const needAuthor = !props.author.trim();

  const run = async (action: () => Promise<Segment>, done: string): Promise<boolean> => {
    setBusy(true);
    setProblems([]);
    setMessage("");
    try {
      const updated = await action();
      setText(updated.current?.text ?? "");
      props.onSaved(updated);
      setMessage(done);
      if (history) setHistory(await api.history(projectId, s.id));
      return true;
    } catch (e) {
      if (e instanceof ApiError) {
        setMessage(e.message);
        setProblems(e.problems);
      } else setMessage(String(e));
      return false;
    } finally {
      setBusy(false);
    }
  };

  const warnings = s.current?.warnings ?? [];
  return (
    <article className={`segment${s.approved ? " approved" : ""}${s.needs_attention ? " attention" : ""}`}>
      <header>
        <code>{s.id}</code>
        <span className="section">{s.section}</span>
        {s.current && <span className="chip">{KIND[s.current.kind] ?? s.current.kind}</span>}
        {!s.current && <span className="chip bad">{STATUS[s.status] ?? s.status}</span>}
        {s.approved && <span className="chip ok">aprovado</span>}
        {s.source_extracted !== null && <span className="chip">original corrigido</span>}
      </header>
      <div className="columns">
        {sourceText === null ? (
          <div className="source" lang="en">{s.source}</div>
        ) : (
          <div>
            <textarea lang="en" value={sourceText} onChange={(e) => setSourceText(e.target.value)} disabled={busy}
                      rows={Math.min(14, Math.max(3, Math.ceil(sourceText.length / 70)))}
                      aria-label={`Original de ${s.id}`} />
            <div className="row">
              <button disabled={busy || needAuthor || !sourceText.trim() || sourceText === s.source}
                      onClick={() => run(() => api.editSource(projectId, s.id, sourceText, props.author),
                                         "Original corrigido. Traduza de novo (Traduzir → pendentes).")
                        .then((ok) => ok && setSourceText(null))}>
                Salvar original
              </button>
              {s.source_extracted !== null && (
                <button disabled={busy} onClick={() => setSourceText(s.source_extracted)}>Voltar ao texto lido</button>
              )}
              <button disabled={busy} onClick={() => setSourceText(null)}>Cancelar</button>
            </div>
          </div>
        )}
        <div>
          <textarea lang="pt-BR" value={text} onChange={(e) => setText(e.target.value)} disabled={!s.current || busy}
                    rows={Math.min(14, Math.max(3, Math.ceil(text.length / 70)))}
                    aria-label={`Tradução de ${s.id}`} />
        </div>
      </div>
      {s.source_flags.length > 0 && (
        <details className="source-flags" open={!s.approved}>
          <summary>
            Texto lido por OCR: confira com a página original e aprove
            {s.source_flags.length > 1 && ` (${s.source_flags.length - 1} trechos duvidosos)`}
          </summary>
          <ul>{s.source_flags.slice(1).map((f) => <li key={f}>{f}</li>)}</ul>
        </details>
      )}
      {s.source_extracted !== null && (
        <details className="source-flags">
          <summary>Texto como foi lido da imagem</summary>
          <p lang="en">{s.source_extracted}</p>
        </details>
      )}
      {s.machine_problems.length > 0 && (
        <ul className="problems">{s.machine_problems.map((p) => <li key={p}>{p}</li>)}</ul>
      )}
      {warnings.length > 0 && (
        <ul className="warnings">
          {warnings.map((w) => <li key={w} className={w.startsWith("glossario_evitar") ? "bad" : ""}>{w}</li>)}
        </ul>
      )}
      <footer>
        <button disabled={!dirty || busy || needAuthor}
                onClick={() => run(() => api.edit(projectId, s.id, text, props.author), "Salvo como nova versão.")}>
          Salvar
        </button>
        <button disabled={!(s.current || s.kept_as_image) || dirty || busy || needAuthor}
                onClick={() => run(() => api.approve(projectId, s.id, !s.approved, props.author),
                                   s.approved ? "Aprovação retirada." : "Aprovado.")}
                title={s.kept_as_image ? "O bloco fica como na imagem original (não é traduzido)" : undefined}>
          {s.approved ? "Retirar aprovação" : s.kept_as_image ? "Manter como na imagem" : "Aprovar"}
        </button>
        {dirty && <button onClick={() => setText(s.current?.text ?? "")}>Descartar</button>}
        {canFixSource && sourceText === null && (
          <button onClick={() => setSourceText(s.source)}
                  title="Corrigir o texto lido da imagem (lances, números, palavras) antes de traduzir">
            Corrigir original
          </button>
        )}
        <button onClick={async () => setHistory(history ? null : await api.history(projectId, s.id))}>
          {history ? "Ocultar histórico" : "Histórico"}
        </button>
        {s.status !== "blocked" && (!s.current || s.current.kind === "machine") && (
          <button onClick={() => props.onRetranslate(s)} title="Pedir outra tradução automática, com previsão de custo">
            Retraduzir…
          </button>
        )}
        {needAuthor && <span className="muted">Informe o nome do revisor para salvar.</span>}
        {message && <span className={problems.length ? "bad" : "ok"} role="status">{message}</span>}
      </footer>
      {problems.length > 0 && (
        <ul className="problems" role="alert">{problems.map((p) => <li key={p}>{p}</li>)}</ul>
      )}
      {history && (
        <ol className="history">
          {history.map((v) => (
            <li key={v.version}>
              <strong>v{v.version}</strong> {KIND[v.kind] ?? v.kind} · {v.author} · {v.created_at.replace("T", " ")}
              {v.version !== s.current?.version && (
                <button disabled={busy || needAuthor}
                        onClick={() => run(() => api.revert(projectId, s.id, v.version, props.author),
                                           `Voltou à v${v.version} (como nova versão).`)}>
                  Voltar a esta versão
                </button>
              )}
              <p>{v.text}</p>
            </li>
          ))}
        </ol>
      )}
    </article>
  );
}

const EMPTY: Omit<GlossaryEntry, "source"> = {
  term: "", preferred: "", alternatives: [], avoid: [], context: "", category: "geral", case_sensitive: false,
  check: true,
};

function GlossaryView(props: { projectId: string; author: string }) {
  const [entries, setEntries] = useState<GlossaryEntry[]>([]);
  const [form, setForm] = useState(EMPTY);
  const [filter, setFilter] = useState("");
  const [message, setMessage] = useState("");

  const load = useCallback(() => api.glossary(props.projectId).then(setEntries), [props.projectId]);
  useEffect(() => { load(); }, [load]);

  const list = (v: string) => v.split(",").map((x) => x.trim()).filter(Boolean);
  const save = async () => {
    try {
      await api.setGlossary(props.projectId, form, props.author);
      setMessage(`"${form.term}" salvo no glossário do projeto. Vale para as próximas traduções e conferências.`);
      setForm(EMPTY);
      load();
    } catch (e) {
      setMessage(String(e));
    }
  };
  const shown = entries.filter((e) => !filter || `${e.term} ${e.preferred}`.toLowerCase().includes(filter.toLowerCase()));

  return (
    <section className="glossary">
      <h2>Glossário</h2>
      <form onSubmit={(e) => { e.preventDefault(); save(); }}>
        <input required placeholder="termo em inglês" value={form.term}
               onChange={(e) => setForm({ ...form, term: e.target.value })} />
        <input required placeholder="tradução preferencial" value={form.preferred}
               onChange={(e) => setForm({ ...form, preferred: e.target.value })} />
        <input placeholder="alternativas aceitas (vírgulas)" value={form.alternatives.join(", ")}
               onChange={(e) => setForm({ ...form, alternatives: list(e.target.value) })} />
        <input placeholder="nunca usar (vírgulas)" value={form.avoid.join(", ")}
               onChange={(e) => setForm({ ...form, avoid: list(e.target.value) })} />
        <input placeholder="contexto / observação" value={form.context}
               onChange={(e) => setForm({ ...form, context: e.target.value })} />
        <label><input type="checkbox" checked={form.case_sensitive}
                      onChange={(e) => setForm({ ...form, case_sensitive: e.target.checked })} /> maiúsculas importam</label>
        <button disabled={!props.author.trim()}>Salvar termo</button>
        {!props.author.trim() && <span className="muted">Informe o nome do revisor.</span>}
      </form>
      {message && <p role="status">{message}</p>}
      <input className="search" placeholder="filtrar" value={filter} onChange={(e) => setFilter(e.target.value)} />
      <div className="table-wrap">
        <table>
          <thead>
            <tr><th>Termo</th><th>Preferido</th><th>Aceitos</th><th>Nunca</th><th>Contexto</th><th>Origem</th><th /></tr>
          </thead>
          <tbody>
            {shown.map((e) => (
              <tr key={e.term}>
                <td>{e.term}</td><td>{e.preferred}</td><td>{e.alternatives.join(", ")}</td>
                <td>{e.avoid.join(", ")}</td><td>{e.context}</td><td>{e.source}</td>
                <td><button onClick={() => { const { source: _s, ...rest } = e; void _s; setForm(rest); }}>Editar</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
