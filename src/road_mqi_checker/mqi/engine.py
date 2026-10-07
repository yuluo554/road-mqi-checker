"""MQI 三级汇总与技术状况等级判定（模块 3，M4 交付）。

三级（路段 → 路线 → 路网）必须**共用同一套权重来源与同一个分母口径**，任何一级都不能
另起一套"平均分"。本模块的三条硬约束：

1. **权重与阈值一律来自规则集**：分项权重取 `mqi_weight.<分项>`，分级档位取
   `grade_threshold.mqi`；代码里不出现任何规范数字（`SCORE_SCALE` 那类结构常量除外，
   本模块连量程都不需要 —— 汇总的是已舍入的分项得分）。
2. **部分口径是红线**：首期只有路面分项有得分来源，其余三个分项没有数据。缺数据不等于 0 分，
   所以汇总值只能是"注明口径的部分指标值"，状态 `partial` + `scope_note` 逐一点名未纳入的
   分项与原因，并声明**不套用完整 MQI 的分级档位**（等级字段保持 None）。
3. **拒算对象不被平均**：某个路段的 PCI 因系数门 / 数据门 / 检出项门未出数时，它不进入任何
   一级的加权（既不按 0 也不按比例摊分），并在上级 `scope_note` 里点名；若一个成员都不剩，
   上级同样 `blocked`。

分母口径（M4 新定，见 `plan/02` §9 第 25 条）：路线级与路网级按**纳入汇总的路段长度**加权，
长度由台账桩号相减得到（整米），既不是路段条数也不是路线里程；被排除的 blocked 成员其长度
同时从分母里去掉，这一点必须写进 `scope_note`，否则"分母变小"会被读成"口径没变"。
"""

from typing import Dict, List, Optional, Sequence, Tuple

from road_mqi_checker import results as res
from road_mqi_checker.pci import engine as pci_engine

MODULE_KEY = "road_mqi_checker.mqi.engine"
MILESTONE = "M4"

#: 等级词汇（顺序即由好到差，来自题目 01 的分级表述；阈值数字一律待核对）
GRADE_LABELS = ("优", "良", "中", "次", "差")

#: 首期分项可用性：路面参与评定，其余以"未评定"进入汇总口径声明
COMPONENTS = ("pavement", "subgrade", "bridge_tunnel", "appurtenances")
ASSESSED_IN_PHASE_ONE = ("pavement",)
UNASSESSED_COMPONENTS = tuple(c for c in COMPONENTS if c not in ASSESSED_IN_PHASE_ONE)

AGGREGATION_LEVELS = ("segment", "route", "network")

#: 部分口径必须携带的声明文本前缀（报告与 GUI 共用，属既定口径）
PARTIAL_SCOPE_PREFIX = "部分口径（仅已评定分项）："

#: 分项 → 权重格；MQI 分级阈值格
COMPONENT_WEIGHT_KEY = dict((name, "mqi_weight." + name) for name in COMPONENTS)
GRADE_THRESHOLD_KEY = "grade_threshold.mqi"

#: 路网级汇总对象的标识（一个年度只有一个路网对象）
NETWORK_OBJECT_ID = "network"

#: 未评定分项在口径声明里的说法（只说"首期不评定"，不说"不重要"）
UNASSESSED_REASON_TEXT = "首期不评定（本题范围见 plan/01 非目标）"


def aggregation_required_keys(components=ASSESSED_IN_PHASE_ONE):
    # type: (Sequence[str]) -> Tuple[str, ...]
    """汇总路径必须生效的系数格：纳入分项的权重格 + MQI 分级阈值格。

    与 `bench.generator.TRUTH_GOVERNING_KEYS["mqi_partial_truth"]` 一一对账（有测试）：
    评定要用的格与真值敢出数的格必须是同一批，否则会出现"真值有数、汇总拒算"的假账。
    判据是"必需格是否全生效"，**不是**"本包生效了几格"（`plan/02` §9 第 23 条）。
    """
    keys = [COMPONENT_WEIGHT_KEY[name] for name in components]  # type: List[str]
    keys.append(GRADE_THRESHOLD_KEY)
    return tuple(keys)


# ---- 输入定位（不另起取数通路：PCI 一律来自 assess 的输出） ----


