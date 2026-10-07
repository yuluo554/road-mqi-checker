"""年对比与变化贡献（模块 4 的对比侧，M4 交付）。

三段式回答：评分变了多少 → 是不是可比 → 变化由哪个指标的哪一次变化贡献。
不可比时只出 uncomparable 与原因，绝不出变化率（题目纪律）。

四条落地纪律：

1. **不可比要拒变化率，不要摊分**：跨年划分变更（`partition_change` 表）是不比的基础设施，
   只要该路段在两个年度之间发生过 新增/消失/合并/拆分/位移，本模块就出 `uncomparable` +
   原因代码，数值字段全空。绝不"按重叠里程折算一个变化率"——那是把账做糊。
2. **口径不同也不比**：两年 PCI 参与加权的分项集合不同（例如一年车辙缺测）时，两个分数不
   在同一个分母上，差值没有意义 → `uncomparable`（原因代码 `component_scope_mismatch`）。
   路面类型跨年改变同理（两套扣分表不同）。
3. **规则集版本换了要记为不可比**：两个结果来自不同 `ruleset_id/version` ⇒ `rule_version_change`。
   至于"同一包内某格系数年中被改动"（`coefficient_change`）：台账没有逐年登记规则集版本的表，
   单文件规则包本身也不可变，所以这一档**目前只能靠换包版本来表达**，代码不做无依据的断言。
4. **变化必须能拆到贡献项**：`explain_change` 把差值拆成"某类某程度的破损（或某个实测指标）
   扣分的增减"，每条仍挂系数 key + 条款号 + 台账行号 —— 与 M2 的贡献展开同一套可追溯要求。
"""

from typing import Dict, List, Optional, Sequence, Tuple

from road_mqi_checker import results as res
from road_mqi_checker.errors import InputUnavailable
from road_mqi_checker.pci import engine as pci_engine
from road_mqi_checker.pci import trace as pci_trace

MODULE_KEY = "road_mqi_checker.strategy.compare"
MILESTONE = "M4"

#: 不可比原因代码（与 ledger.db.CHANGE_KINDS 对应，属既定口径；
#: 后两档是 M4 新增：口径不一致与路面类型改变，见模块开头纪律 2）
UNCOMPARABLE_REASONS = (
    "partition_new",
    "partition_disappeared",
    "partition_merged",
    "partition_split",
    "partition_shifted",
    "coefficient_change",
    "rule_version_change",
    "component_scope_mismatch",
)

#: 划分变更类别 → 不可比原因代码（`unchanged` 不在表里：那是可比的前提）
CHANGE_KIND_TO_REASON = {
    "new": "partition_new",
    "disappeared": "partition_disappeared",
    "merged": "partition_merged",
    "split": "partition_split",
    "shifted": "partition_shifted",
}

COMPARE_COLUMNS = (
    "segment_id",
    "route_id",
    "year_from",
    "year_to",
    "status",
    "delta",
    "deterioration_rate_per_year",
    "grade_from",
    "grade_to",
    "comparability_reason",
    "top_contributors",
)

#: 变化贡献项的展示上限（全部差值仍参与排序，只是对外清单默认截断）
TOP_CONTRIBUTOR_LIMIT = 3


def _extent(conn, segment_id, year):
    # type: (object, str, int) -> Optional[Tuple[int, int]]
    if conn is None:
        return None
    row = conn.execute(
        "SELECT start_stake_m, end_stake_m, route_id FROM segment WHERE segment_id = ? AND year = ?",
        (segment_id, year),
    ).fetchone()
    return None if row is None else (int(row["start_stake_m"]), int(row["end_stake_m"]))


def _overlap_m(extent_from, extent_to):
    # type: (Optional[Tuple[int, int]], Optional[Tuple[int, int]]) -> Optional[float]
    if extent_from is None or extent_to is None:
        return None
    return float(max(0, min(extent_from[1], extent_to[1]) - max(extent_from[0], extent_to[0])))


def _change_rows(conn, route_id, segment_id, year_from, year_to):
    # type: (object, str, str, int, int) -> List[str]
    """该路段在这两个年度之间的划分变更类别（查询顺序无关：两个方向的年序都查）。"""
    if conn is None or not route_id:
        return []
    rows = conn.execute(
        "SELECT change_kind FROM partition_change WHERE segment_id = ? AND route_id = ? AND"
        " ((year_from = ? AND year_to = ?) OR (year_from = ? AND year_to = ?))",
        (segment_id, route_id, year_from, year_to, year_to, year_from),
    ).fetchall()
    kinds = sorted(set(str(row["change_kind"]) for row in rows if row["change_kind"] != "unchanged"))
    unknown = sorted(set(kinds) - set(CHANGE_KIND_TO_REASON))
    if unknown:
        from road_mqi_checker.errors import SchemaViolation

        raise SchemaViolation(
            "partition_change 出现未登记的变更类别 %s，不可比原因代码需同步（见 ledger.db.CHANGE_KINDS）" % unknown
        )
    return kinds


