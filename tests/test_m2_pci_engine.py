"""M2 PCI 评定内核：换算黄金用例、系数门、含异常数据拒算、零漂移。

数值断言全部可手算复核（`plan/05-评定与汇总算法说明.md` §二 写了推导式），
夹具数值刻意避开任何真实规范数字 —— 这里验证的是"换算式本身算得对"，
不是"符合某本规范"。
"""

import pytest

import support_pci as sup
from road_mqi_checker import results as res
from road_mqi_checker.bench import generator
from road_mqi_checker.ledger import checks as ledger_checks
from road_mqi_checker.ledger import db as ledger_db
from road_mqi_checker.pci import engine
from road_mqi_checker.ruleset import loader as ruleset_loader

BUILTIN = ruleset_loader.select_ruleset()


def compute(obj, ruleset=None, blockers=()):
    return engine.compute_pci(sup.kernel_input(obj), ruleset or sup.asphalt_ruleset(), blockers)


# ---- 评定路径必需系数集合 ----


def test_surface_table_keys_cover_both_surfaces():
    for surface in ("asphalt", "cement"):
        keys = engine.surface_table_keys(surface)
        assert keys, surface
        assert len(set(keys)) == len(keys), "同一集合里不许出现重复 key"
        for key in keys:
            assert BUILTIN.find(key) is not None, "%s 是评定路径必需格，内置包却没登记 %s" % (surface, key)
    assert engine.surface_table_keys("gravel") == ()


def test_required_keys_match_the_truth_governing_keys():
    """引擎要用的格与真值敢出数的格必须同一批，否则会出现"真值有数、引擎拒算"的假账。"""
    for surface in ("asphalt", "cement"):
        required = set(engine.surface_table_keys(surface))
        governed = {key.format(surface=surface) for key in generator.TRUTH_GOVERNING_KEYS["pci_truth"]}
        graded = {key.format(surface=surface) for key in generator.TRUTH_GOVERNING_KEYS["grade_truth"]}
        assert governed <= required, sorted(governed - required)
        assert required == governed | graded, (sorted(required), sorted(governed | graded))


# ---- 黄金用例：沥青 ----


def test_asphalt_golden_case_matches_hand_arithmetic():
    result = compute(sup.spec())
    assert result.status == res.STATUS_OK
    # 破损扣分：0.2×150/7500×100 + 0.04×100/2000×100 + 0.05×75/7500×100 = 0.4+0.2+0.05
    assert result.component_scores["distress"] == pytest.approx(99.4)
    assert result.component_scores["ride_quality"] == pytest.approx(85.0)
    assert result.component_scores["rutting"] == pytest.approx(75.0)
    assert result.component_scores["skid_resistance"] == pytest.approx(75.0)
    # (40×99.35 + 30×85 + 15×75 + 15×75) / 100 = 87.74 → 半值向上舍入到 87.7
    assert result.pci == pytest.approx(87.7)
    assert result.deducted_total == pytest.approx(12.3)
    assert result.grade == "良"
    assert result.blocked_reason == ""
    result.check_contract()


def test_cement_golden_case_matches_hand_arithmetic_and_declares_partial_scope():
    result = compute(sup.spec(**{"surface_type": "cement", "rows": sup.GOLDEN_CEMENT_ROWS,
                                 "width_m": 9.0, "panel_count": 100, "rqi": 90.0,
                                 "rut_depth_mm": None, "skid_indicator": 30.0,
                                 "skid_indicator_kind": "BPN"}), sup.cement_ruleset())
    # 板数分母：0.35×5/100×100 = 1.75；长度分母：0.02×200/2000×100 = 0.2 → 得分 98.05
    assert result.component_scores["distress"] == pytest.approx(98.1)
    assert result.component_scores["skid_resistance"] == pytest.approx(25.0)
    # 缺测车辙不参与加权：(45×98.05 + 25×90 + 15×25) / 85 = 82.79117…
    assert result.pci == pytest.approx(82.8)
    assert result.status == res.STATUS_PARTIAL
    assert "rutting" in result.scope_note and "rut_depth_mm" in result.scope_note
    assert result.grade == "良"
    result.check_contract()


def test_ledger_path_and_kernel_path_agree():
    """同一份输入走台账（CLI 通路）与走评定核（真值通路）必须逐字段相同 —— 只有一套行为。"""
    obj = sup.spec()
    conn = sup.open_ledger()
    sup.insert(conn, obj)
    from_ledger = engine.compute_segment_pci(conn, obj["segment_id"], obj["year"], sup.asphalt_ruleset())
    from_kernel = compute(obj)
    assert engine.result_payload(from_ledger) == engine.result_payload(from_kernel)


# ---- 系数门：未核对不出数 ----


