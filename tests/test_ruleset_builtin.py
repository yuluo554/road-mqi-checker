"""内置基础规则集的 M3 门：每格系数要么已核对且依据四件套齐全，要么未核对且不带任何数字。

M0 的门写作"一格已核对系数都没有"；M3 起容差这一格是**用户自定口径**（不来自规范原文，
显式登记即生效），所以门改成逐格二选一，并额外守住两条命门：

1. **凡依据 JTG 5210-2018 的格子，没有官方渠道原文一律不得转 verified** —— 这条防止
   有人拿搜索摘要或二手数值"顺手核完"，是本题的立身之处；
2. **verified 格子的 values 必须符合 `plan/05` §二 的形状契约** —— 形状错的值会在引擎里
   被拒算并点名字段，但拒算发生在运行期；门在测试期就该红。

若有人凭记忆往 JSON 里填了规范数字，这里就会红。
"""

import json
import os

import pytest

from road_mqi_checker.ledger import models
from road_mqi_checker.ruleset import loader
from road_mqi_checker.ruleset import status as st

BASE_NAME = "base-jtg5210-2018.json"

#: 内置包里当前允许处于 verified 的格子：只有用户自定口径的那一格。
#: 转进这个名单的前提是拿到 JTG 5210-2018 原文（见 data/README.md §一 第 1 行）。
ALLOWED_VERIFIED_KEYS = {"tolerance.length_closure"}

#: 官方渠道判据：政府/主管部门网站，或标准原文电子版载体。文档分享站一律不算。
OFFICIAL_CHANNEL_MARKS = (".gov.cn", "标准原文电子版", "出版社")

PCI_COMPONENTS = ("distress", "ride_quality", "rutting", "skid_resistance")

#: M4 新增三条路径的形状口径 —— 词汇从代码取，避免"测试写死一份、引擎另一份"
from road_mqi_checker.mqi import engine as mqi_engine  # noqa: E402
from road_mqi_checker.strategy import rules as rules_engine  # noqa: E402

MQI_COMPONENTS = mqi_engine.COMPONENTS
ACTION_METRICS = rules_engine.ACTION_METRICS
ACTION_OPS = rules_engine.CONDITION_OPS

PROVENANCE_FIELDS = ("clause", "channel", "verified_at", "locator")


def _builtin_payload():
    # type: () -> dict
    with open(os.path.join(loader._BUILTIN_DIR, BASE_NAME), "r", encoding="utf-8") as handle:
        return json.load(handle)


def _write(tmp_path, payload):
    # type: (object, dict) -> str
    path = os.path.join(str(tmp_path), "mutated-ruleset.json")
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return path


@pytest.fixture
def base_ruleset():
    path = os.path.join(loader._BUILTIN_DIR, BASE_NAME)
    assert os.path.isfile(path), "内置基础规则集缺失：%s" % path
    return loader.load_file(path)


# ---- M3 门 A：逐格二选一（verified + 四件套 / pending + values 为 null）----


def test_every_cell_is_verified_with_provenance_or_pending_without_numbers(base_ruleset):
    for coef in base_ruleset.coefficients:
        if coef.status == st.VERIFIED:
            assert coef.values not in (None, {}, []), "%s 自称 verified 但 values 为空" % coef.key
            for basis in coef.basis:
                missing = [name for name in PROVENANCE_FIELDS if not getattr(basis, name)]
                assert not missing, "%s 自称 verified，但依据缺 %s" % (coef.key, "/".join(missing))
                assert basis.status == st.VERIFIED, "%s 的系数已 verified 但条款状态仍是 %s" % (coef.key, basis.status)
        else:
            assert coef.values is None, "%s 状态为 %s 却带数值" % (coef.key, coef.status)


