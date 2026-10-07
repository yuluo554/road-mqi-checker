"""养护对策规则链与优先序排序（模块 4 的规则侧，M4 交付）。

规则形态固定为：IF 条件（指标 + 阈值 + 比较符）→ THEN 建议工程类别与规模档，
每条必须挂条款号或"用户自定"来源。排序键可配置但必须确定：
同分时的次级键是固定字段序列，禁止随机、禁止依赖 set/dict 迭代顺序。

三条落地纪律：

1. **阈值与类别词汇全来自规则集那一格**（`action_rule.maintenance_trigger`）：本模块代码里
   不出现任何阈值数字，也不硬编码"小修/中修/大修"这类工程类别词汇 —— 那些是 THEN 侧的
   登记内容，未核对就一律不出结论。
2. **上位规范号未被查证前不引用**：`data/README.md` §一 第 4 行记着"公路养护技术标准 /
   JTG 5142-2019"的编号-名称对应关系查证失败。因此内置包该格保持 pending（不出数），
   而对策结论的出处一律取该格 `basis` 里登记的 `standard_id + clause`，代码不拼任何规范号。
3. **拒算对象也要出现在清单上**：`suggest_actions` 对每个进入评定路径的对象出一条记录，
   系数未核对 / 指标未出数 / 条件均未触发都各自是 `blocked` 并写明原因，不是"从清单里删掉"。
   未触发是"本次没有对策结论"，与"规则集没生效"是两件事，原因文本必须能区分。
"""

from typing import Dict, List, Optional, Sequence, Tuple

from road_mqi_checker import results as res
from road_mqi_checker.pci import engine as pci_engine

MODULE_KEY = "road_mqi_checker.strategy.rules"
MILESTONE = "M4"

#: 条件比较符（规则 JSON 里的 op 字段合法值）
CONDITION_OPS = ("lt", "le", "gt", "ge", "between")

#: 同分次级键的固定顺序（既定口径：改了会让优先序表整体漂移）
TIE_BREAK_KEYS = ("route_id", "start_stake_m", "segment_id")

#: 建议类别词汇表：由规则 THEN 侧给出，具体取值待 M3 条款核对后定
ACTION_FIELDS = ("rule_id", "clause", "condition_text", "action_class", "scale_band", "triggered_by")

#: 对策规则格与可判定的指标词汇（首期只有路面 PCI 与部分口径 MQI）
ACTION_RULE_KEY = "action_rule.maintenance_trigger"
ACTION_METRICS = ("pci", "mqi_partial")

#: `rank_priority` 允许的主键（次级键固定为 TIE_BREAK_KEYS，不接受配置）
RANK_PRIMARY_KEYS = ("pci", "mqi_partial", "scale_band_value")

_OP_TEXT = {"lt": "<", "le": "≤", "gt": ">", "ge": "≥", "between": "介于"}


def action_required_keys():
    # type: () -> Tuple[str, ...]
    """对策路径必需格：与 `generator.TRUTH_GOVERNING_KEYS["recommended_action_truth"]` 对账。"""
    return (ACTION_RULE_KEY,)


def _number(value):
    # type: (object) -> Optional[float]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def condition_text(rule):
    # type: (Dict[str, object]) -> str
    """条件的人类可读文本（同一格规则两次生成的文本逐字一致）。"""
    metric = str(rule["metric"])
    op = str(rule["op"])
    if op == "between":
        bounds = rule["threshold"]
        return "%s %s %s 与 %s 之间" % (metric, op, bounds["lo"], bounds["hi"])
    return "%s %s %s" % (metric, _OP_TEXT[op], _trimmed(rule["threshold"]))


def _trimmed(value):
    # type: (object) -> str
    text = "%.1f" % float(value)
    return text.rstrip("0").rstrip(".") if "." in text else text


