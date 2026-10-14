"""Semantic layer: what the data means, in business terms. The agent reads this instead of guessing.

This plays the role a Looker model (LookML) plays in production: one agreed definition of each metric
(e.g. "on-time rate" counts delivered shipments only), so the AI and the dashboards report the same numbers.
"""

VIEWS = {
    "v_shipments": {
        "description": "One row per LTL shipment (PRO number) from pickup to delivery.",
        "columns": {
            "pro_number": "Shipment tracking number", "bol_number": "Bill of lading number",
            "shipper_name": "Customer that sent the freight", "shipper_industry": "Shipper's industry",
            "consignee_name": "Receiver ('Residential customer' for home deliveries)",
            "consignee_type": "GROCERY_DC, RETAIL_STORE, CONTRACTOR, MANUFACTURING_PLANT, RESIDENCE, HOSPITAL, TRADE_SHOW_VENUE",
            "consignee_city": "Receiver city", "consignee_state": "Receiver state",
            "origin_terminal": "Terminal code where freight was picked up (e.g. CLT)", "origin_city": "Origin city",
            "destination_terminal": "Terminal code that delivers (e.g. ATL)", "destination_city": "Destination city",
            "lane": "ORIGIN-DESTINATION terminal pair, e.g. CLT-ATL",
            "hub_terminal": "Breakbulk hub the freight was routed through (MEM, HAR, DAL) or NULL for direct",
            "service_level": "STANDARD, TIME_CRITICAL (guaranteed), GROCERY_APPOINTMENT (strict delivery window)",
            "freight_class": "NMFC freight class 50-500 (higher = lighter/bulkier/more fragile, costs more)",
            "pallets": "Handling units", "weight_lbs": "Weight in pounds", "miles": "Lane distance",
            "revenue_usd": "Freight charges in USD", "accessorials": "ARRAY<STRING> of extra services: LIFTGATE, RESIDENTIAL, APPOINTMENT, INSIDE_DELIVERY",
            "pickup_ts": "Pickup timestamp", "pickup_date": "Pickup date", "promised_delivery_ts": "Promised delivery time",
            "delivered_ts": "Actual delivery time (NULL if in transit)", "delivery_date": "Actual delivery date",
            "status": "DELIVERED or IN_TRANSIT", "on_time": "TRUE/FALSE for delivered shipments, NULL in transit",
            "delay_reason": "For late shipments: LINEHAUL_DELAY, WEATHER, CAPACITY, MISSORT, CONSIGNEE_CLOSED, MISSED_APPOINTMENT",
            "delay_hours": "Hours late (0 when on time)",
        },
    },
    "v_claims": {
        "description": "Freight claims filed by customers (OS&D: over, short and damaged).",
        "columns": {
            "claim_id": "Claim id", "pro_number": "Shipment", "claim_type": "DAMAGE, SHORTAGE, LOSS",
            "amount_usd": "Amount claimed", "filed_date": "Date filed", "status": "OPEN, PAID, DENIED",
            "description": "What happened", "shipper_name": "Shipper", "origin_terminal": "Origin",
            "destination_terminal": "Destination", "hub_terminal": "Hub routed through or NULL",
            "service_level": "Service level", "freight_class": "Freight class", "weight_lbs": "Weight",
        },
    },
    "v_terminals": {
        "description": "Service centers. END_OF_LINE terminals pick up and deliver locally; BREAKBULK hubs sort and re-route.",
        "columns": {"terminal_id": "Code, e.g. ATL", "name": "Name", "city": "City", "state": "State",
                    "region": "SOUTHEAST, MID_ATLANTIC, MIDWEST, SOUTHWEST, MOUNTAIN",
                    "terminal_type": "END_OF_LINE or BREAKBULK", "dock_doors": "Number of dock doors"},
    },
    "v_shipment_events": {
        "description": "Tracking scans: PICKED_UP, ARRIVED_TERMINAL, DEPARTED_TERMINAL, EXCEPTION, OUT_FOR_DELIVERY, DELIVERED.",
        "columns": {"pro_number": "Shipment", "event_ts": "Scan time", "event_type": "Scan type",
                    "terminal_id": "Where it happened", "note": "Exception reason for EXCEPTION scans"},
    },
    "v_bills_of_lading": {
        "description": "Bills of lading read by the document AI (uploaded scans).",
        "columns": {"document_id": "Id", "uploaded_at": "Upload time", "status": "NEEDS_REVIEW, READY, APPROVED",
                    "bol_number": "BOL number", "ship_date": "Ship date", "shipper_name": "Shipper",
                    "consignee_name": "Consignee", "total_pieces": "Pieces", "total_weight_lbs": "Weight",
                    "freight_classes": "ARRAY<STRING>", "hazmat": "Hazardous materials", "issues": "ARRAY<STRING> validation issues"},
    },
    "v_trailers": {
        "description": "Trailer fleet. Every trailer has a telematics unit.",
        "columns": {"trailer_id": "Trailer number, e.g. V530012", "trailer_type": "DRY_VAN_53, REEFER_53 (refrigerated), PUP_28 (city/drop trailer)",
                    "length_ft": "53 or 28", "home_terminal": "Terminal the trailer is assigned to", "in_service_year": "Year"},
    },
    "v_sites": {
        "description": "Geofences: terminals (900 m radius) and customer sites where trailers are dropped (400 m).",
        "columns": {"site_id": "Terminal code or S-<consignee id>", "site_name": "Name", "site_type": "TERMINAL or CUSTOMER",
                    "terminal_id": "Terminal that serves the site", "center": "GEOGRAPHY point", "latitude": "Latitude",
                    "longitude": "Longitude", "radius_m": "Geofence radius in meters"},
    },
    "v_trailer_pings": {
        "description": "Telematics readings, last 30 days: every 15 min moving, hourly parked, and on each event. "
                       "Large: always filter on ping_ts or ping_date and trailer_id where possible.",
        "columns": {"trailer_id": "Trailer", "ping_ts": "Reading time (UTC)", "ping_date": "Date of ping_ts",
                    "event_type": "PERIODIC, MOTION_START, MOTION_STOP, DOOR_OPENED, DOOR_CLOSED, CARGO_LOADED, CARGO_EMPTY",
                    "location": "GEOGRAPHY point (use ST_DISTANCE, ST_DWITHIN)", "latitude": "Latitude", "longitude": "Longitude",
                    "speed_mph": "Speed; above 5 means moving", "heading_deg": "Compass heading", "door_open": "Rear door open",
                    "loaded": "Cargo sensor: TRUE if freight is inside", "reefer_temp_f": "Box temperature in F (refrigerated and loaded only, else NULL)",
                    "site_id": "Geofence the trailer is inside, NULL when on the road", "site_name": "Site name",
                    "site_type": "TERMINAL or CUSTOMER, NULL on the road", "site_terminal": "Terminal serving that site"},
    },
    "v_trailer_positions": {
        "description": "Current position and status of every trailer (its latest telematics reading).",
        "columns": {"trailer_id": "Trailer", "trailer_type": "Type", "home_terminal": "Home terminal",
                    "last_ping_ts": "Latest reading", "latitude": "Latitude", "longitude": "Longitude", "speed_mph": "Speed",
                    "door_open": "Door open now", "loaded": "Freight inside", "reefer_temp_f": "Box temperature",
                    "site_id": "Current geofence or NULL", "site_name": "Where it is", "site_type": "TERMINAL, CUSTOMER or NULL",
                    "site_terminal": "Terminal serving that site",
                    "status": "MOVING, AT_TERMINAL, AT_CUSTOMER, STOPPED_EN_ROUTE",
                    "hours_stationary": "Hours since the trailer last moved (dwell time); 0 when moving"},
    },
    "v_trailer_trips": {
        "description": "Trailer moves between sites.",
        "columns": {"trip_id": "Trip", "trailer_id": "Trailer", "trailer_type": "Type",
                    "trip_type": "LINEHAUL (loaded, terminal to terminal), EMPTY_REPOSITION, CUSTOMER_DROP, RETURN_EMPTY",
                    "origin_site_id": "From site", "origin_name": "From", "destination_site_id": "To site",
                    "destination_name": "To", "depart_ts": "Departure", "arrive_ts": "Arrival (or ETA if in progress)",
                    "trip_status": "IN_PROGRESS or COMPLETED", "loaded": "Carried freight", "pallets": "Pallets on board",
                    "miles": "Trip miles"},
    },
    "v_trailer_loads": {
        "description": "Which shipments rode on which linehaul trip. Join v_shipments or v_claims on pro_number, "
                       "v_trailer_trips on trip_id.",
        "columns": {"trip_id": "Trip", "pro_number": "Shipment"},
    },
}

