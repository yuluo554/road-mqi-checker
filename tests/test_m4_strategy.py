"""M4 对策规则链、优先序与年对比：IF/THEN 出处、不可比拒变化率、变化拆到贡献项。

同样是双向门：内置包下对策与对比一律拒算；数值通路只在 `tests/fixtures/` 的夹具包里跑。
"""

import os

import pytest
import support_pci as sup

from road_mqi_checker import privacy
from road_mqi_checker import results as res
from road_mqi_checker.errors import InputUnavailable
from road_mqi_checker.mqi import engine as mqi
from road_mqi_checker.pci import engine as pci
from road_mqi_checker.ruleset import loader
from road_mqi_checker.strategy import compare, rules


def builtin_ruleset():
    return loader.load_file(os.path.join(loader._BUILTIN_DIR, "base-jtg5210-2018.json"))


def assess(objs, ruleset=None):
    return [pci.compute_pci(sup.kernel_input(obj), ruleset or sup.m4_ruleset()) for obj in objs]


def actions(conn, year, pci_results, ruleset=None, mqi_results=None):
    ruleset = ruleset or sup.m4_ruleset()
    if mqi_results is None:
        mqi_results = mqi.aggregate_year(conn, year, pci_results, ruleset, level="segment")
    return rules.suggest_actions(conn, year, pci_results, mqi_results, ruleset)


# ---- 对策规则链：内置包 blocked ----


def test_actions_are_blocked_under_the_builtin_package_but_still_listed():
    obj = sup.spec()
    conn = sup.open_ledger()
    sup.insert(conn, obj)
    pci_results = assess([obj], builtin_ruleset())
    suggestions = actions(conn, 2025, pci_results, builtin_ruleset(), mqi_results=[])
    assert len(suggestions) == 1
    item = suggestions[0]
    assert item.status == res.STATUS_BLOCKED
    assert item.action_class is None and item.rule_id == "" and item.clause == ""
    assert "action_rule.maintenance_trigger" in item.blocked_reason
    assert "pending" in item.blocked_reason


def test_builtin_package_does_not_cite_the_unverified_upstream_standard():
    """上位养护规范的编号-名称对应关系查证失败（台账第 4 行）⇒ 该格未核对时不得引用那个规范号。

    门是两层：内置包的对策格登记文本里不能有那个编号；对策模块的**代码字符串常量**里也不能有
    （文档段落里作为"查证失败记录"提到它是允许的，那正是留痕；拼进结论出处就不行）。
    """
    import ast

    ruleset = builtin_ruleset()
    coef = ruleset.find(rules.ACTION_RULE_KEY)
    text = " ".join(
        [coef.key, coef.note, coef.register_ref] + [basis.standard_id + basis.clause + basis.note for basis in coef.basis]
    )
    assert coef.register_ref == "data/README.md#1"
    assert "5142" not in text, "未查证的规范编号进了系数登记"

    path = os.path.join(os.path.dirname(__file__), os.pardir, "src", "road_mqi_checker", "strategy", "rules.py")
    with open(path, encoding="utf-8") as handle:
        source = handle.read()
    tree = ast.parse(source)
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                docstrings.add(id(first.value))
    constants = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings
    ]
    assert not [text for text in constants if "5142" in text], "对策模块把未查证规范号写进了字符串常量"


def test_suggestions_carry_rule_id_clause_and_trigger_source():
    obj = sup.spec()
    conn = sup.open_ledger()
    sup.insert(conn, obj)
    item = actions(conn, 2025, assess([obj]))[0]
    assert item.status == res.STATUS_OK, item.blocked_reason
    assert item.rule_id == "FX-3"
    assert item.clause == "夹具式 F-1"
    assert item.condition_text == "pci ≥ 70"
    assert item.action_class == "夹具工程类别丙"
    assert item.scale_band == "夹具规模档三"
    assert item.scale_band_value == 1.0
    assert item.triggered_by == "pci=87.7 命中规则 FX-3 的条件「pci ≥ 70」"
    assert item.pci == pytest.approx(87.7)
    assert item.mqi_partial == pytest.approx(87.7)
    assert item.start_stake_m == 0
    for field in rules.ACTION_FIELDS:
        assert field in rules.result_payload(item), field


