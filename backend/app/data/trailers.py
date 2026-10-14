"""Synthetic trailer telematics for the last 30 days, built on top of the shipments already in BigQuery.

Every trailer has a telematics unit that reports GPS position, speed, door open/closed, a cargo (loaded) sensor and,
for refrigerated trailers, the box temperature: every 15 minutes while moving, hourly while parked, and immediately
on events (door opened or closed, motion started or stopped, cargo loaded or empty).

Trailer movements follow the freight: shipments are grouped into nightly linehaul trips (origin -> hub -> destination),
a trailer at the origin terminal is assigned, and empties are repositioned when a terminal runs short. Pup trailers
are dropped at customer sites for loading and unloading.

Patterns for the AI to find:
- Detention: trailers dropped at FreshMart DC - Atlanta and Precision Stamping Works - Detroit sit 2-5 days.
- Empty trailers piling up at the Memphis hub (repositioned in, never used again).
- On linehaul trips that later had a shortage claim, the door was opened at an unplanned stop between terminals.
- A refrigerated trailer's temperature rose above 41 F for several hours.

Run after app.data.generate: python -m app.data.trailers   (replaces the trailer tables; safe to re-run)
"""
from __future__ import annotations

import math
import random
import zlib
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from google.cloud import bigquery

from .. import config
from .generate import TERMINALS, T, _schema, miles

random.seed(20261014)
NOW = datetime.now(timezone.utc).replace(second=0, microsecond=0)
START = NOW - timedelta(days=30)
LINEHAUL_MPH, CITY_MPH = 52, 32
CAPACITY = {"DRY_VAN_53": 26, "REEFER_53": 26, "PUP_28": 13}  # pallets
DETENTION_SITES = {"FreshMart DC - Atlanta", "Precision Stamping Works - Detroit"}


@dataclass
class Trailer:
    trailer_id: str
    trailer_type: str
    home: str
    site: str              # site where it is (or will be after its current trip)
    last_t: datetime       # pings are generated up to here
    free_at: datetime      # available for the next trip from this time
    door_open: bool = False
    loaded: bool = False
    parked: bool = False   # never assigned again (the Memphis pile-up)
    excursion: tuple[datetime, datetime] | None = None
    pending: list = field(default_factory=list)  # (ts, attribute, value) changes while parked at a site


SITES: dict[str, dict] = {}
PINGS: list[dict] = []
TRIPS: list[dict] = []
LOADS: list[dict] = []
FLEET: list[Trailer] = []


def offset(lat: float, lon: float, north_mi: float, east_mi: float) -> tuple[float, float]:
    return lat + north_mi / 69.0, lon + east_mi / (69.0 * math.cos(math.radians(lat)))


def road_miles(a: str, b: str) -> float:
    if a in T and b in T:
        return miles(a, b)
    (la1, lo1), (la2, lo2) = (SITES[a]["lat"], SITES[a]["lon"]), (SITES[b]["lat"], SITES[b]["lon"])
    p1, p2, dp, dl = map(math.radians, (la1, la2, la2 - la1, lo2 - lo1))
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 3959 * 2 * math.asin(math.sqrt(h)) * 1.25


def bearing(a: tuple[float, float], b: tuple[float, float]) -> int:
    la1, la2, dl = math.radians(a[0]), math.radians(b[0]), math.radians(b[1] - a[1])
    y = math.sin(dl) * math.cos(la2)
    x = math.cos(la1) * math.sin(la2) - math.sin(la1) * math.cos(la2) * math.cos(dl)
    return round(math.degrees(math.atan2(y, x))) % 360


def reefer_temp(tr: Trailer, ts: datetime) -> float | None:
    if tr.trailer_type != "REEFER_53" or not tr.loaded:
        return None
    if tr.excursion and tr.excursion[0] <= ts <= tr.excursion[1]:
        f = (ts - tr.excursion[0]) / (tr.excursion[1] - tr.excursion[0])
        return round(36 + 14 * math.sin(math.pi * f) + random.gauss(0, 0.4), 1)  # rises to about 50 F, then recovers
    return round(36 + random.gauss(0, 0.6), 1)


