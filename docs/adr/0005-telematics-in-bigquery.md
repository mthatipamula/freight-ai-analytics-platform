# 0005: Trailer telematics in BigQuery, Bigtable only if needed

**Status:** Accepted

## Context
Every trailer reports GPS, speed, door, cargo and temperature: every 5-15 minutes moving and hourly parked, which is
millions of rows a day for a large fleet. The business needs history and analytics (detention, idle empties,
door openings linked to claims), plus the current position of each trailer.

## Decision
Store pings in **BigQuery**: `trailer_pings` partitioned by day, clustered by trailer, with a `GEOGRAPHY` column.
Geofencing (terminal and customer sites) is done in SQL with `ST_DWITHIN`; status and dwell time are views. In
production, devices publish to **Pub/Sub** with a BigQuery subscription, and **Dataflow** raises real-time alerts.

## Alternatives considered
| Option | Why not (as the primary store) |
|---|---|
| Bigtable | Excellent for millisecond reads of "where is trailer X now" at very high write volume, but no SQL analytics or joins to shipments and claims; add it as a latest-position cache only if a live app needs it |
| AlloyDB / Cloud SQL with PostGIS | Great geospatial features, but costly at billions of rows and the data would still be copied to BigQuery for analytics |
| Firestore | Fine for a few live positions, not for history or analytics |

## Consequences
- The AI agent queries trailers through the same governed views, and can join trailer trips to shipments and claims
  ("was the door opened on the load that had a shortage claim?").
- The geofence view scans the ping table (about 20 MB in the demo); at production scale, queries filter on the
  partition date and a nightly table of site visits replaces the per-query spatial join.