METRICS = {
    "on_time_rate": "AVG(IF(on_time, 1, 0)) over delivered shipments only (status = 'DELIVERED'). Format as a percentage.",
    "shipments": "COUNT(*) of shipments (by pickup_date unless the question is about deliveries).",
    "revenue": "SUM(revenue_usd).",
    "revenue_per_shipment": "SUM(revenue_usd) / COUNT(*).",
    "claim_rate": "Claims divided by delivered shipments for the same grouping: LEFT JOIN v_claims USING (pro_number).",
    "claims_cost": "SUM(amount_usd) from v_claims (status PAID for money actually paid out).",
    "average_delay_hours": "AVG(delay_hours) over late delivered shipments (on_time = FALSE).",
    "transit_days": "TIMESTAMP_DIFF(delivered_ts, pickup_ts, HOUR) / 24 for delivered shipments.",
    "dwell_hours": "hours_stationary from v_trailer_positions (current), or time between arrival and next departure in v_trailer_trips.",
    "detention": "A trailer at a CUSTOMER site with hours_stationary > 48 (free time exceeded; billable to the customer).",
    "idle_empty_trailers": "status = 'AT_TERMINAL' AND NOT loaded AND hours_stationary > 72 in v_trailer_positions.",
    "empty_miles_share": "SUM(IF(NOT loaded, miles, 0)) / SUM(miles) in v_trailer_trips.",
    "unplanned_door_open": "event_type = 'DOOR_OPENED' AND site_id IS NULL in v_trailer_pings (door opened away from any terminal or customer: theft or shortage risk).",
    "temperature_excursion": "reefer_temp_f > 41 in v_trailer_pings (refrigerated freight should stay 34-40 F).",
}