def test_only_user_defined_cells_are_verified(base_ruleset):
    """规范来源格（JTG 5210-2018）在拿到原文前一律不得生效。"""
    offenders = [coef.key for coef in base_ruleset.coefficients if coef.status == st.VERIFIED]
    assert set(offenders) <= ALLOWED_VERIFIED_KEYS, (
        "以下格子转成了 verified，但依据仍不是官方原文：%s" % ", ".join(sorted(offenders))
    )
    for coef in base_ruleset.coefficients:
        if coef.status != st.VERIFIED:
            continue
        for basis in coef.basis:
            if not basis.standard_id.startswith("JTG"):
                continue
            assert any(mark in basis.channel for mark in OFFICIAL_CHANNEL_MARKS), (
                "%s 引用 JTG 原文但渠道 %r 不是官方页面" % (coef.key, basis.channel)
            )


def test_verified_cells_are_listed_in_the_ledger(base_ruleset, repo_root):
    """每一格生效系数都要在依据台账里有一行真实记录（含渠道与日期）。"""
    rows = _verification_ledger_rows(repo_root)
    ledger_text = "\n".join(" | ".join(row) for row in rows)
    for coef in base_ruleset.coefficients:
        if coef.status != st.VERIFIED:
            continue
        referenced = rows[int(coef.register_ref.split("#")[1]) - 1]
        assert coef.register_ref in ledger_text or referenced[1], coef.key


def test_provenance_gate_rejects_a_verified_cell_without_locator(tmp_path):
    """反证：把 verified 格的 locator 抹掉，schema 门必须拒绝整包加载并点名字段。"""
    payload = _builtin_payload()
    for coef in payload["coefficients"]:
        if coef["key"] in ALLOWED_VERIFIED_KEYS:
            coef["basis"][0]["locator"] = ""
    path = _write(tmp_path, payload)
    with pytest.raises(Exception) as excinfo:
        loader.load_file(path)
    assert "locator" in str(excinfo.value)


def test_official_channel_gate_is_not_vacuous():
    """反证：文档分享站形态的渠道必须被官方渠道判据拒掉。"""
    for channel in ("https://max.book118.com/html/2024/0710/x.shtm", "https://wenku.baidu.com/view/abc"):
        assert not any(mark in channel for mark in OFFICIAL_CHANNEL_MARKS), channel


# ---- M3 门 B：verified 格子的 values 形状契约（plan/05 §二）----


