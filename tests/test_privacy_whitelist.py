"""隐私白名单：正例过、真实形态一律拒。

红线来自题目 §六.3 —— 演示数据不得出现真实路线、真实行政代码、真实号段。
负例（真实形态）必须被拒，否则白名单等于没有。
"""

import pytest

from road_mqi_checker import privacy
from road_mqi_checker.errors import PrivacyViolation


@pytest.mark.parametrize(
    "kind,value",
    [
        ("route_id", "S99"),
        ("route_id", "X990"),
        ("route_id", "Y999"),
        ("route_id", "Z9901"),
        ("adcode", "990000"),
        ("adcode", "990101"),
        ("stake", "K0+000"),
        ("stake", "K99+999"),
        ("segment_name", "SYN-清河县东段"),
        ("org_name", "示例公路工程检测有限公司"),
        ("org_name", "某某养护中心第 3 分部"),
        ("phone", "19900000000"),
        ("phone", "19900009999"),
        ("report_no", "SYN-LG-2026-0001"),
        ("doi", "10.9999/SYN.0001"),
    ],
)
def test_whitelisted_forms_pass(kind, value):
    assert privacy.assert_synthetic(kind, value) == value


@pytest.mark.parametrize(
    "kind,value",
    [
        ("route_id", "G25"),
        ("route_id", "S304"),
        ("route_id", "G60"),
        ("route_id", "X123"),
        ("adcode", "110101"),
        ("adcode", "440300"),
        ("stake", "K120+500"),
        ("stake", "K999+000"),
        ("segment_name", "清河县东段"),
        ("org_name", "山东省公路研究院"),
        ("phone", "19912345678"),
        ("phone", "19900010000"),
        ("phone", "1990000000"),
        ("report_no", "LG-2026-0001"),
        ("doi", "10.1016/j.road.2020.01.002"),
    ],
)
def test_real_looking_forms_are_rejected(kind, value):
    with pytest.raises(PrivacyViolation):
        privacy.assert_synthetic(kind, value)


def test_unknown_kind_is_rejected():
    with pytest.raises(PrivacyViolation):
        privacy.assert_synthetic("plate_number", "京A12345")


def test_optional_kinds_allow_missing_but_not_bad_values():
    assert privacy.is_synthetic("phone", None) is True
    assert privacy.is_synthetic("route_id", None) is False


def test_check_row_validates_by_field_name():
    good = {
        "route_id": "S99",
        "segment_name": "SYN-东段",
        "start_stake": "K12+300",
        "end_stake": "K16+500",
        "detect_org": "示例公路工程检测有限公司",
        "surface_type": "asphalt",
        "pci_truth": 88.5,
    }
    privacy.check_row(good)
    bad = dict(good)
    bad["route_id"] = "G2"
    with pytest.raises(PrivacyViolation):
        privacy.check_row(bad)


def test_honest_wording_gate():
    privacy.assert_honest_wording("该系数待核对，应核实原文后再算")
    for banned in privacy.BANNED_ASSERTIONS:
        with pytest.raises(PrivacyViolation):
            privacy.assert_honest_wording("该系数%s，可直接采用" % banned)


def test_whitelist_and_ledger_agree(repo_root):
    """白名单形式必须在 data/README §三 登记过，未登记的新形式不许悄悄加进代码。"""
    import os

    with open(os.path.join(repo_root, "data", "README.md"), "r", encoding="utf-8") as handle:
        ledger = handle.read()
    for token in ("S99", "990000", "19900000000", "10.9999/", "SYN-", "K99+999"):
        assert token in ledger, "%s 未登记在 data/README 白名单" % token