def find_pci(pci_results, segment_id, year):
    # type: (Sequence[res.PciResult], str, int) -> Optional[res.PciResult]
    """从 `pci.engine.assess_year` 的输出里取该路段该年度的结果（定位逻辑单点定义在 pci 侧）。"""
    return pci_engine.find_result(pci_results, segment_id, year)


def segment_rows(conn, year, route_id=None):
    # type: (object, int, Optional[str]) -> List[Tuple[str, str, int]]
    """台账里该年度的路段行：[(segment_id, route_id, length_m)]，按桩号与编号定序。

    长度 = `end_stake_m − start_stake_m`（整米），是加权分母的唯一来源。
    """
    clause = "WHERE year = ?"
    args = [year]  # type: List[object]
    if route_id:
        clause += " AND route_id = ?"
        args.append(route_id)
    return [
        (row["segment_id"], row["route_id"], int(row["end_stake_m"]) - int(row["start_stake_m"]))
        for row in conn.execute(
            "SELECT segment_id, route_id, start_stake_m, end_stake_m FROM segment %s"
            " ORDER BY start_stake_m, segment_id" % clause,
            tuple(args),
        ).fetchall()
    ]


def route_ids_in_year(conn, year):
    # type: (object, int) -> List[str]
    """该年度台账里出现过的路段所属路线（按首段桩号定序，不依赖 SQLite 返回顺序）。"""
    return [
        row["route_id"]
        for row in conn.execute(
            "SELECT route_id, MIN(start_stake_m) AS first_stake FROM segment WHERE year = ?"
            " GROUP BY route_id ORDER BY first_stake, route_id",
            (year,),
        ).fetchall()
    ]


# ---- 系数门 ----


def _require_cells(ruleset, keys):
    # type: (object, Sequence[str]) -> Dict[str, object]
    """必需格一次查全：只报第一格会让用户改一格跑一次，核对队列无法收敛（与 M2 同口径）。"""
    found = {}  # type: Dict[str, object]
    refusals = []  # type: List[str]
    for key in keys:
        try:
            found[key] = pci_engine.coefficient(ruleset, key)
        except pci_engine.Refusal as exc:
            refusals.append(str(exc))
    if refusals:
        raise pci_engine.Refusal("；".join(refusals))
    return found


# ---- 结果构造 ----


def _blocked(reason, level, object_id, year, ruleset):
    # type: (str, str, str, int, object) -> res.MqiResult
    result = res.MqiResult(
        level=level,
        object_id=object_id,
        year=year,
        status=res.STATUS_BLOCKED,
        blocked_reason=reason,
        ruleset_id=ruleset.ruleset_id,
        ruleset_version=ruleset.version,
    )
    result.check_contract()
    return result


def _excluded_text(components, ruleset):
    # type: (Sequence[str], object) -> str
    """未纳入分项逐一点名 + 原因（口径声明的正文，不得只写"部分口径"四个字）。"""
    parts = []  # type: List[str]
    for name in components:
        coef = ruleset.find(COMPONENT_WEIGHT_KEY[name])
        if coef is None:
            reason = "权重格 %s 未登记" % COMPONENT_WEIGHT_KEY[name]
        elif not coef.computable:
            reason = "权重格 %s 核对状态 %s" % (coef.key, coef.effective_status)
        elif name in UNASSESSED_COMPONENTS:
            reason = UNASSESSED_REASON_TEXT
        else:
            reason = "该分项本年度没有可用得分"
        parts.append("%s（%s）" % (name, reason))
    return "、".join(parts)


def assign_grade(value, threshold_key, ruleset):
    # type: (Optional[float], str, object) -> Tuple[Optional[str], str]
    """按规则集登记的档位与含界口径查档；阈值未核对则不出等级。

    返回 `(等级, 拒算原因)`：成功时原因为空串。等级字段只能来自规则集那一格
    （`grade_threshold.mqi` / `grade_threshold.pci` 同一套档位契约，实现在
    `pci.engine.grade_from_bands`，本模块不复制第二套），含界与否由 `boundary` 说，
    引擎不猜；未核对时等级为 None，绝不"猜一档"。
    """
    if value is None:
        return None, "汇总值未出数，无从查档"
    try:
        coef = pci_engine.coefficient(ruleset, threshold_key)
    except pci_engine.Refusal as exc:
        return None, str(exc)
    try:
        return pci_engine.grade_from_bands(value, coef), ""
    except pci_engine.Refusal as exc:
        return None, str(exc)


