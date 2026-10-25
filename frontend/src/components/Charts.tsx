// Small hand-written SVG charts (no chart library). Each chart also has a visually hidden table with the same
// numbers, so screen-reader users get the data, not just a picture.

import { useEffect, useRef, useState } from "react";

interface DayPoint {
  date: string;
  questions: number;
  refused: number;
}

export function VolumeChart({ series }: { series: DayPoint[] }) {
  // drawn at its real display width (measured), so axis text stays the same readable size on phones and desktops
  const box = useRef<HTMLElement>(null);
  const [W, setW] = useState(1000);
  useEffect(() => {
    const el = box.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(([e]) => setW(Math.max(280, Math.round(e.contentRect.width))));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const H = W < 500 ? 200 : 240;
  const pad = { l: 34, r: 8, t: 12, b: 28 };
  const max = Math.max(1, ...series.map((d) => d.questions));
  const bw = (W - pad.l - pad.r) / Math.max(series.length, 1);
  const y = (v: number) => pad.t + (H - pad.t - pad.b) * (1 - v / top);
  // whole-number gridlines: every value up to 5, otherwise about four even steps
  const step = max <= 5 ? 1 : Math.ceil(max / 4);
  const top = Math.ceil(max / step) * step;
  const ticks = Array.from({ length: top / step + 1 }, (_, i) => i * step);
  // a label every few days, plus the last day unless it would crowd the previous label
  const every = Math.ceil(series.length / (W < 500 ? 4 : 7));
  const last = series.length - 1;
  const showLabel = (i: number) => i % every === 0 ? last - i >= every / 2 || i === last : i === last;
  const label = (iso: string) => new Date(iso + "T00:00:00").toLocaleDateString(undefined, { day: "numeric", month: "short" });

  return (
    <figure className="chart" ref={box}>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Questions per day, answered and refused">
        {ticks.map((t) => (
          <g key={t}>
            <line x1={pad.l} x2={W - pad.r} y1={y(t)} y2={y(t)} className="gridline" />
            <text x={pad.l - 6} y={y(t) + 4} textAnchor="end" className="axis">
              {t}
            </text>
          </g>
        ))}
        {series.map((d, i) => {
          const x = pad.l + i * bw + bw * 0.15;
          const w = bw * 0.7;
          const answered = d.questions - d.refused;
          return (
            <g key={d.date}>
              <rect x={x} y={y(answered)} width={w} height={y(0) - y(answered)} className="bar-answered" rx={2}>
                <title>{`${label(d.date)}: ${answered} answered`}</title>
              </rect>
              <rect x={x} y={y(d.questions)} width={w} height={y(answered) - y(d.questions)} className="bar-refused" rx={2}>
                <title>{`${label(d.date)}: ${d.refused} refused`}</title>
              </rect>
              {showLabel(i) && (
                <text x={i === series.length - 1 ? x + w : x + w / 2} y={H - 6} textAnchor={i === series.length - 1 ? "end" : "middle"} className="axis">
                  {label(d.date)}
                </text>
              )}
            </g>
          );
        })}
      </svg>
      <figcaption className="legend">
        <span>
          <span className="key key-answered" /> Answered
        </span>
        <span>
          <span className="key key-refused" /> Refused (not in the documents)
        </span>
      </figcaption>
      <table className="sr-only">
        <caption>Questions per day</caption>
        <thead>
          <tr>
            <th>Date</th>
            <th>Questions</th>
            <th>Refused</th>
          </tr>
        </thead>
        <tbody>
          {series.map((d) => (
            <tr key={d.date}>
              <td>{d.date}</td>
              <td>{d.questions}</td>
              <td>{d.refused}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}

// Share of one value in a whole, as a horizontal bar (e.g. helpful vs not helpful)
export function SplitBar({ a, b, aLabel, bLabel }: { a: number; b: number; aLabel: string; bLabel: string }) {
  const total = a + b;
  const pa = total ? Math.round((a / total) * 100) : 0;
  return (
    <div className="split">
      <div className="split-bar" role="img" aria-label={`${aLabel} ${a}, ${bLabel} ${b}`}>
        {total > 0 && <span className="split-a" style={{ width: `${pa}%` }} />}
        {total > 0 && <span className="split-b" style={{ width: `${100 - pa}%` }} />}
      </div>
      <div className="split-legend">
        <span>
          <span className="key key-answered" /> {aLabel} {a}
        </span>
        <span>
          <span className="key key-refused" /> {bLabel} {b}
        </span>
      </div>
    </div>
  );
}

export function Stat({ value, label, hint }: { value: string; label: string; hint?: string }) {
  return (
    <div className="stat">
      <b>{value}</b>
      <span>{label}</span>
      {hint && <small>{hint}</small>}
    </div>
  );
}