def declared_rules(coef):
    # type: (object) -> List[Dict[str, object]]
    """把规则格的 values 展开成规则清单，同时把不成立的登记挡在门外。

    契约（写进 `plan/05`）：`values.rules` = 数组，每条含
    `rule_id` / `metric` / `op` / `threshold` / `action_class` / `scale_band`，
    可选 `scale_band_value`。`op=between` 时 `threshold` 是 `{"lo":…,"hi":…}`。
    """
    values = coef.values if isinstance(coef.values, dict) else None
    rules = (values or {}).get("rules")
    if not isinstance(rules, list) or not rules:
        raise pci_engine.Refusal(
            "系数 %s 的 values 缺非空数组 rules（对策规则链无从展开），应核实原文后按形态登记" % coef.key
        )
    seen = set()
    prepared = []  # type: List[Dict[str, object]]
    for index, rule in enumerate(rules):
        where = "系数 %s 的第 %d 条规则" % (coef.key, index + 1)
        if not isinstance(rule, dict):
            raise pci_engine.Refusal("%s 不是对象" % where)
        for field in ("rule_id", "metric", "op", "threshold", "action_class", "scale_band"):
            if field == "threshold":
                if rule.get(field) is None:
                    raise pci_engine.Refusal("%s 缺 threshold" % where)
            elif not isinstance(rule.get(field), str) or not rule.get(field).strip():
                raise pci_engine.Refusal("%s 缺 %s（无出处的结论不得确定表述）" % (where, field))
        rule_id = str(rule["rule_id"])
        if rule_id in seen:
            raise pci_engine.Refusal("%s 的 rule_id %s 与前面重复，优先序无法确定" % (where, rule_id))
        seen.add(rule_id)
        if str(rule["metric"]) not in ACTION_METRICS:
            raise pci_engine.Refusal("%s 的指标 %r 不在 %s 里" % (where, rule["metric"], "/".join(ACTION_METRICS)))
        op = str(rule["op"])
        if op not in CONDITION_OPS:
            raise pci_engine.Refusal("%s 的比较符 %r 非法，合法值 %s" % (where, op, "/".join(CONDITION_OPS)))
        if op == "between":
            bounds = rule["threshold"]
            if not isinstance(bounds, dict):
                raise pci_engine.Refusal("%s 的 between 阈值要是 {lo, hi} 对象" % where)
            lo, hi = _number(bounds.get("lo")), _number(bounds.get("hi"))
            if lo is None or hi is None or hi <= lo:
                raise pci_engine.Refusal("%s 的 between 阈值不成立（要 hi > lo，实际 %r～%r）" % (where, bounds.get("lo"), bounds.get("hi")))
            normalized = dict(rule)
            normalized["threshold"] = {"lo": lo, "hi": hi}
            prepared.append(normalized)
            continue
        threshold = _number(rule["threshold"])
        if threshold is None:
            raise pci_engine.Refusal("%s 的 threshold 不是数值（%r）" % (where, rule["threshold"]))
        normalized = dict(rule)
        normalized["threshold"] = threshold
        prepared.append(normalized)
    return prepared


def _matched(rule, metric, value):
    # type: (Dict[str, object], str, float) -> bool
    if rule["op"] == "between":
        return rule["threshold"]["lo"] <= value <= rule["threshold"]["hi"]
    if rule["op"] == "lt":
        return value < rule["threshold"]
    if rule["op"] == "le":
        return value <= rule["threshold"]
    if rule["op"] == "gt":
        return value > rule["threshold"]
    return value >= rule["threshold"]


def _metrics(pci_result, mqi_result):
    # type: (res.PciResult, Optional[res.MqiResult]) -> Dict[str, Optional[float]]
    return {"pci": pci_result.pci, "mqi_partial": mqi_result.mqi if mqi_result is not None else None}


def _context(conn, segment_id, year):
    # type: (object, str, int) -> Optional[int]
    """路段起点桩号：排序次级键要它。台账不可用（内存真值通路）时返回 None。"""
    if conn is None:
        return None
    row = conn.execute(
        "SELECT start_stake_m FROM segment WHERE segment_id = ? AND year = ?", (segment_id, year)
    ).fetchone()
    return int(row["start_stake_m"]) if row else None


def suggest_actions(conn, year, pci_results, mqi_results, ruleset):
    # type: (object, int, Sequence[res.PciResult], Sequence[res.MqiResult], object) -> List[res.ActionSuggestion]
    """逐路段给出养护需求判定清单（blocked 项也要出现在清单上，标注拒算原因）。

    规则按登记顺序逐条判定，**第一条命中即定案**（命中顺序由规则集声明，不由数据决定）；
    判定所需的指标未出数时整段拒算 —— 不能因为"后面那条规则没法判"就假装前面已定案。
    """
    mqi_by_segment = {}  # type: Dict[Tuple[str, int], res.MqiResult]
    for result in mqi_results or []:
        mqi_by_segment[(result.object_id, result.year)] = result

    reasons = []  # type: List[str]
    coef = ruleset.find(ACTION_RULE_KEY)
    rules = []  # type: List[Dict[str, object]]
    if coef is None:
        reasons.append("规则集 %s 未登记系数 %s，应核实原文后补入" % (ruleset.ruleset_id, ACTION_RULE_KEY))
    elif not coef.computable:
        reasons.append(coef.block_reason())
    else:
        clause = pci_engine.clause_of(coef)
        if not clause:
            reasons.append("系数 %s 可算但未登记条款号，对策结论无出处" % coef.key)
        else:
            try:
                rules = declared_rules(coef)
            except pci_engine.Refusal as exc:
                reasons.append(str(exc))

    out = []  # type: List[res.ActionSuggestion]
    for pci_result in pci_results or []:
        if pci_result.year != year:
            continue
        segment_id = pci_result.segment_id
        mqi_result = mqi_by_segment.get((segment_id, year))
        start_stake_m = _context(conn, segment_id, year)
        common = {
            "segment_id": segment_id,
            "route_id": pci_result.route_id,
            "year": year,
            "start_stake_m": start_stake_m,
            "pci": pci_result.pci,
            "mqi_partial": mqi_result.mqi if mqi_result is not None else None,
        }

        def refused(reason):
            # type: (str) -> res.ActionSuggestion
            suggestion = res.ActionSuggestion(
                status=res.STATUS_BLOCKED, blocked_reason=reason, rank_key="", **common
            )
            suggestion.check_contract()
            out.append(suggestion)
            return suggestion

        if reasons:
            refused("；".join(reasons))
            continue
        if pci_result.pci is None:
            refused(
                "该路段 PCI 未出数（%s：%s），对策规则链无从判定" % (pci_result.status, pci_result.blocked_reason)
            )
            continue

        metrics = _metrics(pci_result, mqi_result)
        hit = None  # type: Optional[Dict[str, object]]
        missing_metric = None  # type: Optional[Tuple[str, str]]
        for rule in rules:
            metric = str(rule["metric"])
            if metrics.get(metric) is None:
                missing_metric = (
                    metric,
                    "规则 %s 的条件要读 %s，但该对象的 %s 未出数（路段级 MQI 未生效或该分项未评定）"
                    % (rule["rule_id"], metric, metric),
                )
                break
            if _matched(rule, metric, metrics[metric]):
                hit = rule
                break
        if missing_metric is not None:
            refused(missing_metric[1])
            continue
        if hit is None:
            refused(
                "该对象在规则集 %s 登记的 %d 条触发条件下均未触发（%s），本次无对策结论"
                % (
                    ruleset.ruleset_id,
                    len(rules),
                    "、".join("%s=%s" % (name, value) for name, value in sorted(metrics.items()) if value is not None),
                )
            )
            continue

        scale_band_value = _number(hit.get("scale_band_value"))
        suggestion = res.ActionSuggestion(
            status=res.STATUS_OK,
            rule_id=str(hit["rule_id"]),
            clause=pci_engine.clause_of(coef),
            condition_text=condition_text(hit),
            action_class=str(hit["action_class"]),
            scale_band=str(hit["scale_band"]),
            scale_band_value=scale_band_value,
            triggered_by="%s=%s 命中规则 %s 的条件「%s」"
            % (hit["metric"], _trimmed(metrics[str(hit["metric"])]), hit["rule_id"], condition_text(hit)),
            rank_key="",
            **common
        )
        suggestion.rank_key = "primary=pci↑|tie=%s" % "/".join(TIE_BREAK_KEYS)
        suggestion.check_contract()
        out.append(suggestion)
    return out


