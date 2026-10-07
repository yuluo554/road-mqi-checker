"""M4 三级 MQI 汇总与分级判定：权重来源、部分口径、拒算不摊分、三级同分母。

双向门纪律（同 M2/M3）：内置包一律如实 blocked，数值通路用 `tests/fixtures/m4-fixture-asphalt.json`
自证；夹具值不是规范事实。
"""

import os

import pytest
import support_pci as sup

from road_mqi_checker import results as res
from road_mqi_checker.bench import generator
from road_mqi_checker.mqi import engine as mqi
from road_mqi_checker.pci import engine as pci
from road_mqi_checker.ruleset import loader

BUILTIN = None  # 延迟取，避免模块级读文件


def builtin_ruleset():
    return loader.load_file(
        os.path.join(loader._BUILTIN_DIR, "base-jtg5210-2018.json")
    )


def ledger_with(*objs):
    conn = sup.open_ledger()
    for obj in objs:
        sup.insert(conn, obj)
    return conn


def pci_of(obj, ruleset=None):
    return pci.compute_pci(sup.kernel_input(obj), ruleset or sup.m4_ruleset())


# ---- 判据对账 ----


def test_aggregation_required_keys_match_the_truth_column_gate():
    """汇总路径必需格 = 真值那一列的支配格（缺一格就是"真值有数、引擎拒算"的假账）。"""
    assert set(mqi.aggregation_required_keys()) == set(generator.TRUTH_GOVERNING_KEYS["mqi_partial_truth"])
    assert mqi.GRADE_THRESHOLD_KEY in mqi.aggregation_required_keys()
    assert mqi.COMPONENT_WEIGHT_KEY["pavement"] in mqi.aggregation_required_keys()


def test_action_required_keys_match_the_truth_column_gate():
    from road_mqi_checker.strategy import rules

    assert set(rules.action_required_keys()) == set(generator.TRUTH_GOVERNING_KEYS["recommended_action_truth"])


# ---- 内置包：三级都拒算 ----


@pytest.mark.parametrize("level", list(mqi.AGGREGATION_LEVELS))
def test_builtin_package_blocks_every_level(level):
    ruleset = builtin_ruleset()
    obj = sup.spec()
    conn = ledger_with(obj)
    pci_results = [pci_of(obj)]
    results = mqi.aggregate_year(conn, obj["year"], pci_results, ruleset, level=level)
    assert results, level
    for result in results:
        assert result.status == res.STATUS_BLOCKED, result.object_id
        assert result.mqi is None and result.grade is None
        assert result.weighted_length_m is None
        assert result.component_scores == {}
        reason = result.blocked_reason
        assert "mqi_weight.pavement" in reason and "grade_threshold.mqi" in reason, reason


def test_builtin_blocked_reason_names_every_missing_cell_at_once():
    """一次报全：只报第一格会让用户改一格跑一次，核对队列无法收敛。"""
    result = mqi.aggregate_segment_mqi(None, "SYN-G1", 2025, [pci_of(sup.spec())], builtin_ruleset())
    reason = result.blocked_reason
    assert reason.count("未进入评定路径") == 2, reason


def test_assign_grade_refuses_under_builtin_and_says_which_cell():
    grade, reason = mqi.assign_grade(80.0, mqi.GRADE_THRESHOLD_KEY, builtin_ruleset())
    assert grade is None
    assert mqi.GRADE_THRESHOLD_KEY in reason and "pending" in reason


# ---- 路段级：部分口径 ----


def test_segment_level_is_partial_and_names_every_unassessed_component():
    result = mqi.aggregate_segment_mqi(None, "SYN-G1", 2025, [pci_of(sup.spec())], sup.m4_ruleset())
    assert result.status == res.STATUS_PARTIAL, result.blocked_reason
    assert result.mqi == pytest.approx(87.7)
    assert result.included_components == ["pavement"]
    assert sorted(result.excluded_components) == ["appurtenances", "bridge_tunnel", "subgrade"]
    for name in mqi.UNASSESSED_COMPONENTS:
        assert name in result.scope_note, name
    assert result.scope_note.startswith(mqi.PARTIAL_SCOPE_PREFIX)
    assert "不是完整 MQI" in result.scope_note
    assert result.grade is None, "部分口径不得套用完整 MQI 的分级表述"
    assert result.component_scores == {"pavement": 87.7}


def test_partial_scope_note_survives_the_contract_gate():
    """partial 必须带口径声明，这条门在 results.py；缺声明直接构造失败。"""
    result = mqi.aggregate_segment_mqi(None, "SYN-G1", 2025, [pci_of(sup.spec())], sup.m4_ruleset())
    result.scope_note = ""
    with pytest.raises(Exception):
        result.check_contract()


def test_blocked_pci_input_is_not_treated_as_zero_score():
    blocked = pci.compute_pci(sup.kernel_input(sup.spec()), builtin_ruleset())
    result = mqi.aggregate_segment_mqi(None, "SYN-G1", 2025, [blocked], sup.m4_ruleset())
    assert result.status == res.STATUS_BLOCKED
    assert result.mqi is None
    assert "不当 0 分" in result.blocked_reason or "不把它当 0 分" in result.blocked_reason