# ---- 路段级 ----


def aggregate_segment_mqi(conn, segment_id, year, pci_results, ruleset, extra_component_scores=None):
    # type: (object, str, int, Sequence[res.PciResult], object, Optional[Dict[str, float]]) -> res.MqiResult
    """路段级 MQI：把该路段已有的分项得分按 `mqi_weight.*` 加权。

    `extra_component_scores` 是**调用方给的**其他分项得分（首期台账里没有这类数据，故默认不给）。
    有它才能走通"完整 MQI + 分级"那条通路 —— 引擎绝不缺数据补 0，也绝不按比例摊分。
    """
    pci_result = find_pci(pci_results, segment_id, year)
    if pci_result is None:
        return _blocked(
            "该路段在 %s 年度没有 PCI 评定结果（未进入评定路径），路段级 MQI 无从合成" % year,
            "segment",
            segment_id,
            year,
            ruleset,
        )
    if pci_result.pci is None:
        return _blocked(
            "该路段 PCI 未出数（%s：%s），MQI 不把它当 0 分参与加权" % (pci_result.status, pci_result.blocked_reason),
            "segment",
            segment_id,
            year,
            ruleset,
        )

    scores = {"pavement": pci_result.pci}  # type: Dict[str, float]
    for name, value in (extra_component_scores or {}).items():
        if name not in COMPONENTS:
            return _blocked(
                "外部提供的分项 %r 不在分项词汇 %s 里，汇总拒绝未知分项" % (name, "/".join(COMPONENTS)),
                "segment",
                segment_id,
                year,
                ruleset,
            )
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return _blocked(
                "分项 %s 提供的得分不是数值（%r）" % (name, value),
                "segment",
                segment_id,
                year,
                ruleset,
            )
        scores[name] = float(value)

    included = [name for name in COMPONENTS if name in scores]
    excluded = [name for name in COMPONENTS if name not in scores]
    lengths = None  # type: Optional[List[int]]
    if conn is not None:
        for current_id, _route_id, length_m in segment_rows(conn, year):
            if current_id == segment_id:
                lengths = [length_m]
                break
        if lengths is None:
            return _blocked(
                "台账里没有 %s 在 %s 年度的路段行，加权分母（路段长度）无从取值" % (segment_id, year),
                "segment",
                segment_id,
                year,
                ruleset,
            )

    try:
        cells = _require_cells(ruleset, aggregation_required_keys(included))
        weights = {}  # type: Dict[str, float]
        for name in included:
            coef = cells[COMPONENT_WEIGHT_KEY[name]]
            raw = coef.values.get("weight") if isinstance(coef.values, dict) else None
            if not isinstance(raw, (int, float)) or isinstance(raw, bool) or float(raw) <= 0:
                raise pci_engine.Refusal(
                    "系数 %s 的 weight 必须是正数值（实际 %r），非正权重无法加权" % (COMPONENT_WEIGHT_KEY[name], raw)
                )
            weights[name] = float(raw)
    except pci_engine.Refusal as exc:
        return _blocked(str(exc), "segment", segment_id, year, ruleset)

    weight_total = sum(weights[name] for name in included)
    value = sum(weights[name] * scores[name] for name in included) / weight_total
    grade, grade_refusal = assign_grade(pci_engine.quantize(value), GRADE_THRESHOLD_KEY, ruleset)

    status = res.STATUS_OK if not excluded else res.STATUS_PARTIAL
    scope_note = ""
    if excluded:
        scope_note = (
            "%s未纳入汇总的分项：%s。本值只是已评定分项的加权值，不是完整 MQI；"
            "权重按纳入分项归一，等级字段不套用完整 MQI 的分级档位。"
            % (PARTIAL_SCOPE_PREFIX, _excluded_text(excluded, ruleset))
        )
    elif grade_refusal:
        status = res.STATUS_PARTIAL
        scope_note = "%s等级判定未生效：%s" % (PARTIAL_SCOPE_PREFIX, grade_refusal)

    result = res.MqiResult(
        level="segment",
        object_id=segment_id,
        year=year,
        status=status,
        scope_note=scope_note,
        mqi=pci_engine.quantize(value),
        grade=grade if status == res.STATUS_OK else None,
        component_scores=dict((name, scores[name]) for name in included),
        included_components=list(included),
        excluded_components=list(excluded),
        weighted_length_m=float(sum(lengths)) if lengths else None,
        ruleset_id=ruleset.ruleset_id,
        ruleset_version=ruleset.version,
    )
    result.check_contract()
    return result


