import { useCallback, useEffect, useState } from "react";
import { api, EstimateResponse, Job } from "./api";

const STATE: Record<string, string> = {
  queued: "na fila",
  running: "traduzindo",
  cancel_requested: "cancelando…",
  done: "concluída",
  done_with_warnings: "concluída com pendências",
  cancelled: "cancelada",
  stopped_budget: "parou no teto de gasto",
  failed: "falhou",
};
const ACTIVE = new Set(["queued", "running", "cancel_requested"]);
const pollen = (v: number) => (v < 0.01 ? v.toFixed(4) : v < 1 ? v.toFixed(3) : v.toFixed(2));
const minutes = (m: number) => (m < 60 ? `${Math.max(1, Math.round(m))} min` : `${(m / 60).toFixed(1)} h`);

export default function TranslateView(props: { projectId: string; pages: number; author: string;
                                               onChange: () => void }) {
  const [spec, setSpec] = useState(`1-${props.pages}`);
  const [est, setEst] = useState<EstimateResponse | null>(null);
  const [engine, setEngine] = useState("");
  const [budget, setBudget] = useState("");
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

  const chosen = est?.estimates.find((e) => e.engine === engine);
  useEffect(() => {
    // Teto sugerido: o topo da faixa prevista, com folga de 20 %.
    if (chosen) setBudget(pollen(Math.max(chosen.cost_high * 1.2, 0.001)));
  }, [chosen]);

  const calculate = async () => {
    setBusy(true);
    setError("");
    try {
      const out = await api.estimate(props.projectId, spec);
      setEst(out);
      setEngine((cur) => (out.estimates.some((e) => e.engine === cur) ? cur
        : out.estimates.find((e) => e.status === "recomendado")?.engine ?? out.estimates[0]?.engine ?? ""));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setEst(null);
    } finally {
      setBusy(false);
    }
  };

  const start = async () => {
    if (!chosen || !est) return;
    const value = Number(budget.replace(",", "."));
    if (!(value > 0)) {
      setError("Informe um teto de gasto maior que zero.");
      return;
    }
    const ok = window.confirm(
      `Traduzir ${chosen.segments_to_send} segmentos (páginas ${spec}) com ${chosen.label}?\n\n` +
      `Previsão: ${pollen(chosen.cost)} pollen (de ${pollen(chosen.cost_low)} a ${pollen(chosen.cost_high)}), ` +
      `cerca de ${minutes(chosen.minutes)}.\nTeto: ${pollen(value)} pollen — a tradução para se passar disso.\n\n` +
      "O texto (com os lances trocados por marcadores) será enviado à Pollinations.",
    );
    if (!ok) return;
    setBusy(true);
    setError("");
    try {
      await api.startJob(props.projectId, chosen.engine, spec, value, props.author);
      await loadJobs();
      setEst(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="translate">
      <h2>Traduzir</h2>
      <form className="row" onSubmit={(e) => { e.preventDefault(); calculate(); }}>
        <label>
          Páginas
          <input value={spec} onChange={(e) => { setSpec(e.target.value); setEst(null); }}
                 placeholder="ex.: 1-441 ou 21,438" aria-describedby="pages-help" />
        </label>
        <button disabled={busy || !spec.trim()}>Calcular previsão</button>
        <span id="pages-help" className="muted">Só os parágrafos ainda não traduzidos entram na conta.</span>
      </form>
      {error && <p className="bad" role="alert">{error}</p>}
      {est && (
        <>
          <p>
            {est.pages} páginas · {est.segments} segmentos: {est.already_translated} já traduzidos,{" "}
            {est.notation_only} só de notação (não são enviados), <strong>{est.pending} pendentes</strong>.
          </p>
          {est.pending === 0 ? <p className="muted">Nada a traduzir nessas páginas.</p> : (
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
                    {est.estimates.map((e) => (
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
                pelo gasto medido de cada modelo; o raciocínio de alguns modelos varia, por isso a faixa.
              </p>
              <div className="row">
                <label>
                  Teto de gasto (pollen)
                  <input value={budget} onChange={(e) => setBudget(e.target.value)} inputMode="decimal" size={8} />
                </label>
                <button className="primary" disabled={busy || !chosen || running || !props.author.trim()}
                        onClick={start}>
                  Iniciar tradução com {chosen?.label ?? "…"}
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
              <span className={j.state === "failed" || j.state === "stopped_budget" ? "bad" : j.state.startsWith("done") ? "ok" : ""}>
                {STATE[j.state] ?? j.state}
              </span>
              {ACTIVE.has(j.state) && j.state !== "cancel_requested" && (
                <button onClick={async () => { await api.cancelJob(props.projectId, j.id); loadJobs(); }}>Cancelar</button>
              )}
            </div>
            <progress max={Math.max(1, j.total)} value={j.done} aria-label={`Progresso da tradução ${j.id}`} />
            <div className="muted small">
              {j.done}/{j.total} segmentos · gasto {pollen(j.cost)} pollen
              {j.estimate != null && ` (previsto ${pollen(j.estimate)})`} · teto {pollen(j.budget)}
              {Object.keys(j.counts).length > 0 && ` · ${Object.entries(j.counts).map(([k, v]) => `${k}: ${v}`).join(", ")}`}
            </div>
            {j.error && <div className="bad small">{j.error}</div>}
          </li>
        ))}
      </ul>
    </section>
  );
}