def _surface_of(conn, result, segment_id, year):
    # type: (object, Optional[res.PciResult], str, int) -> str
    """路面类型：优先取评定结果，其次取台账（划分事实要比"有没有出数"更早判定）。"""
    if result is not None and result.surface_type:
        return result.surface_type
    if conn is None:
        return ""
    row = conn.execute(
        "SELECT surface_type FROM segment WHERE segment_id = ? AND year = ?", (segment_id, year)
    ).fetchone()
    return row["surface_type"] if row else ""


def _refuse(reason, segment_id, route_id, year_from, year_to, comparability_reason="", status=res.STATUS_BLOCKED):
    # type: (str, str, str, int, int, str, str) -> res.CompareResult
    result = res.CompareResult(
        segment_id=segment_id,
        route_id=route_id,
        year_from=year_from,
        year_to=year_to,
        status=status,
        blocked_reason=reason,
        comparability_reason=comparability_reason,
    )
    result.check_contract()
    return result


def explain_change(compare_result, pci_from, pci_to):
    # type: (res.CompareResult, res.PciResult, res.PciResult) -> List[res.DeductContribution]
    """把评分差值拆到破损项/实测指标级别（变化贡献项）。

    对账键是 `(source_kind, distress_type, severity)`：同一类型同一程度的多条记录先各自汇总再
    求差（"坑槽/重 从今年 1.2 分变到 3.4 分"），差值**正号表示扣分增加（劣化）**。
    某一键只在一个年度出现 → 差值取该侧的相反数/原值，并把该侧的台账行号带出来。
    """
    delta = compare_result.delta
    grouped = {
        "from": _group(pci_from.contributions),
        "to": _group(pci_to.contributions),
    }
    keys = sorted(set(grouped["from"]) | set(grouped["to"]))
    out = []  # type: List[res.DeductContribution]
    for key in keys:
        source_kind, distress_type, severity = key
        left = grouped["from"].get(key)
        right = grouped["to"].get(key)
        points_from = left["points"] if left else 0.0
        points_to = right["points"] if right else 0.0
        diff = pci_engine.quantize(points_to - points_from)
        if diff == 0.0:
            continue  # 舍入到显示位后没有变化，不列成一条"看起来像结论"的贡献
        reference = right if right is not None else left
        quantity_from = left["quantity"] if left else 0.0
        quantity_to = right["quantity"] if right else 0.0
        out.append(
            res.DeductContribution(
                source_kind=source_kind,
                distress_type=distress_type,
                severity=severity,
                quantity=pci_engine.quantize(quantity_to - quantity_from),
                quantity_unit=reference["unit"],
                coefficient_key=reference["coefficient_key"],
                clause=reference["clause"],
                deducted_points=diff,
                share=_share_of_change(diff, delta),
                source_row_no=reference["source_row_no"],
            )
        )
    out.sort(key=_change_order_key)
    return out


def _share_of_change(diff, delta):
    # type: (float, Optional[float]) -> Optional[float]
    """占比分母取"变化量的绝对值"：劣化时各条贡献同为正、占比合计 ≈ 1，不出现负占比。"""
    if delta is None or delta == 0.0:
        return None
    return pci_engine.quantize(diff / abs(delta), pci_engine.SHARE_DECIMALS)


def _group(contributions):
    # type: (Sequence[res.DeductContribution]) -> Dict[Tuple[str, str, str], Dict[str, object]]
    grouped = {}  # type: Dict[Tuple[str, str, str], Dict[str, object]]
    for item in contributions or []:
        key = (item.source_kind, item.distress_type, item.severity)
        entry = grouped.get(key)
        if entry is None:
            grouped[key] = {
                "points": float(item.deducted_points or 0.0),
                "quantity": float(item.quantity or 0.0),
                "unit": item.quantity_unit,
                "coefficient_key": item.coefficient_key,
                "clause": item.clause,
                "source_row_no": item.source_row_no,
            }
            continue
        entry["points"] = float(entry["points"]) + float(item.deducted_points or 0.0)
        entry["quantity"] = float(entry["quantity"]) + float(item.quantity or 0.0)
        if item.source_row_no is not None:
            current = entry["source_row_no"]
            entry["source_row_no"] = int(item.source_row_no) if current is None else min(int(current), int(item.source_row_no))
    return grouped


