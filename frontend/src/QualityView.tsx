import { useCallback, useEffect, useState } from "react";
import { api, Assembly, Quality } from "./api";

const ISSUE: Record<string, string> = {
  not_written: "bloco não escrito",
  review: "redução abaixo de 85 %",
  missing_text: "texto ausente",
  cut_text: "texto cortado",
  missing_notation: "notação ausente",
  overlaps: "sobreposição",
  leftover_original: "original não removido",
  diagrams_changed: "diagrama alterado",
};

const ASSEMBLY_STATE: Record<string, string> = {
  running: "montando", done: "concluída", failed: "falhou", cancelled: "cancelada", interrupted: "interrompida",
};

function AssemblyPanel(props: { projectId: string; author: string; onDone: () => void }) {
  const [a, setA] = useState<Assembly | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(() => api.assembly(props.projectId).then(setA), [props.projectId]);
  useEffect(() => { load(); }, [load]);
  const running = a?.state === "running";
  useEffect(() => {
    if (!running) return;
    const t = setInterval(async () => {
      const cur = await api.assembly(props.projectId);
      setA(cur);
      if (cur?.state !== "running") props.onDone();
    }, 1500);
    return () => clearInterval(t);
  }, [running, props]);

  const start = async () => {
    setError("");
    try {
      setA(await api.assemble(props.projectId, props.author));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };
  const pr = a?.progress;
  return (
    <div className="assembly">
      <div className="row">
        <button className="primary" disabled={running || !props.author.trim()} onClick={start}>
          {a ? "Montar de novo" : "Montar PDF traduzido"}
        </button>
        {running && <button onClick={async () => setA(await api.cancelAssembly(props.projectId))}>Cancelar</button>}
        {a && <span className={a.state === "done" ? "ok" : a.state === "running" ? "" : "bad"}>
          Montagem #{a.id}: {ASSEMBLY_STATE[a.state] ?? a.state}</span>}
        {a?.outdated && <span className="chip bad">há edições depois desta montagem</span>}
        {!props.author.trim() && <span className="muted">Informe o nome do revisor.</span>}
      </div>
      {running && pr && (
        <>
          <progress max={Math.max(1, pr.pages_total)} value={pr.pages_done} aria-label="Andamento da montagem" />
          <div className="muted small">
            {pr.pages_done}/{pr.pages_total} páginas · partes {pr.chunks_done}/{pr.chunks_total}
            {pr.chunks_reused > 0 && ` (${pr.chunks_reused} reaproveitadas, sem mudanças)`}
          </div>
        </>
      )}
      {running && !pr && <p className="muted small">Lendo o livro…</p>}
      {a?.state === "done" && a.summary && (
        <p className="muted small">
          {a.summary.blocks_placed}/{a.summary.blocks} blocos · {a.summary.chunks_reused} de {a.summary.chunks} partes
          de 20 páginas reaproveitadas (só as partes com texto alterado são refeitas).
        </p>
      )}
      {a?.error && <p className="bad small">{a.error}</p>}
      {error && <p className="bad" role="alert">{error}</p>}
    </div>
  );
}

export default function QualityView(props: { projectId: string; author: string; onOpenPage: (page: number) => void;
                                             onAssembled: () => void }) {
  const [q, setQ] = useState<Quality | null>(null);
  const [error, setError] = useState("");
  const [onlyProblems, setOnlyProblems] = useState(true);

  const load = useCallback(() => {
    setError("");
    api.quality(props.projectId).then(setQ, (e) => { setQ(null); setError(e instanceof Error ? e.message : String(e)); });
  }, [props.projectId]);
  useEffect(() => { load(); }, [load]);

  const panel = <AssemblyPanel projectId={props.projectId} author={props.author}
                               onDone={() => { load(); props.onAssembled(); }} />;
  if (error) return <section className="quality"><h2>Qualidade</h2>{panel}<p className="muted">{error}</p></section>;
  if (!q) return <section className="quality"><h2>Qualidade</h2>{panel}<p className="muted">Carregando…</p></section>;
  const shown = q.pages.filter((p) => !onlyProblems || !p.ok);
  const counts: Record<string, number> = {};
  q.pages.forEach((p) => Object.keys(p.issues).forEach((k) => { counts[k] = (counts[k] ?? 0) + 1; }));

  return (
    <section className="quality">
      <h2>Qualidade da montagem</h2>
      {panel}
      <p>
        <strong>{q.pages_ok}</strong> de {q.pages_total} páginas sem pendências · montado em{" "}
        {q.assembled_at.replace("T", " ")} 
      </p>
      {Object.keys(counts).length > 0 && (
        <p className="row">
          {Object.entries(counts).map(([k, n]) => <span key={k} className="chip bad">{ISSUE[k] ?? k}: {n} pág.</span>)}
        </p>
      )}
      <label className="filter">
        <input type="checkbox" checked={onlyProblems} onChange={(e) => setOnlyProblems(e.target.checked)} />
        só páginas com pendência
      </label>
      <div className="table-wrap">
        <table>
          <thead>
            <tr><th>Página</th><th>Estado</th><th>Blocos</th><th>Reduzidos</th><th>Menor fonte</th><th>Pendências</th></tr>
          </thead>
          <tbody>
            {shown.map((p) => (
              <tr key={p.page}>
                <td><button onClick={() => props.onOpenPage(p.page)}>p. {p.page}</button></td>
                <td className={p.ok ? "ok" : "bad"}>{p.ok ? "ok" : "revisar"}</td>
                <td>{p.blocks}</td>
                <td>{p.reduced}</td>
                <td>{Math.round(p.min_scale * 100)} %</td>
                <td className="small">
                  {Object.entries(p.issues).map(([k, v]) => <div key={k}>{ISSUE[k] ?? k}: {v.join(", ")}</div>)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {shown.length === 0 && <p className="muted">Nenhuma página com pendência.</p>}
    </section>
  );
}