GLOSSARY = {
    "LTL": "Less-than-truckload: shipments of 1-6 pallets from many shippers sharing a trailer.",
    "terminal / service center": "Building where freight is cross-docked between pickup, linehaul and delivery trucks.",
    "linehaul": "Long-distance moves between terminals, usually overnight.",
    "consignee": "The receiver of a shipment. The shipper is the sender.",
    "appointment window": "Delivery time slot set by the receiver; grocery DCs refuse loads that miss it.",
    "freight class": "NMFC classification (50-500) based on density, handling and liability; drives the rate.",
    "accessorials": "Extra services charged on top: liftgate, residential, appointment, inside delivery.",
    "telematics": "GPS and sensor unit on each trailer reporting position, speed, door, cargo and temperature.",
    "geofence": "A circle around a terminal or customer site; a ping inside it means the trailer is at that site.",
    "drop trailer": "A trailer left at a customer to load or unload on their schedule, collected later.",
    "detention": "Charge when a customer keeps a trailer longer than the free time.",
    "empty repositioning": "Moving empty trailers to terminals that need them; costs miles without revenue.",
    "reefer": "Refrigerated trailer.",
    "pup": "28-foot trailer used for city pickup and delivery or pulled in pairs on linehaul.",
}


def describe() -> str:
    lines = ["# Approved views (query ONLY these)"]
    for view, spec in VIEWS.items():
        lines.append(f"\n## {view}: {spec['description']}")
        lines += [f"- {col}: {desc}" for col, desc in spec["columns"].items()]
    lines.append("\n# Metric definitions (use exactly these)")
    lines += [f"- {k}: {v}" for k, v in METRICS.items()]
    lines.append("\n# Glossary")
    lines += [f"- {k}: {v}" for k, v in GLOSSARY.items()]
    return "\n".join(lines)