def test_first_match_wins_in_the_order_the_ruleset_declares():
    """命中顺序由规则集声明，不由数据决定：同一对象换顺序就换结论，证明没另排一套优先级。"""
    obj = sup.spec()
    conn = sup.open_ledger()
    sup.insert(conn, obj)
    broad_first = sup.patched_ruleset(
        sup.M4_FIXTURE,
        sup.mutate_value(
            "action_rule.maintenance_trigger",
            "rules",
            [
                {"rule_id": "FX-A", "metric": "pci", "op": "ge", "threshold": 0.0, "action_class": "先登记的类别", "scale_band": "档甲"},
                {"rule_id": "FX-B", "metric": "pci", "op": "lt", "threshold": 90.0, "action_class": "后登记的类别", "scale_band": "档乙"},
            ],
        ),
    )
    narrow_first = sup.patched_ruleset(
        sup.M4_FIXTURE,
        sup.mutate_value(
            "action_rule.maintenance_trigger",
            "rules",
            [
                {"rule_id": "FX-B", "metric": "pci", "op": "lt", "threshold": 90.0, "action_class": "后登记的类别", "scale_band": "档乙"},
                {"rule_id": "FX-A", "metric": "pci", "op": "ge", "threshold": 0.0, "action_class": "先登记的类别", "scale_band": "档甲"},
            ],
        ),
    )
    assert actions(conn, 2025, assess([obj]), broad_first)[0].action_class == "先登记的类别"
    assert actions(conn, 2025, assess([obj]), narrow_first)[0].action_class == "后登记的类别"


@pytest.mark.parametrize(
    "op,threshold,expected",
    [("lt", 87.7, False), ("le", 87.7, True), ("gt", 87.7, False), ("ge", 87.7, True), ("between", {"lo": 80.0, "hi": 87.7}, True)],
)
def test_condition_operators_are_applied_as_declared(op, threshold, expected):
    obj = sup.spec()
    conn = sup.open_ledger()
    sup.insert(conn, obj)
    package = sup.patched_ruleset(
        sup.M4_FIXTURE,
        sup.mutate_value(
            "action_rule.maintenance_trigger",
            "rules",
            [{"rule_id": "FX-1", "metric": "pci", "op": op, "threshold": threshold, "action_class": "类别甲", "scale_band": "档一"}],
        ),
    )
    item = actions(conn, 2025, assess([obj]), package)[0]
    if expected:
        assert item.action_class == "类别甲", item.blocked_reason
    else:
        assert item.status == res.STATUS_BLOCKED and "均未触发" in item.blocked_reason


def test_no_trigger_says_so_rather_than_inventing_a_category():
    obj = sup.spec()
    conn = sup.open_ledger()
    sup.insert(conn, obj)
    package = sup.patched_ruleset(
        sup.M4_FIXTURE,
        sup.mutate_value(
            "action_rule.maintenance_trigger",
            "rules",
            [{"rule_id": "FX-1", "metric": "pci", "op": "lt", "threshold": 10.0, "action_class": "类别甲", "scale_band": "档一"}],
        ),
    )
    item = actions(conn, 2025, assess([obj]), package)[0]
    assert item.status == res.STATUS_BLOCKED
    assert "均未触发" in item.blocked_reason and "pci=87.7" in item.blocked_reason
    assert item.action_class is None


def test_rule_needing_an_unavailable_metric_is_refused():
    """规则要读 mqi_partial 而汇总未出数时：整段拒算，不能因为"这条判不了"就用后面的结论顶上。"""
    obj = sup.spec()
    conn = sup.open_ledger()
    sup.insert(conn, obj)
    package = sup.patched_ruleset(
        sup.M4_FIXTURE,
        sup.mutate_value(
            "action_rule.maintenance_trigger",
            "rules",
            [
                {"rule_id": "FX-1", "metric": "mqi_partial", "op": "lt", "threshold": 10.0, "action_class": "类别甲", "scale_band": "档一"},
                {"rule_id": "FX-2", "metric": "pci", "op": "lt", "threshold": 90.0, "action_class": "类别乙", "scale_band": "档二"},
            ],
        ),
    )
    item = actions(conn, 2025, assess([obj]), package, mqi_results=[])[0]
    assert item.status == res.STATUS_BLOCKED
    assert "mqi_partial" in item.blocked_reason and "FX-1" in item.blocked_reason


