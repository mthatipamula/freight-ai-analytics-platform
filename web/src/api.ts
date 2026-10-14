export async function api<T = any>(path: string, init: RequestInit = {}): Promise<T> { // eslint-disable-line
  const res = await fetch(path, init);
  const text = await res.text();
  const body = text ? (() => { try { return JSON.parse(text); } catch { return text; } })() : null;
  if (!res.ok) throw new Error(typeof body?.detail === 'string' ? body.detail : res.statusText);
  return body as T;
}

/** Reads the agent's NDJSON stream and calls onEvent for each step as it arrives. */
export async function streamAsk(question: string, sessionId: string | null, onEvent: (e: AgentEvent) => void): Promise<void> {
  const res = await fetch('/api/ask', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, session_id: sessionId }),
  });
  if (!res.ok || !res.body) throw new Error(`Request failed (${res.status})`);
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let nl;
    while ((nl = buffer.indexOf('\n')) >= 0) {
      const line = buffer.slice(0, nl).trim();
      buffer = buffer.slice(nl + 1);
      if (line) onEvent(JSON.parse(line));
    }
  }
}

export interface QueryResult { index: number; sql: string; columns: string[]; rows: unknown[][]; bytes: number; truncated: boolean; rowCount?: number }
export interface ChartSpec { type: 'bar' | 'line' | 'table'; x?: string; y?: string; title: string }
export type AgentEvent =
  | { type: 'session'; sessionId: string; model: string }
  | { type: 'step'; step: number; purpose: string; sql: string }
  | ({ type: 'result' } & QueryResult)
  | { type: 'blocked'; reason: string; sql: string }
  | { type: 'sql_error'; message: string }
  | { type: 'error'; message: string }
  | { type: 'answer'; answer: string; chart: ChartSpec | null; result: QueryResult | null; followUps: string[]; queries?: number };

export const fmtNum = (v: unknown, col = ''): string => {
  if (v == null) return '-';
  if (typeof v !== 'number') return String(v);
  if (/rate|pct|percent/i.test(col)) return v <= 1 ? `${(v * 100).toFixed(1)}%` : `${v.toFixed(1)}%`;
  if (/revenue|amount|usd|cost/i.test(col)) return v.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });
  return Number.isInteger(v) ? v.toLocaleString('en-US') : v.toLocaleString('en-US', { maximumFractionDigits: 2 });
};
export const fmtBytes = (b: number) => (b > 1e6 ? `${(b / 1e6).toFixed(1)} MB` : `${Math.round(b / 1e3)} KB`);
