import { useEffect, useState } from "react";
import { api, Quality } from "./api";

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

export default function QualityView(props: { projectId: string; onOpenPage: (page: number) => void }) {
  const [q, setQ] = useState<Quality | null>(null);
  const [error, setError] = useState("");
  const [onlyProblems, setOnlyProblems] = useState(true);

  useEffect(() => {
    api.quality(props.projectId).then(setQ, (e) => setError(e instanceof Error ? e.message : String(e)));
  }, [props.projectId]);

  if (error) return <section className="quality"><h2>Qualidade</h2><p className="muted">{error}</p></section>;
  if (!q) return <section className="quality"><h2>Qualidade</h2><p className="muted">Carregando…</p></section>;
  const shown = q.pages.filter((p) => !onlyProblems || !p.ok);
  const counts: Record<string, number> = {};
  q.pages.forEach((p) => Object.keys(p.issues).forEach((k) => { counts[k] = (counts[k] ?? 0) + 1; }));

  return (
    <section className="quality">
      <h2>Qualidade da montagem</h2>
      <p>
        <strong>{q.pages_ok}</strong> de {q.pages_total} páginas sem pendências · montado em{" "}
        {q.assembled_at.replace("T", " ")} (edições posteriores só aparecem depois de montar de novo)
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
