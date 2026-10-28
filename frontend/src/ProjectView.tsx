import { useCallback, useEffect, useState } from "react";
import { api, Creation, Project, Reprocess, Settings } from "./api";

const OCR_LABEL: Record<string, string> = {
  auto: "Automático (só se a maioria do livro for digitalizada)",
  on: "Ler por OCR toda página que só tem imagem",
  off: "Não usar OCR",
};
const CREATION_STATE: Record<string, string> = {
  running: "criando", done: "pronto", failed: "falhou", interrupted: "interrompido",
};

function slug(name: string): string {
  return name.normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase()
    .replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 64);
}

/** Novo projeto a partir de um PDF, com o andamento da extração (e do OCR, se houver). */
export function NewProject(props: { settings: Settings | null; onCreated: (id: string) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [id, setId] = useState("");
  const [ocr, setOcr] = useState("auto");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [creations, setCreations] = useState<Creation[]>([]);

  const load = useCallback(() => api.creations().then(setCreations), []);
  useEffect(() => { load(); }, [load]);
  const running = creations.some((c) => c.state === "running");
  useEffect(() => {
    if (!running) return;
    const t = setInterval(async () => {
      const before = creations.filter((c) => c.state === "running").map((c) => c.id);
      const list = await api.creations();
      setCreations(list);
      const finished = list.find((c) => before.includes(c.id) && c.state === "done");
      if (finished) props.onCreated(finished.id);
    }, 1500);
    return () => clearInterval(t);
  }, [running, creations, props]);

  const submit = async () => {
    if (!file || !name.trim()) return;
    setBusy(true);
    setError("");
    try {
      await api.createProject(file, name.trim(), id.trim() || slug(name), ocr);
      setFile(null);
      setName("");
      setId("");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const max = props.settings?.max_upload_mb;
  return (
    <div className="panel">
      <h3>Novo projeto</h3>
      <form className="stack" onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <label>
          Livro (PDF{max ? `, até ${max} MB` : ""})
          <input type="file" accept="application/pdf,.pdf" onChange={(e) => {
            const f = e.target.files?.[0] ?? null;
            setFile(f);
            if (f && !name) setName(f.name.replace(/\.pdf$/i, ""));
          }} />
        </label>
        <label>
          Nome
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="ex.: Dvoretsky's Endgame Manual" />
        </label>
        <label>
          Identificador
          <input value={id} onChange={(e) => setId(e.target.value)} placeholder={slug(name) || "gerado do nome"} />
        </label>
        <label>
          Páginas digitalizadas
          <select value={ocr} onChange={(e) => setOcr(e.target.value)}>
            {Object.entries(OCR_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
        {props.settings && !props.settings.tesseract && ocr !== "off" && (
          <p className="bad small">Tesseract não instalado: páginas digitalizadas não serão lidas.</p>
        )}
        <div className="row">
          <button className="primary" disabled={busy || !file || !name.trim()}>
            {busy ? "Enviando…" : "Criar projeto"}
          </button>
          <span className="muted small">O livro fica só neste computador; o original nunca é alterado.</span>
        </div>
      </form>
      {error && <p className="bad" role="alert">{error}</p>}
      {creations.length > 0 && (
        <ul className="jobs">
          {creations.slice().reverse().slice(0, 5).map((c) => (
            <li key={c.id}>
              <div className="row">
                <strong>{c.name}</strong>
                <span className="muted small">{c.id} · {c.pages} páginas</span>
                <span className={c.state === "done" ? "ok" : c.state === "running" ? "" : "bad"}>
                  {CREATION_STATE[c.state] ?? c.state}
                </span>
                {c.state === "done" && <button onClick={() => props.onCreated(c.id)}>Abrir</button>}
              </div>
              {c.state === "running" && c.progress && (
                <>
                  <progress max={Math.max(1, c.progress.total)} value={c.progress.done}
                            aria-label={`Criação de ${c.name}`} />
                  <div className="muted small">{c.progress.stage}: {c.progress.done}/{c.progress.total}</div>
                </>
              )}
              {c.error && <div className="bad small">{c.error}</div>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function RestoreBackup(props: { onRestored: (id: string) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [id, setId] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    if (!file) return;
    setBusy(true);
    setMessage("");
    try {
      const out = await api.restoreBackup(file, id.trim());
      props.onRestored(out.id);
    } catch (e) {
      setMessage(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="panel">
      <h3>Restaurar backup</h3>
      <form className="stack" onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <label>
          Arquivo .chessbook.zip
          <input type="file" accept=".zip,application/zip" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </label>
        <label>
          Restaurar como (opcional)
          <input value={id} onChange={(e) => setId(e.target.value)} placeholder="o mesmo identificador" />
        </label>
        <div className="row">
          <button disabled={busy || !file}>{busy ? "Conferindo…" : "Restaurar"}</button>
          <span className="muted small">Cada arquivo é conferido pelo sha256; um projeto existente nunca é sobrescrito.</span>
        </div>
      </form>
      {message && <p className="bad" role="alert">{message}</p>}
    </div>
  );
}

const PIECES: [string, string][] = [["♔", "♔ rei"], ["♕", "♕ dama"], ["♖", "♖ torre"], ["♗", "♗ bispo"],
                                    ["♘", "♘ cavalo"], ["", "não é peça"]];
const STAGE: Record<string, string> = { "extração": "lendo o livro", ocr: "OCR", figurinas: "figurinas" };

function reprocessText(r: Reprocess): string {
  const what = r.kind === "figurines" ? "Releitura com as figurinas"
    : r.kind === "symbols" ? "Reescrita dos lances com os símbolos"
    : r.kind === "pieces" ? "Posições dos diagramas com as peças" : "Sincronização";
  if (r.state === "running") {
    const pr = r.progress;
    return `${what} em andamento` + (pr ? `: ${STAGE[pr.stage] ?? pr.stage} ${pr.done}/${pr.total} páginas` : "…");
  }
  if (r.state === "done" && r.result) {
    const x = r.result;
    return `${what} concluída. Mantidos ${x.kept}, renomeados ${x.renamed}, novos ${x.added}, removidos ${x.removed}, ` +
      `guardados como obsoletos ${x.obsolete}, para retraduzir ${x.retranslate}` +
      (x.ocr_pieces !== undefined ? `; ${x.ocr_pieces} lances com peça lidos (${x.ocr_uncertain} com dúvida).`
        : x.ocr_moves !== undefined ? `; ${x.ocr_moves} lances com símbolos decididos (${x.ocr_uncertain} sem).`
        : x.ocr_diagrams !== undefined ? `; ${x.ocr_complete} de ${x.ocr_diagrams} posições completas.` : ".") +
      (x.added ? " Os parágrafos novos ficam pendentes: Traduzir → pendentes." : "");
  }
  return `${what}: ${r.error ?? r.state}`;
}

const SYMBOL_OPTIONS: [string, string][] = [
  ["†", "† xeque"], ["+", "+ xeque"], ["#", "# mate"], ["!", "!"], ["?", "?"], ["!!", "!!"], ["??", "??"],
  ["!?", "!?"], ["?!", "?!"], ["±", "± brancas melhor"], ["∓", "∓ pretas melhor"],
  ["⩲", "⩲ brancas um pouco melhor"], ["⩱", "⩱ pretas um pouco melhor"], ["=", "= igual / promoção"],
  ["∞", "∞ pouco claro"], ["−", "− (de +− e −+)"], ["♕", "♕ dama (promoção)"], ["♖", "♖ torre (promoção)"],
  ["♗", "♗ bispo (promoção)"], ["♘", "♘ cavalo (promoção)"], ["=♕", "=♕ promoção a dama"],
  ["", "não é símbolo (fica o que o OCR leu)"],
  ["∅", "descartar (algarismo da casa ou sujeira)"],
];
const UNSET = "__";  // "— escolha —": não é enviado (o "?" é um símbolo de verdade)

const PIECE_OPTIONS: [string, string][] = [
  ["K", "♔ rei branco"], ["Q", "♕ dama branca"], ["R", "♖ torre branca"], ["B", "♗ bispo branco"],
  ["N", "♘ cavalo branco"], ["P", "♙ peão branco"], ["k", "♚ rei preto"], ["q", "♛ dama preta"],
  ["r", "♜ torre preta"], ["b", "♝ bispo preto"], ["n", "♞ cavalo preto"], ["p", "♟ peão preto"],
  ["", "casa vazia / não é peça"],
];
const KIND_TEXT = {
  figurines: {
    title: "Figurinas do livro", button: "Confirmar e reler o livro", unit: "lances",
    help: "Desenhos iguais achados no começo dos lances. Confira cada grupo e escolha a peça; depois, o livro é " +
          "relido com elas (alguns minutos) e só os parágrafos cujo texto mudou voltam a pendentes.",
  },
  symbols: {
    title: "Símbolos do livro", button: "Confirmar e reescrever os lances", unit: "vezes",
    help: "Desenhos iguais achados depois da casa dos lances: xeque, mate, ! e ?, avaliação (± ⩲ ⩱ ∓ = ∞) e a " +
          "peça da promoção. Confira cada grupo; o fim dos lances é reescrito com o símbolo escolhido (segundos). " +
          "Grupo sem símbolo decidido deixa o lance como o OCR leu, com aviso.",
  },
  pieces: {
    title: "Peças dos diagramas", button: "Confirmar e refazer as posições", unit: "casas",
    help: "Os desenhos das peças nas casas dos diagramas, agrupados. Confira cada grupo; as posições de todos os " +
          "diagramas são refeitas (segundos). Grupo pequeno sem peça decidida herda a do grupo confirmado mais " +
          "parecido; casa que fica sem peça decidida deixa a posição incompleta, para revisão.",
  },
};

type GroupInfo = { available: boolean; reason: string; labels: Record<string, string>;
                   groups: { id: number; count: number; auto: string; margin?: number; ocr?: string[];
                             read?: string[]; black?: boolean; image: string }[] };

/** Grupos de desenhos achados pelo OCR (figurinas no começo dos lances, símbolos depois da casa):
 * o usuário diz o que é cada grupo, e o livro é reescrito com isso. */
function GroupsPanel(props: { kind: "figurines" | "symbols" | "pieces"; projectId: string; author: string;
                              busy: boolean; onStart: (r: Reprocess) => void }) {
  const figurines = props.kind === "figurines";
  const text = KIND_TEXT[props.kind];
  const [info, setInfo] = useState<GroupInfo | null>(null);
  const [labels, setLabels] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const [showSmall, setShowSmall] = useState(false);

  useEffect(() => {
    const load = figurines ? api.figurines(props.projectId)
      : props.kind === "symbols" ? api.symbols(props.projectId) : api.pieces(props.projectId);
    load.then((f: GroupInfo) => {
      setInfo(f);
      const initial: Record<string, string> = {};
      for (const g of f.groups) {
        // símbolos e peças: sem confirmação nem sugestão, fica "— escolha —" e não é enviado
        initial[g.id] = f.labels[g.id] ?? (figurines ? ((g.margin ?? 0) >= 0.05 ? g.auto : "") : (g.auto || UNSET));
      }
      setLabels(initial);
    }, (e) => setError(String(e)));
  }, [props.projectId, props.busy, figurines, props.kind]);

  if (!info || (!info.available && !info.reason.includes("versão anterior"))) return null;
  const confirmed = Object.keys(info.labels).length > 0;
  const options = figurines ? PIECES : props.kind === "symbols" ? SYMBOL_OPTIONS : PIECE_OPTIONS;
  const submit = async () => {
    setError("");
    const chosen = Object.fromEntries(Object.entries(labels).filter(([, v]) => v !== UNSET));
    try {
      props.onStart(await (figurines ? api.setFigurines(props.projectId, chosen, props.author)
        : props.kind === "symbols" ? api.setSymbols(props.projectId, chosen, props.author)
        : api.setPieces(props.projectId, chosen, props.author)));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };
  return (
    <div className="panel">
      <h3>{text.title}</h3>
      {!info.available ? (
        <p className="muted small">{info.reason}.</p>
      ) : (
        <>
          <p className="muted small">
            {text.help}
            {confirmed ? " As escolhas atuais já foram confirmadas." : " Nada foi confirmado ainda: os valores são sugestões."}
          </p>
          <ul className="figurines">
            {info.groups.filter((g) => figurines || showSmall || g.count > 5).map((g) => {
              const read = (figurines ? g.ocr : g.read) ?? [];
              const doubtful = !(String(g.id) in info.labels) && (figurines ? (g.margin ?? 0) < 0.05 : !g.auto);
              return (
                <li key={g.id} className={doubtful ? "doubt" : ""}>
                  <img src={g.image} alt={`grupo ${g.id}`} width={48} height={48} />
                  <select value={labels[g.id] ?? ""} aria-label={`Grupo ${g.id}`}
                          onChange={(e) => setLabels({ ...labels, [g.id]: e.target.value })}>
                    {!figurines && <option value={UNSET}>— escolha —</option>}
                    {!figurines && labels[g.id] !== UNSET && !options.some(([v]) => v === (labels[g.id] ?? "")) && (
                      <option value={labels[g.id]}>{labels[g.id]}</option>
                    )}
                    {options.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
                  </select>
                  <small>
                    {g.count} {text.unit}
                    {props.kind === "pieces" ? "" : ` · OCR leu “${read.join(" ") || "?"}”`}
                    {doubtful ? (figurines ? " · sugestão incerta" : " · sem sugestão") : ""}
                  </small>
                </li>
              );
            })}
          </ul>
          {!figurines && info.groups.some((g) => g.count <= 5) && (
            <p className="small">
              <button onClick={() => setShowSmall(!showSmall)}>
                {showSmall ? "Ocultar" : "Mostrar"} os {info.groups.filter((g) => g.count <= 5).length} grupos pequenos
              </button>{" "}
              <span className="muted">(até 5 vezes; sem escolha, herdam do grupo decidido mais parecido)</span>
            </p>
          )}
          <button className="primary" disabled={props.busy || !props.author.trim()} onClick={submit}>
            {text.button}
          </button>
        </>
      )}
      {error && <p className="bad" role="alert">{error}</p>}
    </div>
  );
}

export default function ProjectView(props: { project: Project | null; author: string; settings: Settings | null;
                                             onOpen: (id: string) => void; onChange: () => void }) {
  const { project, settings } = props;
  const [task, setTask] = useState<Reprocess | null>(null);
  const [error, setError] = useState("");
  const running = task?.state === "running";
  const projectId = project?.id;
  const onChange = props.onChange;

  useEffect(() => {
    setTask(null);
    if (projectId) api.reprocess(projectId).then((r) => setTask(r.state === "none" ? null : r));
  }, [projectId]);
  useEffect(() => {
    if (!running || !projectId) return;
    const t = setInterval(async () => {
      const r = await api.reprocess(projectId);
      setTask(r);
      if (r.state !== "running") onChange();
    }, 2000);
    return () => clearInterval(t);
  }, [running, projectId, onChange]);

  const sync = async () => {
    if (!project) return;
    setError("");
    try {
      setTask(await api.sync(project.id, props.author));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <section className="project-view">
      {project && (
        <div className="panel">
          <h2>{project.name}</h2>
          <p className="muted small">
            {project.pages} páginas · {project.segments} segmentos · {project.approved} aprovados ·{" "}
            {project.attention.length} pedem atenção · original {project.original_ok
              ? <span className="ok">intacto</span> : <strong className="bad">alterado!</strong>}{" "}
            (sha256 {project.sha256.slice(0, 12)}…)
          </p>
          <div className="row">
            {project.has_translated_pdf
              ? <a className="button primary" href={api.downloadUrl(project.id)}>Baixar PDF traduzido</a>
              : <span className="muted">PDF traduzido ainda não montado (aba Qualidade).</span>}
            <a className="button" href={api.backupUrl(project.id)}>Baixar backup</a>
            <button disabled={running || !props.author.trim()} onClick={sync}
                    title="Depois de atualizar o programa: alinha os parágrafos com a extração nova, sem perder traduções. Num livro digitalizado, refaz o OCR (cerca de 5 s por página)">
              {running ? "Reprocessando…" : "Sincronizar com a versão atual"}
            </button>
          </div>
          {task && <p className={`small${task.state === "failed" ? " bad" : ""}`} role="status">{reprocessText(task)}</p>}
          {error && <p className="bad small" role="alert">{error}</p>}
        </div>
      )}
      {project && <GroupsPanel kind="figurines" projectId={project.id} author={props.author} busy={running}
                               onStart={setTask} />}
      {project && <GroupsPanel kind="symbols" projectId={project.id} author={props.author} busy={running}
                               onStart={setTask} />}
      {project && <GroupsPanel kind="pieces" projectId={project.id} author={props.author} busy={running}
                               onStart={setTask} />}
      <NewProject settings={settings} onCreated={props.onOpen} />
      <RestoreBackup onRestored={props.onOpen} />
      {settings && (
        <div className="panel">
          <h3>Configuração</h3>
          <ul className="audit">
            <li className={settings.remote_allowed ? "ok" : "bad"}>
              {settings.remote_allowed ? "✓" : "✗"} envio para tradução externa{" "}
              {settings.remote_allowed ? "permitido" : `bloqueado (CHESSBOOK_PRIVACY_MODE=${settings.privacy_mode})`}
            </li>
            <li className={settings.pollinations_key ? "ok" : "bad"}>
              {settings.pollinations_key ? "✓ chave da Pollinations configurada (não é mostrada)"
                : "✗ chave da Pollinations ausente (POLLINATIONS_API_KEY no .env)"}
            </li>
            <li className={settings.tesseract ? "ok" : "muted"}>
              {settings.tesseract ? "✓ Tesseract instalado (OCR de livros digitalizados)" : "Tesseract ausente: sem OCR"}
            </li>
            <li className="muted">{settings.workers} seções traduzidas ao mesmo tempo · projetos em {settings.storage}</li>
          </ul>
        </div>
      )}
    </section>
  );
}
