import { useEffect, useMemo, useRef, useState } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { api } from '../api';

interface Trailer { trailer_id: string; trailer_type: string; home_terminal: string; last_ping_ts: string; latitude: number; longitude: number;
  speed_mph: number; heading_deg: number; door_open: boolean; loaded: boolean; reefer_temp_f: number | null; site_name: string | null;
  site_type: string | null; site_terminal: string | null; status: Status; hours_stationary: number }
interface Terminal { site_id: string; site_name: string; latitude: number; longitude: number }
interface Ping { ping_ts: string; event_type: string; latitude: number; longitude: number; speed_mph: number; door_open: boolean;
  loaded: boolean; reefer_temp_f: number | null; site_name: string | null }
interface Trip { trip_id: string; trip_type: string; origin_name: string; destination_name: string; depart_ts: string; arrive_ts: string;
  trip_status: string; loaded: boolean; pallets: number; miles: number; shipments: number; claims: string[] }
interface Alerts {
  detention: { trailer_id: string; site_name: string; hours_stationary: number }[];
  idleEmpties: { terminal: string; trailers: number; avg_hours: number; examples: string[] }[];
  doorOpens: { trailer_id: string; ping_ts: string; origin_name: string | null; destination_name: string | null; shipments_on_board: number; claims: string[] }[];
  temperature: { trailer_id: string; first_ts: string; max_temp_f: number; hours_above: number }[];
}
type Status = 'MOVING' | 'AT_TERMINAL' | 'AT_CUSTOMER' | 'STOPPED_EN_ROUTE';

const STATUS: Record<Status, { label: string; cls: string }> = {
  MOVING: { label: 'Moving', cls: 'moving' },
  AT_TERMINAL: { label: 'At terminal', cls: 'terminal' },
  AT_CUSTOMER: { label: 'At customer', cls: 'customer' },
  STOPPED_EN_ROUTE: { label: 'Stopped en route', cls: 'stopped' },
};
const TYPE: Record<string, string> = { DRY_VAN_53: "53' dry van", REEFER_53: "53' reefer", PUP_28: "28' pup" };
const when = (ts: string) => new Date(ts).toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
const css = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