# ---- 路线级与路网级 ----


def _combine_members(members, ruleset, level, object_id, year):
    # type: (Sequence[Tuple[str, res.MqiResult, int]], object, str, str, int) -> res.MqiResult
    """成员 → 上级：只把"已出数"的成员按路段长度加权，blocked 成员点名排除，不摊分。

    `members` 是 [(segment_id, 路段级结果, 路段长度)]，顺序即台账桩号顺序。
    """
    usable = [item for item in members if item[1].mqi is not None]
    refused = [item for item in members if item[1].mqi is None]
    if not usable:
        reasons = sorted(set("%s：%s" % (segment_id, result.blocked_reason) for segment_id, result, _l in refused))
        return _blocked(
            "该%s的全部成员都未出数，不做任何平均：%s"
            % ("路线" if level == "route" else "路网", "；".join(reasons)),
            level,
            object_id,
            year,
            ruleset,
        )

    total_length = sum(length for _id, _result, length in usable)
    if total_length <= 0:
        return _blocked(
            "纳入汇总的路段长度和为 %s，分母不成立（桩号账要能撑起加权）" % total_length,
            level,
            object_id,
            year,
            ruleset,
        )

    value = sum(result.mqi * length for _id, result, length in usable) / total_length
    included = sorted(set(name for _id, result, _length in usable for name in result.included_components))
    excluded = sorted(set(name for _id, result, _length in usable for name in result.excluded_components))
    status = res.STATUS_OK if usable and not excluded and not refused else res.STATUS_PARTIAL

    notes = []  # type: List[str]
    if excluded:
        notes.append("未纳入汇总的分项：%s" % _excluded_text(sorted(excluded), ruleset))
    if refused:
        notes.append(
            "未出数成员已从加权与分母中排除（不按 0 计、不按比例摊分）：%s"
            % "、".join("%s(%d m)：%s" % (segment_id, length, result.blocked_reason)
                        for segment_id, result, length in sorted(refused))
        )
    partial_members = [result for _id, result, _length in usable if result.status == res.STATUS_PARTIAL]
    if partial_members:
        notes.append("成员自身即为部分口径（%d 个）" % len(partial_members))
    scope_note = ""
    if status == res.STATUS_PARTIAL:
        scope_note = "%s%s。本值按纳入汇总的路段长度（%d m）加权，不是完整 MQI，等级不套用完整 MQI 的分级档位。" % (
            PARTIAL_SCOPE_PREFIX,
            "；".join(notes),
            total_length,
        )

    grade, grade_refusal = assign_grade(pci_engine.quantize(value), GRADE_THRESHOLD_KEY, ruleset)
    if grade_refusal:
        return _blocked(grade_refusal, level, object_id, year, ruleset)

    # 分项层面的上级视图：同一批成员、同一分母，逐分项加权（分项缺员的不参与，也不补值）
    component_values = {}  # type: Dict[str, float]
    for name in included:
        holders = [(result.component_scores[name], length) for _id, result, length in usable if name in result.component_scores]
        if len(holders) == len(usable) and sum(length for _v, length in holders) > 0:
            component_values[name] = sum(v * length for v, length in holders) / sum(length for v, length in holders)

    result = res.MqiResult(
        level=level,
        object_id=object_id,
        year=year,
        status=status,
        scope_note=scope_note,
        mqi=pci_engine.quantize(value),
        grade=grade if status == res.STATUS_OK else None,
        component_scores=dict((name, pci_engine.quantize(component_values[name])) for name in sorted(component_values)),
        included_components=included,
        excluded_components=sorted(excluded),
        weighted_length_m=float(total_length),
        ruleset_id=ruleset.ruleset_id,
        ruleset_version=ruleset.version,
    )
    result.check_contract()
    return result


