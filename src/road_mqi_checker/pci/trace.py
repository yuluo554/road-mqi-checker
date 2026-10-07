"""扣分贡献展开（"这段今年比去年低 6 分是哪几处坑槽扣掉的"）。

评分变化必须能追到具体破损项 —— 这是本工具相对 Excel 模板的立身之处，
也是聊天框做不到的（它没有路段台账）。

三条落地纪律：

1. **每条贡献都挂"系数 key + 条款号"**（结构上由 `results.DeductContribution.check_contract` 强制），
   破损类贡献还必须回指台账行号 `source_row_no`；台账行号 = 原始检测表的数据行序
   （`ledger.importer.read_table` 的编号语义），所以展开视图能一路指回用户手里那份 CSV 的那一行；
2. **排序必须有固定次级键**：主键是扣分从大到小，同分时按 `TRACE_ORDER_KEYS` 逐字段比较，
   禁止依赖 set/dict 迭代顺序或 SQLite 返回顺序，保证两次冷启动逐行一致；
3. **拒算对象展开为空清单**：blocked 的结果本身数值字段全空，没有贡献可展开，
   报告与 GUI 只显示拒算原因（不显示"扣 0 分"这种像是结论的东西）。
"""

from typing import Dict, List, Optional

from road_mqi_checker import results as res

MODULE_KEY = "road_mqi_checker.pci.trace"
MILESTONE = "M2"

#: 展开视图的列（GUI 与报告导出共用，属既定口径；M2 追加末列 `source_row_no` 做行号回指）
TRACE_COLUMNS = (
    "segment_id",
    "year",
    "source_kind",
    "distress_type",
    "severity",
    "quantity",
    "quantity_unit",
    "coefficient_key",
    "clause",
    "deducted_points",
    "share",
    "source_row_no",
)

#: 固定排序键序列：第一项是主键（扣分降序），其余是同分时的次级键（升序、空值排后）
TRACE_ORDER_KEYS = (
    "deducted_points",
    "source_kind",
    "distress_type",
    "severity",
    "quantity",
    "source_row_no",
    "coefficient_key",
)


def order_key(contribution):
    # type: (res.DeductContribution) -> tuple
    """把一条贡献变成可比较的固定元组（扣分取负实现降序，空值统一排到后面）。"""
    points = contribution.deducted_points
    return (
        -(points if points is not None else 0.0),
        contribution.source_kind,
        contribution.distress_type,
        contribution.severity,
        _null_last(contribution.quantity),
        _null_last(contribution.source_row_no),
        contribution.coefficient_key,
    )


def _null_last(value):
    # type: (Optional[float]) -> tuple
    if value is None:
        return (1, 0.0)
    return (0, float(value))


def sorted_contributions(pci_result):
    # type: (res.PciResult) -> List[res.DeductContribution]
    """按 `TRACE_ORDER_KEYS` 排序的贡献对象清单（稳定、与输入顺序无关）。"""
    return sorted(pci_result.contributions, key=order_key)


def expand_list(segment_id, year, contributions):
    # type: (str, Optional[int], Sequence[res.DeductContribution]) -> List[Dict[str, object]]
    """把任意一批贡献项展开成 `TRACE_COLUMNS` 结构的行（M4 的变化贡献项走同一套列）。"""
    rows = []  # type: List[Dict[str, object]]
    for item in sorted(contributions, key=order_key):
        rows.append(
            {
                "segment_id": segment_id,
                "year": year,
                "source_kind": item.source_kind,
                "distress_type": item.distress_type,
                "severity": item.severity,
                "quantity": item.quantity,
                "quantity_unit": item.quantity_unit,
                "coefficient_key": item.coefficient_key,
                "clause": item.clause,
                "deducted_points": item.deducted_points,
                "share": item.share,
                "source_row_no": item.source_row_no,
            }
        )
    return rows


def expand_contributions(pci_result):
    # type: (res.PciResult) -> List[Dict[str, object]]
    """把 PciResult 展开成逐条破损/逐指标的贡献清单（列序即 `TRACE_COLUMNS`）。"""
    return expand_list(pci_result.segment_id, pci_result.year, pci_result.contributions)


def contributions_for_cell(pci_result, distress_type, severity):
    # type: (res.PciResult, str, str) -> List[Dict[str, object]]
    """按"破损类型 × 程度"定位贡献行（GUI 点一格看它扣了多少、来自哪些台账行）。"""
    return [
        row
        for row in expand_contributions(pci_result)
        if row["source_kind"] == "distress"
        and row["distress_type"] == distress_type
        and (severity in (None, "") or row["severity"] == severity)
    ]


def top_contributors(pci_result, limit=3):
    # type: (res.PciResult, int) -> List[res.DeductContribution]
    """扣分最多的若干贡献项（M4 年对比的 `CompareResult.top_contributors` 用它）。"""
    ordered = sorted_contributions(pci_result)
    return ordered[:limit] if limit > 0 else ordered


def report_lines(pci_result, limit=5):
    # type: (res.PciResult, int) -> List[str]
    """人读形式的贡献清单；拒算对象只出拒算原因，不出"扣 0 分"。"""
    if pci_result.status in (res.STATUS_BLOCKED, res.STATUS_UNCOMPARABLE):
        return ["%s/%s %s：%s" % (pci_result.segment_id, pci_result.year, pci_result.status, pci_result.blocked_reason)]
    rows = expand_contributions(pci_result)[:limit] if limit > 0 else expand_contributions(pci_result)
    lines = []  # type: List[str]
    for row in rows:
        if row["source_kind"] == "distress":
            lines.append(
                "  %s（%s）%s %s → 扣 %s 分（占扣分 %s，系数 %s %s，台账行 %s）"
                % (
                    row["distress_type"],
                    row["severity"],
                    _trim(row["quantity"]),
                    row["quantity_unit"],
                    _trim(row["deducted_points"]),
                    _percent(row["share"]),
                    row["coefficient_key"],
                    row["clause"],
                    row["source_row_no"],
                )
            )
        else:
            lines.append(
                "  分项 %s 实测 %s → 扣 %s 分（占扣分 %s，系数 %s %s）"
                % (
                    row["distress_type"],
                    _trim(row["quantity"]),
                    _trim(row["deducted_points"]),
                    _percent(row["share"]),
                    row["coefficient_key"],
                    row["clause"],
                )
            )
    return lines


def _trim(value):
    # type: (Optional[float]) -> str
    if value is None:
        return "-"
    text = ("%.1f" % float(value)).rstrip("0").rstrip(".")
    return text if text else "0"


def _percent(share):
    # type: (Optional[float]) -> str
    if share is None:
        return "-"
    return "%.1f%%" % (float(share) * 100.0)