def test_segment_without_pci_result_is_blocked():
    result = mqi.aggregate_segment_mqi(None, "SYN-GX", 2025, [], sup.m4_ruleset())
    assert result.status == res.STATUS_BLOCKED
    assert "没有 PCI 评定结果" in result.blocked_reason


# ---- 权重只从规则集来 ----


def complete_scores():
    return {"subgrade": 95.0, "bridge_tunnel": 93.0, "appurtenances": 94.0}


def test_complete_mqi_path_is_graded_from_the_ruleset_bands():
    result = mqi.aggregate_segment_mqi(
        None, "SYN-G1", 2025, [pci_of(sup.spec())], sup.m4_ruleset(), extra_component_scores=complete_scores()
    )
    assert result.status == res.STATUS_OK, result.scope_note
    assert result.mqi == pytest.approx(90.5), result.mqi
    assert result.grade == "良", (result.mqi, result.grade)
    assert result.excluded_components == []
    assert result.scope_note == ""
    assert sorted(result.component_scores) == ["appurtenances", "bridge_tunnel", "pavement", "subgrade"]


def test_changing_the_ruleset_weight_changes_the_aggregate():
    """代码里不出现规范数字的反证：换掉一格权重，汇总值与等级都要跟着变。"""
    before = mqi.aggregate_segment_mqi(
        None, "SYN-G1", 2025, [pci_of(sup.spec())], sup.m4_ruleset(), extra_component_scores=complete_scores()
    )
    heavy = sup.patched_ruleset(sup.M4_FIXTURE, sup.mutate_value("mqi_weight.subgrade", "weight", 60.0))
    after = mqi.aggregate_segment_mqi(
        None, "SYN-G1", 2025, [pci_of(sup.spec())], heavy, extra_component_scores=complete_scores()
    )
    assert before.mqi == pytest.approx(90.5)
    assert after.mqi == pytest.approx(91.9), after.mqi
    assert after.grade == "优", (after.mqi, after.grade)


def test_non_positive_weight_is_refused():
    broken = sup.patched_ruleset(sup.M4_FIXTURE, sup.mutate_value("mqi_weight.pavement", "weight", 0.0))
    result = mqi.aggregate_segment_mqi(None, "SYN-G1", 2025, [pci_of(sup.spec())], broken)
    assert result.status == res.STATUS_BLOCKED
    assert "正数值" in result.blocked_reason


# ---- 分级：含界与否由规则集说 ----


def test_grade_boundary_openness_comes_from_the_ruleset():
    inclusive = sup.m4_ruleset()
    exclusive = sup.patched_ruleset(sup.M4_FIXTURE, sup.mutate_value("grade_threshold.mqi", "boundary", "lower_exclusive"))
    for ruleset, expected in ((inclusive, "优"), (exclusive, "良")):
        grade, reason = mqi.assign_grade(91.5, mqi.GRADE_THRESHOLD_KEY, ruleset)
        assert grade == expected, (grade, reason)


def test_unregistered_band_grade_labels_are_kept_in_the_ruleset_only():
    """档位名与数量都由规则集登记；代码里的 GRADE_LABELS 只是词汇，不是判据。"""
    patched = sup.patched_ruleset(
        sup.M4_FIXTURE,
        sup.mutate_value(
            "grade_threshold.mqi",
            "bands",
            [{"grade": "甲", "min": 55.0}, {"grade": "乙", "min": 0.0}],
        ),
    )
    grade, reason = mqi.assign_grade(60.0, mqi.GRADE_THRESHOLD_KEY, patched)
    assert grade == "甲", reason
    assert grade not in mqi.GRADE_LABELS


# ---- 三级同分母 ----


def three_segment_ledger():
    objs = [
        sup.spec(segment_id="SYN-A1", start_m=0, end_m=1000, rqi=85.0),
        sup.spec(segment_id="SYN-A2", start_m=1000, end_m=3000, rqi=75.0),
        sup.spec(segment_id="SYN-A3", start_m=3000, end_m=3500, rqi=95.0),
    ]
    conn = ledger_with(*objs)
    return conn, objs


def test_route_level_is_length_weighted_over_its_segments():
    conn, objs = three_segment_ledger()
    pci_results = [pci_of(obj) for obj in objs]
    segments = [mqi.aggregate_segment_mqi(conn, obj["segment_id"], obj["year"], pci_results, sup.m4_ruleset()) for obj in objs]
    route = mqi.aggregate_route_mqi(conn, "S99", 2025, pci_results, sup.m4_ruleset())
    expected = sum(s.mqi * length for s, length in zip(segments, (1000, 2000, 500))) / 3500
    assert route.mqi == pytest.approx(round(expected, 1)), (route.mqi, expected)
    assert route.weighted_length_m == 3500.0
    assert route.level == "route" and route.object_id == "S99"


