"""拒算契约：blocked 的结果对象数值字段必须全空。

这是"未核对系数不生效"的第二道门 —— 第一道在规则集加载，
这一道在结果出口，防止有人绕过加载层直接构造结果。
"""

import pytest

from road_mqi_checker import results as R
from road_mqi_checker.errors import ContractViolation


def _pci(**overrides):
    kwargs = dict(
        segment_id="SYN-01",
        route_id="S99",
        year=2025,
        surface_type="asphalt",
        status=R.STATUS_BLOCKED,
        blocked_reason="扣分比率未核对，应核实",
    )
    kwargs.update(overrides)
    return R.PciResult(**kwargs)


def _mqi(**overrides):
    kwargs = dict(
        level="route",
        object_id="S99",
        year=2025,
        status=R.STATUS_BLOCKED,
        blocked_reason="MQI 分项权重未核对，应核实",
    )
    kwargs.update(overrides)
    return R.MqiResult(**kwargs)


def test_blocked_result_passes():
    _pci().check_contract()
    _mqi().check_contract()


def test_blocked_with_number_is_rejected():
    with pytest.raises(ContractViolation) as info:
        _pci(pci=88.5).check_contract()
    assert "不出数" in str(info.value)


def test_blocked_with_component_scores_is_rejected():
    with pytest.raises(ContractViolation):
        _pci(component_scores={"rqi": 80.0}).check_contract()


def test_blocked_with_grade_is_rejected():
    """等级也是结论：未核对时不能给"良"。"""
    with pytest.raises(ContractViolation):
        _pci(grade="良").check_contract()


def test_blocked_without_reason_is_rejected():
    with pytest.raises(ContractViolation):
        _pci(blocked_reason="").check_contract()


def test_nan_is_rejected_everywhere():
    with pytest.raises(ContractViolation):
        _pci(status=R.STATUS_OK, pci=float("nan"), blocked_reason="").check_contract()


def test_partial_scope_must_be_declared():
    from road_mqi_checker.mqi import engine as mqi_engine

    with pytest.raises(ContractViolation):
        _mqi(status=R.STATUS_PARTIAL, mqi=86.0, scope_note="").check_contract()
    ok = _mqi(
        status=R.STATUS_PARTIAL,
        mqi=86.0,
        scope_note=mqi_engine.PARTIAL_SCOPE_PREFIX + "路面",
        excluded_components=list(mqi_engine.UNASSESSED_COMPONENTS),
    )
    ok.check_contract()


def test_unknown_status_is_rejected():
    with pytest.raises(ContractViolation):
        _pci(status="pretty_good").check_contract()


def test_uncomparable_compare_must_explain():
    from road_mqi_checker.strategy import compare

    bad = R.CompareResult(
        segment_id="SYN-01",
        route_id="S99",
        year_from=2024,
        year_to=2025,
        status=R.STATUS_UNCOMPARABLE,
        blocked_reason="",
    )
    with pytest.raises(ContractViolation):
        bad.check_contract()
    good = R.CompareResult(
        segment_id="SYN-01",
        route_id="S99",
        year_from=2024,
        year_to=2025,
        status=R.STATUS_UNCOMPARABLE,
        blocked_reason="路段划分变更（merged），不可比：" + compare.UNCOMPARABLE_REASONS[2],
        comparability_reason=compare.UNCOMPARABLE_REASONS[2],
    )
    good.check_contract()


def test_uncomparable_compare_must_carry_a_reason_code():
    """M4 接线后：光有说明文字不够，必须给可归类的不可比因素代码（清单要能分档统计）。"""
    with pytest.raises(ContractViolation):
        R.CompareResult(
            segment_id="SYN-01",
            route_id="S99",
            year_from=2024,
            year_to=2025,
            status=R.STATUS_UNCOMPARABLE,
            blocked_reason="不可比",
            comparability_reason="",
        ).check_contract()


