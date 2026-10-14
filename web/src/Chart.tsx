import { useState } from 'react';
import { fmtNum, type ChartSpec, type QueryResult } from './api';

/** Single-series bar or line chart for one query result, with hover values and a table view. */
export default function Chart({ spec, result }: { spec: ChartSpec; result: QueryResult }) {
  const [asTable, setAsTable] = useState(spec.type === 'table');
  const [hover, setHover] = useState<number | null>(null);
  const xi = spec.x ? result.columns.indexOf(spec.x) : -1;
  const yi = spec.y ? result.columns.indexOf(spec.y) : -1;
  const points = xi >= 0 && yi >= 0
    ? result.rows.slice(0, 40).map((r) => ({ x: String(r[xi] ?? ''), y: Number(r[yi]) })).filter((p) => Number.isFinite(p.y))
    : [];
  const canChart = points.length > 0 && spec.type !== 'table';
  const isLine = spec.type === 'line';
  const data = isLine ? [...points].sort((a, b) => a.x.localeCompare(b.x)) : points;

  const W = 720, H = 300, L = 84, R = 16, Tp = 16, B = 70;
  // Rates stored as fractions (0-1) cap the axis at 100% so every tick formats as a percentage.
  const fraction = /rate|pct|percent/i.test(spec.y ?? '') && data.every((p) => p.y <= 1);
  const dataMax = Math.max(...data.map((p) => p.y), 0);
  let min = 0, max = fraction ? Math.min(1, niceCeil(dataMax * 1.05)) : niceCeil(dataMax * 1.05);
  if (isLine) {  // lines zoom to the data range, with four round tick steps
    const lo = Math.min(...data.map((p) => p.y)) * 0.97;
    let tick = niceCeil((dataMax - lo) / 4 || 1);
    min = Math.floor(lo / tick) * tick;
    if (min + 4 * tick < dataMax) tick = niceCeil(tick * 1.01);
    max = min + 4 * tick;
  }
  const yScale = (v: number) => Tp + (H - Tp - B) * (1 - (v - min) / (max - min || 1));
  const step = (W - L - R) / Math.max(1, data.length);
  const xPos = (i: number) => L + step * i + step / 2;
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((t) => min + (max - min) * t);

  return (
    <figure className="chart">
      <figcaption>
        <span className="chart-title">{spec.title}</span>
        {canChart && <button className="link small" onClick={() => setAsTable(!asTable)}>{asTable ? 'Show chart' : 'Show table'}</button>}
      </figcaption>
      {canChart && !asTable ? (
        <div className="chart-box">
          <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={spec.title}>
            {ticks.map((t) => (
              <g key={t}>
                <line x1={L} x2={W - R} y1={yScale(t)} y2={yScale(t)} className="grid" />
                <text x={L - 8} y={yScale(t) + 4} textAnchor="end" className="axis">{fmtNum(t, spec.y)}</text>
              </g>
            ))}
            {isLine ? (
              <>
                <polyline fill="none" className="line" points={data.map((p, i) => `${xPos(i)},${yScale(p.y)}`).join(' ')} />
                {data.map((p, i) => <circle key={i} cx={xPos(i)} cy={yScale(p.y)} r={hover === i ? 5 : 3} className="dot" />)}
              </>
            ) : data.map((p, i) => (
              <rect key={i} x={xPos(i) - Math.min(28, step * 0.35)} width={Math.min(56, step * 0.7)} y={yScale(p.y)}
                    height={Math.max(1, H - B - yScale(p.y))} rx={3} className={`bar ${hover === i ? 'active' : ''}`} />
            ))}
            {data.map((p, i) => (data.length <= 14 || i % Math.ceil(data.length / 14) === 0) && (
              <text key={`l${i}`} x={xPos(i)} y={H - B + 18} textAnchor="end" transform={`rotate(-30 ${xPos(i)} ${H - B + 18})`} className="axis">
                {p.x.length > 14 ? `${p.x.slice(0, 13)}…` : p.x}</text>
            ))}
            {data.map((_, i) => (
              <rect key={`h${i}`} x={xPos(i) - step / 2} y={Tp} width={step} height={H - Tp - B} fill="transparent"
                    onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} />
            ))}
          </svg>
          {hover != null && data[hover] && (
            <div className="tooltip" style={{ left: `${(xPos(hover) / W) * 100}%` }}>
              <div className="muted small">{data[hover].x}</div><strong>{fmtNum(data[hover].y, spec.y)}</strong>
            </div>
          )}
        </div>
      ) : <ResultTable result={result} />}
    </figure>
  );
}

/** Rounds up to 1, 2, 2.5 or 5 times a power of ten so axis ticks are round numbers. */
function niceCeil(v: number): number {
  if (v <= 0) return 1;
  const p = 10 ** Math.floor(Math.log10(v));
  return ([1, 2, 2.5, 5, 10].find((m) => m * p >= v) ?? 10) * p;
}

export function ResultTable({ result, limit = 25 }: { result: QueryResult; limit?: number }) {
  return (
    <div className="table-wrap">
      <table>
        <thead><tr>{result.columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
        <tbody>{result.rows.slice(0, limit).map((r, i) => (
          <tr key={i}>{r.map((v, j) => <td key={j} className={typeof v === 'number' ? 'num' : ''}>{fmtNum(v, result.columns[j])}</td>)}</tr>
        ))}</tbody>
      </table>
      {result.rows.length > limit && <p className="muted small">Showing {limit} of {result.rows.length} rows.</p>}
    </div>
  );
}
