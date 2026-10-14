"""Generates realistic, synthetic LTL freight data and loads it into BigQuery.

All companies, people and numbers are fictional. The data contains patterns for the AI to discover:
- Atlanta deliveries from Charlotte, Richmond and Harrisburg ran late for two weeks (late inbound linehaul).
- One grocery distribution center misses delivery appointments far more often than the others.
- Freight routed through the Memphis hub has a much higher damage-claim rate; light, high-class freight
  (furniture, fitness equipment) is damaged more often everywhere.
- A winter-style weather event slowed the Northeast terminals for a few days.

Run: python -m app.data.generate   (creates the dataset, tables and views; safe to re-run, replaces data)
"""
from __future__ import annotations

import math
import random
from datetime import date, datetime, time, timedelta, timezone

from google.cloud import bigquery

from .. import config

random.seed(20261013)
TODAY = date.today()
START = TODAY - timedelta(days=120)

TERMINALS = [
    # id, name, city, state, region, type, dock doors, lat, lon
    ("ATL", "Atlanta Service Center", "Atlanta", "GA", "SOUTHEAST", "END_OF_LINE", 120, 33.75, -84.39),
    ("CLT", "Charlotte Service Center", "Charlotte", "NC", "SOUTHEAST", "END_OF_LINE", 96, 35.23, -80.84),
    ("JAX", "Jacksonville Service Center", "Jacksonville", "FL", "SOUTHEAST", "END_OF_LINE", 64, 30.33, -81.66),
    ("NAS", "Nashville Service Center", "Nashville", "TN", "SOUTHEAST", "END_OF_LINE", 72, 36.16, -86.78),
    ("MEM", "Memphis Breakbulk", "Memphis", "TN", "SOUTHEAST", "BREAKBULK", 210, 35.15, -90.05),
    ("RIC", "Richmond Service Center", "Richmond", "VA", "MID_ATLANTIC", "END_OF_LINE", 88, 37.54, -77.44),
    ("HAR", "Harrisburg Breakbulk", "Harrisburg", "PA", "MID_ATLANTIC", "BREAKBULK", 190, 40.27, -76.88),
    ("NWK", "Newark Service Center", "Newark", "NJ", "MID_ATLANTIC", "END_OF_LINE", 84, 40.74, -74.17),
    ("COL", "Columbus Service Center", "Columbus", "OH", "MIDWEST", "END_OF_LINE", 70, 39.96, -83.00),
    ("CHI", "Chicago Service Center", "Chicago", "IL", "MIDWEST", "END_OF_LINE", 110, 41.88, -87.63),
    ("DET", "Detroit Service Center", "Detroit", "MI", "MIDWEST", "END_OF_LINE", 76, 42.33, -83.05),
    ("DAL", "Dallas Breakbulk", "Dallas", "TX", "SOUTHWEST", "BREAKBULK", 200, 32.78, -96.80),
    ("PHX", "Phoenix Service Center", "Phoenix", "AZ", "SOUTHWEST", "END_OF_LINE", 60, 33.45, -112.07),
    ("DEN", "Denver Service Center", "Denver", "CO", "MOUNTAIN", "END_OF_LINE", 58, 39.74, -104.99),
]
T = {t[0]: t for t in TERMINALS}
HUBS = ["MEM", "HAR", "DAL"]