def test_malformed_rule_registration_is_refused():
    for broken in (
        [],
        [{"metric": "pci", "op": "lt", "threshold": 1.0, "action_class": "甲", "scale_band": "一"}],
        [{"rule_id": "A", "metric": "traffic", "op": "lt", "threshold": 1.0, "action_class": "甲", "scale_band": "一"}],
        [{"rule_id": "A", "metric": "pci", "op": "ne", "threshold": 1.0, "action_class": "甲", "scale_band": "一"}],
        [{"rule_id": "A", "metric": "pci", "op": "lt", "threshold": "abc", "action_class": "甲", "scale_band": "一"}],
        [{"rule_id": "A", "metric": "pci", "op": "between", "threshold": {"lo": 9.0, "hi": 1.0}, "action_class": "甲", "scale_band": "一"}],
        [
            {"rule_id": "A", "metric": "pci", "op": "lt", "threshold": 1.0, "action_class": "甲", "scale_band": "一"},
            {"rule_id": "A", "metric": "pci", "op": "lt", "threshold": 2.0, "action_class": "乙", "scale_band": "二"},
        ],
    ):
        package = sup.patched_ruleset(sup.M4_FIXTURE, sup.mutate_value("action_rule.maintenance_trigger", "rules", broken))
        obj = sup.spec()
        conn = sup.open_ledger()
        sup.insert(conn, obj)
        item = actions(conn, 2025, assess([obj]), package)[0]
        assert item.status == res.STATUS_BLOCKED, broken
        assert item.action_class is None


def test_clause_missing_coefficient_cannot_authorize_a_conclusion():
    package = sup.patched_ruleset(sup.M4_FIXTURE, sup.clear_clause("action_rule.maintenance_trigger"))
    obj = sup.spec()
    conn = sup.open_ledger()
    sup.insert(conn, obj)
    item = actions(conn, 2025, assess([obj]), package)[0]
    assert item.status == res.STATUS_BLOCKED
    assert "未登记条款号" in item.blocked_reason


# ---- 优先序：固定次级键 ----


def tied_ledger():
    objs = [
        sup.spec(segment_id="SYN-T3", start_m=2000, end_m=3000, rqi=75.0),
        sup.spec(segment_id="SYN-T1", start_m=0, end_m=1000, rqi=75.0),
        sup.spec(segment_id="SYN-T2", start_m=1000, end_m=2000, rqi=85.0),
    ]
    conn = sup.open_ledger()
    for obj in objs:
        sup.insert(conn, obj)
    return conn, objs


def test_ranking_is_stable_under_rotation_and_reversal():
    """同分对象靠固定次级键定序：旋转或反序输入后，输出序列逐位相同。"""
    conn, objs = tied_ledger()
    reference = rules.rank_priority(actions(conn, 2025, assess(objs)), "pci")
    assert [item.segment_id for item in reference] == ["SYN-T1", "SYN-T3", "SYN-T2"], [
        (item.segment_id, item.pci) for item in reference
    ]
    for shift in range(1, len(objs)):
        rotated = objs[shift:] + objs[:shift]
        again = rules.rank_priority(actions(conn, 2025, assess(rotated)), "pci")
        assert [item.segment_id for item in again] == [item.segment_id for item in reference]
    reversed_input = list(reversed(objs))
    again = rules.rank_priority(actions(conn, 2025, assess(reversed_input)), "pci")
    assert [item.segment_id for item in again] == [item.segment_id for item in reference]


def test_unnumbered_objects_sort_last_in_both_directions():
    conn, objs = tied_ledger()
    suggestions = actions(conn, 2025, assess(objs))
    suggestions[1] = res.ActionSuggestion(
        segment_id=suggestions[1].segment_id,
        route_id=suggestions[1].route_id,
        year=2025,
        status=res.STATUS_BLOCKED,
        blocked_reason="夹具：该项未出数",
    )
    for ascending in (True, False):
        ranked = rules.rank_priority(suggestions, "pci", ascending=ascending)
        assert ranked[-1].pci is None, ascending


def test_ranking_rejects_an_undeclared_primary_key():
    conn, objs = tied_ledger()
    with pytest.raises(ValueError):
        rules.rank_priority(actions(conn, 2025, assess(objs)), "route_name")


