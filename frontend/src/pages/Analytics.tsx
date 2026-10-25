import { useState } from "react";
import { api } from "../api";
import { SplitBar, Stat, VolumeChart } from "../components/Charts";
import { Loading } from "../components/Loading";
import { useLoad } from "../components/useLoad";
import { useKb } from "./KbShell";

export function AnalyticsPage() {
  const { kb } = useKb();
  const [days, setDays] = useState(14);
  const { data: a, error } = useLoad(() => api.analytics(kb.id, days), [kb.id, days]);

  if (error) return <p className="error">{error}</p>;
  if (!a) return <Loading label="Crunching the numbers…" />;
  const rated = a.feedback.up + a.feedback.down;
  const ms = (v: number | null) => (v === null ? "–" : `${Math.round(v)} ms`);

  return (
    <>
      <div className="toolbar">
        <label>
          Period{" "}
          <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
            <option value={7}>Last 7 days</option>
            <option value={14}>Last 14 days</option>
            <option value={30}>Last 30 days</option>
            <option value={90}>Last 90 days</option>
          </select>
        </label>
      </div>
      <div className="stats">
        <Stat value={String(a.questions)} label="questions" />
        <Stat value={`${Math.round(a.refusal_rate * 100)}%`} label="refused" hint={`${a.refused} not covered by the documents`} />
        <Stat value={rated ? `${Math.round((a.feedback.up / rated) * 100)}%` : "–"} label="rated helpful" hint={`${rated} ratings`} />
        <Stat value={ms(a.latency_ms.p95)} label="p95 answer time" hint={a.latency_ms.p50 === null ? "no timed answers in this period" : `median ${ms(a.latency_ms.p50)}`} />
      </div>
      <div className="analytics-grid">
        <section className="card wide-card">
          <h2>Questions per day</h2>
          <VolumeChart series={a.series} />
        </section>
        <section className="card">
          <h2>Feedback</h2>
          <SplitBar a={a.feedback.up} b={a.feedback.down} aLabel="Helpful" bLabel="Not helpful" />
          <h3>Low-rated answers</h3>
          {a.low_rated.length === 0 && <p className="muted small">No thumbs-down yet.</p>}
          <ul className="low-rated">
            {a.low_rated.map((r) => (
              <li key={r.message_id}>
                <p className="strong">{r.question}</p>
                {r.comment && <p className="quote">“{r.comment}”</p>}
                <p className="muted small">Cited: {r.sources.join(", ") || "nothing"}</p>
              </li>
            ))}
          </ul>
        </section>
        <section className="card">
          <h2>Gaps: questions the documents do not answer</h2>
          <p className="muted small">Refused questions grouped by their most common word. Each group is a candidate for a new article.</p>
          {a.gaps.length === 0 && <p className="muted small">No refused questions in this period.</p>}
          <ol className="gaps">
            {a.gaps.map((g) => (
              <li key={g.topic}>
                <div className="gap-head">
                  <span className="topic">{g.topic}</span>
                  <span className="pill warn">
                    {g.count} question{g.count === 1 ? "" : "s"}
                  </span>
                </div>
                <ul>
                  {g.examples.map((q) => (
                    <li key={q} className="small">
                      {q}
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ol>
        </section>
      </div>
      <p className="muted small">Includes sample conversations from the demo seed (marked “demo” under Conversations); their ratings are invented.</p>
    </>
  );
}
