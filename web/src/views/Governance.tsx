import { Fragment, useEffect, useState } from 'react';
import { api, fmtBytes } from '../api';
import Scorecard from './Scorecard';

interface Gov {
  policy: { allowedViews: string[]; maxBytesPerQuery: number; maxRows: number; readOnly: boolean; maskedFields: string[] };
  totals: { status: string; n: number; bytes: number | null }[];
  log: { ts: string; question: string; sql: string; status: string; reason: string | null; bytes_processed: number | null; rows_returned: number | null }[];
}

export default function Governance() {
  const [g, setG] = useState<Gov | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  useEffect(() => { api<Gov>('/api/governance').then(setG).catch((e) => setError(e.message)); }, []);
  if (error) return <div className="page"><div className="notice error">{error}</div></div>;
  if (!g) return <div className="page muted"><span className="spinner" /> Loading…</div>;
  const total = (s: string) => g.totals.find((t) => t.status === s)?.n ?? 0;
  return (
    <div className="page">
      <h1>Governance</h1>
      <p className="muted">The model never touches BigQuery directly. Every SQL statement it writes passes these checks in code, and every attempt is logged.</p>
      <div className="kpis">
        <div className="kpi"><span>Queries allowed (7 days)</span><strong>{total('ALLOWED')}</strong></div>
        <div className="kpi"><span>Blocked by policy</span><strong>{total('BLOCKED')}</strong></div>
        <div className="kpi"><span>Errors (self-corrected)</span><strong>{total('ERROR')}</strong></div>
        <div className="kpi"><span>Data scanned</span><strong>{fmtBytes(g.totals.reduce((s, t) => s + (t.bytes ?? 0), 0))}</strong></div>
      </div>
      <div className="policy">
        <div><h3>Guardrails</h3><ul>
          <li>Read-only: one SELECT statement, no DML or DDL</li>
          <li>Only approved views; raw tables and INFORMATION_SCHEMA are refused</li>
          <li>Dry run first; refused above {fmtBytes(g.policy.maxBytesPerQuery)} scanned, and BigQuery enforces the same cap</li>
          <li>At most {g.policy.maxRows} rows returned to the model</li>
          <li>Every query labeled and written to the audit log</li></ul></div>
        <div><h3>Approved views</h3><ul>{g.policy.allowedViews.map((v) => <li key={v}><code>{v}</code></li>)}</ul></div>
        <div><h3>Hidden from the AI</h3><ul>{g.policy.maskedFields.map((m) => <li key={m}>{m}</li>)}</ul></div>
      </div>
      <h2>AI quality scorecard</h2>
      <Scorecard />
      <h2>Audit log</h2>
      <div className="table-wrap"><table>
        <thead><tr><th>Time</th><th>Status</th><th>Question</th><th className="num">Scanned</th><th className="num">Rows</th><th>Reason</th></tr></thead>
        <tbody>{g.log.map((r, i) => (
          <Fragment key={i}>
            <tr className="clickable" onClick={() => setOpen(open === i ? null : i)}>
              <td className="small">{new Date(r.ts).toLocaleString()}</td>
              <td><span className={`badge ${r.status.toLowerCase()}`}>{r.status}</span></td>
              <td>{r.question}</td><td className="num">{r.bytes_processed != null ? fmtBytes(r.bytes_processed) : '-'}</td>
              <td className="num">{r.rows_returned ?? '-'}</td><td className="small">{r.reason?.slice(0, 120) ?? ''}</td>
            </tr>
            {open === i && <tr><td colSpan={6}><pre className="sql">{r.sql}</pre></td></tr>}
          </Fragment>
        ))}</tbody>
      </table></div>
    </div>
  );
}
