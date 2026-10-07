"""台账结构层：建表、幂等、异常值可入库、模型字段校验。

注意"异常值可入库"是设计决定：负值/超范围要被检出而不是被数据库拒绝。
"""

import pytest

from road_mqi_checker.errors import InputUnavailable
from road_mqi_checker.ledger import db
from road_mqi_checker.ledger import models


@pytest.fixture
def conn():
    connection = db.connect(":memory:")
    db.initialize(connection)
    yield connection
    connection.close()


def test_expected_tables_created(conn):
    assert db.table_names(conn) == db.expected_tables()


def test_initialize_is_idempotent(conn):
    db.initialize(conn)
    db.initialize(conn)
    assert db.table_names(conn) == db.expected_tables()


def test_meta_records_schema_version(conn):
    assert db.read_meta(conn, db.META_SCHEMA_KEY) == db.SCHEMA_VERSION


def test_negative_quantity_is_storable(conn):
    """录入异常（负值）必须进得了库，否则模块 1 的"异常识别召回"无从谈起。"""
    conn.execute(
        "INSERT INTO route (route_id, year, route_name, admin_grade, tech_grade,"
        " start_stake_m, end_stake_m, adcode, note) VALUES (?,?,?,?,?,?,?,?,?)",
        ("S99", 2025, "SYN 试验线", "二级", "二级", 0, 4200, "990000", ""),
    )
    conn.execute(
        "INSERT INTO segment (segment_id, route_id, year, segment_name, start_stake_m,"
        " end_stake_m, surface_type, note) VALUES (?,?,?,?,?,?,?,?)",
        ("SYN-01", "S99", 2025, "SYN-东段", 0, 4200, "asphalt", ""),
    )
    conn.execute(
        "INSERT INTO distress (segment_id, year, distress_type, severity, quantity, quantity_unit, source_row_no)"
        " VALUES (?,?,?,?,?,?,?)",
        ("SYN-01", 2025, "坑槽", "重", -12.5, "m2", 3),
    )
    conn.commit()
    rows = conn.execute("SELECT quantity FROM distress").fetchall()
    assert [row["quantity"] for row in rows] == [-12.5]


def test_duplicate_segment_key_is_rejected(conn):
    args = ("SYN-01", "S99", 2025, "SYN-东段", 0, 4200, "asphalt", "")
    conn.execute(
        "INSERT INTO segment (segment_id, route_id, year, segment_name, start_stake_m,"
        " end_stake_m, surface_type, note) VALUES (?,?,?,?,?,?,?,?)",
        args,
    )
    with pytest.raises(Exception):
        conn.execute(
            "INSERT INTO segment (segment_id, route_id, year, segment_name, start_stake_m,"
            " end_stake_m, surface_type, note) VALUES (?,?,?,?,?,?,?,?)",
            args,
        )
        conn.commit()


def test_partition_change_kinds_are_declared():
    assert set(db.CHANGE_KINDS) >= {"new", "disappeared", "merged", "split"}


def test_route_requires_fields_and_rejects_reversed_stakes():
    good = models.Route("S99", "SYN 试验线", "二级", "二级", 0, 4200, adcode="990000")
    good.validate()
    with pytest.raises(InputUnavailable):
        models.Route("S99", "SYN 试验线", "二级", "二级", 4200, 0).validate()
    with pytest.raises(InputUnavailable):
        models.Route("", "SYN 试验线", "二级", "二级", 0, 4200).validate()


def test_segment_surface_type_vocabulary():
    with pytest.raises(InputUnavailable):
        models.Segment("SYN-01", "S99", 2025, "SYN-东段", 0, 100, "gravel").validate()
    assert models.Segment("SYN-01", "S99", 2025, "SYN-东段", 0, 100, "cement").length_m == 100


def test_measured_indicator_none_is_not_zero():
    """缺测必须保持 None：填 0 会被加权当真值。"""
    survey = models.SurveyRecord("SYN-01", "S99", 2025, "asphalt")
    assert survey.rqi is None
    assert survey.measured_indicators()["rut_depth_mm"] is None


def test_distress_row_must_belong_to_its_survey():
    row = models.DistressRow("SYN-02", 2024, "坑槽", "轻", 1.0, "m2")
    survey = models.SurveyRecord("SYN-01", "S99", 2025, "asphalt", distress_rows=[row])
    with pytest.raises(InputUnavailable):
        survey.validate()


def test_injected_issue_vocabulary_matches_ledger_doc():
    assert "unit_error" in models.INJECTED_ISSUES
    assert "none" in models.INJECTED_ISSUES
