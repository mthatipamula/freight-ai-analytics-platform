import pytest

from app.governance import QueryBlocked, check_sql

OK = [
    "SELECT destination_terminal, AVG(IF(on_time,1,0)) FROM v_shipments GROUP BY 1",
    "SELECT * FROM `my-test-project-279216.freight_analytics.v_claims` WHERE claim_type = 'DAMAGE'",
    "WITH weekly AS (SELECT DATE_TRUNC(delivery_date, WEEK) wk FROM v_shipments) SELECT wk FROM weekly",
    "SELECT s.lane, COUNT(c.claim_id) FROM v_shipments s LEFT JOIN v_claims c USING (pro_number) GROUP BY 1",
    "SELECT a FROM v_shipments, UNNEST(accessorials) a",
    "SELECT 'DROP TABLE x' AS label FROM v_terminals",            # keywords inside strings are fine
    "-- delete everything\nSELECT COUNT(*) FROM v_shipments",       # and inside comments
    "SELECT DATE_TRUNC(pickup_date, WEEK) AS week, COUNT(*) AS shipments FROM v_shipments GROUP BY 1",  # alias = table name
    "SELECT EXTRACT(WEEK FROM pickup_date) AS wk, COUNT(*) AS claims FROM v_claims c GROUP BY 1 ORDER BY claims",
    "SELECT * FROM v_shipments s JOIN v_terminals t ON s.destination_terminal = t.terminal_code",
]
BLOCKED = [
    ("SELECT contact_phone FROM consignees", "not approved"),
    ("SELECT * FROM `my-test-project-279216.freight_analytics.consignees`", "not approved"),
    ("SELECT * FROM v_shipments, consignees", "not approved"),               # comma join to a raw table
    ("SELECT * FROM shipments", "not approved"),
    ("SELECT * FROM v_shipments AS s, `my-test-project-279216.freight_analytics.consignees` c", "not approved"),
    ("SELECT * FROM v_shipments s LEFT JOIN shippers sh ON TRUE", "not approved"),
    ("SELECT * FROM v_shipments WHERE pro_number IN (SELECT pro_number FROM claims)", "not approved"),
    ("SELECT * FROM (SELECT * FROM consignees) x", "not approved"),
    ("DELETE FROM v_shipments WHERE TRUE", "SELECT"),
    ("SELECT 1; DROP TABLE v_shipments", "one SQL statement"),
    ("SELECT * FROM other_dataset.v_shipments", "outside the approved dataset"),
    ("SELECT * FROM region-us.INFORMATION_SCHEMA.TABLES", "Metadata"),
    ("WITH x AS (SELECT 1) SELECT * FROM x; UPDATE v_claims SET status='PAID'", "one SQL statement"),
]


@pytest.mark.parametrize("sql", OK)
def test_allowed(sql):
    check_sql(sql)


@pytest.mark.parametrize("sql,reason", BLOCKED)
def test_blocked(sql, reason):
    with pytest.raises(QueryBlocked, match=reason):
        check_sql(sql)