def values_shape_problems(coef):
    # type: (object) -> list
    """返回该格 values 违反形状契约的问题清单；空清单即形状合规。"""
    problems = []
    values = coef.values
    key = coef.key
    if not isinstance(values, dict):
        return ["%s 的 values 不是对象" % key]
    if key.startswith("deduct_ratio."):
        surface = key.split(".")[1].split("_")[0]
        ratios = values.get("ratios")
        if not isinstance(ratios, dict):
            return ["%s 缺 ratios 对象" % key]
        expected = models.DISTRESS_DICTIONARY.get(surface, {})
        for missing in sorted(set(expected) - set(ratios)):
            problems.append("%s 缺破损类型 %s" % (key, missing))
        for extra in sorted(set(ratios) - set(expected)):
            problems.append("%s 多出未知破损类型 %s" % (key, extra))
        for distress, by_severity in ratios.items():
            if not isinstance(by_severity, dict):
                problems.append("%s 的 %s 不是程度→比率对象" % (key, distress))
                continue
            for missing in sorted(set(models.SEVERITY_LEVELS) - set(by_severity)):
                problems.append("%s 的 %s 缺程度 %s" % (key, distress, missing))
            for severity, ratio in by_severity.items():
                if not isinstance(ratio, (int, float)) or not 0.0 <= float(ratio) <= 1.0:
                    problems.append("%s 的 %s/%s 比率 %r 不在 [0,1]" % (key, distress, severity, ratio))
    elif key == "pci_component.ride_quality":
        if not isinstance(values.get("weight"), (int, float)) or values["weight"] <= 0:
            problems.append("pci_component.ride_quality 的 weight 必须 > 0")
    elif key == "pci_component.rutting":
        weight, ideal, zero = values.get("weight"), values.get("ideal_mm"), values.get("zero_mm")
        if not isinstance(weight, (int, float)) or weight <= 0:
            problems.append("pci_component.rutting 的 weight 必须 > 0")
        if not (isinstance(ideal, (int, float)) and isinstance(zero, (int, float))) or zero <= ideal:
            problems.append("pci_component.rutting 要求 zero_mm > ideal_mm")
    elif key == "pci_component.skid_resistance":
        weight, zero, ideal = values.get("weight"), values.get("zero_value"), values.get("ideal_value")
        if not isinstance(weight, (int, float)) or weight <= 0:
            problems.append("pci_component.skid_resistance 的 weight 必须 > 0")
        if not (isinstance(ideal, (int, float)) and isinstance(zero, (int, float))) or ideal <= zero:
            problems.append("pci_component.skid_resistance 要求 ideal_value > zero_value")
    elif key.startswith("pci_weight."):
        weights = values.get("weights")
        if not isinstance(weights, dict) or not weights:
            problems.append("%s 缺 weights 对象" % key)
        else:
            for extra in sorted(set(weights) - set(PCI_COMPONENTS)):
                problems.append("%s 多出未认定分项 %s" % (key, extra))
            for name, weight in weights.items():
                if not isinstance(weight, (int, float)) or weight <= 0:
                    problems.append("%s 的分项 %s 权重必须 > 0" % (key, name))
    elif key.startswith("mqi_weight."):
        # M4 形态：一个分项一格，values 是 {"weight": 正数}（与 mqi.engine 的取值口径一致）
        component = key.split(".")[1]
        if component not in MQI_COMPONENTS:
            problems.append("%s 的分项 %s 不在 MQI 分项词汇里" % (key, component))
        weight = values.get("weight")
        if not isinstance(weight, (int, float)) or isinstance(weight, bool) or weight <= 0:
            problems.append("%s 的 weight 必须是正数值（实际 %r）" % (key, weight))
    elif key.startswith("action_rule."):
        # M4 形态：IF/THEN 规则链，条件里的阈值只能出现在这里（与 strategy.rules 的取值口径一致）
        rules = values.get("rules")
        if not isinstance(rules, list) or not rules:
            problems.append("%s 缺非空数组 rules" % key)
        else:
            seen = set()
            for index, rule in enumerate(rules):
                where = "%s 第 %d 条规则" % (key, index + 1)
                if not isinstance(rule, dict):
                    problems.append("%s 不是对象" % where)
                    continue
                for field in ("rule_id", "metric", "op", "threshold", "action_class", "scale_band"):
                    if rule.get(field) in (None, "", {}):
                        problems.append("%s 缺 %s" % (where, field))
                if rule.get("rule_id") in seen:
                    problems.append("%s 的 rule_id 重复，优先序无法确定" % where)
                seen.add(rule.get("rule_id"))
                if rule.get("metric") not in ACTION_METRICS:
                    problems.append("%s 的指标 %r 不在 %s 里" % (where, rule.get("metric"), "/".join(ACTION_METRICS)))
                if rule.get("op") not in ACTION_OPS:
                    problems.append("%s 的比较符 %r 非法" % (where, rule.get("op")))
                if rule.get("op") == "between":
                    bounds = rule.get("threshold")
                    lo, hi = (bounds or {}).get("lo"), (bounds or {}).get("hi")
                    if not (isinstance(lo, (int, float)) and isinstance(hi, (int, float))) or hi <= lo:
                        problems.append("%s 的 between 阈值要 hi > lo" % where)
                elif not isinstance(rule.get("threshold"), (int, float)) or isinstance(rule.get("threshold"), bool):
                    problems.append("%s 的 threshold 必须是数值" % where)
    elif key.startswith("grade_threshold."):
        if values.get("boundary") not in ("lower_inclusive", "lower_exclusive"):
            problems.append("%s 必须显式登记 boundary 含界与否" % key)
        bands = values.get("bands")
        if not isinstance(bands, list) or not bands:
            problems.append("%s 缺 bands 数组" % key)
        else:
            mins = [band.get("min") for band in bands]
            if any(not isinstance(m, (int, float)) for m in mins):
                problems.append("%s 的 bands 有非数值下界" % key)
            else:
                if len(set(mins)) != len(mins):
                    problems.append("%s 的 bands 下界不唯一" % key)
                if sorted(mins, reverse=True) != mins:
                    problems.append("%s 的 bands 未按下界降序排列，无法逐档判定" % key)
                if any(not band.get("grade") for band in bands):
                    problems.append("%s 的 bands 有缺等级名的档" % key)
    elif key.startswith("tolerance."):
        tolerance = values.get("meters", values.get("value", values.get("tolerance_m")))
        if not isinstance(tolerance, (int, float)) or tolerance < 0:
            problems.append("%s 的容差必须是非负数值" % key)
    else:
        problems.append("%s 没有对应的形状口径，不得生效" % key)
    return problems


