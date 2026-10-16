import { Fragment, useEffect, useState } from 'react';
import { api } from '../api';

interface Check { name: string; passed: boolean; detail: string }
interface EvalRow { case_id: string; category: string; question: string; expected: string; passed: boolean; checks: Check[];
  answer: string; latency_s: number; queries: number; blocked: number; sql_errors: number; cost_usd: number; model: string; run_ts: string }

const CATEGORY: Record<string, string> = { accuracy: 'Accuracy', metric: 'Metric definitions', safety: 'Safety' };

/** Latest AI quality scorecard run: fixed questions with expected answers computed from BigQuery. */
export default function Scorecard() {
  const [rows, setRows] = useState<EvalRow[] | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  useEffect(() => { api<{ rows: EvalRow[] }>('/api/evals').then((d) => setRows(d.rows)).catch(() => setRows([])); }, []);
  if (!rows) return <p className="muted small"><span className="spinner" /> Loading scorecard…</p>;
  if (!rows.length) return <p className="muted">No scorecard yet. Run <code>./scripts/dev.sh eval</code>.</p>;
  const passed = rows.filter((r) => r.passed).length;
  const avg = (f: (r: EvalRow) => number) => rows.reduce((s, r) => s + f(r), 0) / rows.length;
  const byCat = (c: string) => rows.filter((r) => r.category === c);
  return (
    <>
      <p className="muted small">Run {new Date(rows[0].run_ts).toLocaleString()} with {rows[0].model}. Expected answers are computed with
        fixed SQL at run time; safety cases must be refused or blocked. Run before any prompt or model change.</p>
      <div className="kpis">
        <div className={`kpi ${passed === rows.length ? 'good' : 'alert'}`}><span>Passed</span><strong>{passed} / {rows.length}</strong></div>
        {Object.keys(CATEGORY).map((c) => (
          <div className="kpi" key={c}><span>{CATEGORY[c]}</span><strong>{byCat(c).filter((r) => r.passed).length} / {byCat(c).length}</strong></div>))}
        <div className="kpi"><span>Avg time per question</span><strong>{avg((r) => r.latency_s).toFixed(0)} s</strong></div>
        <div className="kpi"><span>Avg cost per question</span><strong>${avg((r) => r.cost_usd).toFixed(3)}</strong></div>
      </div>
      <div className="table-wrap"><table>
        <thead><tr><th>Result</th><th>Type</th><th>Question</th><th>Expected</th><th className="num">Queries</th><th className="num">Time</th><th className="num">Cost</th></tr></thead>
        <tbody>{rows.map((r) => (
          <Fragment key={r.case_id}>
            <tr className="clickable" onClick={() => setOpen(open === r.case_id ? null : r.case_id)}>
              <td><span className={`badge ${r.passed ? 'allowed' : 'blocked'}`}>{r.passed ? 'PASS' : 'FAIL'}</span></td>
              <td className="small">{CATEGORY[r.category]}</td><td>{r.question}</td><td className="small">{r.expected}</td>
              <td className="num">{r.queries}{r.blocked ? ` (+${r.blocked} blocked)` : ''}</td>
              <td className="num">{r.latency_s.toFixed(0)} s</td><td className="num">${r.cost_usd.toFixed(3)}</td>
            </tr>
            {open === r.case_id && (
              <tr><td colSpan={7}>
                <ul className="checks">{r.checks.map((c) => (
                  <li key={c.name} className={c.passed ? '' : 'bad'}>{c.passed ? '✓' : '✗'} {c.name} <span className="muted small">· {c.detail}</span></li>))}</ul>
                <p className="small answer-text">{r.answer}</p>
              </td></tr>)}
          </Fragment>))}</tbody>
      </table></div>
    </>
  );
}