def rank_order_key(suggestion, primary_key):
    # type: (res.ActionSuggestion, str) -> tuple
    """排序键：主键（空值排后）→ `TIE_BREAK_KEYS` 逐字段升序，固定字段序列，不看迭代顺序。"""
    return (
        _null_last(getattr(suggestion, primary_key)),
        str(suggestion.route_id),
        _null_last(suggestion.start_stake_m),
        str(suggestion.segment_id),
    )


def _null_last(value):
    # type: (Optional[float]) -> tuple
    if value is None:
        return (1, 0.0)
    return (0, float(value))


def _flip_primary(scalar):
    # type: (tuple) -> tuple
    """只把主键方向翻过来；次级键永远正序（既定口径），空值仍排最后。"""
    kind, value = scalar
    if kind == 1:
        return (1, 0.0)
    return (0, -value)


def rank_priority(suggestions, primary_key="pci", ascending=True):
    # type: (Sequence[res.ActionSuggestion], str, bool) -> List[res.ActionSuggestion]
    """按可配置主键排序，同分用 `TIE_BREAK_KEYS` 固定次级键，保证确定性。

    未出数（主键为空）的对象一律排在最后，且它们之间仍按次级键定序 —— 不允许依赖
    "blocked 项原本在第几位"。本函数不改动入参顺序。
    """
    if primary_key not in RANK_PRIMARY_KEYS:
        raise ValueError(
            "主键 %r 不在可排序字段 %s 里（改动会让优先序表整体漂移，见 plan/02 §9）"
            % (primary_key, "/".join(RANK_PRIMARY_KEYS))
        )
    rows = []  # type: List[tuple]
    for suggestion in suggestions or []:
        primary, route_id, start_stake, segment_id = rank_order_key(suggestion, primary_key)
        if not ascending:
            primary = _flip_primary(primary)
        rows.append((primary, route_id, start_stake, segment_id, suggestion))
    rows.sort(key=lambda row: row[:4])
    return [row[4] for row in rows]


def result_payload(suggestion):
    # type: (res.ActionSuggestion) -> Dict[str, object]
    """对策清单的对外结构（CLI `--json` 与 M6 优先序导出共用同一份字段口径）。"""
    return {
        "segment_id": suggestion.segment_id,
        "route_id": suggestion.route_id,
        "year": suggestion.year,
        "start_stake_m": suggestion.start_stake_m,
        "status": suggestion.status,
        "blocked_reason": suggestion.blocked_reason,
        "scope_note": suggestion.scope_note,
        "pci": suggestion.pci,
        "mqi_partial": suggestion.mqi_partial,
        "rule_id": suggestion.rule_id,
        "clause": suggestion.clause,
        "condition_text": suggestion.condition_text,
        "action_class": suggestion.action_class,
        "scale_band": suggestion.scale_band,
        "scale_band_value": suggestion.scale_band_value,
        "triggered_by": suggestion.triggered_by,
        "rank_key": suggestion.rank_key,
        "coefficient_key": ACTION_RULE_KEY,
    }