def ping(tr: Trailer, ts: datetime, lat: float, lon: float, speed: float, heading: int, event: str) -> None:
    if ts > NOW or ts < START:
        return
    if speed == 0:  # parked GPS jitter of a few meters
        lat, lon = lat + random.gauss(0, 0.00004), lon + random.gauss(0, 0.00004)
    PINGS.append({
        "ping_id": len(PINGS) + 1, "trailer_id": tr.trailer_id, "ping_ts": ts.isoformat(), "event_type": event,
        "location": f"POINT({lon:.6f} {lat:.6f})", "latitude": round(lat, 6), "longitude": round(lon, 6),
        "speed_mph": round(speed, 1), "heading_deg": heading, "door_open": tr.door_open, "loaded": tr.loaded,
        "reefer_temp_f": reefer_temp(tr, ts),
    })


def stay(tr: Trailer, until: datetime) -> None:
    """Hourly pings while parked at tr.site, plus an event ping for each door or cargo change."""
    s = SITES[tr.site]
    marks = [(tr.last_t + timedelta(hours=h), None, None) for h in range(1, int((until - tr.last_t).total_seconds() // 3600) + 1)]
    changes = [c for c in tr.pending if tr.last_t <= c[0] <= until]
    tr.pending = [c for c in tr.pending if c[0] > until]
    for ts, attr, value in sorted(marks + changes, key=lambda m: (m[0], m[1] is None)):
        if attr is None:
            ping(tr, ts, s["lat"], s["lon"], 0, 0, "PERIODIC")
        else:
            setattr(tr, attr, value)
            event = {"door_open": ("DOOR_CLOSED", "DOOR_OPENED"), "loaded": ("CARGO_EMPTY", "CARGO_LOADED")}[attr][value]
            ping(tr, ts, s["lat"], s["lon"], 0, 0, event)
    tr.last_t = until


def move(tr: Trailer, dest: str, depart: datetime, mph: float, unplanned_stop: bool = False) -> datetime:
    """Pings every 15 minutes along the route, with a 30-minute rest stop every 5 hours of driving.
    unplanned_stop adds a stop between terminals where the door is opened for 20 minutes."""
    stay(tr, depart)
    a, b = (SITES[tr.site]["lat"], SITES[tr.site]["lon"]), (SITES[dest]["lat"], SITES[dest]["lon"])
    drive_h = road_miles(tr.site, dest) / mph
    stops = [(k * 5 / drive_h, 0.5, False) for k in range(1, math.ceil(drive_h / 5)) if k * 5 / drive_h < 0.97]
    if unplanned_stop:
        stops.append((random.uniform(0.4, 0.65), 0.75, True))
    stops.sort()
    heading = bearing(a, b)
    pos = lambda f: (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)  # noqa: E731
    t, f = depart, 0.0
    for fs, dur, door in stops + [(1.0, 0, False)]:
        leg_end = t + timedelta(hours=(fs - f) * drive_h)
        ping(tr, t, *pos(f), random.uniform(8, 20), heading, "MOTION_START")
        k = 1
        while (pt := t + timedelta(minutes=15 * k)) < leg_end:
            frac = f + (fs - f) * (pt - t) / (leg_end - t)
            ping(tr, pt, *pos(frac), random.uniform(mph + 3, mph + 12) if mph > 40 else random.uniform(22, 45), heading, "PERIODIC")
            k += 1
        t, f = leg_end, fs
        ping(tr, t, *pos(f), 0, heading, "MOTION_STOP")
        if dur:
            if door:
                tr.door_open = True
                ping(tr, t + timedelta(minutes=8), *pos(f), 0, heading, "DOOR_OPENED")
                tr.door_open = False
                ping(tr, t + timedelta(minutes=28), *pos(f), 0, heading, "DOOR_CLOSED")
            k = 1
            while (pt := t + timedelta(minutes=15 * k)) < t + timedelta(hours=dur):
                ping(tr, pt, *pos(f), 0, heading, "PERIODIC")
                k += 1
            t += timedelta(hours=dur)
    tr.site, tr.last_t = dest, t
    return t


def add_trip(tr: Trailer, trip_type: str, dest: str, depart: datetime, mph: float, pallets: int = 0,
             pros: list[str] | None = None, unplanned_stop: bool = False) -> datetime:
    origin = tr.site
    trip_id = f"TRP-{len(TRIPS) + 1:06d}"
    arrive = move(tr, dest, depart, mph, unplanned_stop)
    TRIPS.append({"trip_id": trip_id, "trailer_id": tr.trailer_id, "trip_type": trip_type, "origin_site_id": origin,
                  "destination_site_id": dest, "depart_ts": depart.isoformat(), "arrive_ts": arrive.isoformat(),
                  "loaded": pallets > 0, "pallets": pallets, "miles": round(road_miles(origin, dest))})
    LOADS.extend({"trip_id": trip_id, "pro_number": p} for p in pros or [])
    return arrive


def new_trailer(ttype: str, site: str, at: datetime) -> Trailer:
    prefix = {"DRY_VAN_53": "V", "REEFER_53": "R", "PUP_28": "P"}[ttype]
    n = sum(1 for t in FLEET if t.trailer_type == ttype) + 1
    tr = Trailer(f"{prefix}{28 if ttype == 'PUP_28' else 53}{n:04d}", ttype, site, site, at, at)  # e.g. V530012
    FLEET.append(tr)
    return tr


def pick(ttypes: tuple[str, ...], site: str, ready_by: datetime) -> Trailer | None:
    ok = [t for t in FLEET if t.trailer_type in ttypes and not t.parked and t.site == site and t.free_at <= ready_by]
    return min(ok, key=lambda t: t.free_at) if ok else None


def reposition(ttypes: tuple[str, ...], to: str, ready_by: datetime, keep: int = 3) -> Trailer | None:
    """Brings an empty trailer from the terminal with the most spare trailers within 700 miles (else the nearest)."""
    def spare(src: str) -> int:
        return sum(1 for t in FLEET if t.site == src and not t.parked and t.trailer_type in ttypes and t.free_at <= ready_by)
    near = [t[0] for t in TERMINALS if t[0] not in (to, "MEM") and miles(t[0], to) <= 700]
    far = sorted((t[0] for t in TERMINALS if t[0] not in (to, "MEM") and t[0] not in near), key=lambda s: miles(s, to))
    for src in sorted(near, key=spare, reverse=True) + far:
        hours = miles(src, to) / LINEHAUL_MPH + 2
        tr = pick(ttypes, src, ready_by - timedelta(hours=hours))
        if tr and sum(1 for t in FLEET if t.site == src and not t.parked and t.trailer_type in ttypes) > keep:
            depart = max(tr.free_at, ready_by - timedelta(hours=hours))
            tr.free_at = add_trip(tr, "EMPTY_REPOSITION", to, depart, LINEHAUL_MPH) + timedelta(hours=0.5)
            return tr
    return None


def load_inputs(client: bigquery.Client) -> tuple[list[dict], set[str], list[dict]]:
    shipments = [dict(r) for r in client.query(f"""
        SELECT s.pro_number, s.origin_terminal, s.destination_terminal, s.hub_terminal, s.pallets, s.pickup_ts,
               sh.industry
        FROM {config.table('shipments')} s JOIN {config.table('shippers')} sh USING (shipper_id)
        WHERE s.pickup_ts >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 33 DAY)""").result()]
    shortage = {r["pro_number"] for r in client.query(
        f"SELECT pro_number FROM {config.table('claims')} WHERE claim_type = 'SHORTAGE'").result()}
    customers = [dict(r) for r in client.query(f"""
        SELECT consignee_id, name, consignee_type, terminal_id FROM {config.table('consignees')}
        WHERE consignee_type IN ('GROCERY_DC', 'MANUFACTURING_PLANT') ORDER BY consignee_id""").result()]
    return shipments, shortage, customers


def build(shipments: list[dict], shortage: set[str], customers: list[dict]) -> None:
    # Geofences: terminals (900 m) and customer sites a few miles out of town (400 m).
    for t in TERMINALS:
        SITES[t[0]] = {"site_id": t[0], "site_name": t[1], "site_type": "TERMINAL", "terminal_id": t[0],
                       "lat": t[7], "lon": t[8], "radius_m": 900}
    for c in customers:
        ang, dist = random.uniform(0, 2 * math.pi), random.uniform(5, 16)
        lat, lon = offset(T[c["terminal_id"]][7], T[c["terminal_id"]][8], dist * math.sin(ang), dist * math.cos(ang))
        SITES[f"S-{c['consignee_id']}"] = {"site_id": f"S-{c['consignee_id']}", "site_name": c["name"], "site_type": "CUSTOMER",
                                           "terminal_id": c["terminal_id"], "lat": lat, "lon": lon, "radius_m": 400}

    # Starting fleet, sized to each terminal.
    for t in TERMINALS:
        for _ in range(t[6] // 12):
            new_trailer("DRY_VAN_53", t[0], START - timedelta(hours=random.uniform(1, 30)))
        if t[0] in ("ATL", "CLT", "JAX", "NAS", "DAL", "CHI"):
            for _ in range(3):
                new_trailer("REEFER_53", t[0], START - timedelta(hours=random.uniform(1, 30)))
        if t[5] == "END_OF_LINE":
            for _ in range(14 if t[0] in ("ATL", "DET") else 5):
                new_trailer("PUP_28", t[0], START - timedelta(hours=random.uniform(1, 30)))

    # Nightly linehaul legs: each shipment rides origin -> hub -> destination; legs on the same lane and night share trailers.
    def depart_at(src: str, dst: str, ready: datetime) -> datetime:
        hour = 20 + zlib.crc32(f"{src}{dst}".encode()) % 12  # each lane has its own departure time, 20:00-07:00 UTC
        d = datetime.combine(ready.date(), datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=hour)
        return d if d >= ready else d + timedelta(days=1)

    groups: dict[tuple, list[dict]] = defaultdict(list)
    for s in shipments:
        first = depart_at(s["origin_terminal"], s["hub_terminal"] or s["destination_terminal"], s["pickup_ts"] + timedelta(hours=4))
        if s["hub_terminal"]:
            groups[(s["origin_terminal"], s["hub_terminal"], first)].append(s)
            at_hub = first + timedelta(hours=miles(s["origin_terminal"], s["hub_terminal"]) / LINEHAUL_MPH + 5)
            groups[(s["hub_terminal"], s["destination_terminal"], depart_at(s["hub_terminal"], s["destination_terminal"], at_hub))].append(s)
        else:
            groups[(s["origin_terminal"], s["destination_terminal"], first)].append(s)

    tasks: list[tuple] = []
    for (src, dst, dep), ships in groups.items():
        if not START <= dep < NOW:
            continue
        load, pallets = [], 0
        for s in sorted(ships, key=lambda s: s["pro_number"]):
            if pallets + s["pallets"] > CAPACITY["DRY_VAN_53"] and load:
                tasks.append((dep, "LINEHAUL", src, dst, load))
                load, pallets = [], 0
            load.append(s)
            pallets += s["pallets"]
        tasks.append((dep, "LINEHAUL", src, dst, load))

    # Pup trailers dropped at customer sites on weekdays (detention at two of them).
    for day in range(31):
        d = (START + timedelta(days=day)).date()
        if d.weekday() >= 5:
            continue
        for c in customers:
            for _ in range(2 if c["name"] in DETENTION_SITES else int(random.random() < 0.35)):
                dep = datetime.combine(d, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=random.uniform(11, 15))
                if dep < NOW:
                    tasks.append((dep, "CUSTOMER_DROP", c["terminal_id"], f"S-{c['consignee_id']}", c["name"]))

    # Memphis pile-up: empties sent to the hub 6-9 days ago and never used.
    for i in range(22):
        dep = NOW - timedelta(days=9) + timedelta(hours=i * 3.2)
        tasks.append((dep, "PILEUP", random.choice(["NAS", "ATL", "DAL", "CHI", "COL", "JAX"]), "MEM", None))

    excursion_done = False
    for dep, kind, src, dst, payload in sorted(tasks, key=lambda x: x[0]):
        if kind == "LINEHAUL":
            pallets = sum(s["pallets"] for s in payload)
            food = sum(s["industry"] == "FOOD_BEVERAGE" for s in payload) / len(payload)
            want_excursion = not excursion_done and food >= 0.5 and dep > NOW - timedelta(days=8) and miles(src, dst) > 200
            types = ("REEFER_53",) if food >= 0.5 and (want_excursion or random.random() < 0.4) else ("DRY_VAN_53",)
            tr = pick(types, src, dep - timedelta(hours=3))
            if not tr and types == ("REEFER_53",):
                tr = reposition(types, src, dep - timedelta(hours=3), keep=0) or pick(("DRY_VAN_53",), src, dep - timedelta(hours=3))
            tr = tr or reposition(("DRY_VAN_53",), src, dep - timedelta(hours=3)) or new_trailer("DRY_VAN_53", src, START)
            tr.pending += [(dep - timedelta(hours=2.5), "door_open", True), (dep - timedelta(hours=1), "loaded", True),
                           (dep - timedelta(hours=0.5), "door_open", False)]
            pros = [s["pro_number"] for s in payload]
            stop = any(s["pro_number"] in shortage and src == (s["hub_terminal"] or s["origin_terminal"]) for s in payload) \
                or random.random() < 0.002
            if tr.trailer_type == "REEFER_53" and want_excursion:
                hours = miles(src, dst) / LINEHAUL_MPH
                tr.excursion = (dep + timedelta(hours=hours * 0.2), dep + timedelta(hours=hours * 0.2 + 5))
                excursion_done = True
                print(f"reefer excursion: {tr.trailer_id} {src}->{dst} departing {dep:%Y-%m-%d %H:%M}")
            arrive = add_trip(tr, "LINEHAUL", dst, dep, LINEHAUL_MPH, pallets, pros, unplanned_stop=stop)
            tr.pending += [(arrive + timedelta(hours=0.5), "door_open", True), (arrive + timedelta(hours=2), "loaded", False),
                           (arrive + timedelta(hours=2.5), "door_open", False)]
            tr.free_at = arrive + timedelta(hours=3)
        elif kind == "CUSTOMER_DROP":
            tr = pick(("PUP_28",), src, dep - timedelta(hours=2))
            if not tr:
                continue
            tr.pending += [(dep - timedelta(hours=1.5), "door_open", True), (dep - timedelta(hours=1), "loaded", True),
                           (dep - timedelta(hours=0.7), "door_open", False)]
            arrive = add_trip(tr, "CUSTOMER_DROP", dst, dep, CITY_MPH, random.randint(6, 13))
            dwell = random.uniform(70, 150) if payload in DETENTION_SITES else random.uniform(5, 28)
            unload = min(dwell * 0.5, 8)
            tr.pending += [(arrive + timedelta(hours=1), "door_open", True), (arrive + timedelta(hours=unload), "loaded", False),
                           (arrive + timedelta(hours=unload + 0.3), "door_open", False)]
            back = arrive + timedelta(hours=dwell)
            if payload in DETENTION_SITES and dep > NOW - timedelta(days=6) and random.random() < 0.6:
                back = NOW + timedelta(days=1)  # nobody has collected it yet
            if back < NOW:
                tr.free_at = add_trip(tr, "RETURN_EMPTY", src, back, CITY_MPH) + timedelta(hours=0.5)
            else:
                tr.free_at, tr.parked = NOW + timedelta(days=30), True  # still sitting at the customer
        else:  # PILEUP
            tr = pick(("DRY_VAN_53",), src, dep)
            if tr:
                add_trip(tr, "EMPTY_REPOSITION", dst, dep, LINEHAUL_MPH)
                tr.parked = True

    for tr in FLEET:  # bring every trailer's pings up to now
        if tr.last_t < NOW:
            stay(tr, NOW)


TRAILER_SCHEMA = [("trailer_id", "STRING"), ("trailer_type", "STRING"), ("length_ft", "INT64"), ("home_terminal", "STRING"),
                  ("telematics_unit_id", "STRING"), ("in_service_year", "INT64")]
SITE_SCHEMA = [("site_id", "STRING"), ("site_name", "STRING"), ("site_type", "STRING"), ("terminal_id", "STRING"),
               ("center", "GEOGRAPHY"), ("latitude", "FLOAT64"), ("longitude", "FLOAT64"), ("radius_m", "INT64")]
PING_SCHEMA = [("ping_id", "INT64"), ("trailer_id", "STRING"), ("ping_ts", "TIMESTAMP"), ("event_type", "STRING"),
               ("location", "GEOGRAPHY"), ("latitude", "FLOAT64"), ("longitude", "FLOAT64"), ("speed_mph", "FLOAT64"),
               ("heading_deg", "INT64"), ("door_open", "BOOL"), ("loaded", "BOOL"), ("reefer_temp_f", "FLOAT64")]
TRIP_SCHEMA = [("trip_id", "STRING"), ("trailer_id", "STRING"), ("trip_type", "STRING"), ("origin_site_id", "STRING"),
               ("destination_site_id", "STRING"), ("depart_ts", "TIMESTAMP"), ("arrive_ts", "TIMESTAMP"),
               ("loaded", "BOOL"), ("pallets", "INT64"), ("miles", "INT64")]
LOAD_SCHEMA = [("trip_id", "STRING"), ("pro_number", "STRING")]

VIEWS = {
    "v_trailers": "SELECT trailer_id, trailer_type, length_ft, home_terminal, in_service_year FROM {trailers}",
    "v_sites": "SELECT site_id, site_name, site_type, terminal_id, center, latitude, longitude, radius_m FROM {sites}",
    # Geofencing in BigQuery: each ping is matched to the site whose radius it falls inside (if any).
    "v_trailer_pings": """
        WITH matched AS (
          SELECT p.ping_id, s.site_id, s.site_name, s.site_type, s.terminal_id
          FROM {trailer_pings} p JOIN {sites} s ON ST_DWITHIN(p.location, s.center, s.radius_m))
        SELECT p.trailer_id, p.ping_ts, DATE(p.ping_ts) AS ping_date, p.event_type, p.location, p.latitude, p.longitude,
               p.speed_mph, p.heading_deg, p.door_open, p.loaded, p.reefer_temp_f,
               m.site_id, m.site_name, m.site_type, m.terminal_id AS site_terminal
        FROM {trailer_pings} p LEFT JOIN matched m USING (ping_id)""",
    "v_trailer_positions": """
        WITH latest AS (
          SELECT * FROM {v_trailer_pings}
          QUALIFY ROW_NUMBER() OVER (PARTITION BY trailer_id ORDER BY ping_ts DESC) = 1),
        motion AS (
          SELECT trailer_id, MAX(IF(speed_mph > 5, ping_ts, NULL)) AS last_moving_ts, MIN(ping_ts) AS first_ts
          FROM {trailer_pings} GROUP BY trailer_id)
        SELECT l.trailer_id, t.trailer_type, t.home_terminal, l.ping_ts AS last_ping_ts, l.latitude, l.longitude,
               l.speed_mph, l.heading_deg, l.door_open, l.loaded, l.reefer_temp_f,
               l.site_id, l.site_name, l.site_type, l.site_terminal,
               CASE WHEN l.speed_mph > 5 THEN 'MOVING' WHEN l.site_type = 'TERMINAL' THEN 'AT_TERMINAL'
                    WHEN l.site_type = 'CUSTOMER' THEN 'AT_CUSTOMER' ELSE 'STOPPED_EN_ROUTE' END AS status,
               IF(l.speed_mph > 5, 0,
                  ROUND(TIMESTAMP_DIFF(l.ping_ts, COALESCE(m.last_moving_ts, m.first_ts), MINUTE) / 60, 1)) AS hours_stationary
        FROM latest l JOIN {trailers} t USING (trailer_id) JOIN motion m USING (trailer_id)""",
    "v_trailer_trips": """
        SELECT tr.trip_id, tr.trailer_id, t.trailer_type, tr.trip_type, tr.origin_site_id, o.site_name AS origin_name,
               tr.destination_site_id, d.site_name AS destination_name, tr.depart_ts, tr.arrive_ts,
               IF(tr.arrive_ts > CURRENT_TIMESTAMP(), 'IN_PROGRESS', 'COMPLETED') AS trip_status,
               tr.loaded, tr.pallets, tr.miles
        FROM {trailer_trips} tr JOIN {trailers} t USING (trailer_id)
        JOIN {sites} o ON o.site_id = tr.origin_site_id JOIN {sites} d ON d.site_id = tr.destination_site_id""",
    "v_trailer_loads": "SELECT trip_id, pro_number FROM {trailer_loads}",
}


def main() -> None:
    client = bigquery.Client(project=config.PROJECT)
    build(*load_inputs(client))
    trailers = [{"trailer_id": t.trailer_id, "trailer_type": t.trailer_type,
                 "length_ft": 28 if t.trailer_type == "PUP_28" else 53, "home_terminal": t.home,
                 "telematics_unit_id": f"TU-{zlib.crc32(t.trailer_id.encode()):08X}", "in_service_year": random.randint(2015, 2025)}
                for t in FLEET]
    sites = [{**{k: s[k] for k in ("site_id", "site_name", "site_type", "terminal_id", "radius_m")},
              "center": f"POINT({s['lon']:.6f} {s['lat']:.6f})", "latitude": round(s["lat"], 6), "longitude": round(s["lon"], 6)}
             for s in SITES.values()]
    for name, rows, schema, extra in (
            ("trailers", trailers, TRAILER_SCHEMA, {}), ("sites", sites, SITE_SCHEMA, {}),
            ("trailer_trips", TRIPS, TRIP_SCHEMA, {}), ("trailer_loads", LOADS, LOAD_SCHEMA, {}),
            ("trailer_pings", PINGS, PING_SCHEMA, {
                "time_partitioning": bigquery.TimePartitioning(type_=bigquery.TimePartitioningType.DAY, field="ping_ts"),
                "clustering_fields": ["trailer_id"]})):
        job = client.load_table_from_json(rows, f"{config.PROJECT}.{config.DATASET}.{name}", job_config=bigquery.LoadJobConfig(
            schema=_schema(schema), write_disposition="WRITE_TRUNCATE", **extra))
        job.result()
        print(f"loaded {len(rows):>7} rows into {name}")
    names = {n: config.table(n) for n in ("trailers", "sites", "trailer_pings", "trailer_trips", "trailer_loads", "v_trailer_pings")}
    for view, sql in VIEWS.items():
        client.query(f"CREATE OR REPLACE VIEW {config.table(view)} AS {sql.format(**names)}").result()
        print(f"view {view}")
    print(f"Done. Pings {START:%Y-%m-%d %H:%M} to {NOW:%Y-%m-%d %H:%M} UTC.")


if __name__ == "__main__":
    main()