def test_builtin_ruleset_blocks_every_object_with_numbers_all_empty():
    """内置包 15 格全 pending：所有路段必须 blocked，且数值字段全空、等级也不给。"""
    obj = sup.spec()
    result = compute(obj, BUILTIN)
    assert result.status == res.STATUS_BLOCKED
    assert result.pci is None
    assert result.deducted_total is None
    assert result.component_scores == {}
    assert result.grade is None
    assert result.contributions == []
    for key in engine.surface_table_keys("asphalt"):
        assert key in result.blocked_reason, key
    result.check_contract()


@pytest.mark.parametrize(
    "key",
    [
        "deduct_ratio.asphalt_distress",
        "pci_component.ride_quality",
        "pci_component.rutting",
        "pci_component.skid_resistance",
        "pci_weight.asphalt",
        "grade_threshold.pci",
    ],
)
def test_each_required_cell_alone_can_hold_the_whole_segment_back(key):
    """必需格里缺任一格（或那一格退回 located）都只能 blocked —— 不"用剩下的格子凑一个数"。"""
    ruleset = sup.patched_ruleset(sup.ASPHALT_FIXTURE, sup.drop_coefficient(key))
    blocked = compute(sup.spec(), ruleset)
    assert blocked.status == res.STATUS_BLOCKED and key in blocked.blocked_reason
    located = compute(sup.spec(), sup.patched_ruleset(sup.ASPHALT_FIXTURE, sup.set_status(key, "located")))
    assert located.status == res.STATUS_BLOCKED
    assert located.pci is None and located.grade is None


def test_computable_cell_without_clause_is_refused():
    """系数可算但没登记条款号 → 扣分不可追溯，一律不出数（结论纪律，不是文档承诺）。"""
    result = compute(sup.spec(), sup.patched_ruleset(sup.ASPHALT_FIXTURE, sup.clear_clause("pci_weight.asphalt")))
    assert result.status == res.STATUS_BLOCKED
    assert "条款" in result.blocked_reason


def test_conversion_parameters_must_be_consistent():
    """换算端点自相矛盾（zero ≤ ideal）时拒算，而不是算出一个方向反了的分。"""
    ruleset = sup.patched_ruleset(sup.ASPHALT_FIXTURE, sup.mutate_value("pci_component.rutting", "zero_mm", 1.0))
    result = compute(sup.spec(), ruleset)
    assert result.status == res.STATUS_BLOCKED and "方向" in result.blocked_reason


def test_ratio_outside_unit_interval_is_refused():
    ruleset = sup.patched_ruleset(
        sup.ASPHALT_FIXTURE, sup.mutate_value("deduct_ratio.asphalt_distress", "ratios", {"坑槽": {"重": 1.5}})
    )
    result = compute(sup.spec(), ruleset)
    assert result.status == res.STATUS_BLOCKED and "不在 0～1 之间" in result.blocked_reason


def test_weight_table_rejects_unknown_component():
    ruleset = sup.patched_ruleset(
        sup.ASPHALT_FIXTURE,
        sup.mutate_value("pci_weight.asphalt", "weights", {"distress": 40.0, "ride_quality": 30.0, "rutting": 15.0, "skid_resistance": 15.0, "shoulder": 5.0}),
    )
    result = compute(sup.spec(), ruleset)
    assert result.status == res.STATUS_BLOCKED and "shoulder" in result.blocked_reason


# ---- 数据门：含异常行即拒算 ----


def test_negative_quantity_is_refused_not_skipped():
    result = compute(sup.spec(rows=(("坑槽", "重", -150.0, "m2", 1),)))
    assert result.status == res.STATUS_BLOCKED
    assert result.pci is None
    assert "为负" in result.blocked_reason


def test_unit_mismatch_is_refused_not_silently_converted():
    result = compute(sup.spec(rows=(("坑槽", "重", 150.0, "m", 1),)))
    assert result.status == res.STATUS_BLOCKED and "换算分母对不上" in result.blocked_reason


def test_distress_beyond_geometric_bound_is_refused():
    """数量超过该路段几何上界（占比 > 1）时，"扣多少分"失去意义，只能拒算。"""
    result = compute(sup.spec(rows=(("坑槽", "重", 7501.0, "m2", 1),)))
    assert result.status == res.STATUS_BLOCKED and "几何上界" in result.blocked_reason


def test_missing_geometry_denominator_is_refused():
    """缺宽度就算不出面积分母：只能 blocked 并说明缺哪个属性，不能"当作 0 面积以外的什么"。"""
    result = compute(sup.spec(width_m=None))
    assert result.status == res.STATUS_BLOCKED
    assert "segment_width_m" in result.blocked_reason


def test_indicator_outside_its_domain_is_refused():
    result = compute(sup.spec(rqi=101.0))
    assert result.status == res.STATUS_BLOCKED and "定义域" in result.blocked_reason


