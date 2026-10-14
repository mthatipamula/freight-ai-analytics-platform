import { Fragment, useEffect, useState } from 'react';
import { api } from '../api';

interface Catalog {
  views: Record<string, { description: string; columns: Record<string, string> }>;
  metrics: Record<string, string>;
  glossary: Record<string, string>;
}

export default function Catalog() {
  const [c, setC] = useState<Catalog | null>(null);
  useEffect(() => { api<Catalog>('/api/catalog').then(setC).catch(() => setC(null)); }, []);
  if (!c) return <div className="page muted"><span className="spinner" /> Loading…</div>;
  return (
    <div className="page">
      <h1>Data catalog</h1>
      <p className="muted">The semantic layer the AI is given: approved views, column meanings and one agreed definition per metric
        (the same role LookML plays in Looker). Changing a definition here changes every answer consistently.</p>
      <h2>Metric definitions</h2>
      <dl className="kv wide">{Object.entries(c.metrics).map(([k, v]) => <Fragment key={k}><dt><code>{k}</code></dt><dd>{v}</dd></Fragment>)}</dl>
      <h2>Approved views</h2>
      <div className="catalog-grid">{Object.entries(c.views).map(([name, v]) => (
        <section key={name} className="card">
          <h3><code>{name}</code></h3><p className="muted small">{v.description}</p>
          <dl className="kv">{Object.entries(v.columns).map(([col, d]) => <Fragment key={col}><dt><code>{col}</code></dt><dd>{d}</dd></Fragment>)}</dl>
        </section>))}</div>
      <h2>Glossary</h2>
      <dl className="kv wide">{Object.entries(c.glossary).map(([k, v]) => <Fragment key={k}><dt>{k}</dt><dd>{v}</dd></Fragment>)}</dl>
    </div>
  );
}