SHIPPERS = [
    ("SHP-001", "Brightway Foods", "FOOD_BEVERAGE", "CLT"), ("SHP-002", "Summit HVAC Supply", "HVAC", "DAL"),
    ("SHP-003", "Northline Auto Parts", "AUTOMOTIVE", "DET"), ("SHP-004", "Peak Fitness Direct", "ECOMMERCE", "COL"),
    ("SHP-005", "Riverbend Beverages", "FOOD_BEVERAGE", "ATL"), ("SHP-006", "Granite Building Products", "BUILDING_MATERIALS", "CHI"),
    ("SHP-007", "Coastal Paper Goods", "CONSUMER_GOODS", "JAX"), ("SHP-008", "Ironclad Industrial Tools", "INDUSTRIAL", "COL"),
    ("SHP-009", "Harvest Table Foods", "FOOD_BEVERAGE", "NAS"), ("SHP-010", "Lumen Lighting Co", "ELECTRICAL", "NWK"),
    ("SHP-011", "Cedar & Oak Furniture", "FURNITURE", "CLT"), ("SHP-012", "Apex Medical Supply", "HEALTHCARE", "RIC"),
    ("SHP-013", "Desert Sun Solar", "ELECTRICAL", "PHX"), ("SHP-014", "Frontier Pet Foods", "FOOD_BEVERAGE", "DEN"),
    ("SHP-015", "Keystone Plumbing Supply", "PLUMBING", "HAR"), ("SHP-016", "Metro Expo Services", "TRADE_SHOW", "CHI"),
    ("SHP-017", "Bluegrass Bottling", "FOOD_BEVERAGE", "NAS"), ("SHP-018", "Precision Machine Parts", "INDUSTRIAL", "DET"),
    ("SHP-019", "Sunrise Snacks", "FOOD_BEVERAGE", "DAL"), ("SHP-020", "Hometown Appliances Online", "ECOMMERCE", "ATL"),
]
VOLUME_WEIGHT = {"FOOD_BEVERAGE": 1.6, "ECOMMERCE": 1.3, "FURNITURE": 1.0, "HVAC": 1.0, "AUTOMOTIVE": 1.1}

CONSIGNEE_TYPES_BY_INDUSTRY = {
    "FOOD_BEVERAGE": [("GROCERY_DC", 0.8), ("RETAIL_STORE", 0.2)],
    "HVAC": [("CONTRACTOR", 0.7), ("RETAIL_STORE", 0.3)], "PLUMBING": [("CONTRACTOR", 0.7), ("RETAIL_STORE", 0.3)],
    "BUILDING_MATERIALS": [("CONTRACTOR", 0.6), ("RETAIL_STORE", 0.4)], "ELECTRICAL": [("CONTRACTOR", 0.5), ("RETAIL_STORE", 0.5)],
    "AUTOMOTIVE": [("MANUFACTURING_PLANT", 0.9), ("RETAIL_STORE", 0.1)], "INDUSTRIAL": [("MANUFACTURING_PLANT", 1.0)],
    "ECOMMERCE": [("RESIDENCE", 0.75), ("RETAIL_STORE", 0.25)], "FURNITURE": [("RESIDENCE", 0.6), ("RETAIL_STORE", 0.4)],
    "CONSUMER_GOODS": [("RETAIL_STORE", 0.7), ("GROCERY_DC", 0.3)], "HEALTHCARE": [("HOSPITAL", 1.0)],
    "TRADE_SHOW": [("TRADE_SHOW_VENUE", 1.0)],
}
FREIGHT_CLASS = {
    "FOOD_BEVERAGE": [55, 60, 65, 70], "HVAC": [85, 92.5, 100], "AUTOMOTIVE": [70, 77.5, 85], "ECOMMERCE": [125, 150, 175],
    "BUILDING_MATERIALS": [50, 55, 65], "CONSUMER_GOODS": [85, 100, 125], "INDUSTRIAL": [60, 65, 77.5], "ELECTRICAL": [100, 125, 150],
    "FURNITURE": [150, 175, 200, 250], "HEALTHCARE": [92.5, 100, 110], "PLUMBING": [70, 77.5, 85], "TRADE_SHOW": [150, 175, 200],
}
FIRST = ["James", "Maria", "Robert", "Linda", "David", "Aisha", "Kevin", "Priya", "Daniel", "Sofia", "Marcus", "Emily",
         "Andre", "Grace", "Luis", "Hannah", "Tyrone", "Mei", "Carlos", "Olivia"]