export default function Trailers({ onAsk }: { onAsk: (q: string) => void }) {
  const [trailers, setTrailers] = useState<Trailer[]>([]);
  const [terminals, setTerminals] = useState<Terminal[]>([]);
  const [alerts, setAlerts] = useState<Alerts | null>(null);
  const [filter, setFilter] = useState<Status | 'ALL'>('ALL');
  const [selected, setSelected] = useState<string | null>(null);
  const [hours, setHours] = useState(72);  // how much route history to draw
  const [terminal, setTerminal] = useState<string | null>(null);
  const [detail, setDetail] = useState<{ pings: Ping[]; trips: Trip[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const mapEl = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const layer = useRef<L.LayerGroup | null>(null);
  const trailLayer = useRef<L.LayerGroup | null>(null);

  useEffect(() => {
    api<{ trailers: Trailer[]; terminals: Terminal[] }>('/api/trailers')
      .then((d) => { setTrailers(d.trailers); setTerminals(d.terminals); }).catch((e) => setError(e.message));
    api<Alerts>('/api/trailers/alerts').then(setAlerts).catch(() => setAlerts(null));
  }, []);

  useEffect(() => {
    if (!mapEl.current || map.current) return;
    const m = L.map(mapEl.current, { zoomSnap: 0.5 }).setView([37.5, -88], 4.5);
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 18, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(m);
    m.createPane('trailers').style.zIndex = '650';  // trailer dots above the terminal labels
    layer.current = L.layerGroup().addTo(m);
    trailLayer.current = L.layerGroup().addTo(m);
    map.current = m;
    const resize = new ResizeObserver(() => m.invalidateSize());  // the box can change size after first paint
    resize.observe(mapEl.current);
    return () => { resize.disconnect(); m.remove(); map.current = null; };
  }, []);

  useEffect(() => {  // start zoomed to the terminal network
    if (map.current && terminals.length) map.current.fitBounds(L.latLngBounds(terminals.map((t) => [t.latitude, t.longitude] as [number, number])).pad(0.08));
  }, [terminals]);

  const detained = useMemo(() => new Set(alerts?.detention.map((d) => d.trailer_id)), [alerts]);
  const visible = useMemo(() => trailers.filter((t) => filter === 'ALL' || t.status === filter), [trailers, filter]);
  const atTerminal = useMemo(() => {
    const by: Record<string, Trailer[]> = {};
    visible.filter((t) => t.status === 'AT_TERMINAL').forEach((t) => { (by[t.site_terminal ?? ''] ??= []).push(t); });
    return by;
  }, [visible]);

  // Trailers parked at a terminal are shown as one count per terminal; everything else as its own dot.
  useEffect(() => {
    const g = layer.current;
    if (!g) return;
    g.clearLayers();
    terminals.forEach((t) => {
      const n = atTerminal[t.site_id]?.length ?? 0;
      L.marker([t.latitude, t.longitude], {
        icon: L.divIcon({ className: '', html: `<div class="term-pin ${terminal === t.site_id ? 'active' : ''}"><b>${t.site_id}</b>${n ? `<span>${n}</span>` : ''}</div>`, iconSize: [0, 0] }),
        title: `${t.site_name}: ${n} trailers`,
      }).on('click', () => { setTerminal(t.site_id); setSelected(null); }).addTo(g);
    });
    visible.filter((t) => t.status !== 'AT_TERMINAL').forEach((t) => {
      const alert = detained.has(t.trailer_id);
      L.circleMarker([t.latitude, t.longitude], {
        pane: 'trailers', radius: (selected === t.trailer_id ? 3 : 0) + (alert ? 8 : 6), weight: 2, color: css('--surface'), fillOpacity: 1,
        fillColor: css(alert ? '--bad' : `--st-${STATUS[t.status].cls}`),
      }).bindTooltip(`${t.trailer_id} · ${STATUS[t.status].label}${t.site_name ? ` · ${t.site_name}` : ''}`)
        .on('click', () => { setSelected(t.trailer_id); setHours(72); setTerminal(null); }).addTo(g);
    });
  }, [visible, terminals, atTerminal, detained, selected, terminal]);

  // Selected trailer: load its last 3 days and draw the route, with unplanned door openings marked.
  useEffect(() => {
    trailLayer.current?.clearLayers();
    setDetail(null);
    if (!selected) return;
    let cancelled = false;
    api<{ pings: Ping[]; trips: Trip[] }>(`/api/trailers/${selected}?hours=${hours}`).then((d) => {
      if (cancelled || !trailLayer.current || !map.current) return;
      setDetail(d);
      const pts = d.pings.map((p) => [p.latitude, p.longitude] as [number, number]);
      if (pts.length > 1) {
        L.polyline(pts, { color: css('--accent'), weight: 3, opacity: 0.85 }).addTo(trailLayer.current);
        map.current.fitBounds(L.latLngBounds(pts).pad(0.3), { maxZoom: 9 });
      } else if (pts.length) map.current.setView(pts[0], 9);
      d.pings.filter((p) => p.event_type === 'DOOR_OPENED' && !p.site_name).forEach((p) =>
        L.circleMarker([p.latitude, p.longitude], { pane: 'trailers', radius: 8, color: css('--bad'), weight: 3, fillOpacity: 0 })
          .bindTooltip(`Door opened away from any site · ${when(p.ping_ts)}`).addTo(trailLayer.current!));
    }).catch(() => setDetail({ pings: [], trips: [] }));
    return () => { cancelled = true; };
  }, [selected, hours]);

  // since: show the route back to that moment (e.g. a door-open event), otherwise the last 72 hours
  const select = (id: string, since?: string) => {
    setSelected(id); setTerminal(null); setFilter('ALL');
    setHours(since ? Math.min(720, Math.ceil((Date.now() - new Date(since).getTime()) / 3.6e6) + 12) : 72);
    const t = trailers.find((x) => x.trailer_id === id);
    if (t && map.current) map.current.setView([t.latitude, t.longitude], 9);
  };
  const count = (s: Status) => trailers.filter((t) => t.status === s).length;
  const current = trailers.find((t) => t.trailer_id === selected);

  return (
    <div className="page trailers">
      <h1>Trailer tracking</h1>
      <p className="muted">Live position and sensors from each trailer's telematics unit, stored in BigQuery. Geofences around terminals
        and customer sites are matched with BigQuery GIS. Ask the AI anything about the fleet from here.</p>
      {error && <div className="notice error">{error}</div>}
      <div className="kpis">
        <div className="kpi"><span>Trailers</span><strong>{trailers.length || '-'}</strong></div>
        <div className="kpi"><span>Moving</span><strong>{count('MOVING')}</strong></div>
        <div className="kpi"><span>At terminals</span><strong>{count('AT_TERMINAL')}</strong></div>
        <div className="kpi"><span>At customers</span><strong>{count('AT_CUSTOMER')}</strong></div>
        <div className="kpi alert"><span>Detention &gt; 48 h</span><strong>{alerts?.detention.length ?? '-'}</strong></div>
        <div className="kpi alert"><span>Door opened en route</span><strong>{alerts?.doorOpens.length ?? '-'}</strong></div>
      </div>

      <div className="filters" role="group" aria-label="Filter by status">
        {(['ALL', 'MOVING', 'AT_TERMINAL', 'AT_CUSTOMER', 'STOPPED_EN_ROUTE'] as const).map((s) => (
          <button key={s} className={`chip-btn ${filter === s ? 'active' : ''}`} onClick={() => setFilter(s)}>
            {s !== 'ALL' && <i className={`dot st-${STATUS[s].cls}`} />}{s === 'ALL' ? 'All' : STATUS[s].label}
            <span className="muted"> {s === 'ALL' ? trailers.length : count(s)}</span>
          </button>))}
        <span className="legend muted small"><i className="dot st-alert" /> detention &gt; 48 h · terminal numbers = trailers parked there</span>
      </div>

      <div className="map-grid">
        <div className="map" ref={mapEl} />
        <aside className="map-panel">
          {current ? (
            <TrailerDetail t={current} detail={detail} hours={hours} detained={detained.has(current.trailer_id)} onClose={() => setSelected(null)} onAsk={onAsk} />
          ) : terminal ? (
            <TerminalList code={terminal} trailers={trailers.filter((t) => t.status === 'AT_TERMINAL' && t.site_terminal === terminal)}
                          onSelect={select} onClose={() => setTerminal(null)} onAsk={onAsk} />
          ) : <AlertList alerts={alerts} onSelect={select} onAsk={onAsk} />}
        </aside>
      </div>
    </div>
  );
}

function TrailerDetail({ t, detail, hours, detained, onClose, onAsk }: {
  t: Trailer; hours: number; detail: { pings: Ping[]; trips: Trip[] } | null; detained: boolean; onClose: () => void; onAsk: (q: string) => void }) {
  const events = detail?.pings.filter((p) => ['DOOR_OPENED', 'CARGO_LOADED', 'CARGO_EMPTY'].includes(p.event_type)).slice(-8).reverse() ?? [];
  return (
    <div className="panel-body">
      <div className="panel-head"><h3>{t.trailer_id}</h3><button className="link small" onClick={onClose}>Back to alerts</button></div>
      <div className="doc-head">
        <span className={`badge st-${STATUS[t.status].cls}`}>{STATUS[t.status].label}</span>
        {detained && <span className="badge blocked">Detention</span>}
        <span className="muted small">{TYPE[t.trailer_type]} · home {t.home_terminal}</span>
      </div>
      <dl className="kv">
        <dt>Where</dt><dd>{t.site_name ?? `On the road (${t.latitude.toFixed(3)}, ${t.longitude.toFixed(3)})`}</dd>
        <dt>{t.status === 'MOVING' ? 'Speed' : 'Stationary'}</dt><dd>{t.status === 'MOVING' ? `${t.speed_mph} mph` : `${t.hours_stationary} h`}</dd>
        <dt>Cargo</dt><dd>{t.loaded ? 'Loaded' : 'Empty'} · door {t.door_open ? 'open' : 'closed'}</dd>
        {t.reefer_temp_f != null && <><dt>Box temp</dt><dd>{t.reefer_temp_f} °F</dd></>}
        <dt>Last reading</dt><dd>{when(t.last_ping_ts)}</dd>
      </dl>
      <button className="secondary" onClick={() => onAsk(`Tell me about trailer ${t.trailer_id} over the last 14 days: where it went, what it carried, any door openings away from terminals, and any claims on its loads.`)}>
        Ask AI about this trailer</button>
      {!detail ? <p className="muted small"><span className="spinner" /> Loading route…</p> : (
        <>
          <h4>Recent trips</h4>
          {detail.trips.length === 0 ? <p className="muted small">No trips in the last 14 days.</p> : (
            <ul className="trip-list">{detail.trips.slice(0, 6).map((tr) => (
              <li key={tr.trip_id}>
                <div><strong>{tr.origin_name.replace(/ (Service Center|Breakbulk)/, '')} → {tr.destination_name.replace(/ (Service Center|Breakbulk)/, '')}</strong></div>
                <div className="muted small">{tr.trip_type.replace('_', ' ').toLowerCase()} · {when(tr.depart_ts)} · {tr.miles} mi
                  {tr.loaded ? ` · ${tr.pallets} pallets${tr.shipments ? `, ${tr.shipments} shipments` : ''}` : ' · empty'}{tr.trip_status === 'IN_PROGRESS' && ' · in progress'}</div>
                {tr.claims.length > 0 && <div className="small bad">Claims on this load: {tr.claims.join(', ')}</div>}
              </li>))}</ul>)}
          <h4>Sensor events ({hours > 72 ? `${Math.round(hours / 24)} days` : '72 h'})</h4>
          {events.length === 0 ? <p className="muted small">None.</p> : (
            <ul className="trip-list">{events.map((e) => (
              <li key={e.ping_ts} className={e.event_type === 'DOOR_OPENED' && !e.site_name ? 'bad' : ''}>
                <span className="small">{when(e.ping_ts)} · {e.event_type.replace('_', ' ').toLowerCase()} · {e.site_name ?? 'away from any site'}</span>
              </li>))}</ul>)}
        </>
      )}
    </div>
  );
}

function TerminalList({ code, trailers, onSelect, onClose, onAsk }: {
  code: string; trailers: Trailer[]; onSelect: (id: string) => void; onClose: () => void; onAsk: (q: string) => void }) {
  const empties = trailers.filter((t) => !t.loaded && t.hours_stationary > 72).length;
  return (
    <div className="panel-body">
      <div className="panel-head"><h3>{code} terminal</h3><button className="link small" onClick={onClose}>Back to alerts</button></div>
      <p className="small">{trailers.length} trailers parked · <strong>{empties}</strong> empty and idle more than 3 days</p>
      <button className="secondary" onClick={() => onAsk(`Why are there so many idle empty trailers at ${code}, and where could they be used instead?`)}>Ask AI about {code}</button>
      <div className="table-wrap"><table>
        <thead><tr><th>Trailer</th><th>Type</th><th>Cargo</th><th className="num">Idle h</th></tr></thead>
        <tbody>{[...trailers].sort((a, b) => b.hours_stationary - a.hours_stationary).map((t) => (
          <tr key={t.trailer_id} className="clickable" onClick={() => onSelect(t.trailer_id)}>
            <td>{t.trailer_id}</td><td className="small">{TYPE[t.trailer_type]}</td><td>{t.loaded ? 'Loaded' : 'Empty'}</td>
            <td className="num">{Math.round(t.hours_stationary)}</td></tr>))}</tbody>
      </table></div>
    </div>
  );
}

function AlertList({ alerts, onSelect, onAsk }: { alerts: Alerts | null; onSelect: (id: string, since?: string) => void; onAsk: (q: string) => void }) {
  if (!alerts) return <div className="panel-body muted"><span className="spinner" /> Checking the fleet…</div>;
  return (
    <div className="panel-body">
      <h3>Needs attention</h3>
      <section>
        <h4>Detention: at a customer over 48 h</h4>
        <ul className="alert-list">{alerts.detention.map((d) => (
          <li key={d.trailer_id}><button className="link" onClick={() => onSelect(d.trailer_id)}>{d.trailer_id}</button>
            <span className="small">{d.site_name} · {Math.round(d.hours_stationary)} h</span></li>))}</ul>
        <button className="link small" onClick={() => onAsk('Which customers are holding our trailers longer than 48 hours, and how often has this happened in the last 30 days?')}>Ask AI why →</button>
      </section>
      <section>
        <h4>Door opened away from any site</h4>
        <ul className="alert-list">{alerts.doorOpens.slice(0, 6).map((d) => (
          <li key={d.trailer_id + d.ping_ts}><button className="link" onClick={() => onSelect(d.trailer_id, d.ping_ts)}>{d.trailer_id}</button>
            <span className="small">{when(d.ping_ts)} · {d.origin_name?.split(' ')[0]} → {d.destination_name?.split(' ')[0]}
              {d.claims.length > 0 && <b className="bad"> · claim {d.claims.join(', ')}</b>}</span></li>))}</ul>
        <button className="link small" onClick={() => onAsk('Do unplanned trailer door openings between terminals line up with shortage claims? Show the trips and claims.')}>Ask AI to compare with claims →</button>
      </section>
      <section>
        <h4>Reefer temperature above 41 °F</h4>
        {alerts.temperature.length === 0 ? <p className="muted small">None in 30 days.</p> : (
          <ul className="alert-list">{alerts.temperature.map((d) => (
            <li key={d.trailer_id}><button className="link" onClick={() => onSelect(d.trailer_id, d.first_ts)}>{d.trailer_id}</button>
              <span className="small">{when(d.first_ts)} · peak {d.max_temp_f} °F · {d.hours_above} h</span></li>))}</ul>)}
      </section>
      <section>
        <h4>Empty trailers idle over 3 days</h4>
        <ul className="alert-list">{alerts.idleEmpties.slice(0, 4).map((d) => (
          <li key={d.terminal}><b>{d.terminal}</b><span className="small">{d.trailers} trailers · avg {Math.round(d.avg_hours)} h idle</span></li>))}</ul>
        <button className="link small" onClick={() => onAsk('Where are empty trailers piling up, and which terminals were short of trailers in the last two weeks?')}>Ask AI where to move them →</button>
      </section>
    </div>
  );
}