def _change_order_key(contribution):
    # type: (res.DeductContribution) -> tuple
    """固定排序：|差值| 降序为主键，同分时按 trace 的字段序列升序（不依赖迭代顺序）。"""
    points = contribution.deducted_points
    magnitude = abs(points) if points is not None else 0.0
    return (-magnitude,) + pci_trace.order_key(contribution)[1:]


def compare_years(conn, segment_id, year_from, year_to, pci_results, ruleset):
    # type: (object, str, int, int, Sequence[res.PciResult], object) -> res.CompareResult
    """两个年度的同一路段对比；不可比因素优先于任何数值。

    `pci_results` 是 `pci.engine.assess_year` 的输出（两个年度各一次，合并传入即可）；
    本函数不查评定核、不重算分数，只做定位、判可比、算差值与拆解。
    """
    if year_to == year_from:
        raise InputUnavailable("年对比的两个年度相同（%s），无差值可算" % year_from)
    span = abs(year_to - year_from)
    pci_from = pci_engine.find_result(pci_results, segment_id, year_from)
    pci_to = pci_engine.find_result(pci_results, segment_id, year_to)
    route_id = (pci_from.route_id if pci_from else "") or (pci_to.route_id if pci_to else "")
    if not route_id and conn is not None:
        for candidate in (year_from, year_to):
            row = conn.execute(
                "SELECT route_id FROM segment WHERE segment_id = ? AND year = ?", (segment_id, candidate)
            ).fetchone()
            if row:
                route_id = row["route_id"]
                break
    if pci_from is None and pci_to is None:
        raise InputUnavailable(
            "评定结果里没有 %s 在 %s/%s 年度的记录，未进入对比路径（先 rmqc assess --year）"
            % (segment_id, year_from, year_to)
        )

    kinds = _change_rows(conn, route_id, segment_id, year_from, year_to)
    if kinds:
        reasons = [CHANGE_KIND_TO_REASON[kind] for kind in kinds]
        detail = "、".join(
            "%s（台账划分变更 %s）" % (reason, kind) for reason, kind in zip(reasons, kinds)
        )
        return _refuse(
            "跨年划分不可比：%s —— 不按重叠里程摊分，不出变化率" % detail,
            segment_id,
            route_id,
            year_from,
            year_to,
            comparability_reason=",".join(reasons),
            status=res.STATUS_UNCOMPARABLE,
        )
    if pci_from is None or pci_to is None:
        absent_year = year_from if pci_from is None else year_to
        present_year = year_to if pci_from is None else year_from
        reason = "partition_new" if pci_from is None else "partition_disappeared"
        return _refuse(
            "%s 年度台账里没有 %s 的路段行（划分变更：%s），与 %s 年度不可比"
            % (absent_year, segment_id, reason, present_year),
            segment_id,
            route_id,
            year_from,
            year_to,
            comparability_reason=reason,
            status=res.STATUS_UNCOMPARABLE,
        )

    surface_from = _surface_of(conn, pci_from, segment_id, year_from)
    surface_to = _surface_of(conn, pci_to, segment_id, year_to)
    if surface_from and surface_to and surface_from != surface_to:
        return _refuse(
            "路段 %s 的路面类型在 %s 与 %s 年度之间由 %s 变为 %s（两套扣分比率表与换算式都不同），差值无意义"
            % (segment_id, year_from, year_to, surface_from, surface_to),
            segment_id,
            route_id,
            year_from,
            year_to,
            comparability_reason="component_scope_mismatch",
            status=res.STATUS_UNCOMPARABLE,
        )

    refused = []  # type: List[Tuple[str, res.PciResult]]
    for label, current in (("%s 年度" % year_from, pci_from), ("%s 年度" % year_to, pci_to)):
        if current.pci is None:
            refused.append((label, current))
    if refused:
        return _refuse(
            "；".join("%s PCI 未出数（%s：%s）" % (label, item.status, item.blocked_reason) for label, item in refused)
            + "，差值无从算起",
            segment_id,
            route_id,
            year_from,
            year_to,
        )

    if (pci_from.ruleset_id, pci_from.ruleset_version) != (pci_to.ruleset_id, pci_to.ruleset_version):
        return _refuse(
            "两个年度用的规则集包不同（%s v%s vs %s v%s），系数面变化未逐格核对前不出变化率"
            % (
                pci_from.ruleset_id,
                pci_from.ruleset_version,
                pci_to.ruleset_id,
                pci_to.ruleset_version,
            ),
            segment_id,
            route_id,
            year_from,
            year_to,
            comparability_reason="rule_version_change",
            status=res.STATUS_UNCOMPARABLE,
        )
    if pci_from.scope_note != pci_to.scope_note:
        return _refuse(
            "两年参与加权的分项口径不同（%s vs %s），两个分数不在同一分母上，差值无意义"
            % (pci_from.scope_note or "全分项", pci_to.scope_note or "全分项"),
            segment_id,
            route_id,
            year_from,
            year_to,
            comparability_reason="component_scope_mismatch",
            status=res.STATUS_UNCOMPARABLE,
        )

    delta = pci_engine.quantize(pci_to.pci - pci_from.pci)
    rate = pci_engine.quantize((pci_from.pci - pci_to.pci) / span)
    overlap = _overlap_m(_extent(conn, segment_id, year_from), _extent(conn, segment_id, year_to))
    preliminary = res.CompareResult(
        segment_id=segment_id,
        route_id=route_id,
        year_from=year_from,
        year_to=year_to,
        status=res.STATUS_OK,
        delta=delta,
        deterioration_rate_per_year=rate,
        length_overlap_m=overlap,
        grade_from=pci_from.grade,
        grade_to=pci_to.grade,
    )
    contributors = explain_change(preliminary, pci_from, pci_to)

    status = res.STATUS_OK if contributors else res.STATUS_PARTIAL
    scope_note = ""
    if not contributors:
        scope_note = "部分口径（无变化）：两年扣分贡献逐项相同（差值 %s），无变化贡献项可列" % delta
    result = res.CompareResult(
        segment_id=segment_id,
        route_id=route_id,
        year_from=year_from,
        year_to=year_to,
        status=status,
        scope_note=scope_note,
        delta=delta,
        deterioration_rate_per_year=rate,
        length_overlap_m=overlap,
        grade_from=pci_from.grade,
        grade_to=pci_to.grade,
        top_contributors=contributors[:TOP_CONTRIBUTOR_LIMIT] if contributors else [],
        comparability_reason="",
    )
    result.check_contract()
    return result