LAST = ["Johnson", "Garcia", "Williams", "Patel", "Brown", "Nguyen", "Davis", "Martinez", "Wilson", "Thompson", "Lee",
        "Robinson", "Clark", "Lewis", "Walker", "Young", "Allen", "King", "Wright", "Scott"]
BUSINESS_NAMES = {
    "GROCERY_DC": ["Southeast Grocers DC", "FreshMart DC", "ValuFoods Distribution", "GreenLeaf Market DC"],
    "RETAIL_STORE": ["HomeBase Hardware", "Main Street Supply", "Value Home Center", "Corner Outfitters"],
    "CONTRACTOR": ["Allied Mechanical", "ProBuild Contractors", "Spark Electric Services", "Reliable Plumbing & Heat"],
    "MANUFACTURING_PLANT": ["Midstate Assembly Plant", "Precision Stamping Works", "Union Motor Assembly"],
    "HOSPITAL": ["Regional Medical Center", "St. Brigid Hospital"],
    "TRADE_SHOW_VENUE": ["Convention Center"],
}


def miles(a: str, b: str) -> float:
    (la1, lo1), (la2, lo2) = (T[a][7], T[a][8]), (T[b][7], T[b][8])
    p1, p2, dp, dl = map(math.radians, (la1, la2, la2 - la1, lo2 - lo1))
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 3959 * 2 * math.asin(math.sqrt(h)) * 1.18  # road distance is longer than straight-line


def add_business_days(d: date, n: int) -> date:
    while n > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


def ts(d: date, hour: float) -> datetime:
    return datetime.combine(d, time(0), tzinfo=timezone.utc) + timedelta(hours=hour)


def build_consignees() -> list[dict]:
    rows, n = [], 0
    for t in TERMINALS:
        if t[5] == "BREAKBULK" and t[0] != "DAL":
            continue
        city, state = t[2], t[3]
        for ctype, count in (("GROCERY_DC", 1), ("RETAIL_STORE", 2), ("CONTRACTOR", 1), ("MANUFACTURING_PLANT", 1),
                             ("RESIDENCE", 4), ("HOSPITAL", 1)):
            for i in range(count):
                n += 1
                if ctype == "RESIDENCE":
                    first, last = random.choice(FIRST), random.choice(LAST)
                    name, contact = f"{first} {last}", f"{first} {last}"
                    email = f"{first.lower()}.{last.lower()}{n}@example.com"
                else:
                    base = BUSINESS_NAMES[ctype][(n + i) % len(BUSINESS_NAMES[ctype])]
                    name = f"{base} - {city}"
                    contact = f"{random.choice(FIRST)} {random.choice(LAST)}"
                    email = f"receiving{n}@example.com"
                rows.append({"consignee_id": f"CON-{n:04d}", "name": name, "consignee_type": ctype, "terminal_id": t[0],
                             "city": city, "state": state, "contact_name": contact,
                             "contact_phone": f"555-{random.randint(200, 999)}-{random.randint(1000, 9999)}",
                             "contact_email": email})
    for t in ("ATL", "CHI", "DAL", "NWK"):
        n += 1
        rows.append({"consignee_id": f"CON-{n:04d}", "name": f"Convention Center - {T[t][2]}",
                     "consignee_type": "TRADE_SHOW_VENUE", "terminal_id": t, "city": T[t][2], "state": T[t][3],
                     "contact_name": "Exhibitor Services", "contact_phone": f"555-{random.randint(200, 999)}-0100",
                     "contact_email": f"exhibits{n}@example.com"})
    return rows