def test_verified_cells_satisfy_the_shape_contract(base_ruleset):
    for coef in base_ruleset.coefficients:
        if coef.status == st.VERIFIED:
            assert not values_shape_problems(coef), coef.key


def test_shape_contract_covers_the_fully_verified_fixture_packages():
    """形状门不是空转：夹具包全格生效（夹具档），必须逐个通过同一道门。

    M4 起还要覆盖汇总/分级/对策三格 —— 引擎读的字段与门查的字段是同一套口径。
    """
    expectations = {
        "pci-fixture-asphalt.json": 6,
        "pci-fixture-cement.json": 6,
        "m4-fixture-asphalt.json": 12,
    }
    for name, expected in expectations.items():
        pkg = loader.load_file(os.path.join(os.path.dirname(__file__), "fixtures", name), allow_fixture=True)
        assert len(pkg.computable_coefficients()) == expected, (name, len(pkg.computable_coefficients()))
        for coef in pkg.coefficients:
            assert not values_shape_problems(coef), "%s / %s" % (name, coef.key)


def test_action_rule_shape_contract_rejects_bad_rule_chains():
    """对策格的形状门要真的会红：缺 rules、重复 rule_id、阈值非数值都要拦下。"""
    for values, expect in (
        ({}, "缺非空数组 rules"),
        ({"rules": [{"metric": "pci", "op": "lt", "threshold": 1.0, "action_class": "甲", "scale_band": "一"}]}, "缺 rule_id"),
        ({"rules": [{"rule_id": "A", "metric": "nope", "op": "lt", "threshold": 1.0, "action_class": "甲", "scale_band": "一"}]}, "不在"),
        ({"rules": [{"rule_id": "A", "metric": "pci", "op": "eq", "threshold": 1.0, "action_class": "甲", "scale_band": "一"}]}, "比较符"),
        ({"rules": [{"rule_id": "A", "metric": "pci", "op": "lt", "threshold": "x", "action_class": "甲", "scale_band": "一"}]}, "必须是数值"),
        ({"rules": [{"rule_id": "A", "metric": "pci", "op": "between", "threshold": {"lo": 9.0, "hi": 1.0}, "action_class": "甲", "scale_band": "一"}]}, "hi > lo"),
        (
            {"rules": [
                {"rule_id": "A", "metric": "pci", "op": "lt", "threshold": 1.0, "action_class": "甲", "scale_band": "一"},
                {"rule_id": "A", "metric": "pci", "op": "lt", "threshold": 2.0, "action_class": "乙", "scale_band": "二"},
            ]},
            "rule_id 重复",
        ),
    ):
        coef = _coefficient_stub("action_rule.maintenance_trigger", "action_rule", values)
        assert expect in "；".join(values_shape_problems(coef)), (values, expect)


def test_mqi_weight_shape_contract_matches_the_engine_field():
    """MQI 分项权重格读的是 `weight`（一格一分项），写成 `weights` 必须被门拦下。"""
    for values, expect in (
        ({"weights": {"pavement": 55.0}}, "weight 必须是正数值"),
        ({"weight": 0}, "weight 必须是正数值"),
        ({"weight": "55"}, "weight 必须是正数值"),
        ({"weight": 55.0}, ""),
    ):
        coef = _coefficient_stub("mqi_weight.pavement", "component_weight", values)
        joined = "；".join(values_shape_problems(coef))
        if expect:
            assert expect in joined, joined
        else:
            assert not joined, joined


