"""路面 PCI 评定引擎（模块 2，本题核心）。

规则优先、纯算术、无概率无模型。四条硬约束：

1. **每一格系数都来自规则集并挂条款号**：扣分比率、分项权重、分级阈值任一未核对
   （`pending` / `located`）或未登记条款号，整段即 `blocked`，数值字段全空；
2. **含异常数据即拒算**：台账里被 M1 校验层判为"检出的"破损字典/量纲/负值超范围/重复导入
   的对象，扣分本身不可解释，引擎出 `blocked`，不是"跳过那条破损行再算出一个数"；
3. **浮点比较一律走固定舍入**（`ROUND_HALF_UP` + `PCI_DECIMALS`），杜绝同一套数据两次算分不同；
4. **同一内核两种输入通路**：CLI/GUI 从 SQLite 台账读行（`compute_segment_pci` / `assess_year`），
   生成器的数值真值从内存行喂同一个换算核（`compute_pci`），不存在第二套公式。

换算式形态（本实现口径，数值一律来自规则集，见 `plan/05-评定与汇总算法说明.md` §二）：

- 破损分项：一条破损的扣分 = 扣分比率(类型×程度) × 该破损占评定单元的几何比例 × 满分；
  分项得分 = 满分 − 各条扣分之和（下限 0）；
- 实测指标分项：RQI 直接取实测指数；车辙/抗滑按规则集登记的 `ideal/zero` 两端做线性换算（区间外截断）；
- PCI 合成：各分项得分按 `pci_weight.<surface>` 的权重加权平均（缺测分项不参与，整体转 `partial`）；
- 等级：按 `grade_threshold.pci` 登记的档位与开闭区间口径判定，含界与否由规则集说，引擎不猜。

`SCORE_SCALE` / `SCORE_FLOOR` 是百分制的量程边界（结构常量，与 `PCI_DECIMALS` 同类），
不是任何规范阈值；所有阈值类数字都必须由规则集给出才能生效。
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Dict, List, Optional, Sequence, Tuple

from road_mqi_checker import results as res
from road_mqi_checker.ledger import models

MODULE_KEY = "road_mqi_checker.pci.engine"
MILESTONE = "M2"

#: 得分保留位数（既定口径：改动会让所有基准数字漂移）
PCI_DECIMALS = 1

#: 贡献占比的保留位数：扣分值保留 1 位，占比要 3 位才不会把 0.016 抹成 0.0
SHARE_DECIMALS = 3

#: 百分制量程（结构常量：满分与下限，不是规范阈值）
SCORE_SCALE = 100.0
SCORE_FLOOR = 0.0

#: 分项名称（`pci_weight.<surface>` 的 weights 键名，也是 component_scores 的键名）
COMPONENT_DISTRESS = "distress"
COMPONENT_RIDE = "ride_quality"
COMPONENT_RUTTING = "rutting"
COMPONENT_SKID = "skid_resistance"
COMPONENT_NAMES = (COMPONENT_DISTRESS, COMPONENT_RIDE, COMPONENT_RUTTING, COMPONENT_SKID)

#: 实测指标分项 → 读取的检测列
COMPONENT_SOURCE_COLUMN = {
    COMPONENT_RIDE: "rqi",
    COMPONENT_RUTTING: "rut_depth_mm",
    COMPONENT_SKID: "skid_indicator",
}

#: 路面类型 → 破损扣分比率格 / PCI 合成权重格
DEDUCT_RATIO_KEY = {
    "asphalt": "deduct_ratio.asphalt_distress",
    "cement": "deduct_ratio.cement_distress",
}
PCI_WEIGHT_KEY = {"asphalt": "pci_weight.asphalt", "cement": "pci_weight.cement"}
GRADE_THRESHOLD_KEY = "grade_threshold.pci"
COMPONENT_KEY = {
    COMPONENT_RIDE: "pci_component.ride_quality",
    COMPONENT_RUTTING: "pci_component.rutting",
    COMPONENT_SKID: "pci_component.skid_resistance",
}

#: 分级边界开闭口径的合法登记值（含界与否必须按原文确认，引擎不猜）
GRADE_BOUNDARIES = ("lower_inclusive", "lower_exclusive")

#: 让扣分不可解释的 M1 校验项：字典外类型没有比率格、量纲错则换算分母错、
#: 负值/超范围让"占比"失去意义、重复行会把同一破损扣两遍
BLOCKING_CHECK_KINDS = (
    "distress_dictionary",
    "unit_consistency",
    "value_range",
    "duplicate_import",
)

MISSING_GEOMETRY_HINT = {
    "length": "车道数（lane_count）",
    "area": "路段宽度（segment_width_m）",
    "panel": "板块总数（panel_count）",
}


def quantize(value, decimals=PCI_DECIMALS):
    # type: (float, int) -> float
    """固定舍入规则：十进制半值向上，不用 Python 内置 round 的银行家舍入。

    M0 就实现并锁死，避免 M2 之后再改口径打挂"零漂移"这条指标。
    """
    quant = Decimal(1).scaleb(-decimals)
    return float(Decimal(repr(value)).quantize(quant, rounding=ROUND_HALF_UP))


def surface_table_keys(surface_type):
    # type: (str) -> Tuple[str, ...]
    """给定路面类型，返回评定路径必须生效的系数 key 集合（缺任一即 blocked）。

    这个集合与 `bench.generator.TRUTH_GOVERNING_KEYS` 的 pci/grade 两列支配格一一对应：
    评定要用的格与真值敢出数的格必须是同一批，否则会出现"真值有数、引擎拒算"的假账。
    """
    if surface_type not in DEDUCT_RATIO_KEY:
        return ()
    return (
        DEDUCT_RATIO_KEY[surface_type],
        COMPONENT_KEY[COMPONENT_RIDE],
        COMPONENT_KEY[COMPONENT_RUTTING],
        COMPONENT_KEY[COMPONENT_SKID],
        PCI_WEIGHT_KEY[surface_type],
        GRADE_THRESHOLD_KEY,
    )


class Refusal(Exception):
    """一条拒算原因（缺系数 / 数据不可解释），各引擎共用，统一转成 blocked 结果。"""

    def __init__(self, reason):
        # type: (str) -> None
        self.reason = reason
        super(Refusal, self).__init__(reason)


# ---- 系数门 ----


def coefficient(ruleset, key):
    # type: (object, str) -> object
    coef = ruleset.find(key)
    if coef is None:
        raise Refusal("规则集 %s 未登记系数 %s，应核实原文后补入" % (ruleset.ruleset_id, key))
    if not coef.computable:
        raise Refusal(coef.block_reason())
    clause = clause_of(coef)
    if not clause:
        raise Refusal("系数 %s 可算但未登记条款号，扣分不可追溯，应核实原文后补条款" % key)
    return coef


def clause_of(coef):
    # type: (object) -> str
    for basis in coef.basis:
        if basis.clause:
            return basis.clause
    return ""


def _value_number(coef, field):
    # type: (object, str) -> float
    values = coef.values if isinstance(coef.values, dict) else {}
    raw = values.get(field)
    if not isinstance(raw, (int, float)) or isinstance(raw, bool):
        raise Refusal("系数 %s 的 %s 不是数值（实际 %r），未核对不出数" % (coef.key, field, raw))
    return float(raw)


# ---- 几何分母 ----


def _extent_denominator(extent, segment):
    # type: (str, Dict[str, object]) -> Optional[float]
    """换算比例的分母：一律由该路段自带的几何事实算出（不引用任何规范阈值）。"""
    length_m = segment.get("length_m")
    if not length_m:
        return None
    if extent == "area":
        width_m = segment.get("segment_width_m")
        return float(length_m) * float(width_m) if width_m else None
    if extent == "length":
        lane_count = segment.get("lane_count")
        return float(length_m) * float(lane_count) if lane_count else None
    if extent == "panel":
        panel_count = segment.get("panel_count")
        return float(panel_count) if panel_count else None
    return None


# ---- 破损扣分 ----


def _distress_deductions(segment, ratio_coef):
    # type: (Dict[str, object], object) -> List[Dict[str, object]]
    """逐条破损算出"扣了满分中的几分"，同时把不可解释的行变成拒算理由。"""
    surface_type = segment.get("surface_type")
    table = models.DISTRESS_DICTIONARY.get(str(surface_type), {})
    ratios = ratio_coef.values.get("ratios") if isinstance(ratio_coef.values, dict) else None
    if not isinstance(ratios, dict):
        raise Refusal("系数 %s 的 values 缺 ratios 映射，换算式无法落地" % ratio_coef.key)
    out = []  # type: List[Dict[str, object]]
    for row in segment.get("distress_rows") or []:
        distress_type = str(row.get("distress_type") or "")
        severity = str(row.get("severity") or "")
        entry = table.get(distress_type)
        if entry is None:
            raise Refusal(
                "破损类型 %r 不在 %s 路面字典里（台账行 %s），扣分比率格无从取值"
                % (distress_type, surface_type, row.get("source_row_no"))
            )
        if severity not in models.SEVERITY_LEVELS:
            raise Refusal(
                "破损程度 %r 不在字典档位 %s 里（台账行 %s）"
                % (severity, "/".join(models.SEVERITY_LEVELS), row.get("source_row_no"))
            )
        unit = str(row.get("quantity_unit") or "")
        if unit != entry["unit"]:
            raise Refusal(
                "%s 按字典口径应以 %s 计，本行记为 %s（台账行 %s），换算分母对不上"
                % (distress_type, entry["unit"], unit, row.get("source_row_no"))
            )
        quantity = row.get("quantity")
        if not isinstance(quantity, (int, float)) or isinstance(quantity, bool):
            raise Refusal("%s 的数量不是数值（台账行 %s）" % (distress_type, row.get("source_row_no")))
        if float(quantity) < 0:
            raise Refusal(
                "%s（%s）数量为负：%s %s（台账行 %s），扣分不可解释"
                % (distress_type, severity, quantity, unit, row.get("source_row_no"))
            )
        denominator = _extent_denominator(entry["extent"], segment)
        if denominator is None:
            raise Refusal(
                "%s 需要%s才能算占评定单元的比例，台账里缺该属性（台账行 %s）"
                % (distress_type, MISSING_GEOMETRY_HINT.get(entry["extent"], entry["extent"]), row.get("source_row_no"))
            )
        if float(quantity) > denominator:
            raise Refusal(
                "%s 数量 %s %s 超过该路段几何上界 %s %s（台账行 %s），占比失去意义"
                % (
                    distress_type,
                    quantity,
                    unit,
                    denominator,
                    unit,
                    row.get("source_row_no"),
                )
            )
        by_severity = ratios.get(distress_type)
        if not isinstance(by_severity, dict):
            raise Refusal("系数 %s 未登记破损类型 %s 的扣分比率" % (ratio_coef.key, distress_type))
        ratio = by_severity.get(severity)
        if not isinstance(ratio, (int, float)) or isinstance(ratio, bool):
            raise Refusal("系数 %s 未登记 %s 在 %s 程度的扣分比率" % (ratio_coef.key, distress_type, severity))
        if not 0.0 <= float(ratio) <= 1.0:
            raise Refusal(
                "系数 %s 的 %s/%s 比率 %s 不在 0～1 之间，扣分比率越界即换算式不成立"
                % (ratio_coef.key, distress_type, severity, ratio)
            )
        share_of_unit = float(quantity) / denominator
        out.append(
            {
                "distress_type": distress_type,
                "severity": severity,
                "quantity": float(quantity),
                "quantity_unit": unit,
                "source_row_no": row.get("source_row_no"),
                "coefficient_key": ratio_coef.key,
                "clause": clause_of(ratio_coef),
                "ratio": float(ratio),
                "share_of_unit": share_of_unit,
                "deducted_points": float(ratio) * share_of_unit * SCORE_SCALE,
            }
        )
    return out


# ---- 实测指标换算 ----


def _component_score(component, coef, value):
    # type: (str, object, float) -> float
    """实测值 → 分项得分；换算参数全部来自该格系数的 values。"""
    if component == COMPONENT_RIDE:
        return value
    params = coef.values if isinstance(coef.values, dict) else {}
    if component == COMPONENT_RUTTING:
        ideal, zero = params.get("ideal_mm"), params.get("zero_mm")
        if not isinstance(ideal, (int, float)) or not isinstance(zero, (int, float)):
            raise Refusal("系数 %s 缺 ideal_mm / zero_mm，车辙换算式无法落地" % coef.key)
        if float(zero) <= float(ideal):
            raise Refusal("系数 %s 的 zero_mm(%s) 不大于 ideal_mm(%s)，换算方向不成立" % (coef.key, zero, ideal))
        return _clamp_scale(SCORE_SCALE * (float(zero) - value) / (float(zero) - float(ideal)))
    if component == COMPONENT_SKID:
        zero, ideal = params.get("zero_value"), params.get("ideal_value")
        if not isinstance(zero, (int, float)) or not isinstance(ideal, (int, float)):
            raise Refusal("系数 %s 缺 zero_value / ideal_value，抗滑换算式无法落地" % coef.key)
        if float(ideal) <= float(zero):
            raise Refusal("系数 %s 的 ideal_value(%s) 不大于 zero_value(%s)，换算方向不成立" % (coef.key, ideal, zero))
        return _clamp_scale(SCORE_SCALE * (value - float(zero)) / (float(ideal) - float(zero)))
    raise Refusal("未登记的分项 %s，不允许参与 PCI 合成" % component)


def _clamp_scale(score):
    # type: (float) -> float
    return max(SCORE_FLOOR, min(SCORE_SCALE, score))


def _check_indicator_domain(segment, component, value):
    # type: (Dict[str, object], str, float) -> None
    """实测值超出自身定义域 → 该行不可能是真值，扣分不可解释。"""
    column = COMPONENT_SOURCE_COLUMN[component]
    kind = segment.get("skid_indicator_kind") if column == "skid_indicator" else None
    domain = models.indicator_domain(column, kind)
    if domain is None:
        raise Refusal("检测列 %s 没有登记定义域，无法判取值是否可用" % column)
    low, high = domain
    if (low is not None and value < low) or (high is not None and value > high):
        raise Refusal(
            "%s = %s 超出该指标定义域 [%s, %s]，扣分不可解释" % (column, value, low, high)
        )
    if component == COMPONENT_SKID and str(segment.get("skid_indicator_kind") or "") not in models.SKID_INDICATOR_KINDS:
        raise Refusal("抗滑指标量纲 %r 未登记，换算式无从取值" % segment.get("skid_indicator_kind"))


# ---- 分级 ----


def grade_from_bands(pci, grade_coef):
    # type: (float, object) -> str
    params = grade_coef.values if isinstance(grade_coef.values, dict) else {}
    boundary = params.get("boundary")
    if boundary not in GRADE_BOUNDARIES:
        raise Refusal(
            "系数 %s 未登记分级边界开闭口径（boundary 应为 %s 之一）—— 含界与否要按原文确认，引擎不猜"
            % (grade_coef.key, "/".join(GRADE_BOUNDARIES))
        )
    bands = params.get("bands")
    if not isinstance(bands, list) or not bands:
        raise Refusal("系数 %s 的 bands 不是非空数组" % grade_coef.key)
    prepared = []  # type: List[Tuple[float, str]]
    for band in bands:
        if not isinstance(band, dict) or band.get("grade") in (None, ""):
            raise Refusal("系数 %s 的某个档位缺 grade 名" % grade_coef.key)
        lower = band.get("min")
        if not isinstance(lower, (int, float)) or isinstance(lower, bool):
            raise Refusal("系数 %s 的档位 %s 缺数值下界 min" % (grade_coef.key, band.get("grade")))
        prepared.append((float(lower), str(band["grade"])))
    lowers = [lower for lower, _name in prepared]
    if len(set(lowers)) != len(lowers):
        raise Refusal("系数 %s 的分级下界有重复值，档位无法唯一" % grade_coef.key)
    prepared.sort(key=lambda item: -item[0])
    for lower, name in prepared:
        satisfied = pci > lower if boundary == "lower_exclusive" else pci >= lower
        if satisfied:
            return name
    return prepared[-1][1]


# ---- 内核 ----


def compute_pci(segment, ruleset, blockers=()):
    # type: (Dict[str, object], object, Sequence[Tuple[str, str]]) -> res.PciResult
    """评定核：输入一段"路段 + 检测记录 + 破损行"（纯字典），输出 PciResult。

    `blockers` 是 M1 校验层对该对象的检出项（kind, detail）；非空即拒算 ——
    评定层不另起第二套判据，只用校验层的结论。
    """
    segment_id = str(segment.get("segment_id") or "")
    route_id = str(segment.get("route_id") or "")
    year = segment.get("year")
    surface_type = str(segment.get("surface_type") or "")

    def blocked(reason):
        # type: (str) -> res.PciResult
        result = res.PciResult(
            segment_id=segment_id,
            route_id=route_id,
            year=year,
            surface_type=surface_type,
            status=res.STATUS_BLOCKED,
            blocked_reason=reason,
            ruleset_id=ruleset.ruleset_id,
            ruleset_version=ruleset.version,
        )
        result.check_contract()
        return result

    required = surface_table_keys(surface_type)
    if not required:
        return blocked("路面类型 %r 不在评定路径里（首期只支持 %s）" % (surface_type, "/".join(sorted(DEDUCT_RATIO_KEY))))
    if not segment.get("has_survey", True):
        return blocked("该路段在该年度没有检测记录行，实测指标无从取值，未进入评定路径")
    if blockers:
        return blocked(
            "台账含 M1 检出项（%s）：%s —— 扣分不可解释，应先核实数据再评定"
            % (
                "、".join(kind for kind, _detail in blockers),
                "；".join(detail for _kind, detail in blockers),
            )
        )

    try:
        # 必需格一次查全：拒算原因要能说清"这一段的哪几格还进不了评定路径"，
        # 只报第一格会让用户改一格跑一次，核对队列无法收敛。
        coefficients = {}  # type: Dict[str, object]
        refusals = []  # type: List[str]
        for key in required:
            try:
                coefficients[key] = coefficient(ruleset, key)
            except Refusal as exc:
                refusals.append(exc.reason)
        if refusals:
            raise Refusal("；".join(refusals))
        ratio_coef = coefficients[DEDUCT_RATIO_KEY[surface_type]]
        weight_coef = coefficients[PCI_WEIGHT_KEY[surface_type]]
        grade_coef = coefficients[GRADE_THRESHOLD_KEY]

        deductions = _distress_deductions(segment, ratio_coef)
        distressed_total = sum(item["deducted_points"] for item in deductions)
        scores = {COMPONENT_DISTRESS: max(SCORE_FLOOR, SCORE_SCALE - distressed_total)}
        component_coefficients = {COMPONENT_DISTRESS: weight_coef}

        weights = weight_coef.values.get("weights") if isinstance(weight_coef.values, dict) else None
        if not isinstance(weights, dict):
            raise Refusal("系数 %s 的 values 缺 weights 映射，PCI 合成无从取值" % weight_coef.key)
        unknown = sorted(name for name in weights if name not in COMPONENT_NAMES)
        if unknown:
            raise Refusal("系数 %s 登记了未认定的分项 %s" % (weight_coef.key, ",".join(unknown)))

        excluded = []  # type: List[str]
        for component in (COMPONENT_RIDE, COMPONENT_RUTTING, COMPONENT_SKID):
            column = COMPONENT_SOURCE_COLUMN[component]
            raw = (segment.get("indicators") or {}).get(column)
            if raw is None:
                excluded.append("%s（缺测 %s）" % (component, column))
                continue
            if not isinstance(raw, (int, float)) or isinstance(raw, bool):
                raise Refusal("检测列 %s 的值不是数值（%r）" % (column, raw))
            coef = coefficients[COMPONENT_KEY[component]]
            _check_indicator_domain(segment, component, float(raw))
            scores[component] = _component_score(component, coef, float(raw))
            component_coefficients[component] = coef

        used = {}  # type: Dict[str, float]
        for component in COMPONENT_NAMES:
            if component not in scores:
                continue
            weight = weights.get(component)
            if not isinstance(weight, (int, float)) or isinstance(weight, bool):
                raise Refusal("系数 %s 未登记分项 %s 的权重" % (weight_coef.key, component))
            if float(weight) <= 0:
                raise Refusal("系数 %s 的分项 %s 权重为 %s，非正权重无法加权" % (weight_coef.key, component, weight))
            used[component] = float(weight)
        weight_total = sum(used.values())

        pci = sum(used[component] * scores[component] for component in used) / weight_total
        shortfall = SCORE_SCALE - pci
        contributions = []  # type: List[res.DeductContribution]
        for item in deductions:
            points = item["deducted_points"] * used[COMPONENT_DISTRESS] / weight_total
            contributions.append(
                res.DeductContribution(
                    source_kind="distress",
                    distress_type=item["distress_type"],
                    severity=item["severity"],
                    quantity=item["quantity"],
                    quantity_unit=item["quantity_unit"],
                    coefficient_key=item["coefficient_key"],
                    clause=item["clause"],
                    deducted_points=quantize(points),
                    share=_share(points, shortfall),
                    source_row_no=item["source_row_no"],
                )
            )
        for component in COMPONENT_NAMES:
            if component == COMPONENT_DISTRESS or component not in scores:
                continue
            points = (SCORE_SCALE - scores[component]) * used[component] / weight_total
            coef = component_coefficients[component]
            contributions.append(
                res.DeductContribution(
                    source_kind="measured_indicator",
                    distress_type=component,
                    severity="",
                    quantity=float((segment.get("indicators") or {}).get(COMPONENT_SOURCE_COLUMN[component])),
                    quantity_unit=COMPONENT_SOURCE_COLUMN[component],
                    coefficient_key=coef.key,
                    clause=clause_of(coef),
                    deducted_points=quantize(points),
                    share=_share(points, shortfall),
                    source_row_no=None,
                )
            )

        status = res.STATUS_PARTIAL if excluded else res.STATUS_OK
        scope_note = _scope_note(excluded) if excluded else ""
        result = res.PciResult(
            segment_id=segment_id,
            route_id=route_id,
            year=year,
            surface_type=surface_type,
            status=status,
            blocked_reason="",
            scope_note=scope_note,
            component_scores=dict(
                (name, quantize(scores[name])) for name in COMPONENT_NAMES if name in scores
            ),
            deducted_total=quantize(shortfall),
            pci=quantize(pci),
            grade=grade_from_bands(quantize(pci), grade_coef),
            contributions=contributions,
            ruleset_id=ruleset.ruleset_id,
            ruleset_version=ruleset.version,
        )
        result.check_contract()
        return result
    except Refusal as exc:
        return blocked(exc.reason)


def _share(points, shortfall):
    # type: (float, float) -> Optional[float]
    if shortfall <= 0:
        return 0.0
    return quantize(points / shortfall, SHARE_DECIMALS)


def _scope_note(excluded):
    # type: (Sequence[str]) -> str
    return "缺测分项不参与加权（%s），权重按其余分项归一，非全分项口径" % "、".join(excluded)


# ---- 台账通路（CLI / GUI / M4 汇总共用） ----


def load_segment_input(conn, segment_id, year):
    # type: (object, str, int) -> Optional[Dict[str, object]]
    """从台账拼出评定核要的字典输入；路段不在该年度时返回 None。"""
    segment = conn.execute(
        "SELECT * FROM segment WHERE segment_id = ? AND year = ?", (segment_id, year)
    ).fetchone()
    if segment is None:
        return None
    survey = conn.execute(
        "SELECT * FROM survey WHERE segment_id = ? AND year = ?", (segment_id, year)
    ).fetchone()
    rows = conn.execute(
        "SELECT distress_type, severity, quantity, quantity_unit, lane_no, source_row_no, row_id"
        " FROM distress WHERE segment_id = ? AND year = ? ORDER BY row_id",
        (segment_id, year),
    ).fetchall()
    indicators = {
        "rqi": None if survey is None else survey["rqi"],
        "rut_depth_mm": None if survey is None else survey["rut_depth_mm"],
        "skid_indicator": None if survey is None else survey["skid_indicator"],
    }
    return {
        "segment_id": segment_id,
        "route_id": segment["route_id"],
        "year": year,
        "surface_type": segment["surface_type"],
        "length_m": int(segment["end_stake_m"]) - int(segment["start_stake_m"]),
        "lane_count": segment["lane_count"],
        "segment_width_m": segment["segment_width_m"],
        "panel_count": segment["panel_count"],
        "skid_indicator_kind": "" if survey is None else survey["skid_indicator_kind"],
        "indicators": indicators,
        "distress_rows": [
            {
                "distress_type": row["distress_type"],
                "severity": row["severity"],
                "quantity": row["quantity"],
                "quantity_unit": row["quantity_unit"],
                "lane_no": row["lane_no"],
                "source_row_no": row["source_row_no"],
            }
            for row in rows
        ],
        "source_table": "%s/%s 年度检测记录" % (segment_id, year),
        "has_survey": survey is not None,
    }


def blocking_findings(conn, year):
    # type: (object, int) -> Dict[str, List[Tuple[str, str]]]
    """取该年度里"让扣分不可解释"的 M1 检出项，按路段分组（判定口径全在 checks 层）。"""
    from road_mqi_checker.ledger import checks

    grouped = {}  # type: Dict[str, List[Tuple[str, str]]]
    findings = []  # type: List[object]
    findings.extend(checks.check_distress_dictionary(conn, year))
    findings.extend(checks.check_unit_consistency(conn, year))
    findings.extend(checks.check_value_range(conn, year))
    findings.extend(checks.check_duplicate_import(conn))
    for finding in findings:
        if finding.verdict != checks.VERDICT_FOUND:
            continue
        if finding.kind not in BLOCKING_CHECK_KINDS:
            continue
        if not finding.segment_id:
            continue
        grouped.setdefault(finding.segment_id, []).append((finding.kind, finding.detail))
    for items in grouped.values():
        items.sort()
    return grouped


def compute_segment_pci(conn, segment_id, year, ruleset):
    # type: (object, str, int, object) -> res.PciResult
    """返回 PciResult：分项得分、合成得分、等级，以及可展开的扣分贡献清单。

    系数不全或台账对象含 M1 检出项时返回 blocked 的 PciResult（数值字段全空 + 拒算原因），不出数。
    """
    segment = load_segment_input(conn, segment_id, year)
    if segment is None:
        result = res.PciResult(
            segment_id=segment_id,
            route_id="",
            year=year,
            surface_type="",
            status=res.STATUS_BLOCKED,
            blocked_reason="台账里没有 %s 在 %s 年度的路段行，未进入评定路径" % (segment_id, year),
            ruleset_id=ruleset.ruleset_id,
            ruleset_version=ruleset.version,
        )
        result.check_contract()
        return result
    blockers = blocking_findings(conn, year).get(segment_id, [])
    return compute_pci(segment, ruleset, blockers)


def assess_year(conn, year, ruleset, segment_id=None):
    # type: (object, int, object, Optional[str]) -> List[res.PciResult]
    """评定该年度台账里的全部路段（或只评一个），按路段起点排序，输出可直接被 M4/M6 消费。"""
    from road_mqi_checker.errors import InputUnavailable

    clause = "WHERE year = ?"
    args = [year]  # type: List[object]
    if segment_id:
        clause += " AND segment_id = ?"
        args.append(segment_id)
    ids = [
        (row["segment_id"], row["route_id"])
        for row in conn.execute(
            "SELECT segment_id, route_id, start_stake_m FROM segment %s"
            " ORDER BY start_stake_m, segment_id" % clause,
            tuple(args),
        ).fetchall()
    ]
    if not ids:
        scope = "路段 %s 在 %s 年度" % (segment_id, year) if segment_id else "%s 年度" % year
        raise InputUnavailable("台账里%s没有路段行，未进入评定路径（先 rmqc import）" % scope)
    blockers_by_segment = blocking_findings(conn, year)
    results = []  # type: List[res.PciResult]
    for current_id, _route_id in ids:
        segment = load_segment_input(conn, current_id, year)
        results.append(compute_pci(segment, ruleset, blockers_by_segment.get(current_id, [])))
    return results


def result_payload(result):
    # type: (res.PciResult) -> Dict[str, object]
    """结果对象的对外结构（CLI --json、M4 汇总、M6 GUI 共用同一份，不另起第二套）。"""
    from road_mqi_checker.pci import trace

    return {
        "segment_id": result.segment_id,
        "route_id": result.route_id,
        "year": result.year,
        "surface_type": result.surface_type,
        "status": result.status,
        "blocked_reason": result.blocked_reason,
        "scope_note": result.scope_note,
        "pci": result.pci,
        "grade": result.grade,
        "deducted_total": result.deducted_total,
        "component_scores": dict(result.component_scores),
        "ruleset_id": result.ruleset_id,
        "ruleset_version": result.ruleset_version,
        "contributions": trace.expand_contributions(result),
    }


def find_result(results, segment_id, year):
    # type: (Sequence[res.PciResult], str, int) -> Optional[res.PciResult]
    """在评定结果清单里定位"该路段 × 该年度"的结果；没有即 None。

    下游（M4 汇总、年对比、对策）都靠它接同一条 `assess_year` 输出，**不现算、不另起取数通路**。
    """
    for result in results or []:
        if result.segment_id == segment_id and result.year == year:
            return result
    return None


def summarize_status(results):
    # type: (Sequence[res.PciResult]) -> Dict[str, int]
    counts = dict((status, 0) for status in res.ALL_RESULT_STATUSES)
    for result in results:
        counts[result.status] = counts.get(result.status, 0) + 1
    return counts