def generate():
    consignees = build_consignees()
    by_type: dict[str, list[dict]] = {}
    for c in consignees:
        by_type.setdefault(c["consignee_type"], []).append(c)
    problem_dc = next(c for c in by_type["GROCERY_DC"] if c["terminal_id"] == "ATL")  # Southeast Grocers DC - Atlanta
    weights = [VOLUME_WEIGHT.get(s[2], 0.8) for s in SHIPPERS]

    shipments, events, claims = [], [], []
    pro = 4_810_000_000
    d = START
    while d < TODAY:
        weekday = d.weekday() < 5
        days_ago = (TODAY - d).days
        n = int(random.gauss(170 if weekday else 22, 12 if weekday else 5) * (1 + (120 - days_ago) / 900))
        for _ in range(max(0, n)):
            pro += random.randint(1, 9)
            sid, sname, industry, origin = random.choices(SHIPPERS, weights)[0]
            types, tw = zip(*CONSIGNEE_TYPES_BY_INDUSTRY[industry])
            ctype = random.choices(types, tw)[0]
            pool = [c for c in by_type[ctype] if c["terminal_id"] != origin] or by_type[ctype]
            if ctype == "GROCERY_DC" and random.random() < 0.25:
                consignee = problem_dc
            else:
                consignee = random.choice(pool)
            dest = consignee["terminal_id"]
            dist = miles(origin, dest)
            hub = None
            if dist > 650:
                hub = min(HUBS, key=lambda h: miles(origin, h) + miles(h, dest))
                if hub in (origin, dest):
                    hub = None

            service = "STANDARD"
            if ctype == "GROCERY_DC":
                service = "GROCERY_APPOINTMENT"
            elif industry in ("TRADE_SHOW", "AUTOMOTIVE") and random.random() < 0.4 or random.random() < 0.04:
                service = "TIME_CRITICAL"
            fclass = random.choice(FREIGHT_CLASS[industry])
            pallets = random.choices([1, 2, 3, 4, 5, 6], [30, 25, 18, 12, 9, 6])[0]
            per_pallet = random.uniform(1100, 1700) if fclass <= 70 else random.uniform(600, 1100) if fclass <= 110 else random.uniform(250, 600)
            weight = int(pallets * per_pallet)
            accessorials = []
            if ctype == "RESIDENCE":
                accessorials += ["RESIDENTIAL", "LIFTGATE"]
            if ctype in ("GROCERY_DC", "TRADE_SHOW_VENUE") or service == "TIME_CRITICAL":
                accessorials.append("APPOINTMENT")
            if ctype == "RESIDENCE" and random.random() < 0.3:
                accessorials.append("INSIDE_DELIVERY")
            rate_per_cwt = 18 + fclass * 0.22 + dist * 0.012
            revenue = round(weight / 100 * rate_per_cwt + 75 * len(accessorials) + (180 if service == "TIME_CRITICAL" else 0), 2)

            pickup_day = d
            pickup = ts(pickup_day, random.uniform(13, 19))  # afternoon pickups (UTC-ish business hours)
            transit = max(1, math.ceil(dist / 480)) + (1 if hub else 0)
            promise_day = add_business_days(pickup_day, transit)
            promised = ts(promise_day, random.uniform(11, 17) if ctype != "GROCERY_DC" else random.uniform(10, 12))

            # Lateness model with the embedded patterns.
            p_late = 0.055
            reason = random.choices(["CAPACITY", "MISSORT", "CONSIGNEE_CLOSED", "LINEHAUL_DELAY", "WEATHER"], [3, 2, 2, 3, 1])[0]
            if service == "TIME_CRITICAL":
                p_late = 0.02
            if service == "GROCERY_APPOINTMENT":
                p_late = 0.09
                if consignee is problem_dc:
                    p_late, reason = 0.24, "MISSED_APPOINTMENT"
            if dest == "ATL" and origin in ("CLT", "RIC", "HAR") and 21 <= (TODAY - promise_day).days <= 35:
                p_late, reason = p_late + 0.30, "LINEHAUL_DELAY"
            if dest in ("NWK", "HAR") or origin in ("NWK", "HAR"):
                if 56 <= (TODAY - promise_day).days <= 60:
                    p_late, reason = p_late + 0.35, "WEATHER"
            late = random.random() < p_late

            delivered = None
            delay_hours = 0.0
            if promised <= datetime.now(timezone.utc) - timedelta(hours=6):
                if late:
                    delay_hours = random.uniform(5, 52)
                    delivered = promised + timedelta(hours=delay_hours)
                else:
                    delivered = promised - timedelta(hours=random.uniform(0, 3))
            status = "DELIVERED" if delivered else "IN_TRANSIT"

            shipments.append({
                "pro_number": str(pro), "bol_number": f"BOL-{pro % 10_000_000:07d}", "shipper_id": sid,
                "consignee_id": consignee["consignee_id"], "origin_terminal": origin, "destination_terminal": dest,
                "hub_terminal": hub, "service_level": service, "freight_class": fclass, "pallets": pallets,
                "weight_lbs": weight, "miles": round(dist), "revenue_usd": revenue, "accessorials": accessorials,
                "pickup_ts": pickup.isoformat(), "promised_delivery_ts": promised.isoformat(),
                "delivered_ts": delivered.isoformat() if delivered else None, "status": status,
                "on_time": (not late) if delivered else None, "delay_reason": reason if (late and delivered) else None,
                "delay_hours": round(delay_hours, 1) if delivered and late else 0.0,
            })

            # Tracking events.
            ev = [(pickup, "PICKED_UP", origin), (pickup + timedelta(hours=3), "ARRIVED_TERMINAL", origin),
                  (pickup + timedelta(hours=6), "DEPARTED_TERMINAL", origin)]
            cursor = pickup + timedelta(hours=6)
            if hub:
                cursor += timedelta(hours=miles(origin, hub) / 50)
                ev += [(cursor, "ARRIVED_TERMINAL", hub), (cursor + timedelta(hours=4), "DEPARTED_TERMINAL", hub)]
                cursor += timedelta(hours=4)
            arrive_dest = min(promised - timedelta(hours=5), cursor + timedelta(hours=dist / 50))
            if late and reason in ("LINEHAUL_DELAY", "WEATHER") and delivered:
                arrive_dest = delivered - timedelta(hours=4)
            for when, kind, term in ev + [(arrive_dest, "ARRIVED_TERMINAL", dest)]:
                if when <= datetime.now(timezone.utc):
                    events.append({"pro_number": str(pro), "event_ts": when.isoformat(), "event_type": kind,
                                   "terminal_id": term, "note": None})
            if delivered:
                if late:
                    events.append({"pro_number": str(pro), "event_ts": (promised - timedelta(hours=1)).isoformat(),
                                   "event_type": "EXCEPTION", "terminal_id": dest, "note": reason})
                events.append({"pro_number": str(pro), "event_ts": (delivered - timedelta(hours=2)).isoformat(),
                               "event_type": "OUT_FOR_DELIVERY", "terminal_id": dest, "note": None})
                events.append({"pro_number": str(pro), "event_ts": delivered.isoformat(), "event_type": "DELIVERED",
                               "terminal_id": dest, "note": None})

                # Claims: base rate, more for light high-class freight, much more through the Memphis hub.
                p_claim = 0.007 * (2.2 if fclass >= 150 else 1) * (4.5 if hub == "MEM" else 1)
                if random.random() < p_claim:
                    ctype_claim = random.choices(["DAMAGE", "SHORTAGE", "LOSS"], [75, 20, 5])[0]
                    amount = round(min(revenue * random.uniform(1, 6), random.uniform(250, 6000)), 2)
                    filed = delivered.date() + timedelta(days=random.randint(1, 20))
                    if filed < TODAY:
                        claims.append({
                            "claim_id": f"CLM-{len(claims) + 1:05d}", "pro_number": str(pro), "claim_type": ctype_claim,
                            "amount_usd": amount, "filed_date": filed.isoformat(),
                            "status": random.choices(["PAID", "OPEN", "DENIED"], [60, 25, 15])[0],
                            "description": {
                                "DAMAGE": random.choice(["Pallet crushed, cartons torn", "Forklift puncture on two cases",
                                                         "Shrink wrap broken, items shifted and scratched", "Water damage to cartons"]),
                                "SHORTAGE": "Delivered short: fewer pieces than on the bill of lading",
                                "LOSS": "Shipment not delivered; last scan at terminal"}[ctype_claim],
                        })
        d += timedelta(days=1)
    return consignees, shipments, events, claims


