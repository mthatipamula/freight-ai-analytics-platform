import { useEffect, useState } from 'react';
import { api } from './api';
import Ask from './views/Ask';
import Catalog from './views/Catalog';
import Documents from './views/Documents';
import Governance from './views/Governance';

type View = 'ask' | 'documents' | 'governance' | 'catalog';
const NAV: [View, string][] = [['ask', 'Ask your data'], ['documents', 'Bills of lading'], ['governance', 'Governance'], ['catalog', 'Data catalog']];

export default function App() {
  const [view, setView] = useState<View>('ask');
  const [health, setHealth] = useState<{ agentModel: string; fastModel: string; project: string } | null>(null);
  useEffect(() => { api('/health').then(setHealth).catch(() => setHealth(null)); }, []);
  return (
    <div>
      <header className="topbar">
        <div className="brand"><img src="/favicon.svg" alt="" /> Freight AI Analytics</div>
        <nav aria-label="Main">{NAV.map(([id, label]) => (
          <button key={id} className={view === id ? 'active' : ''} onClick={() => setView(id)}>{label}</button>))}</nav>
        {health && <div className="stack-chips" title={`Project ${health.project}`}>
          <span className="chip">Gemini · {health.agentModel}</span><span className="chip">BigQuery</span><span className="chip">Vertex AI</span></div>}
      </header>
      <main>
        {view === 'ask' && <Ask />}
        {view === 'documents' && <Documents />}
        {view === 'governance' && <Governance />}
        {view === 'catalog' && <Catalog />}
      </main>
    </div>
  );
}
