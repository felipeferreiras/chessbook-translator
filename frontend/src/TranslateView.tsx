import { useCallback, useEffect, useState } from "react";
import { api, EstimateResponse, Job, Selection } from "./api";

const STATE: Record<string, string> = {
  queued: "na fila",
  running: "traduzindo",
  cancel_requested: "cancelando…",
  done: "concluída",
  done_with_warnings: "concluída com pendências",
  cancelled: "cancelada",
  stopped_budget: "parou no teto de gasto",
  failed: "falhou",
  interrupted: "interrompida",
};
const MODE_LABEL: Record<string, string> = {
  pending: "Pendentes (ainda sem tradução)",
  problems: "Com problemas (recusados, falhas, glossário contrariado)",
  glossary: "Afetados por mudanças no glossário",
  machine: "Toda tradução automática (trocar de motor)",
  ids: "Segmentos escolhidos na revisão",
};
const SKIPPED: Record<string, string> = {
  human: "com versão humana (nunca substituída)",
  not_needed: "só de notação",
  blocked: "bloqueados (tradução manual)",
  no_glossary_record: "traduzidos antes do registro do glossário (não dá para saber se mudou)",
};
const COUNT: Record<string, string> = {
  translated: "traduzidos", cached: "do cache", needs_review: "para revisão", failed: "falharam",
  kept_human: "versão humana mantida", retry_failed: "nova tentativa falhou (anterior mantida)", not_needed: "só notação",
};
const ACTIVE = new Set(["queued", "running", "cancel_requested"]);
const RESUMABLE = new Set(["interrupted", "cancelled", "stopped_budget", "failed"]);
const pollen = (v: number) => (Math.abs(v) < 0.01 ? v.toFixed(4) : Math.abs(v) < 1 ? v.toFixed(3) : v.toFixed(2));
const minutes = (m: number) => (m < 60 ? `${Math.max(1, Math.round(m))} min` : `${(m / 60).toFixed(1)} h`);
const num = (s: string) => Number(s.replace(",", "."));

