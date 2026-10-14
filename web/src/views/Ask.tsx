import { useEffect, useRef, useState } from 'react';
import { api, fmtBytes, fmtNum, streamAsk, type AgentEvent, type QueryResult } from '../api';
import Chart, { ResultTable } from '../Chart';

const SUGGESTIONS = [
  'Which 5 destination terminals had the worst on-time delivery in the last 30 days?',
  'Why is Atlanta on-time performance low?',
  'Which hub has the highest damage claim rate, and what does it cost us?',
  'Show weekly shipment volume and revenue trend for the last 12 weeks',
  'Which grocery distribution centers miss the most delivery appointments?',
  'Which customers are holding our trailers longer than 48 hours?',
  'Where are empty trailers piling up?',
];

interface Turn { question: string; events: AgentEvent[]; done: boolean }
interface Overview { shipments: number; on_time_pct: number; revenue: number; in_transit: number; claims: number; open_claims: number; claim_amount: number }

export default function Ask({ initialQuestion, onStarted }: { initialQuestion?: string | null; onStarted?: () => void }) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [question, setQuestion] = useState('');
  const [busy, setBusy] = useState(false);
  const [kpi, setKpi] = useState<Overview | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => { api<Overview>('/api/overview').then(setKpi).catch(() => setKpi(null)); }, []);
  useEffect(() => { endRef.current?.scrollIntoView({ block: 'end', behavior: 'smooth' }); }, [turns]);
  useEffect(() => { if (initialQuestion) { onStarted?.(); void ask(initialQuestion); } }, [initialQuestion]); // eslint-disable-line react-hooks/exhaustive-deps

  async function ask(q: string) {
    const text = q.trim();
    if (!text || busy) return;
    setBusy(true); setQuestion('');
    setTurns((t) => [...t, { question: text, events: [], done: false }]);
    const push = (e: AgentEvent) => {
      if (e.type === 'session') setSessionId(e.sessionId);
      setTurns((t) => t.map((turn, i) => (i === t.length - 1 ? { ...turn, events: [...turn.events, e] } : turn)));
    };
    try { await streamAsk(text, sessionId, push); }
    catch (err) { push({ type: 'error', message: (err as Error).message }); }
    setTurns((t) => t.map((turn, i) => (i === t.length - 1 ? { ...turn, done: true } : turn)));
    setBusy(false);
  }

  return (
    <div className="ask">
      {kpi && (
        <div className="kpis">
          <div className="kpi"><span>Shipments (30 days)</span><strong>{fmtNum(kpi.shipments)}</strong></div>
          <div className="kpi"><span>On-time delivery</span><strong>{kpi.on_time_pct}%</strong></div>
          <div className="kpi"><span>Revenue</span><strong>{fmtNum(kpi.revenue, 'revenue')}</strong></div>
          <div className="kpi"><span>In transit now</span><strong>{fmtNum(kpi.in_transit)}</strong></div>
          <div className="kpi"><span>Claims filed (open)</span><strong>{kpi.claims} ({kpi.open_claims})</strong></div>
        </div>
      )}
      {turns.length === 0 && (
        <div className="welcome">
          <h1>Ask your freight data</h1>
          <p className="muted">Gemini writes and runs governed BigQuery SQL against the approved views, then explains the answer. Every query is checked and audited.</p>
          <div className="suggestions">{SUGGESTIONS.map((s) => <button key={s} className="suggestion" onClick={() => ask(s)}>{s}</button>)}</div>
        </div>
      )}
      <div className="turns">{turns.map((t, i) => <TurnView key={i} turn={t} onAsk={ask} />)}<div ref={endRef} /></div>
      <form className="ask-bar" onSubmit={(e) => { e.preventDefault(); void ask(question); }}>
        <input value={question} onChange={(e) => setQuestion(e.target.value)} disabled={busy} maxLength={1000}
               placeholder={turns.length ? 'Ask a follow-up, e.g. "why?" or "break it down by lane"' : 'Ask a question about shipments, terminals, claims…'} />
        <button disabled={busy || question.trim().length < 3}>{busy ? 'Working…' : 'Ask'}</button>
        {turns.length > 0 && <button type="button" className="secondary" disabled={busy} onClick={() => { setTurns([]); setSessionId(null); }}>New conversation</button>}
      </form>
    </div>
  );
}

function TurnView({ turn, onAsk }: { turn: Turn; onAsk: (q: string) => void }) {
  const answer = turn.events.find((e) => e.type === 'answer') as Extract<AgentEvent, { type: 'answer' }> | undefined;
  const error = turn.events.find((e) => e.type === 'error') as Extract<AgentEvent, { type: 'error' }> | undefined;
  const steps = turn.events.filter((e) => ['step', 'result', 'blocked', 'sql_error'].includes(e.type));
  const [showSteps, setShowSteps] = useState(true);
  useEffect(() => { if (answer) setShowSteps(false); }, [answer]);
  const queries = steps.filter((e) => e.type === 'result').length;
  const bytes = steps.reduce((s, e) => s + (e.type === 'result' ? e.bytes : 0), 0);

  return (
    <article className="turn">
      <div className="question">{turn.question}</div>
      <div className="steps-head">
        <button className="link small" onClick={() => setShowSteps(!showSteps)}>
          {showSteps ? 'Hide' : 'Show'} how the AI got this ({queries} quer{queries === 1 ? 'y' : 'ies'}, {fmtBytes(bytes)} scanned)</button>
        {!turn.done && <span className="muted small"><span className="spinner" /> working…</span>}
      </div>
      {showSteps && (
        <ol className="steps">{steps.map((e, i) => <StepView key={i} e={e} />)}</ol>
      )}
      {answer && (
        <div className="answer">
          <p className="answer-text">{answer.answer}</p>
          {answer.chart && answer.result && <Chart spec={answer.chart} result={answer.result} />}
          {answer.followUps.length > 0 && (
            <div className="followups">{answer.followUps.map((f) => <button key={f} className="suggestion small" onClick={() => onAsk(f)}>{f}</button>)}</div>
          )}
        </div>
      )}
      {error && <div className="notice error">{error.message}</div>}
    </article>
  );
}

function StepView({ e }: { e: AgentEvent }) {
  const [open, setOpen] = useState(false);
  if (e.type === 'step') {
    return <li className="step"><span className="step-num">{e.step}</span><div><strong>{e.purpose}</strong>
      <button className="link small" onClick={() => setOpen(!open)}>{open ? 'hide SQL' : 'SQL'}</button>
      {open && <pre className="sql">{e.sql}</pre>}</div></li>;
  }
  if (e.type === 'result') {
    const r = e as QueryResult;
    return <li className="step result"><span className="muted small">↳ {r.rowCount ?? r.rows.length} rows · {fmtBytes(r.bytes)} scanned</span>
      {r.rows.length > 0 && <details><summary className="small">preview</summary><ResultTable result={r} limit={8} /></details>}</li>;
  }
  if (e.type === 'blocked') return <li className="step blocked">🛡️ Blocked by governance: {e.reason}</li>;
  if (e.type === 'sql_error') return <li className="step fixed">↺ Query error; the AI is correcting it: <span className="small">{e.message.slice(0, 160)}</span></li>;
  return null;
}