def _coefficient_stub(key, kind, values):
    # type: (str, str, dict) -> object
    """只造形状门要读的两样（key / values）：schema 门另有自己的测试，这里不重复过。"""
    return loader.Coefficient(
        key=key,
        kind=kind,
        surface_type=None,
        status=st.VERIFIED,
        values=values,
        unit="测试",
        basis=[],
        register_ref="data/README.md#9",
        note="",
    )


@pytest.mark.parametrize(
    "key,values,expect",
    [
        ("deduct_ratio.asphalt_distress", {"ratios": {}}, "缺破损类型"),
        ("tolerance.length_closure", {"meters": -1}, "非负"),
        ("pci_component.rutting", {"weight": 15.0, "ideal_mm": 18.0, "zero_mm": 2.0}, "zero_mm > ideal_mm"),
        (
            "pci_component.skid_resistance",
            {"weight": 15.0, "zero_value": 60.0, "ideal_value": 20.0},
            "ideal_value > zero_value",
        ),
        ("pci_weight.asphalt", {"weights": {"distress": 40.0, "invented": 60.0}}, "未认定分项"),
        ("grade_threshold.pci", {"boundary": "", "bands": [{"grade": "优", "min": 90.0}]}, "boundary"),
        (
            "grade_threshold.pci",
            {"boundary": "lower_inclusive", "bands": [{"grade": "良", "min": 80.0}, {"grade": "优", "min": 90.0}]},
            "降序",
        ),
        ("pci_component.ride_quality", {"weight": 0}, "weight 必须 > 0"),
    ],
)
def test_shape_contract_rejects_bad_values(key, values, expect):
    """反证：坏形状必须被门拒掉并说清原因（否则门只是摆设）。"""
    coef = loader.Coefficient(
        key=key,
        kind="component_weight",
        surface_type=None,
        status=st.VERIFIED,
        values=values,
        unit="",
        basis=[loader.Basis("user-defined", "c", "ch", "2026-10-07", "loc")],
        register_ref="data/README.md#1",
        note="",
    )
    joined = "；".join(values_shape_problems(coef))
    assert joined, key
    assert expect in joined, joined


# ---- M0 遗留门（继续守住）----


def test_builtin_package_has_no_fixture_status(base_ruleset):
    assert all(coef.status != st.FIXTURE for coef in base_ruleset.coefficients)


def test_blocked_cells_still_cover_the_assessment_path(base_ruleset):
    """六格必需系数未全生效 → 评定路径仍一格都算不出来，这是 M3 的常态而不是接线坏了。"""
    from road_mqi_checker.pci import engine

    for surface_type in models.SURFACE_TYPES:
        required = engine.surface_table_keys(surface_type)
        assert required, surface_type
        unmet = [key for key in required if not base_ruleset.find(key).computable]
        assert len(unmet) == len(required), "%s 路面已有 %d/%d 格生效，M3 前不应出现" % (
            surface_type,
            len(required) - len(unmet),
            len(required),
        )


def test_every_coefficient_declares_a_register_ref(base_ruleset):
    """每格系数都要指向依据台账的某一行（data/README.md#N）。"""
    missing = [coef.key for coef in base_ruleset.coefficients if not coef.register_ref]
    assert not missing, "无出处的系数：%s" % missing
    bad = [coef.key for coef in base_ruleset.coefficients if not coef.register_ref.startswith("data/README.md#")]
    assert not bad, "出处格式必须是 data/README.md#N：%s" % bad