def test_network_level_equals_weighting_all_segments_directly():
    """三级口径一致：路网级"先按路线加权再按里程加权"必须等于"直接对全部路段加权"。"""
    conn, objs = three_segment_ledger()
    pci_results = [pci_of(obj) for obj in objs]
    network = mqi.aggregate_network_mqi(conn, 2025, pci_results, sup.m4_ruleset())
    segments = [mqi.aggregate_segment_mqi(conn, obj["segment_id"], obj["year"], pci_results, sup.m4_ruleset()) for obj in objs]
    direct = sum(s.mqi * length for s, length in zip(segments, (1000, 2000, 500))) / 3500
    assert network.mqi == pytest.approx(round(direct, 1))
    assert network.object_id == mqi.NETWORK_OBJECT_ID


def test_blocked_member_is_excluded_and_named_not_averaged():
    """含异常数据的对象不得被"平均"进上级：它连同它的里程一起退出分子与分母。"""
    conn, objs = three_segment_ledger()
    pci_results = [pci_of(objs[0])]  # A2 / A3 没有评定结果 → 路段级 blocked
    route = mqi.aggregate_route_mqi(conn, "S99", 2025, pci_results, sup.m4_ruleset())
    assert route.status == res.STATUS_PARTIAL
    assert route.mqi == pytest.approx(87.7)
    assert route.weighted_length_m == 1000.0
    for missing in ("SYN-A2", "SYN-A3"):
        assert missing in route.scope_note, missing
    assert "不按 0 计" in route.scope_note and "分母" in route.scope_note


def test_route_is_blocked_when_no_member_survives():
    conn, objs = three_segment_ledger()
    route = mqi.aggregate_route_mqi(conn, "S99", 2025, [], sup.m4_ruleset())
    assert route.status == res.STATUS_BLOCKED
    assert "全部成员都未出数" in route.blocked_reason


def test_route_without_ledger_rows_is_blocked():
    conn = sup.open_ledger()
    route = mqi.aggregate_route_mqi(conn, "S99", 2025, [], sup.m4_ruleset())
    assert route.status == res.STATUS_BLOCKED
    assert "没有路线 S99 在 2025 年度的路段行" in route.blocked_reason


def test_segment_level_needs_geometry_for_the_denominator():
    """路段级也要能从台账拿到长度：有 PCI 结果但台账没有该路段行时，分母不成立就拒算。"""
    conn = sup.open_ledger()
    sup.insert(conn, sup.spec())
    orphan = pci.compute_pci(sup.kernel_input(sup.spec(segment_id="SYN-NOGEOM")), sup.m4_ruleset())
    result = mqi.aggregate_segment_mqi(conn, "SYN-NOGEOM", 2025, [orphan], sup.m4_ruleset())
    assert result.status == res.STATUS_BLOCKED
    assert "路段行" in result.blocked_reason
    ok = mqi.aggregate_segment_mqi(conn, "SYN-G1", 2025, [pci_of(sup.spec())], sup.m4_ruleset())
    assert ok.weighted_length_m == 1000.0


def test_unknown_component_is_refused_rather_than_dropped():
    result = mqi.aggregate_segment_mqi(
        None, "SYN-G1", 2025, [pci_of(sup.spec())], sup.m4_ruleset(), extra_component_scores={"traffic_volume": 90.0}
    )
    assert result.status == res.STATUS_BLOCKED
    assert "未知分项" in result.blocked_reason


def test_payload_exposes_weights_clauses_and_denominator():
    conn, objs = three_segment_ledger()
    pci_results = [pci_of(obj) for obj in objs]
    route = mqi.aggregate_route_mqi(conn, "S99", 2025, pci_results, sup.m4_ruleset())
    payload = mqi.result_payload(route)
    assert payload["level"] == "route"
    assert payload["grade_threshold_key"] == "grade_threshold.mqi"
    assert payload["weight_keys"] == ["mqi_weight.pavement"]
    assert payload["weighted_length_m"] == 3500.0
    assert payload["status"] == route.status


def test_summarize_status_counts_every_state():
    conn, objs = three_segment_ledger()
    pci_results = [pci_of(obj) for obj in objs]
    results = mqi.aggregate_year(conn, 2025, pci_results, sup.m4_ruleset(), level="segment")
    counts = mqi.summarize_status(results)
    assert sum(counts.values()) == len(results) == 3
    assert counts[res.STATUS_PARTIAL] == 3
    with pytest.raises(ValueError):
        mqi.aggregate_year(conn, 2025, pci_results, sup.m4_ruleset(), level="province")


def test_aggregate_year_segment_level_follows_stake_order():
    conn, objs = three_segment_ledger()
    pci_results = [pci_of(obj) for obj in objs]
    results = mqi.aggregate_year(conn, 2025, pci_results, sup.m4_ruleset(), level="segment")
    assert [r.object_id for r in results] == ["SYN-A1", "SYN-A2", "SYN-A3"]