# ---- 年对比 ----


def two_year_objs(**overrides):
    base = sup.spec()
    earlier = sup.spec(year=2022)
    later = sup.spec(year=2023, **overrides)
    return base, earlier, later


def ledger_for(*objs):
    conn = sup.open_ledger()
    for obj in objs:
        sup.insert(conn, obj)
    return conn


def test_builtin_package_refuses_the_change_rate():
    _base, earlier, later = two_year_objs(rqi=75.0)
    conn = ledger_for(earlier, later)
    result = compare.compare_years(conn, "SYN-G1", 2022, 2023, assess([earlier, later], builtin_ruleset()), builtin_ruleset())
    assert result.status == res.STATUS_BLOCKED
    assert result.delta is None and result.deterioration_rate_per_year is None
    assert "PCI 未出数" in result.blocked_reason


def test_delta_and_deterioration_rate_are_signed_as_declared():
    _base, earlier, later = two_year_objs(rqi=75.0)
    conn = ledger_for(earlier, later)
    pci_results = assess([earlier, later])
    result = compare.compare_years(conn, "SYN-G1", 2022, 2023, pci_results, sup.m4_ruleset())
    assert result.status == res.STATUS_OK, result.blocked_reason
    assert result.delta == pytest.approx(-3.0)
    assert result.deterioration_rate_per_year == pytest.approx(3.0), "正值表示每年劣化多少分"
    assert result.grade_from == result.grade_to == "良"
    assert result.length_overlap_m == 1000.0


def test_change_decomposes_into_traceable_contributions():
    """变化必须追到"哪个指标的哪一次变化"，每条仍挂系数 key + 条款号 + 台账行号。"""
    _base, earlier, later = two_year_objs(rqi=75.0)
    conn = ledger_for(earlier, later)
    result = compare.compare_years(conn, "SYN-G1", 2022, 2023, assess([earlier, later]), sup.m4_ruleset())
    assert len(result.top_contributors) == 1
    item = result.top_contributors[0]
    assert item.source_kind == "measured_indicator"
    assert item.distress_type == "ride_quality"
    assert item.deducted_points == pytest.approx(3.0)
    assert item.share == pytest.approx(1.0)
    assert item.coefficient_key == "pci_component.ride_quality"
    assert item.clause == "夹具式 B-1"
    rows = compare.explain_change_rows(result)
    assert rows[0]["coefficient_key"] == "pci_component.ride_quality"


def test_distress_that_appears_only_in_the_later_year_is_its_own_contribution():
    """"只在新一年出现"的破损：差值取该侧原值，并回指那一侧的台账行号（可追到原始检测表）。"""
    _base, earlier, _later = two_year_objs()
    later = sup.spec(year=2023, rows=list(sup.GOLDEN_ASPHALT_ROWS) + [("波浪", "重", 3000.0, "m2", 4)])
    conn = ledger_for(earlier, later)
    result = compare.compare_years(conn, "SYN-G1", 2022, 2023, assess([earlier, later]), sup.m4_ruleset())
    contributors = {item.distress_type: item for item in result.top_contributors}
    assert "波浪" in contributors
    assert contributors["波浪"].deducted_points > 0
    assert contributors["波浪"].source_row_no == 4
    assert contributors["波浪"].coefficient_key == "deduct_ratio.asphalt_distress"
    assert sum(item.deducted_points for item in result.top_contributors) == pytest.approx(-result.delta, abs=0.15)


def test_shared_distress_type_aggregates_rows_and_points_to_the_smallest_row_no():
    """同一"类型 × 程度"的多条记录先汇总再求差；行号取所引用年度的最小行号（口径固定）。"""
    _base, earlier, _later = two_year_objs()
    later = sup.spec(year=2023, rows=list(sup.GOLDEN_ASPHALT_ROWS) + [("坑槽", "重", 300.0, "m2", 4)])
    conn = ledger_for(earlier, later)
    result = compare.compare_years(conn, "SYN-G1", 2022, 2023, assess([earlier, later]), sup.m4_ruleset())
    item = [entry for entry in result.top_contributors if entry.distress_type == "坑槽"][0]
    assert item.deducted_points > 0
    assert item.source_row_no == 1


