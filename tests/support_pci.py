"""M2 测试共用构造：夹具规则集 + "一份输入两条通路"的台账对象。

夹具规则集只能在测试通路加载（`allow_fixture=True`），数值刻意避开任何真实规范数字；
`kernel_input()` 与 `insert()` 共用同一份 spec，用来证明评定核（生成器真值走的路）
与台账通路（CLI/GUI 走的路）确实是同一个内核、同一套结果。
"""

import copy
import json
import os

from road_mqi_checker.ledger import db
from road_mqi_checker.ruleset import loader

FIXTURE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
ASPHALT_FIXTURE = "pci-fixture-asphalt.json"
CEMENT_FIXTURE = "pci-fixture-cement.json"


def fixture_ruleset(name):
    return loader.load_file(os.path.join(FIXTURE_DIR, name), allow_fixture=True)


def asphalt_ruleset():
    return fixture_ruleset(ASPHALT_FIXTURE)


def cement_ruleset():
    return fixture_ruleset(CEMENT_FIXTURE)


def patched_ruleset(name, mutate):
    """把夹具包按测试需要改一格（删系数 / 改状态 / 清条款）后重新过 schema 门。"""
    path = os.path.join(FIXTURE_DIR, name)
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    mutate(payload)
    return loader.RuleSet.from_dict(payload, source_path=path, allow_fixture=True)


def drop_coefficient(key):
    def _mutate(payload):
        payload["coefficients"] = [c for c in payload["coefficients"] if c["key"] != key]

    return _mutate


def set_status(key, status, values=None):
    def _mutate(payload):
        for coef in payload["coefficients"]:
            if coef["key"] == key:
                coef["status"] = status
                if status in ("pending", "located"):
                    coef["values"] = None
                elif values is not None:
                    coef["values"] = values

    return _mutate


def clear_clause(key):
    def _mutate(payload):
        for coef in payload["coefficients"]:
            if coef["key"] == key:
                for basis in coef["basis"]:
                    basis["clause"] = ""

    return _mutate


def mutate_value(key, field, value):
    def _mutate(payload):
        for coef in payload["coefficients"]:
            if coef["key"] == key:
                coef["values"][field] = copy.deepcopy(value)

    return _mutate


def append_coefficients(*coefficients):
    """往夹具包里再补几格（测试 M4 支配格时用来把系数门打开，让"引擎未就位"这一档露出来）。"""

    def _mutate(payload):
        payload["coefficients"].extend(copy.deepcopy(list(coefficients)))

    return _mutate


def mqi_and_action_cells():
    """`mqi_partial_truth` / `recommended_action_truth` 两列的支配格（M4 才用得着）。"""
    return (
        {
            "key": "mqi_weight.pavement",
            "kind": "component_weight",
            "status": "fixture",
            "values": {"weight": 100.0},
            "basis": [
                {
                    "standard_id": "fixture",
                    "status": "fixture",
                    "clause": "夹具式 E-1",
                    "channel": "tests/fixtures",
                    "verified_at": "夹具",
                    "locator": "tests/fixtures/pci-fixture-asphalt.json",
                }
            ],
            "register_ref": "tests/fixtures/pci-fixture-asphalt.json",
        },
        {
            "key": "action_rule.maintenance_trigger",
            "kind": "action_rule",
            "status": "fixture",
            "values": {"trigger": "pci_lt_60"},
            "basis": [
                {
                    "standard_id": "fixture",
                    "status": "fixture",
                    "clause": "夹具式 F-1",
                    "channel": "tests/fixtures",
                    "verified_at": "夹具",
                    "locator": "tests/fixtures/pci-fixture-asphalt.json",
                }
            ],
            "register_ref": "tests/fixtures/pci-fixture-asphalt.json",
        },
    )


#: 黄金用例的破损行：(类型, 程度, 数量, 量纲, 原始文件行号)
GOLDEN_ASPHALT_ROWS = (
    ("坑槽", "重", 150.0, "m2", 1),
    ("纵向裂缝", "中", 100.0, "m", 2),
    ("网状裂缝", "轻", 75.0, "m2", 3),
)
GOLDEN_CEMENT_ROWS = (
    ("破碎板", "重", 5.0, "块", 1),
    ("裂缝", "轻", 200.0, "m", 2),
)