def explain_change_rows(result):
    # type: (res.CompareResult) -> List[Dict[str, object]]
    """变化贡献项的展开行（列序同 `pci.trace.TRACE_COLUMNS`，与 M2 的贡献展开共用）。"""
    return pci_trace.expand_list(result.segment_id, result.year_to, result.top_contributors)


def summarize_status(results):
    # type: (Sequence[res.CompareResult]) -> Dict[str, int]
    counts = dict((status, 0) for status in res.ALL_RESULT_STATUSES)
    for result in results:
        counts[result.status] = counts.get(result.status, 0) + 1
    return counts


def segment_ids_in_ledger(conn, year_from, year_to):
    # type: (object, int, int) -> List[str]
    """两个年度**任一年**出现的路段（命令面批量对比的对象集，按首见桩号定序）。

    刻意取并集而不是交集：只在一年出现的对象正是"划分新增/消失"的证据，必须出现在清单上并
    标 `uncomparable`，而不是被交集悄悄滤掉 —— 与"拒算对象也要出现在清单上"同一条纪律。
    """
    rows = conn.execute(
        "SELECT segment_id, MIN(start_stake_m) AS first_stake FROM segment WHERE year IN (?, ?)"
        " GROUP BY segment_id ORDER BY first_stake, segment_id",
        (year_from, year_to),
    ).fetchall()
    return [row["segment_id"] for row in rows]


def result_payload(result):
    # type: (res.CompareResult) -> Dict[str, object]
    """对比结果的对外结构（列序与 `COMPARE_COLUMNS` 一致，贡献项另起一段避免嵌套歧义）。"""
    return {
        "segment_id": result.segment_id,
        "route_id": result.route_id,
        "year_from": result.year_from,
        "year_to": result.year_to,
        "status": result.status,
        "delta": result.delta,
        "deterioration_rate_per_year": result.deterioration_rate_per_year,
        "grade_from": result.grade_from,
        "grade_to": result.grade_to,
        "comparability_reason": result.comparability_reason,
        "top_contributors": pci_trace.expand_list(result.segment_id, result.year_to, result.top_contributors),
        "length_overlap_m": result.length_overlap_m,
        "blocked_reason": result.blocked_reason,
        "scope_note": result.scope_note,
    }