SCHEMAS = {
    "terminals": [("terminal_id", "STRING"), ("name", "STRING"), ("city", "STRING"), ("state", "STRING"),
                  ("region", "STRING"), ("terminal_type", "STRING"), ("dock_doors", "INT64"),
                  ("latitude", "FLOAT64"), ("longitude", "FLOAT64")],
    "shippers": [("shipper_id", "STRING"), ("name", "STRING"), ("industry", "STRING"), ("home_terminal", "STRING")],
    "consignees": [("consignee_id", "STRING"), ("name", "STRING"), ("consignee_type", "STRING"), ("terminal_id", "STRING"),
                   ("city", "STRING"), ("state", "STRING"), ("contact_name", "STRING"), ("contact_phone", "STRING"),
                   ("contact_email", "STRING")],
    "shipments": [("pro_number", "STRING"), ("bol_number", "STRING"), ("shipper_id", "STRING"), ("consignee_id", "STRING"),
                  ("origin_terminal", "STRING"), ("destination_terminal", "STRING"), ("hub_terminal", "STRING"),
                  ("service_level", "STRING"), ("freight_class", "FLOAT64"), ("pallets", "INT64"), ("weight_lbs", "INT64"),
                  ("miles", "INT64"), ("revenue_usd", "NUMERIC"), ("accessorials", "STRING", "REPEATED"),
                  ("pickup_ts", "TIMESTAMP"), ("promised_delivery_ts", "TIMESTAMP"), ("delivered_ts", "TIMESTAMP"),
                  ("status", "STRING"), ("on_time", "BOOL"), ("delay_reason", "STRING"), ("delay_hours", "FLOAT64")],
    "shipment_events": [("pro_number", "STRING"), ("event_ts", "TIMESTAMP"), ("event_type", "STRING"),
                        ("terminal_id", "STRING"), ("note", "STRING")],
    "claims": [("claim_id", "STRING"), ("pro_number", "STRING"), ("claim_type", "STRING"), ("amount_usd", "NUMERIC"),
               ("filed_date", "DATE"), ("status", "STRING"), ("description", "STRING")],
}