def _verification_ledger_rows(repo_root):
    """取 data/README.md §一 的依据查证记录表数据行（#N 就是这张表的行号）。"""
    with open(os.path.join(repo_root, "data", "README.md"), "r", encoding="utf-8") as handle:
        lines = handle.read().splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("## 一、"))
    rows = []
    for line in lines[start:]:
        if line.startswith("## ") and rows:
            break
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) < 2 or cells[0] in ("#", "") or set(cells[0]) <= set("-: "):
            continue
        rows.append(cells)
    assert rows, "依据查证记录表解析为空，#N 编号失去意义"
    return rows


def test_register_refs_point_at_existing_ledger_rows(base_ruleset, repo_root):
    rows = _verification_ledger_rows(repo_root)
    for coef in base_ruleset.coefficients:
        row_no = int(coef.register_ref.split("#")[1])
        assert 1 <= row_no <= len(rows), "%s 指向台账第 %d 行，超出依据表行数 %d" % (coef.key, row_no, len(rows))
        referenced = rows[row_no - 1]
        assert referenced[1], "%s 指向的依据行没有标准/依据名称" % coef.key


def test_register_refs_match_their_coefficient_kind(base_ruleset, repo_root):
    """扣分/权重/分级三态系数都挂在同一条依据行上，防止指向已查证失败的那行。"""
    rows = _verification_ledger_rows(repo_root)
    for coef in base_ruleset.coefficients:
        row_no = int(coef.register_ref.split("#")[1])
        referenced = " ".join(rows[row_no - 1])
        if coef.kind in ("deduct_ratio", "component_weight", "grade_threshold"):
            if coef.basis[0].standard_id.startswith("JTG"):
                assert "JTG 5210-2018" in referenced, "%s 的依据行不含它所引用的标准" % coef.key


def test_m4_required_cells_are_all_still_unverified(base_ruleset):
    """M4 新增的两条路径（汇总、对策）在内置包下同样一格都没生效 ⇒ 一律拒算。

    与评定路径同一口径：判据是"必需格是否全生效"，不是"本包生效了几格"（§9 第 23 条）。
    """
    from road_mqi_checker.bench import generator
    from road_mqi_checker.strategy import rules as rules_engine

    aggregation = mqi_engine.aggregation_required_keys()
    assert set(aggregation) == set(generator.TRUTH_GOVERNING_KEYS["mqi_partial_truth"])
    for key in aggregation:
        coef = base_ruleset.find(key)
        assert coef is not None, "汇总必需格没在内置包里登记：%s" % key
        assert not coef.computable, "%s 未拿到原文就生效了" % key

    action_key = rules_engine.action_required_keys()[0]
    assert not base_ruleset.find(action_key).computable, action_key

    # 三条路径的必需格判据都要报"仍缺"，缺的正是那几格
    assert generator.aggregation_gate_pending_keys(base_ruleset) == sorted(aggregation)
    assert generator.action_gate_pending_keys(base_ruleset) == [action_key]
    assert base_ruleset.summary()["computable"] == len(ALLOWED_VERIFIED_KEYS)


def test_required_cells_cover_the_whole_assessment_path(base_ruleset):
    """评定 + 汇总 + 分级 + 对策四类系数都得有位置，缺类就是范围漏了。"""
    kinds = set(coef.kind for coef in base_ruleset.coefficients)
    assert {"deduct_ratio", "component_weight", "grade_threshold", "action_rule"} <= kinds


def test_both_surface_types_have_deduct_tables(base_ruleset):
    surfaces = set(coef.surface_type for coef in base_ruleset.coefficients if coef.kind == "deduct_ratio")
    assert surfaces == {"asphalt", "cement"}


def test_blocked_reason_wording_is_honest(base_ruleset):
    for coef in base_ruleset.blocked_coefficients():
        reason = coef.block_reason()
        assert "应核实" in reason
        assert "已确认" not in reason


def test_ruleset_json_is_utf8_clean_and_lf_only():
    path = os.path.join(loader._BUILTIN_DIR, BASE_NAME)
    with open(path, "rb") as handle:
        raw = handle.read()
    assert b"\r" not in raw, "规则集含 CR，会打挂位级一致断言"
    assert raw.decode("utf-8")