def test_identical_two_years_report_no_change_instead_of_a_fake_conclusion():
    _base, earlier, later = two_year_objs()
    conn = ledger_for(earlier, later)
    result = compare.compare_years(conn, "SYN-G1", 2022, 2023, assess([earlier, later]), sup.m4_ruleset())
    assert result.status == res.STATUS_PARTIAL
    assert result.delta == pytest.approx(0.0)
    assert result.top_contributors == []
    assert "无变化贡献项" in result.scope_note


@pytest.mark.parametrize(
    "change_kind,reason",
    [
        ("shifted", "partition_shifted"),
        ("merged", "partition_merged"),
        ("split", "partition_split"),
        ("new", "partition_new"),
        ("disappeared", "partition_disappeared"),
    ],
)
def test_partition_change_refuses_the_rate_for_each_kind(change_kind, reason):
    _base, earlier, later = two_year_objs(rqi=75.0)
    conn = ledger_for(earlier, later)
    conn.execute(
        "INSERT INTO partition_change (route_id, year_from, year_to, change_kind, segment_id, detail)"
        " VALUES (?,?,?,?,?,?)",
        ("S99", 2022, 2023, change_kind, "SYN-G1", "夹具：跨年划分变更"),
    )
    conn.commit()
    result = compare.compare_years(conn, "SYN-G1", 2022, 2023, assess([earlier, later]), sup.m4_ruleset())
    assert result.status == res.STATUS_UNCOMPARABLE
    assert result.comparability_reason == reason
    assert result.delta is None and result.deterioration_rate_per_year is None
    assert "摊分" in result.blocked_reason


def test_partition_change_is_found_whatever_the_query_year_order():
    _base, earlier, later = two_year_objs(rqi=75.0)
    conn = ledger_for(earlier, later)
    conn.execute(
        "INSERT INTO partition_change (route_id, year_from, year_to, change_kind, segment_id, detail)"
        " VALUES (?,?,?,?,?,?)",
        ("S99", 2023, 2022, "shifted", "SYN-G1", "夹具：反向登记的变更"),
    )
    conn.commit()
    result = compare.compare_years(conn, "SYN-G1", 2022, 2023, assess([earlier, later]), sup.m4_ruleset())
    assert result.status == res.STATUS_UNCOMPARABLE
    assert result.comparability_reason == "partition_shifted"


def test_segment_present_in_only_one_year_is_a_partition_reason():
    """只在一年出现：新一年没有 → partition_disappeared；起始年没有 → partition_new。"""
    _base, earlier, _later = two_year_objs()
    conn = ledger_for(earlier)
    result = compare.compare_years(conn, "SYN-G1", 2022, 2023, assess([earlier]), sup.m4_ruleset())
    assert result.status == res.STATUS_UNCOMPARABLE
    assert result.comparability_reason == "partition_disappeared"
    assert result.delta is None

    conn2 = ledger_for(sup.spec(year=2023))
    result2 = compare.compare_years(conn2, "SYN-G1", 2022, 2023, assess([sup.spec(year=2023)]), sup.m4_ruleset())
    assert result2.comparability_reason == "partition_new", result2.blocked_reason


def test_different_component_scope_across_years_is_uncomparable():
    """一年车辙缺测：两个 PCI 不在同一分母上，差值无意义（也不许"补一个分"再比）。"""
    _base, earlier, later = two_year_objs(rut_depth_mm=None)
    conn = ledger_for(earlier, later)
    result = compare.compare_years(conn, "SYN-G1", 2022, 2023, assess([earlier, later]), sup.m4_ruleset())
    assert result.status == res.STATUS_UNCOMPARABLE
    assert result.comparability_reason == "component_scope_mismatch"
    assert result.delta is None


def test_different_ruleset_version_is_uncomparable():
    _base, earlier, later = two_year_objs(rqi=75.0)
    conn = ledger_for(earlier, later)

    def bump(payload):
        payload["version"] = "0.0.1-fixture"

    bumped = sup.patched_ruleset(sup.M4_FIXTURE, bump)
    pci_results = [
        pci.compute_pci(sup.kernel_input(earlier), sup.m4_ruleset()),
        pci.compute_pci(sup.kernel_input(later), bumped),
    ]
    result = compare.compare_years(conn, "SYN-G1", 2022, 2023, pci_results, sup.m4_ruleset())
    assert result.status == res.STATUS_UNCOMPARABLE
    assert result.comparability_reason == "rule_version_change"