VIEWS = {
    "v_terminals": "SELECT terminal_id, name, city, state, region, terminal_type, dock_doors FROM {terminals}",
    # Customer contact details never leave the raw tables; residential receivers are masked.
    "v_shipments": """
        SELECT s.pro_number, s.bol_number, s.shipper_id, sh.name AS shipper_name, sh.industry AS shipper_industry,
               s.consignee_id,
               IF(c.consignee_type = 'RESIDENCE', 'Residential customer', c.name) AS consignee_name,
               c.consignee_type, c.city AS consignee_city, c.state AS consignee_state,
               s.origin_terminal, o.city AS origin_city, s.destination_terminal, de.city AS destination_city,
               CONCAT(s.origin_terminal, '-', s.destination_terminal) AS lane, s.hub_terminal,
               s.service_level, s.freight_class, s.pallets, s.weight_lbs, s.miles, s.revenue_usd, s.accessorials,
               s.pickup_ts, DATE(s.pickup_ts) AS pickup_date, s.promised_delivery_ts, s.delivered_ts,
               DATE(s.delivered_ts) AS delivery_date, s.status, s.on_time, s.delay_reason, s.delay_hours
        FROM {shipments} s
        JOIN {shippers} sh USING (shipper_id)
        JOIN {consignees} c USING (consignee_id)
        JOIN {terminals} o ON o.terminal_id = s.origin_terminal
        JOIN {terminals} de ON de.terminal_id = s.destination_terminal""",
    "v_claims": """
        SELECT cl.claim_id, cl.pro_number, cl.claim_type, cl.amount_usd, cl.filed_date, cl.status, cl.description,
               s.shipper_id, sh.name AS shipper_name, s.origin_terminal, s.destination_terminal, s.hub_terminal,
               s.service_level, s.freight_class, s.weight_lbs
        FROM {claims} cl JOIN {shipments} s USING (pro_number) JOIN {shippers} sh USING (shipper_id)""",
    "v_shipment_events": "SELECT pro_number, event_ts, event_type, terminal_id, note FROM {shipment_events}",
    "v_bills_of_lading": """
        SELECT document_id, uploaded_at, status, bol_number, ship_date, shipper_name, consignee_name, consignee_city,
               consignee_state, total_pieces, total_weight_lbs, freight_classes, hazmat, accessorials, issues
        FROM {bills_of_lading}""",
}