def test_type_or_severity_outside_dictionary_is_refused():
    assert "字典" in compute(sup.spec(rows=(("翻浆", "重", 5.0, "m2", 1),))).blocked_reason
    assert "档位" in compute(sup.spec(rows=(("坑槽", "极重", 5.0, "m2", 1),))).blocked_reason


def test_missing_survey_row_is_refused():
    result = compute(sup.spec(has_survey=False))
    assert result.status == res.STATUS_BLOCKED and "检测记录" in result.blocked_reason


def test_ledger_check_findings_block_the_assessment_path():
    """M1 校验层的检出项就是 M2 的拒算依据：同一套判据，评定层不另起第二套。"""
    obj = sup.spec()
    conn = sup.insert(sup.open_ledger(), sup.spec(rows=(("坑槽", "重", -150.0, "m2", 1),)))
    blockers = engine.blocking_findings(conn, obj["year"])
    assert obj["segment_id"] in blockers
    kinds = sorted(kind for kind, _detail in blockers[obj["segment_id"]])
    assert "value_range" in kinds
    result = engine.compute_segment_pci(conn, obj["segment_id"], obj["year"], sup.asphalt_ruleset())
    assert result.status == res.STATUS_BLOCKED
    assert "M1 检出项" in result.blocked_reason and "value_range" in result.blocked_reason


def test_non_blocking_findings_do_not_stop_the_assessment():
    """悬空段影响里程账与跨年可比性，不影响本段扣分是否可解释：照常出数（由 M4 处理不可比）。"""
    conn = sup.open_ledger()
    sup.insert(conn, sup.spec(segment_id="SYN-G1", start_m=0, end_m=1000))
    sup.insert(conn, sup.spec(segment_id="SYN-G9", start_m=1200, end_m=2000))
    findings = ledger_checks.check_stake_continuity(conn, "S99", 2025)
    assert [f.kind for f in findings] == ["stake_gap"]
    assert engine.blocking_findings(conn, 2025) == {}
    assert engine.compute_segment_pci(conn, "SYN-G9", 2025, sup.asphalt_ruleset()).status == res.STATUS_OK


# ---- 分级边界：含界与否由规则集说 ----


def test_grade_boundary_openness_comes_from_the_ruleset():
    """同一个分值在"含下界"与"不含下界"两种登记下必须给出不同等级 —— 证明引擎没有自己猜。"""
    pci = compute(sup.spec()).pci
    bands = [{"grade": "优", "min": pci + 5.0}, {"grade": "良", "min": pci}, {"grade": "差", "min": 0.0}]
    inclusive = compute(sup.spec(), sup.patched_ruleset(sup.ASPHALT_FIXTURE, _both(bands, "lower_inclusive")))
    assert inclusive.grade == "良"
    exclusive = compute(sup.spec(), sup.patched_ruleset(sup.ASPHALT_FIXTURE, _both(bands, "lower_exclusive")))
    assert exclusive.grade == "差"


def _both(bands, boundary):
    def _mutate(payload):
        for coef in payload["coefficients"]:
            if coef["key"] == "grade_threshold.pci":
                coef["values"]["bands"] = bands
                coef["values"]["boundary"] = boundary

    return _mutate


def test_grade_without_declared_boundary_is_refused():
    result = compute(
        sup.spec(),
        sup.patched_ruleset(sup.ASPHALT_FIXTURE, sup.mutate_value("grade_threshold.pci", "boundary", "")),
    )
    assert result.status == res.STATUS_BLOCKED and "含界与否" in result.blocked_reason


def test_duplicate_grade_bounds_are_refused():
    bands = [{"grade": "甲", "min": 90.0}, {"grade": "乙", "min": 90.0}, {"grade": "丙", "min": 0.0}]
    result = compute(sup.spec(), sup.patched_ruleset(sup.ASPHALT_FIXTURE, sup.mutate_value("grade_threshold.pci", "bands", bands)))
    assert result.status == res.STATUS_BLOCKED and "重复" in result.blocked_reason


# ---- 零漂移 ----


def test_same_ledger_same_ruleset_recomputes_identically():
    conn = sup.insert(sup.open_ledger(), sup.spec())
    first = [engine.result_payload(r) for r in engine.assess_year(conn, 2025, sup.asphalt_ruleset())]
    second = [
        engine.result_payload(r)
        for r in engine.assess_year(sup.insert(sup.open_ledger(), sup.spec()), 2025, sup.asphalt_ruleset())
    ]
    assert first == second
    assert first and first[0]["pci"] is not None


def test_quantize_is_half_up_not_bankers():
    assert engine.quantize(87.75, 1) == pytest.approx(87.8)
    assert engine.quantize(0.05, 1) == pytest.approx(0.1)
    assert engine.quantize(-0.05, 1) == pytest.approx(-0.1)