def test_surface_type_change_is_uncomparable():
    _base, earlier, _later = two_year_objs()
    later = sup.spec(year=2023, surface_type="cement")
    conn = ledger_for(earlier, later)
    pci_results = [pci.compute_pci(sup.kernel_input(earlier), sup.m4_ruleset())]
    cement = sup.kernel_input(sup.spec(year=2023, surface_type="cement"))
    pci_results.append(pci.compute_pci(cement, sup.cement_ruleset()))
    result = compare.compare_years(conn, "SYN-G1", 2022, 2023, pci_results, sup.m4_ruleset())
    assert result.status == res.STATUS_UNCOMPARABLE
    assert result.comparability_reason == "component_scope_mismatch"
    assert "路面类型" in result.blocked_reason


def test_unknown_partition_kind_is_a_contract_break_not_a_silent_pass():
    from road_mqi_checker.errors import SchemaViolation

    _base, earlier, later = two_year_objs(rqi=75.0)
    conn = ledger_for(earlier, later)
    conn.execute(
        "INSERT INTO partition_change (route_id, year_from, year_to, change_kind, segment_id, detail)"
        " VALUES (?,?,?,?,?,?)",
        ("S99", 2022, 2023, "reincarnated", "SYN-G1", "夹具：未登记的类别"),
    )
    conn.commit()
    with pytest.raises(SchemaViolation):
        compare.compare_years(conn, "SYN-G1", 2022, 2023, assess([earlier, later]), sup.m4_ruleset())


def test_same_year_and_absent_segment_are_input_unavailable():
    _base, earlier, _later = two_year_objs()
    conn = ledger_for(earlier)
    with pytest.raises(InputUnavailable):
        compare.compare_years(conn, "SYN-G1", 2022, 2022, assess([earlier]), sup.m4_ruleset())
    with pytest.raises(InputUnavailable):
        compare.compare_years(conn, "SYN-GHOST", 2022, 2023, assess([earlier]), sup.m4_ruleset())


def test_segment_ids_in_ledger_takes_the_union_so_partition_changes_stay_visible():
    """只在一年出现的对象不能被交集滤掉：它正是"划分新增/消失"的证据，要出现在清单上。"""
    _base, earlier, later = two_year_objs()
    conn = ledger_for(earlier, later, sup.spec(segment_id="SYN-ONLY22", year=2022, start_m=5000, end_m=6000))
    assert compare.segment_ids_in_ledger(conn, 2022, 2023) == ["SYN-G1", "SYN-ONLY22"]


def test_uncomparable_results_carry_no_numbers_at_all():
    """拒算三类入口对 M4 同样适用：uncomparable 的每个数值字段都得是 None。"""
    _base, earlier, later = two_year_objs(rut_depth_mm=None)
    conn = ledger_for(earlier, later)
    result = compare.compare_years(conn, "SYN-G1", 2022, 2023, assess([earlier, later]), sup.m4_ruleset())
    for name in res.CompareResult.NUMERIC_FIELDS:
        assert getattr(result, name) is None, name


# ---- 对外措辞 ----


def test_m4_texts_pass_the_honest_wording_gate():
    """说明行、口径声明、拒算原因都过措辞门：不许出现"已确认/已核实/最终确定"。"""
    obj = sup.spec()
    conn = sup.open_ledger()
    sup.insert(conn, obj)
    pci_results = assess([obj])
    segments = mqi.aggregate_year(conn, 2025, pci_results, sup.m4_ruleset(), level="segment")
    suggestion = actions(conn, 2025, pci_results)[0]
    builtin_segments = mqi.aggregate_year(conn, 2025, [pci.compute_pci(sup.kernel_input(obj), builtin_ruleset())], builtin_ruleset(), level="segment")
    texts = [segments[0].scope_note, suggestion.triggered_by, suggestion.condition_text, builtin_segments[0].blocked_reason]
    compared = compare.compare_years(conn, "SYN-G1", 2022, 2023, assess([sup.spec(year=2022), sup.spec(year=2023)]), sup.m4_ruleset())
    texts.append(compared.blocked_reason or compared.scope_note)
    for text in texts:
        privacy.assert_honest_wording(text)
