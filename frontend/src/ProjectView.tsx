import { useCallback, useEffect, useState } from "react";
import { api, Creation, Project, Settings } from "./api";

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

export default function ProjectView(props: { project: Project | null; author: string; settings: Settings | null;
                                             onOpen: (id: string) => void; onChange: () => void }) {
  const { project, settings } = props;
  const [syncMsg, setSyncMsg] = useState("");
  const [busy, setBusy] = useState(false);

  const sync = async () => {
    if (!project) return;
    setBusy(true);
    setSyncMsg("");
    try {
      const r = await api.sync(project.id, props.author);
      setSyncMsg(`Mantidos ${r.kept}, renomeados ${r.renamed}, novos ${r.added}, removidos ${r.removed}, ` +
                 `guardados como obsoletos ${r.obsolete}, para retraduzir ${r.retranslate}.`);
      props.onChange();
    } catch (e) {
      setSyncMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
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
            <button disabled={busy || !props.author.trim()} onClick={sync}
                    title="Depois de atualizar o programa: alinha os parágrafos com a extração nova, sem perder traduções">
              {busy ? "Sincronizando…" : "Sincronizar com a versão atual"}
            </button>
          </div>
          {syncMsg && <p className="small">{syncMsg}</p>}
        </div>
      )}
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
