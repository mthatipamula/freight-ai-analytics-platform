"""Trailer tracking API: fixed, parameterized queries over the telematics views (not AI-generated)."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from google.cloud import bigquery

from . import config, governance


def _rows(sql: str, params: list | None = None) -> list[dict]:
    job = governance.client().query(sql, job_config=bigquery.QueryJobConfig(query_parameters=params or []))
    return [{k: governance._jsonable(v) for k, v in dict(r).items()} for r in job.result()]


def positions() -> list[dict]:
    return _rows(f"""
        SELECT trailer_id, trailer_type, home_terminal, last_ping_ts, latitude, longitude, speed_mph, heading_deg,
               door_open, loaded, reefer_temp_f, site_name, site_type, site_terminal, status, hours_stationary
        FROM {config.table('v_trailer_positions')} ORDER BY trailer_id""")


def trail(trailer_id: str, hours: int) -> dict:
    p = [bigquery.ScalarQueryParameter("id", "STRING", trailer_id), bigquery.ScalarQueryParameter("h", "INT64", hours)]
    pings = _rows(f"""
        SELECT ping_ts, event_type, latitude, longitude, speed_mph, door_open, loaded, reefer_temp_f, site_name
        FROM {config.table('v_trailer_pings')}
        WHERE trailer_id = @id AND ping_ts > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @h HOUR)
        ORDER BY ping_ts""", p)
    trips = _rows(f"""
        SELECT t.trip_id, t.trip_type, t.origin_name, t.destination_name, t.depart_ts, t.arrive_ts, t.trip_status,
               t.loaded, t.pallets, t.miles, COUNT(l.pro_number) AS shipments,
               ARRAY_AGG(DISTINCT c.claim_id IGNORE NULLS) AS claims
        FROM {config.table('v_trailer_trips')} t
        LEFT JOIN {config.table('v_trailer_loads')} l USING (trip_id)
        LEFT JOIN {config.table('v_claims')} c ON c.pro_number = l.pro_number
        WHERE t.trailer_id = @id AND t.depart_ts > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 14 DAY)
        GROUP BY 1, 2, 3, 4, 5, 6, 7, 8, 9, 10 ORDER BY t.depart_ts DESC""", p[:1])
    return {"trailerId": trailer_id, "pings": pings, "trips": trips}


def alerts() -> dict:
    v = config.table
    queries = {
        "detention": (f"""
            SELECT trailer_id, site_name, site_terminal, hours_stationary, loaded, latitude, longitude
            FROM {v('v_trailer_positions')}
            WHERE status = 'AT_CUSTOMER' AND hours_stationary > 48 ORDER BY hours_stationary DESC"""),
        "idleEmpties": (f"""
            SELECT site_terminal AS terminal, COUNT(*) AS trailers, ROUND(AVG(hours_stationary)) AS avg_hours,
                   ARRAY_AGG(trailer_id ORDER BY hours_stationary DESC LIMIT 5) AS examples
            FROM {v('v_trailer_positions')}
            WHERE status = 'AT_TERMINAL' AND NOT loaded AND hours_stationary > 72
            GROUP BY 1 ORDER BY trailers DESC"""),
        # Door opened away from any terminal or customer site, with the shipments on board and any claims filed.
        "doorOpens": (f"""
            SELECT p.trailer_id, p.ping_ts, p.latitude, p.longitude, t.trip_id, t.origin_name, t.destination_name,
                   COUNT(DISTINCT l.pro_number) AS shipments_on_board,
                   ARRAY_AGG(DISTINCT c.claim_id IGNORE NULLS) AS claims
            FROM {v('v_trailer_pings')} p
            LEFT JOIN {v('v_trailer_trips')} t ON t.trailer_id = p.trailer_id AND p.ping_ts BETWEEN t.depart_ts AND t.arrive_ts
            LEFT JOIN {v('v_trailer_loads')} l ON l.trip_id = t.trip_id
            LEFT JOIN {v('v_claims')} c ON c.pro_number = l.pro_number
            WHERE p.event_type = 'DOOR_OPENED' AND p.site_id IS NULL
              AND p.ping_ts > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
            GROUP BY 1, 2, 3, 4, 5, 6, 7 ORDER BY p.ping_ts DESC"""),
        "temperature": (f"""
            SELECT trailer_id, MIN(ping_ts) AS first_ts, MAX(ping_ts) AS last_ts, MAX(reefer_temp_f) AS max_temp_f,
                   ROUND(TIMESTAMP_DIFF(MAX(ping_ts), MIN(ping_ts), MINUTE) / 60, 1) AS hours_above
            FROM {v('v_trailer_pings')}
            WHERE reefer_temp_f > 41 AND ping_ts > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
            GROUP BY 1 ORDER BY first_ts DESC"""),
    }
    with ThreadPoolExecutor(len(queries)) as pool:  # independent queries: run them at the same time
        futures = {k: pool.submit(_rows, sql) for k, sql in queries.items()}
        return {k: f.result() for k, f in futures.items()}


def sites() -> list[dict]:
    return _rows(f"SELECT site_id, site_name, site_type, latitude, longitude FROM {config.table('v_sites')} WHERE site_type = 'TERMINAL'")
