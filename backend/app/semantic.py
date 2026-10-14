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
}

GLOSSARY = {
    "LTL": "Less-than-truckload: shipments of 1-6 pallets from many shippers sharing a trailer.",
    "terminal / service center": "Building where freight is cross-docked between pickup, linehaul and delivery trucks.",
    "linehaul": "Long-distance moves between terminals, usually overnight.",
    "consignee": "The receiver of a shipment. The shipper is the sender.",
    "appointment window": "Delivery time slot set by the receiver; grocery DCs refuse loads that miss it.",
    "freight class": "NMFC classification (50-500) based on density, handling and liability; drives the rate.",
    "accessorials": "Extra services charged on top: liftgate, residential, appointment, inside delivery.",
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