ASPHALT_SPEC = {
    "segment_id": "SYN-G1",
    "route_id": "S99",
    "year": 2025,
    "surface_type": "asphalt",
    "start_m": 0,
    "end_m": 1000,
    "lane_count": 2,
    "width_m": 7.5,
    "panel_count": None,
    "rqi": 85.0,
    "rut_depth_mm": 6.0,
    "skid_indicator": 50.0,
    "skid_indicator_kind": "SFC",
    "rows": GOLDEN_ASPHALT_ROWS,
}
CEMENT_SPEC = {
    "segment_id": "SYN-G2",
    "route_id": "X990",
    "year": 2025,
    "surface_type": "cement",
    "start_m": 0,
    "end_m": 1000,
    "lane_count": 2,
    "width_m": 9.0,
    "panel_count": 100,
    "rqi": 90.0,
    "rut_depth_mm": None,
    "skid_indicator": 30.0,
    "skid_indicator_kind": "BPN",
    "rows": GOLDEN_CEMENT_ROWS,
}


def spec(**overrides):
    merged = dict(ASPHALT_SPEC)
    merged.update(overrides)
    return merged


def kernel_input(obj):
    """评定核的输入字典（与 `pci.engine.load_segment_input` 同形）。"""
    return {
        "segment_id": obj["segment_id"],
        "route_id": obj["route_id"],
        "year": obj["year"],
        "surface_type": obj["surface_type"],
        "length_m": obj["end_m"] - obj["start_m"],
        "lane_count": obj["lane_count"],
        "segment_width_m": obj["width_m"],
        "panel_count": obj["panel_count"],
        "skid_indicator_kind": obj["skid_indicator_kind"],
        "indicators": {
            "rqi": obj["rqi"],
            "rut_depth_mm": obj["rut_depth_mm"],
            "skid_indicator": obj["skid_indicator"],
        },
        "distress_rows": [
            {
                "distress_type": distress_type,
                "severity": severity,
                "quantity": quantity,
                "quantity_unit": unit,
                "lane_no": 1,
                "source_row_no": row_no,
            }
            for (distress_type, severity, quantity, unit, row_no) in obj["rows"]
        ],
        "has_survey": obj.get("has_survey", True),
    }


def open_ledger():
    conn = db.connect(":memory:")
    db.initialize(conn)
    return conn


def insert(conn, obj):
    """把一个 spec 落成台账四行（路线/路段/检测记录/破损行），绕过导入层只为造判据素材。"""
    length = obj["end_m"] - obj["start_m"]
    conn.execute(
        "INSERT OR REPLACE INTO route (route_id, year, route_name, admin_grade, tech_grade,"
        " start_stake_m, end_stake_m, adcode, note) VALUES (?,?,?,?,?,?,?,?,?)",
        (obj["route_id"], obj["year"], "SYN-黄金用例线", "二级", "二级", obj["start_m"], obj["end_m"], "990101", ""),
    )
    conn.execute(
        "INSERT OR REPLACE INTO segment (segment_id, route_id, year, segment_name, start_stake_m,"
        " end_stake_m, surface_type, note, lane_count, segment_width_m, panel_count)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            obj["segment_id"],
            obj["route_id"],
            obj["year"],
            "SYN-黄金用例段 K0+000～K%d+000" % (length // 1000),
            obj["start_m"],
            obj["end_m"],
            obj["surface_type"],
            "",
            obj["lane_count"],
            obj["width_m"],
            obj["panel_count"],
        ),
    )
    if obj.get("has_survey", True):
        conn.execute(
            "INSERT OR REPLACE INTO survey (segment_id, route_id, year, surface_type, rqi,"
            " rut_depth_mm, skid_indicator, skid_indicator_kind, report_no, detect_org, note)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                obj["segment_id"],
                obj["route_id"],
                obj["year"],
                obj["surface_type"],
                obj["rqi"],
                obj["rut_depth_mm"],
                obj["skid_indicator"],
                obj["skid_indicator_kind"],
                "SYN-LG-%d-0001" % obj["year"],
                "示例公路工程检测有限公司",
                "",
            ),
        )
    for (distress_type, severity, quantity, unit, row_no) in obj["rows"]:
        conn.execute(
            "INSERT INTO distress (segment_id, year, distress_type, severity, quantity,"
            " quantity_unit, area_m2, lane_no, source_row_no, note) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (obj["segment_id"], obj["year"], distress_type, severity, quantity, unit, None, 1, row_no, ""),
        )
    conn.commit()
    return conn