export default function TranslateView(props: { projectId: string; pages: number; author: string;
                                               spent: number; spendLimit: number | null;
                                               initial: Selection | null; onChange: () => void }) {
  const [spec, setSpec] = useState(props.initial?.pages ?? `1-${props.pages}`);
  const [mode, setMode] = useState(props.initial?.mode ?? "pending");
  const [ids] = useState<string[]>(props.initial?.segment_ids ?? []);
  const [fresh, setFresh] = useState(props.initial?.fresh ?? false);
  const [resumeOf, setResumeOf] = useState<Job | null>(null);
  const [est, setEst] = useState<EstimateResponse | null>(null);
  const [engine, setEngine] = useState("");
  const [budget, setBudget] = useState("");
  const [limit, setLimit] = useState(props.spendLimit == null ? "" : String(props.spendLimit));
  const [jobs, setJobs] = useState<Job[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const loadJobs = useCallback(() => api.jobs(props.projectId).then(setJobs), [props.projectId]);
  useEffect(() => { loadJobs(); }, [loadJobs]);

  const running = jobs.some((j) => ACTIVE.has(j.state));
  useEffect(() => {
    if (!running) return;
    const t = setInterval(async () => {
      const list = await api.jobs(props.projectId);
      setJobs(list);
      if (!list.some((j) => ACTIVE.has(j.state))) props.onChange();
    }, 2000);
    return () => clearInterval(t);
  }, [running, props]);

  const shown = est?.estimates.filter((e) => !resumeOf || e.engine === resumeOf.engine) ?? [];
  const chosen = shown.find((e) => e.engine === engine);
  useEffect(() => {
    // Teto sugerido: o topo da faixa prevista, com folga de 20 %, sem passar do que sobra do projeto.
    if (!chosen) return;
    let value = Math.max(chosen.cost_high * 1.2, 0.001);
    if (est?.remaining != null && est.remaining > 0) value = Math.min(value, est.remaining);
    setBudget(pollen(value));
  }, [chosen, est]);

  const selection = (): Selection => (resumeOf ? { pages: resumeOf.pages, mode: resumeOf.mode, resume_of: resumeOf.id }
    : { pages: spec, mode, segment_ids: mode === "ids" ? ids : [], fresh: mode !== "pending" && fresh });

  const calculate = async (sel: Selection = selection(), job: Job | null = resumeOf) => {
    setBusy(true);
    setError("");
    try {
      const out = await api.estimate(props.projectId, sel);
      setEst(out);
      const list = out.estimates.filter((e) => !job || e.engine === job.engine);
      setEngine((cur) => (list.some((e) => e.engine === cur) ? cur
        : list.find((e) => e.status === "recomendado")?.engine ?? list[0]?.engine ?? ""));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setEst(null);
    } finally {
      setBusy(false);
    }
  };

  // Vindo de "Retraduzir…" na revisão: já calcula a previsão.
  useEffect(() => { if (props.initial) calculate(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const prepareResume = (j: Job) => {
    setResumeOf(j);
    calculate({ pages: j.pages, mode: j.mode, resume_of: j.id }, j);
  };

  const start = async () => {
    if (!chosen || !est) return;
    const value = num(budget);
    if (!(value > 0)) {
      setError("Informe um teto de gasto maior que zero.");
      return;
    }
    const what = resumeOf ? `Retomar a tarefa #${resumeOf.id}: ${chosen.segments_to_send} segmentos`
      : `Traduzir ${chosen.segments_to_send} segmentos (${MODE_LABEL[mode] ?? mode}; páginas ${spec})`;
    const ok = window.confirm(
      `${what} com ${chosen.label}?\n\n` +
      `Previsão: ${pollen(chosen.cost)} pollen (de ${pollen(chosen.cost_low)} a ${pollen(chosen.cost_high)}), ` +
      `cerca de ${minutes(chosen.minutes)}.\nTeto: ${pollen(value)} pollen — a tradução para antes de passar disso.\n\n` +
      "O texto (com os lances trocados por marcadores) será enviado à Pollinations.",
    );
    if (!ok) return;
    setBusy(true);
    setError("");
    try {
      if (resumeOf) await api.resumeJob(props.projectId, resumeOf.id, props.author, value);
      else await api.startJob(props.projectId, chosen.engine, selection(), value, props.author);
      await loadJobs();
      setEst(null);
      setResumeOf(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const saveLimit = async () => {
    const value = limit.trim() === "" ? null : num(limit);
    if (value !== null && !(value >= 0)) {
      setError("Teto do projeto inválido.");
      return;
    }
    try {
      await api.setLimit(props.projectId, value, props.author);
      props.onChange();
      setEst(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const reset = () => { setEst(null); setResumeOf(null); };

  return (
    <section className="translate">
      <h2>Traduzir</h2>
      <div className="row budget-line">
        <span>Gasto do projeto: <strong>{pollen(props.spent)} pollen</strong>
          {props.spendLimit != null && <> de {pollen(props.spendLimit)} (sobram {pollen(props.spendLimit - props.spent)})</>}
        </span>
        <label>
          Teto do projeto
          <input value={limit} onChange={(e) => setLimit(e.target.value)} inputMode="decimal" size={7}
                 placeholder="sem teto" />
        </label>
        <button disabled={!props.author.trim()} onClick={saveLimit}>Salvar teto</button>
      </div>
      {resumeOf ? (
        <p className="row">
          <strong>Retomando a tarefa #{resumeOf.id}</strong>
          <span className="muted">mesmo motor ({resumeOf.engine}), mesmas páginas e seleção; o que ela já tratou é pulado.</span>
          <button onClick={reset}>Voltar</button>
        </p>
      ) : (
        <form className="row" onSubmit={(e) => { e.preventDefault(); calculate(); }}>
          <label>
            Páginas
            <input value={spec} onChange={(e) => { setSpec(e.target.value); setEst(null); }} disabled={mode === "ids"}
                   placeholder="ex.: 1-441 ou 21,438" />
          </label>
          <label>
            O que traduzir
            <select value={mode} onChange={(e) => { setMode(e.target.value); setEst(null); }}>
              {Object.entries(MODE_LABEL).filter(([k]) => k !== "ids" || ids.length > 0).map(([k, v]) => (
                <option key={k} value={k}>{k === "ids" ? `${v} (${ids.length})` : v}</option>
              ))}
            </select>
          </label>
          {mode !== "pending" && (
            <label title="Sem isso, o mesmo motor devolve do cache a mesma tradução, sem custo.">
              <input type="checkbox" checked={fresh} onChange={(e) => { setFresh(e.target.checked); setEst(null); }} />
              pedir tradução nova (ignorar o cache)
            </label>
          )}
          <button disabled={busy || !spec.trim()}>Calcular previsão</button>
        </form>
      )}
      {mode !== "pending" && !resumeOf && (
        <p className="muted small">
          Versões editadas por pessoas nunca são substituídas. Se a nova tentativa falhar, a tradução anterior continua
          valendo; todas as versões ficam no histórico.
        </p>
      )}
      {error && <p className="bad" role="alert">{error}</p>}
      {est && (
        <>
          <p>
            {est.pages} páginas · {est.segments} segmentos: {est.already_translated} já traduzidos,{" "}
            {est.notation_only} só de notação, {est.pending} pendentes.{" "}
            <strong>Selecionados: {est.selected}</strong>.
          </p>
          {Object.keys(est.skipped).length > 0 && (
            <p className="muted small">
              Fora da seleção: {Object.entries(est.skipped).map(([k, v]) => `${v} ${SKIPPED[k] ?? k}`).join("; ")}.
            </p>
          )}
          {est.remaining != null && est.remaining <= 0 && (
            <p className="bad">O teto de gasto do projeto já foi atingido; aumente-o para traduzir mais.</p>
          )}
          {est.selected === 0 ? <p className="muted">Nada a traduzir com essa seleção.</p> : (
            <>
              <div className="table-wrap">
                <table className="engines">
                  <thead>
                    <tr>
                      <th />
                      <th>Motor</th>
                      <th>Preço por milhão de tokens<br /><small>entrada / saída</small></th>
                      <th>Custo previsto (pollen)</th>
                      <th>Tempo</th>
                      <th>Observações</th>
                    </tr>
                  </thead>
                  <tbody>
                    {shown.map((e) => (
                      <tr key={e.engine} className={e.engine === engine ? "chosen" : ""}
                          onClick={() => setEngine(e.engine)}>
                        <td>
                          <input type="radio" name="engine" checked={e.engine === engine}
                                 onChange={() => setEngine(e.engine)} aria-label={e.label} />
                        </td>
                        <td>
                          <strong>{e.label}</strong>
                          {e.status !== "disponível" && <span className={`chip ${e.status === "recomendado" ? "ok" : "bad"}`}>
                            {e.status}</span>}
                          <div className="muted small">{e.model}</div>
                        </td>
                        <td>{e.price_in_per_million} / {e.price_out_per_million}</td>
                        <td>
                          <strong>{pollen(e.cost)}</strong>
                          <div className="muted small">{pollen(e.cost_low)} – {pollen(e.cost_high)}</div>
                          {e.cached > 0 && <div className="muted small">{e.cached} do cache (grátis)</div>}
                        </td>
                        <td>{minutes(e.minutes)}<div className="muted small">{e.calls} chamadas</div></td>
                        <td className="small">{e.note}{e.notes.map((n) => <div key={n} className="bad">{n}</div>)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="muted small">
                Preços: {est.estimates[0]?.price_source}. A previsão monta os mesmos lotes que serão enviados e corrige
                pelo gasto medido de cada modelo; o raciocínio de alguns modelos varia, por isso a faixa. Antes de cada
                seção a tarefa confere se o custo previsto cabe no teto.
              </p>
              <div className="row">
                <label>
                  Teto desta tarefa (pollen)
                  <input value={budget} onChange={(e) => setBudget(e.target.value)} inputMode="decimal" size={8} />
                </label>
                <button className="primary" disabled={busy || !chosen || running || !props.author.trim()}
                        onClick={start}>
                  {resumeOf ? `Retomar #${resumeOf.id}` : `Iniciar com ${chosen?.label ?? "…"}`}
                </button>
                {!props.author.trim() && <span className="muted">Informe o nome do revisor.</span>}
                {running && <span className="muted">Já há uma tradução em andamento.</span>}
              </div>
            </>
          )}
        </>
      )}
      <h3>Traduções deste projeto</h3>
      {jobs.length === 0 && <p className="muted">Nenhuma ainda.</p>}
      <ul className="jobs">
        {jobs.map((j) => (
          <li key={j.id}>
            <div className="row">
              <strong>#{j.id} · {j.engine}</strong>
              <span>p. {j.pages}</span>
              {j.mode !== "pending" && <span className="chip">{MODE_LABEL[j.mode]?.split(" (")[0] ?? j.mode}</span>}
              {j.resumed_from != null && <span className="muted small">retoma #{j.resumed_from}</span>}
              <span className={["failed", "stopped_budget", "interrupted"].includes(j.state) ? "bad"
                : j.state.startsWith("done") ? "ok" : ""}>
                {STATE[j.state] ?? j.state}
              </span>
              {ACTIVE.has(j.state) && j.state !== "cancel_requested" && (
                <button onClick={async () => { await api.cancelJob(props.projectId, j.id); loadJobs(); }}>Cancelar</button>
              )}
              {RESUMABLE.has(j.state) && !running && !jobs.some((o) => o.resumed_from === j.id) && (
                <button onClick={() => prepareResume(j)}>Retomar…</button>
              )}
            </div>
            <progress max={Math.max(1, j.total)} value={j.done} aria-label={`Progresso da tradução ${j.id}`} />
            <div className="muted small">
              {j.done}/{j.total} segmentos · gasto {pollen(j.cost)} pollen
              {j.estimate != null && ` (previsto ${pollen(j.estimate)})`} · teto {pollen(j.budget)}
              {Object.keys(j.counts).length > 0 &&
                ` · ${Object.entries(j.counts).map(([k, v]) => `${COUNT[k] ?? k}: ${v}`).join(", ")}`}
            </div>
            {j.error && <div className="bad small">{j.error}</div>}
          </li>
        ))}
      </ul>
    </section>
  );
}