DOC_SCHEMA = [
    ("document_id", "STRING"), ("uploaded_at", "TIMESTAMP"), ("file_name", "STRING"), ("status", "STRING"),
    ("bol_number", "STRING"), ("ship_date", "DATE"), ("shipper_name", "STRING"), ("shipper_address", "STRING"),
    ("consignee_name", "STRING"), ("consignee_address", "STRING"), ("consignee_city", "STRING"),
    ("consignee_state", "STRING"), ("total_pieces", "INT64"), ("total_weight_lbs", "FLOAT64"),
    ("freight_classes", "STRING", "REPEATED"), ("hazmat", "BOOL"), ("accessorials", "STRING", "REPEATED"),
    ("issues", "STRING", "REPEATED"), ("extracted_json", "JSON"), ("model", "STRING"), ("reviewed_by", "STRING"),
]
AUDIT_SCHEMA = [
    ("ts", "TIMESTAMP"), ("session_id", "STRING"), ("question", "STRING"), ("sql", "STRING"), ("status", "STRING"),
    ("reason", "STRING"), ("bytes_processed", "INT64"), ("rows_returned", "INT64"), ("model", "STRING"),
]


def _schema(cols):
    return [bigquery.SchemaField(c[0], c[1], mode=c[2] if len(c) > 2 else "NULLABLE") for c in cols]


def main() -> None:
    client = bigquery.Client(project=config.PROJECT)
    ds = bigquery.Dataset(f"{config.PROJECT}.{config.DATASET}")
    ds.location = config.BQ_LOCATION
    ds.description = "Synthetic LTL freight data for the Freight AI Analytics Platform demo (fictional)."
    client.create_dataset(ds, exists_ok=True)

    consignees, shipments, events, claims = generate()
    data = {
        "terminals": [dict(zip([c[0] for c in SCHEMAS["terminals"]], t)) for t in TERMINALS],
        "shippers": [dict(zip(["shipper_id", "name", "industry", "home_terminal"], s)) for s in SHIPPERS],
        "consignees": consignees, "shipments": shipments, "shipment_events": events, "claims": claims,
    }
    for name, rows in data.items():
        job = client.load_table_from_json(rows, f"{config.PROJECT}.{config.DATASET}.{name}", job_config=bigquery.LoadJobConfig(
            schema=_schema(SCHEMAS[name]), write_disposition="WRITE_TRUNCATE"))
        job.result()
        print(f"loaded {len(rows):>7} rows into {name}")

    for name, schema in (("bills_of_lading", DOC_SCHEMA), ("ai_audit_log", AUDIT_SCHEMA)):
        tbl = bigquery.Table(f"{config.PROJECT}.{config.DATASET}.{name}", schema=_schema(schema))
        client.create_table(tbl, exists_ok=True)

    names = {n: config.table(n) for n in list(SCHEMAS) + ["bills_of_lading"]}
    for view, sql in VIEWS.items():
        client.query(f"CREATE OR REPLACE VIEW {config.table(view)} AS {sql.format(**names)}").result()
        print(f"view {view}")
    print(f"Done. Shipments {START} to {TODAY - timedelta(days=1)}.")


if __name__ == "__main__":
    main()