def test_compare_reason_codes_are_declared_vocabulary():
    """不可比原因代码是单点词汇：划分变更类别要能逐个映射，列名与结果对象同构。"""
    from road_mqi_checker.ledger import db as ledger_db
    from road_mqi_checker.strategy import compare

    mapped = set(compare.CHANGE_KIND_TO_REASON)
    assert mapped == set(ledger_db.CHANGE_KINDS) - {"unchanged"}, (
        "划分变更类别与不可比原因代码脱节：%s" % sorted(mapped ^ (set(ledger_db.CHANGE_KINDS) - {"unchanged"}))
    )
    for reason in compare.CHANGE_KIND_TO_REASON.values():
        assert reason in compare.UNCOMPARABLE_REASONS, reason
    assert "comparability_reason" in compare.COMPARE_COLUMNS, "对比列名里必须有不可比原因列（与结果对象同构）"


def test_action_suggestion_context_fields_are_not_conclusions():
    """对策 blocked 时，PCI 仍是已核对口径下的事实数字：上下文字段不进 NUMERIC_FIELDS。"""
    suggestion = R.ActionSuggestion(
        segment_id="SYN-01",
        route_id="S99",
        year=2025,
        status=R.STATUS_BLOCKED,
        blocked_reason="对策系数未核对",
        pci=87.7,
        mqi_partial=87.7,
        start_stake_m=12300,
    )
    suggestion.check_contract()
    assert "pci" not in R.ActionSuggestion.NUMERIC_FIELDS
    assert R.ActionSuggestion.CONTEXT_FIELDS == ("pci", "mqi_partial", "start_stake_m")


def test_uncomparable_compare_cannot_publish_delta():
    from road_mqi_checker.strategy import compare

    with pytest.raises(ContractViolation):
        R.CompareResult(
            segment_id="SYN-01",
            route_id="S99",
            year_from=2024,
            year_to=2025,
            status=R.STATUS_UNCOMPARABLE,
            blocked_reason=compare.UNCOMPARABLE_REASONS[0],
            comparability_reason=compare.UNCOMPARABLE_REASONS[0],
            delta=-6.0,
        ).check_contract()


def test_ok_compare_must_name_the_trigger():
    contribution = R.DeductContribution(
        source_kind="distress",
        distress_type="坑槽",
        severity="重",
        quantity=3.5,
        quantity_unit="m2",
        coefficient_key="deduct_ratio.asphalt_distress",
        clause="夹具表 A-1",
        deducted_points=6.0,
        source_row_no=7,
    )
    result = R.CompareResult(
        segment_id="SYN-01",
        route_id="S99",
        year_from=2024,
        year_to=2025,
        status=R.STATUS_OK,
        delta=-6.0,
        deterioration_rate_per_year=-6.0,
        top_contributors=[contribution],
    )
    result.check_contract()
    with pytest.raises(ContractViolation):
        R.CompareResult(
            segment_id="SYN-01",
            route_id="S99",
            year_from=2024,
            year_to=2025,
            status=R.STATUS_OK,
            delta=-6.0,
        ).check_contract()


def test_contribution_requires_clause_and_key():
    with pytest.raises(ContractViolation):
        R.DeductContribution(source_kind="distress", deducted_points=1.0).check_contract()
    with pytest.raises(ContractViolation):
        R.DeductContribution(
            source_kind="distress", coefficient_key="k", deducted_points=1.0
        ).check_contract()


def test_action_suggestion_needs_rule_and_trigger():
    with pytest.raises(ContractViolation):
        R.ActionSuggestion(
            segment_id="SYN-01", route_id="S99", year=2025, status=R.STATUS_OK, action_class="小修"
        ).check_contract()
    R.ActionSuggestion(
        segment_id="SYN-01",
        route_id="S99",
        year=2025,
        status=R.STATUS_OK,
        rule_id="AR-1",
        clause="夹具表 B-2",
        action_class="中修",
        scale_band="档 2",
        triggered_by={"indicator": "pci", "change": -6.0},
        blocked_reason="",
    ).check_contract()
