from app.evals import PHONE, Run, close_to, numbers_in, sql_matches


def test_numbers_in_reads_prose_formats():
    assert numbers_in("on-time was 90.7% across 4,061 shipments") == [90.7, 4061.0]
    assert numbers_in("revenue of $5.25 million") == [5_250_000.0]
    assert numbers_in("about $310K") == [310_000.0]
    assert numbers_in("peaked at 50.5°F after 12 months") == [50.5, 12.0]


def test_close_to_tolerance():
    assert close_to("It was 90.7%.", [90.68], 0.006, "x")[1]
    assert not close_to("It was 88.0%.", [90.68], 0.006, "x")[1]
    assert close_to("7 shortage claims", [7.0], 0.0, "x")[1]


def test_metric_definition_check_looks_at_executed_sql():
    run = Run(sqls=["SELECT AVG(IF(on_time,1,0)) FROM v_shipments WHERE status = 'DELIVERED'"])
    assert sql_matches(run, r"status\s*=\s*'DELIVERED'", "x")[1]
    assert not sql_matches(Run(sqls=["SELECT AVG(IF(on_time,1,0)) FROM v_shipments"]), r"status\s*=\s*'DELIVERED'", "x")[1]


def test_phone_pattern():
    assert PHONE.search("call 555-234-9876")
    assert not PHONE.search("PRO 4810074401 had 3 pallets")


def test_names_place_accepts_natural_phrasing():
    from app.evals import names_place
    assert names_place("FreshMart's Atlanta DC had 113 misses", "FreshMart DC - Atlanta")[1]
    assert not names_place("FreshMart's Detroit DC had 113 misses", "FreshMart DC - Atlanta")[1]
