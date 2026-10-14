import { useEffect, useState } from 'react';
import { api } from '../api';

interface Party { name: string; address: string; city: string; state: string; zip: string }
interface LineItem { handling_units: number | null; package_type: string | null; pieces: number | null; description: string;
  nmfc: string | null; freight_class: string | null; weight_lbs: number | null; hazmat: boolean }
interface Extracted { bol_number: string | null; ship_date: string | null; shipper: Party; consignee: Party; bill_to: string | null;
  line_items: LineItem[]; stated_total_weight_lbs: number | null; special_instructions: string | null; accessorials: string[];
  shipper_signed: boolean; legibility_notes: string | null }
interface Doc { document_id: string; uploaded_at: string; file_name: string; status: string; bol_number: string | null;
  shipper_name: string; consignee_name: string; total_pieces: number; total_weight_lbs: number; freight_classes: string[];
  hazmat: boolean; accessorials: string[]; issues: string[]; reviewed_by: string | null; extracted?: Extracted; model?: string }

const SAMPLE_LABELS: Record<string, string> = {
  'bol-1-clean.png': 'Clean BOL (grocery, appointment)',
  'bol-2-needs-review.png': 'Phone photo with errors',
  'bol-3-hazmat.png': 'Hazardous materials',
};

export default function Documents() {
  const [samples, setSamples] = useState<string[]>([]);
  const [recent, setRecent] = useState<Doc[]>([]);
  const [current, setCurrent] = useState<Doc | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [seconds, setSeconds] = useState<number | null>(null);

  const loadRecent = () => api<Doc[]>('/api/documents').then(setRecent).catch(() => setRecent([]));
  useEffect(() => { api<string[]>('/api/samples').then(setSamples).catch(() => setSamples([])); void loadRecent(); }, []);

  async function upload(file: File) {
    setBusy(true); setError(null); setCurrent(null); setSeconds(null);
    setPreview(file.type.startsWith('image/') ? URL.createObjectURL(file) : null);
    const form = new FormData();
    form.append('file', file);
    const t0 = performance.now();
    try {
      setCurrent(await api<Doc>('/api/documents', { method: 'POST', body: form }));
      setSeconds((performance.now() - t0) / 1000);
      void loadRecent();
    } catch (err) { setError((err as Error).message); }
    setBusy(false);
  }

  async function useSample(name: string) {
    const blob = await (await fetch(`/api/samples/${name}`)).blob();
    await upload(new File([blob], name, { type: 'image/png' }));
  }

  async function approve(id: string) {
    await api(`/api/documents/${id}/approve`, { method: 'POST' });
    setCurrent((c) => (c && c.document_id === id ? { ...c, status: 'APPROVED', reviewed_by: 'operations-reviewer' } : c));
    void loadRecent();
  }

  const x = current?.extracted;
  return (
    <div className="page">
      <h1>Bills of lading</h1>
      <p className="muted">Gemini reads a scanned or photographed bill of lading and returns structured fields. Code then checks them against freight rules
        (valid NMFC class, weights add up, hazmat emergency contact, signature) before the row lands in BigQuery. Anything doubtful goes to a person.</p>

      <div className="upload-row">
        <label className={`button ${busy ? 'disabled' : ''}`}>
          Upload a BOL (PNG, JPEG, PDF)
          <input type="file" accept="image/png,image/jpeg,image/webp,application/pdf" hidden disabled={busy}
                 onChange={(e) => { const f = e.target.files?.[0]; if (f) void upload(f); e.target.value = ''; }} />
        </label>
        <span className="muted small">or try a sample:</span>
        {samples.map((s) => <button key={s} className="secondary" disabled={busy} onClick={() => void useSample(s)}>{SAMPLE_LABELS[s] ?? s}</button>)}
      </div>

      {busy && <div className="notice"><span className="spinner" /> Gemini is reading the document…</div>}
      {error && <div className="notice error">{error}</div>}

      {(preview || current) && (
        <div className="doc-grid">
          <div className="doc-preview">{preview ? <img src={preview} alt="Uploaded bill of lading" /> : <div className="muted">No preview for PDFs</div>}</div>
          {current && x && (
            <div className="doc-fields">
              <div className="doc-head">
                <span className={`badge ${current.status.toLowerCase()}`}>{current.status.replace('_', ' ')}</span>
                <strong>{x.bol_number ?? 'No BOL number'}</strong>
                <span className="muted small">{x.ship_date ?? 'no date'}{seconds != null && ` · read in ${seconds.toFixed(1)} s by ${current.model}`}</span>
              </div>
              {current.issues.length > 0 ? (
                <div className="issues"><strong>Needs a person to check:</strong>
                  <ul>{current.issues.map((i) => <li key={i}>{i}</li>)}</ul></div>
              ) : <div className="notice ok">All checks passed. Ready to rate and dispatch.</div>}
              <div className="parties">
                <PartyCard title="Shipper" p={x.shipper} />
                <PartyCard title="Consignee" p={x.consignee} />
              </div>
              <table>
                <thead><tr><th>Units</th><th>Pieces</th><th>Description</th><th>NMFC</th><th>Class</th><th className="num">Weight</th><th>HM</th></tr></thead>
                <tbody>{x.line_items.map((li, i) => (
                  <tr key={i}><td>{li.handling_units ?? '-'} {li.package_type ?? ''}</td><td>{li.pieces ?? '-'}</td><td>{li.description}</td>
                    <td>{li.nmfc ?? '-'}</td><td className={li.freight_class ? '' : 'missing'}>{li.freight_class ?? 'missing'}</td>
                    <td className="num">{li.weight_lbs?.toLocaleString() ?? '-'}</td><td>{li.hazmat ? '⚠ yes' : ''}</td></tr>))}
                  <tr className="total"><td colSpan={5}>Stated total</td><td className="num">{x.stated_total_weight_lbs?.toLocaleString() ?? '-'}</td><td /></tr>
                </tbody>
              </table>
              <dl className="kv">
                <dt>Accessorials</dt><dd>{x.accessorials.length ? x.accessorials.join(', ') : 'none'}</dd>
                <dt>Instructions</dt><dd>{x.special_instructions ?? '-'}</dd>
                <dt>Bill to</dt><dd>{x.bill_to ?? '-'}</dd>
                <dt>Shipper signed</dt><dd>{x.shipper_signed ? 'yes' : 'no'}</dd>
              </dl>
              {current.status !== 'APPROVED'
                ? <button onClick={() => void approve(current.document_id)}>{current.status === 'READY' ? 'Approve' : 'Reviewed, approve anyway'}</button>
                : <div className="notice ok">Approved by {current.reviewed_by}.</div>}
            </div>
          )}
        </div>
      )}

      <h2>Recent documents</h2>
      {recent.length === 0 ? <p className="muted">None yet.</p> : (
        <div className="table-wrap"><table>
          <thead><tr><th>Uploaded</th><th>BOL</th><th>Shipper</th><th>Consignee</th><th className="num">Weight</th><th>Classes</th><th>Status</th><th>Issues</th></tr></thead>
          <tbody>{recent.map((d) => (
            <tr key={d.document_id}><td>{new Date(d.uploaded_at).toLocaleString()}</td><td>{d.bol_number ?? '-'}</td><td>{d.shipper_name}</td>
              <td>{d.consignee_name}</td><td className="num">{d.total_weight_lbs?.toLocaleString()}</td><td>{d.freight_classes?.join(', ')}</td>
              <td><span className={`badge ${d.status.toLowerCase()}`}>{d.status.replace('_', ' ')}</span>{d.hazmat && ' ⚠'}</td>
              <td className="small">{d.issues?.length ?? 0}</td></tr>))}</tbody>
        </table></div>
      )}
    </div>
  );
}

function PartyCard({ title, p }: { title: string; p: Party }) {
  return <div className="party"><span className="muted small">{title}</span><strong>{p.name}</strong><span>{p.address}</span><span>{p.city}, {p.state} {p.zip}</span></div>;
}
