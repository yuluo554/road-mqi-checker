"""M2 扣分贡献展开：可追溯到"哪条破损哪个程度扣了多少"，并回指原始检测表的行号。

排序一致性是 README 评测表里的一行，这里用**确定性重排**（反序 + 逐位旋转）实测，
不用随机数（本仓库的随机源只有 splitmix64，且测试要能复现失败）。
"""

import pytest

import support_pci as sup
from road_mqi_checker import results as res
from road_mqi_checker.pci import engine, trace


def ok_result(spec=None):
    obj = spec or sup.spec()
    return engine.compute_pci(sup.kernel_input(obj), sup.asphalt_ruleset())


def test_every_distress_contribution_names_key_clause_and_row():
    result = ok_result()
    rows = trace.expand_contributions(result)
    distress_rows = [row for row in rows if row["source_kind"] == "distress"]
    assert len(distress_rows) == len(sup.GOLDEN_ASPHALT_ROWS)
    for row in distress_rows:
        assert row["coefficient_key"] == "deduct_ratio.asphalt_distress"
        assert row["clause"] == "夹具表 A-1"
        assert row["source_row_no"] in (1, 2, 3), row
    assert {row["source_row_no"] for row in distress_rows} == {1, 2, 3}


def test_expanded_columns_follow_trace_columns_exactly():
    for row in trace.expand_contributions(ok_result()):
        assert tuple(row.keys()) == trace.TRACE_COLUMNS


def test_contribution_points_add_up_to_the_score_shortfall():
    """贡献合计 = 满分 − PCI（舍入误差只允许出现在最后一位，逐项 0.05 上界）。"""
    result = ok_result()
    rows = trace.expand_contributions(result)
    total = sum(row["deducted_points"] for row in rows)
    assert result.pci == pytest.approx(87.7)
    assert abs(total - (100.0 - result.pci)) <= 0.05 * (len(rows) + 1)
    unrounded = 0.16 + 0.08 + 0.02 + 4.5 + 3.75 + 3.75
    assert unrounded == pytest.approx(100.0 - 87.74, abs=1e-9)
    assert abs(total - unrounded) <= 0.05 * len(rows)


def test_shares_are_relative_to_the_total_deduction():
    rows = trace.expand_contributions(ok_result())
    assert sum(row["share"] for row in rows) == pytest.approx(1.0, abs=0.01)
    assert rows[0]["source_kind"] == "measured_indicator"
    assert rows[0]["distress_type"] == "ride_quality"
    assert [row["distress_type"] for row in rows[1:3]] == ["rutting", "skid_resistance"]


def test_order_is_deterministic_under_reordering():
    """反序与逐位旋转输入，展开视图必须逐行一致（README 的"排序一致性"实测口径）。"""
    result = ok_result()
    reference = trace.expand_contributions(result)
    original = list(result.contributions)
    assert len(original) == len(reference)
    for step in range(len(original)):
        result.contributions = original[step:] + original[:step]
        assert trace.expand_contributions(result) == reference, "旋转 %d 位后顺序变了" % step
    result.contributions = list(reversed(original))
    assert trace.expand_contributions(result) == reference


def test_ties_are_broken_by_fixed_secondary_keys():
    """两条扣分完全相同的破损：顺序由 类型→程度→数量→行号→系数 key 的固定序列决定。"""
    spec = sup.spec(
        rows=(
            ("坑槽", "重", 150.0, "m2", 1),
            ("松散", "重", 150.0, "m2", 2),
            ("网状裂缝", "轻", 75.0, "m2", 3),
            ("泛油", "轻", 75.0, "m2", 4),
        )
    )
    result = ok_result(spec)
    rows = trace.expand_contributions(result)
    distress = [row for row in rows if row["source_kind"] == "distress"]
    assert len(distress) == 4
    assert distress[0]["deducted_points"] == distress[1]["deducted_points"]
    assert distress[2]["deducted_points"] == distress[3]["deducted_points"]
    assert [row["distress_type"] for row in distress] == sorted(row["distress_type"] for row in distress)
    # 再打乱一次，顺序仍不变
    result.contributions = list(reversed(result.contributions))
    assert trace.expand_contributions(result) == rows


def test_contributions_for_cell_locates_the_cell_only():
    result = ok_result()
    hits = trace.contributions_for_cell(result, "坑槽", "重")
    assert len(hits) == 1 and hits[0]["source_row_no"] == 1
    assert len(trace.contributions_for_cell(result, "坑槽", "")) == 1
    assert trace.contributions_for_cell(result, "纵向裂缝", "轻") == []
    assert trace.contributions_for_cell(result, "skid_resistance", "") == [], "实测指标分项不属于破损格子"


def test_blocked_result_expands_to_nothing_and_reports_the_reason():
    result = engine.compute_pci(sup.kernel_input(sup.spec()), sup.patched_ruleset(sup.ASPHALT_FIXTURE, sup.drop_coefficient("pci_weight.asphalt")))
    assert result.status == res.STATUS_BLOCKED
    assert trace.expand_contributions(result) == []
    lines = trace.report_lines(result)
    assert len(lines) == 1 and "blocked" in lines[0] and "pci_weight.asphalt" in lines[0]


def test_partial_result_reports_scope_note_with_the_excluded_component():
    result = engine.compute_pci(
        sup.kernel_input(
            sup.spec(
                surface_type="cement",
                rows=sup.GOLDEN_CEMENT_ROWS,
                width_m=9.0,
                panel_count=100,
                rqi=90.0,
                rut_depth_mm=None,
                skid_indicator=30.0,
                skid_indicator_kind="BPN",
            )
        ),
        sup.cement_ruleset(),
    )
    rows = trace.expand_contributions(result)
    assert all(row["source_kind"] != "measured_indicator" or row["distress_type"] != "rutting" for row in rows)
    assert "rutting" in result.scope_note
    lines = trace.report_lines(result, limit=2)
    assert len(lines) == 2


def test_top_contributors_is_what_m4_compare_will_cite():
    result = ok_result()
    top = trace.top_contributors(result, limit=2)
    assert len(top) == 2
    assert top[0].deducted_points >= top[1].deducted_points
    for item in top:
        item.check_contract()


def test_report_lines_cite_clause_and_ledger_row_for_a_distress():
    lines = trace.report_lines(ok_result())
    text = "\n".join(lines)
    assert "夹具表 A-1" in text
    assert "台账行" in text