def aggregate_route_mqi(conn, route_id, year, pci_results, ruleset):
    # type: (object, str, int, Sequence[res.PciResult], object) -> res.MqiResult
    """路线级：该路线全部路段的路段级 MQI 按路段长度加权（分母 = 纳入成员的长度和）。"""
    if conn is None:
        return _blocked("路线级汇总需要台账（路段长度是分母），未提供连接", "route", route_id, year, ruleset)
    members = []  # type: List[Tuple[str, res.MqiResult, int]]
    for segment_id, current_route, length_m in segment_rows(conn, year, route_id=route_id):
        if current_route != route_id:
            continue
        members.append((segment_id, aggregate_segment_mqi(None, segment_id, year, pci_results, ruleset), length_m))
    if not members:
        return _blocked(
            "台账里没有路线 %s 在 %s 年度的路段行，未进入汇总路径" % (route_id, year),
            "route",
            route_id,
            year,
            ruleset,
        )
    return _combine_members(members, ruleset, "route", route_id, year)


def aggregate_network_mqi(conn, year, pci_results, ruleset):
    # type: (object, int, Sequence[res.PciResult], object) -> res.MqiResult
    """路网级：该年度全部路段按路段长度加权（与路线级同一分母口径，因此三级可互相复算）。"""
    if conn is None:
        return _blocked("路网级汇总需要台账（路段长度是分母），未提供连接", "network", NETWORK_OBJECT_ID, year, ruleset)
    members = [
        (segment_id, aggregate_segment_mqi(None, segment_id, year, pci_results, ruleset), length_m)
        for segment_id, _route_id, length_m in segment_rows(conn, year)
    ]
    if not members:
        return _blocked(
            "台账里没有 %s 年度的路段行，未进入汇总路径（先 rmqc import）" % year,
            "network",
            NETWORK_OBJECT_ID,
            year,
            ruleset,
        )
    return _combine_members(members, ruleset, "network", NETWORK_OBJECT_ID, year)


def aggregate_year(conn, year, pci_results, ruleset, level="route"):
    # type: (object, int, Sequence[res.PciResult], object, str) -> List[res.MqiResult]
    """命令面用的批量入口：一次出该年度该级别的全部汇总对象（级别词汇见 `AGGREGATION_LEVELS`）。"""
    if level == "segment":
        return [
            aggregate_segment_mqi(conn, segment_id, year, pci_results, ruleset)
            for segment_id, _route_id, _length in segment_rows(conn, year)
        ]
    if level == "route":
        return [aggregate_route_mqi(conn, route_id, year, pci_results, ruleset) for route_id in route_ids_in_year(conn, year)]
    if level == "network":
        return [aggregate_network_mqi(conn, year, pci_results, ruleset)]
    raise ValueError("未知汇总级别 %r，合法值 %s" % (level, "/".join(AGGREGATION_LEVELS)))


def summarize_status(results):
    # type: (Sequence[res.MqiResult]) -> Dict[str, int]
    counts = dict((status, 0) for status in res.ALL_RESULT_STATUSES)
    for result in results:
        counts[result.status] = counts.get(result.status, 0) + 1
    return counts


def result_payload(result):
    # type: (res.MqiResult) -> Dict[str, object]
    """汇总结果的对外结构（CLI `--json`、M6 报告与 GUI 共用，不另起第二套）。"""
    return {
        "level": result.level,
        "object_id": result.object_id,
        "year": result.year,
        "status": result.status,
        "blocked_reason": result.blocked_reason,
        "scope_note": result.scope_note,
        "mqi": result.mqi,
        "grade": result.grade,
        "component_scores": dict(result.component_scores),
        "included_components": list(result.included_components),
        "excluded_components": list(result.excluded_components),
        "weighted_length_m": result.weighted_length_m,
        "ruleset_id": result.ruleset_id,
        "ruleset_version": result.ruleset_version,
        "grade_threshold_key": GRADE_THRESHOLD_KEY,
        "weight_keys": [COMPONENT_WEIGHT_KEY[name] for name in result.included_components],
    }
