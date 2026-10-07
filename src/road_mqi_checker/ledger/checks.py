"""台账确定性校验（模块 1 的校验引擎）。

八类校验各自独立可测，全部只报"应核实"级别的发现（finding），不静默修数据。

三件贯穿全模块的纪律：

1. **判据必须能复算**：几何上界、指标定义域、链条连续性都由台账自身的数据算出；
   需要规范阈值/容差才能判的项（闭合差容差、字典口径核对），在系数未核对时一律出
   `undetermined`（"待核对，未判定"）而不是硬判 —— 硬判就是凭记忆填数。
2. **不可比不摊分**：跨年度路段划分变更只写清单与"不可比"标记，绝不按比例把里程摊平。
3. **拒因代码与导入层同源**：每条 finding 带 `reject_code`，取自
   `ledger.importer.CHECK_KIND_TO_REJECT_CODE`，使"回执"和"校验"用同一套词汇对账。
"""

import sqlite3
from typing import Dict, List, Optional, Sequence, Tuple

from road_mqi_checker.errors import InputUnavailable
from road_mqi_checker.ledger import importer, models

MODULE_KEY = "road_mqi_checker.ledger.checks"
MILESTONE = "M1"

#: 校验项清单（M1 逐项实现，名称即 finding 的 kind，属既定口径）
CHECK_KINDS = (
    "stake_gap",            # 桩号悬空段
    "stake_overlap",        # 桩号重叠段
    "length_closure",       # 路段长度和与路线里程闭合差
    "distress_dictionary",  # 破损类型/程度字典合法性
    "unit_consistency",     # 量纲一致性（面积/长度/数量/板数）
    "value_range",          # 负值与超范围值
    "duplicate_import",     # 重复导入去重
    "partition_change",     # 跨年度路段划分变更
)

#: 校验结论只有两档：检出（判据齐备）与未判定（判据依赖未核对系数或数据不足）
VERDICT_FOUND = "found"
VERDICT_UNDETERMINED = "undetermined"
VERDICTS = (VERDICT_FOUND, VERDICT_UNDETERMINED)
VERDICT_LABELS = {VERDICT_FOUND: "检出", VERDICT_UNDETERMINED: "待核对，未判定"}

#: 划分变更 finding 的固定话术：不可比必须显式说出口，不能只存在表里
UNCOMPARABLE_TEXT = "跨年划分不可比，不做里程摊分"


class Finding(object):
    """一条校验发现：对象（路段/路线/行）+ 判据状态 + 可复算的细节。"""

    __slots__ = ("kind", "reject_code", "route_id", "segment_id", "year", "verdict", "detail", "source_row_no")

    def __init__(self, kind, route_id, segment_id, year, verdict, detail, source_row_no=None):
        if kind not in CHECK_KINDS:
            raise InputUnavailable("未登记的校验项 %r" % (kind,))
        if verdict not in VERDICTS:
            raise InputUnavailable("未登记的校验结论 %r" % (verdict,))
        self.kind = kind
        self.reject_code = importer.CHECK_KIND_TO_REJECT_CODE[kind]
        self.route_id = route_id
        self.segment_id = segment_id
        self.year = year
        self.verdict = verdict
        self.detail = detail
        self.source_row_no = source_row_no

    def as_dict(self):
        # type: () -> Dict[str, object]
        return {
            "check_kind": self.kind,
            "reject_code": self.reject_code,
            "route_id": self.route_id,
            "segment_id": self.segment_id,
            "year": self.year,
            "verdict": self.verdict,
            "verdict_label": VERDICT_LABELS[self.verdict],
            "detail": self.detail,
            "source_row_no": self.source_row_no,
        }

    def key(self):
        # type: () -> Tuple[str, str, str, int]
        """稳定身份：同一类校验对同一对象只应有一条结论。"""
        return (self.kind, self.route_id, self.segment_id, self.year or 0)

    def report_line(self):
        # type: () -> str
        return "%s[%s] %s/%s %s：%s" % (
            self.kind,
            self.reject_code,
            self.route_id,
            self.year,
            self.segment_id or "-",
            VERDICT_LABELS[self.verdict] + "，" + self.detail,
        )

    def __repr__(self):
        return "Finding(%s)" % (self.report_line(),)


def _segments(conn, route_id=None, year=None):
    # type: (sqlite3.Connection, Optional[str], Optional[int]) -> List[sqlite3.Row]
    clause, args = [], []  # type: List[str], List[object]
    if route_id is not None:
        clause.append("route_id = ?")
        args.append(route_id)
    if year is not None:
        clause.append("year = ?")
        args.append(year)
    where = (" WHERE " + " AND ".join(clause)) if clause else ""
    return conn.execute(
        "SELECT * FROM segment%s ORDER BY start_stake_m, segment_id" % where, tuple(args)
    ).fetchall()


def _route_row(conn, route_id, year):
    # type: (sqlite3.Connection, str, int) -> Optional[sqlite3.Row]
    return conn.execute(
        "SELECT * FROM route WHERE route_id = ? AND year = ?", (route_id, year)
    ).fetchone()


def _length(row):
    # type: (sqlite3.Row) -> int
    return int(row["end_stake_m"]) - int(row["start_stake_m"])


# ---- 1 & 2：桩号悬空 / 重叠 ----


def check_stake_continuity(conn, route_id, year):
    """同一路线同一年度的路段链条：既要连续（无悬空），也不能重叠。

    路线首尾也查：链条没覆盖到路线声明的起止桩号，同样是悬空段。
    """
    rows = _segments(conn, route_id=route_id, year=year)
    findings = []  # type: List[Finding]
    for previous, current in zip(rows, rows[1:]):
        gap = int(current["start_stake_m"]) - int(previous["end_stake_m"])
        if gap > 0:
            findings.append(
                Finding(
                    "stake_gap",
                    route_id,
                    current["segment_id"],
                    year,
                    VERDICT_FOUND,
                    "与 %s 之间悬空 %d m（%s～%s）"
                    % (
                        previous["segment_id"],
                        gap,
                        models.format_stake(int(previous["end_stake_m"])),
                        models.format_stake(int(current["start_stake_m"])),
                    ),
                )
            )
        elif gap < 0:
            findings.append(
                Finding(
                    "stake_overlap",
                    route_id,
                    current["segment_id"],
                    year,
                    VERDICT_FOUND,
                    "与 %s 重叠 %d m，该区间里程会被重复计账" % (previous["segment_id"], -gap),
                )
            )
    route = _route_row(conn, route_id, year)
    if route is None or not rows:
        return findings
    head_gap = int(rows[0]["start_stake_m"]) - int(route["start_stake_m"])
    tail_gap = int(route["end_stake_m"]) - int(rows[-1]["end_stake_m"])
    if head_gap > 0:
        findings.append(
            Finding(
                "stake_gap",
                route_id,
                rows[0]["segment_id"],
                year,
                VERDICT_FOUND,
                "路线起点 %s 到首个路段 %s 之间悬空 %d m"
                % (models.format_stake(int(route["start_stake_m"])), rows[0]["segment_id"], head_gap),
            )
        )
    if tail_gap > 0:
        findings.append(
            Finding(
                "stake_gap",
                route_id,
                rows[-1]["segment_id"],
                year,
                VERDICT_FOUND,
                "末段 %s 到路线终点 %s 之间悬空 %d m"
                % (rows[-1]["segment_id"], models.format_stake(int(route["end_stake_m"])), tail_gap),
            )
        )
    return findings


# ---- 3：闭合差（容差是 pending 系数，未核对只报差值不判定）----


def check_length_closure(conn, route_id, year, tolerance_coefficient_key="tolerance.length_closure"):
    """路段长度和 vs 路线声明里程：差值算得出来，判不判定取决于容差这一格系数。

    容差属"用户自定口径"，内置规则集里还是 pending —— 所以本期输出"待核对，未判定"，
    并把实测差值一并写进 detail（看得见，但不假装判过）。
    """
    rows = _segments(conn, route_id=route_id, year=year)
    route = _route_row(conn, route_id, year)
    if route is None or not rows:
        return []
    total = sum(_length(row) for row in rows)
    declared = int(route["end_stake_m"]) - int(route["start_stake_m"])
    closure = total - declared
    if closure == 0:
        # 没有差值就没有要判的东西：任何非负容差都容得下 0，不需要未核对的容差来背书
        return []
    ruleset = importer_ruleset()
    coefficient = ruleset.find(tolerance_coefficient_key) if ruleset is not None else None
    detail = "路段长度和 %d m 与路线里程 %d m 的闭合差 %+d m" % (total, declared, closure)
    if coefficient is None:
        return [
            Finding(
                "length_closure",
                route_id,
                "",
                year,
                VERDICT_UNDETERMINED,
                detail + "；规则集没有登记容差系数 %s，未判定" % tolerance_coefficient_key,
            )
        ]
    if not coefficient.computable:
        return [
            Finding(
                "length_closure",
                route_id,
                "",
                year,
                VERDICT_UNDETERMINED,
                detail + "；容差系数核对状态为 %s，未判定（应核实后重算）" % coefficient.effective_status,
            )
        ]
    tolerance = _tolerance_value(coefficient)
    if tolerance is None:
        return [
            Finding(
                "length_closure",
                route_id,
                "",
                year,
                VERDICT_UNDETERMINED,
                detail + "；容差系数已核对但取不到数值，未判定",
            )
        ]
    if abs(closure) > tolerance:
        return [
            Finding(
                "length_closure",
                route_id,
                "",
                year,
                VERDICT_FOUND,
                detail + "，超出已核对容差 %s m" % tolerance,
            )
        ]
    return []


_RULESET_CACHE = None


def importer_ruleset():
    """闭合差判据用的规则集包（单点选取，避免每次校验都重新扫目录）。"""
    global _RULESET_CACHE
    if _RULESET_CACHE is None:
        from road_mqi_checker.ruleset import loader

        _RULESET_CACHE = loader.select_ruleset()
    return _RULESET_CACHE


def reset_ruleset_cache():
    global _RULESET_CACHE
    _RULESET_CACHE = None


def _tolerance_value(coefficient):
    # type: (object) -> Optional[float]
    values = getattr(coefficient, "values", None)
    if not isinstance(values, dict):
        return None
    for name in ("meters", "value", "tolerance_m"):
        if isinstance(values.get(name), (int, float)):
            return float(values[name])
    return None


# ---- 4：破损类型 / 程度字典 ----


def check_distress_dictionary(conn, year):
    """破损类型是否在该路面类型的字典里、程度是否在字典档位里。

    字典本身是合成口径（待 M3 按原文核对），所以这里判的是"与已登记字典是否一致"，
    不是"与规范是否一致"——detail 里要说清这一点。
    """
    findings = []  # type: List[Finding]
    rows = conn.execute(
        "SELECT d.row_id, d.segment_id, d.distress_type, d.severity, d.quantity_unit, d.source_row_no,"
        " s.surface_type, s.route_id FROM distress d JOIN segment s"
        " ON s.segment_id = d.segment_id AND s.year = d.year WHERE d.year = ?"
        " ORDER BY d.row_id",
        (year,),
    ).fetchall()
    for row in rows:
        surface = row["surface_type"]
        table = models.DISTRESS_DICTIONARY.get(surface, {})
        entry = table.get(row["distress_type"])
        if entry is None:
            findings.append(
                Finding(
                    "distress_dictionary",
                    row["route_id"],
                    row["segment_id"],
                    year,
                    VERDICT_FOUND,
                    "破损类型 %r 不在 %s 路面字典里（字典口径见 plan/03 §四，属待核对合成口径）"
                    % (row["distress_type"], surface),
                    source_row_no=row["source_row_no"],
                )
            )
        if row["severity"] not in models.SEVERITY_LEVELS:
            findings.append(
                Finding(
                    "distress_dictionary",
                    row["route_id"],
                    row["segment_id"],
                    year,
                    VERDICT_FOUND,
                    "破损程度 %r 不在字典档位 %s 里" % (row["severity"], "/".join(models.SEVERITY_LEVELS)),
                    source_row_no=row["source_row_no"],
                )
            )
    return findings


# ---- 5：量纲一致性 ----


def check_unit_consistency(conn, year):
    """量纲与字典口径是否一致；类型不在字典里的交给 distress_dictionary，不重复报。"""
    findings = []  # type: List[Finding]
    rows = conn.execute(
        "SELECT d.row_id, d.segment_id, d.distress_type, d.quantity_unit, d.source_row_no, s.surface_type,"
        " s.route_id FROM distress d JOIN segment s ON s.segment_id = d.segment_id AND s.year = d.year"
        " WHERE d.year = ? ORDER BY d.row_id",
        (year,),
    ).fetchall()
    for row in rows:
        entry = models.distress_entry(row["surface_type"], row["distress_type"])
        if entry is None:
            continue
        if row["quantity_unit"] not in models.QUANTITY_UNITS:
            findings.append(
                Finding(
                    "unit_consistency",
                    row["route_id"],
                    row["segment_id"],
                    year,
                    VERDICT_FOUND,
                    "量纲 %r 不在登记单位 %s 里" % (row["quantity_unit"], "/".join(models.QUANTITY_UNITS)),
                    source_row_no=row["source_row_no"],
                )
            )
        elif row["quantity_unit"] != entry["unit"]:
            findings.append(
                Finding(
                    "unit_consistency",
                    row["route_id"],
                    row["segment_id"],
                    year,
                    VERDICT_FOUND,
                    "%s 按字典口径应以 %s 计，本行记为 %s"
                    % (row["distress_type"], entry["unit"], row["quantity_unit"]),
                    source_row_no=row["source_row_no"],
                )
            )
    return findings


# ---- 6：负值与超范围（判据来自台账自身：几何上界 + 指标定义域）----


def check_value_range(conn, year):
    findings = []  # type: List[Finding]
    segments = {row["segment_id"]: row for row in _segments(conn, year=year)}
    rows = conn.execute(
        "SELECT row_id, segment_id, distress_type, severity, quantity, quantity_unit, source_row_no, lane_no"
        " FROM distress WHERE year = ? ORDER BY row_id",
        (year,),
    ).fetchall()
    for row in rows:
        segment = segments.get(row["segment_id"])
        if segment is None:
            findings.append(
                Finding(
                    "value_range",
                    "",
                    row["segment_id"],
                    year,
                    VERDICT_FOUND,
                    "破损行指向的路段不在该年度台账里（悬空引用）",
                    source_row_no=row["source_row_no"],
                )
            )
            continue
        if row["quantity"] is None:
            continue
        if float(row["quantity"]) < 0:
            findings.append(
                Finding(
                    "value_range",
                    segment["route_id"],
                    row["segment_id"],
                    year,
                    VERDICT_FOUND,
                    "%s（%s）数量为负：%s %s"
                    % (row["distress_type"], row["severity"], row["quantity"], row["quantity_unit"]),
                    source_row_no=row["source_row_no"],
                )
            )
            continue
        entry = models.distress_entry(segment["surface_type"], row["distress_type"])
        if entry is None or row["quantity_unit"] != entry["unit"]:
            continue  # 类型或量纲本身有问题，交给字典/量纲校验，这里不重复判
        upper = models.geometric_upper_bound(
            entry["extent"],
            _length(segment),
            segment["lane_count"],
            segment["segment_width_m"],
            segment["panel_count"],
        )
        if upper is None:
            findings.append(
                Finding(
                    "value_range",
                    segment["route_id"],
                    row["segment_id"],
                    year,
                    VERDICT_UNDETERMINED,
                    "%s 需要%s类上界（车道数/路面宽/板块总数之一）才能判，台账里缺该属性，未判定"
                    % (row["distress_type"], entry["extent"]),
                    source_row_no=row["source_row_no"],
                )
            )
        elif float(row["quantity"]) > upper:
            findings.append(
                Finding(
                    "value_range",
                    segment["route_id"],
                    row["segment_id"],
                    year,
                    VERDICT_FOUND,
                    "%s 数量 %s %s 超过该路段几何上界 %s %s（长度 %d m × 车道/宽度/板数）"
                    % (
                        row["distress_type"],
                        row["quantity"],
                        row["quantity_unit"],
                        _trim(upper),
                        row["quantity_unit"],
                        _length(segment),
                    ),
                    source_row_no=row["source_row_no"],
                )
            )

    surveys = conn.execute(
        "SELECT segment_id, route_id, surface_type, rqi, rut_depth_mm, skid_indicator, skid_indicator_kind"
        " FROM survey WHERE year = ? ORDER BY segment_id",
        (year,),
    ).fetchall()
    for row in surveys:
        for name in ("rqi", "rut_depth_mm", "skid_indicator"):
            value = row[name]
            if value is None:
                continue
            domain = models.indicator_domain(name, row["skid_indicator_kind"] if name == "skid_indicator" else None)
            if domain is None:
                findings.append(
                    Finding(
                        "value_range",
                        row["route_id"],
                        row["segment_id"],
                        year,
                        VERDICT_UNDETERMINED,
                        "%s 无定义域登记，未判定" % name,
                    )
                )
                continue
            low, high = domain
            if (low is not None and float(value) < low) or (high is not None and float(value) > high):
                findings.append(
                    Finding(
                        "value_range",
                        row["route_id"],
                        row["segment_id"],
                        year,
                        VERDICT_FOUND,
                        "%s = %s 超出该指标定义域 %s" % (name, _trim(float(value)), _domain_text(domain)),
                    )
                )
    return findings


def _trim(value):
    # type: (float) -> str
    text = ("%.3f" % float(value)).rstrip("0").rstrip(".")
    return text if text else "0"


def _domain_text(domain):
    # type: (Tuple[Optional[float], Optional[float]]) -> str
    low, high = domain
    return "[%s, %s]" % (_trim(low) if low is not None else "-∞", _trim(high) if high is not None else "+∞")


# ---- 7：重复导入（库内同内容重复，与导入层的文件内重复互补）----


def check_duplicate_import(conn, source_digest=None):
    """同一"路段 + 破损四要素 + 车道"在台账里出现多次 → 报出，不自动删。

    导入层已经拒掉同一份文件内的完全重复行；这里管的是**跨文件/跨批次**把同一份内容
    又灌了一遍的情形（换个文件名再导一次，digest 不同，导入层看不见）。
    `source_digest` 给定时额外报该来源是否被整份重复导入。
    """
    findings = []  # type: List[Finding]
    groups = conn.execute(
        "SELECT d.segment_id, d.distress_type, d.severity, d.quantity, d.quantity_unit, d.lane_no,"
        " d.year, COUNT(*) AS times FROM distress d"
        " JOIN segment s ON s.segment_id = d.segment_id AND s.year = d.year"
        " GROUP BY d.segment_id, d.year, d.distress_type, d.severity, d.quantity, d.quantity_unit, d.lane_no"
        " HAVING COUNT(*) > 1 ORDER BY d.year, d.segment_id, d.distress_type, d.severity, d.quantity"
    ).fetchall()
    for group in groups:
        row_ids = conn.execute(
            "SELECT d.source_row_no FROM distress d JOIN segment s"
            " ON s.segment_id = d.segment_id AND s.year = d.year"
            " WHERE d.segment_id = ? AND d.year = ? AND d.distress_type = ? AND d.severity = ?"
            " AND d.quantity = ? AND d.quantity_unit = ? AND IFNULL(d.lane_no, -1) = IFNULL(?, -1)"
            " ORDER BY d.row_id",
            (
                group["segment_id"],
                group["year"],
                group["distress_type"],
                group["severity"],
                group["quantity"],
                group["quantity_unit"],
                group["lane_no"],
            ),
        ).fetchall()
        route_id = conn.execute(
            "SELECT route_id FROM segment WHERE segment_id = ? AND year = ?",
            (group["segment_id"], group["year"]),
        ).fetchone()["route_id"]
        findings.append(
            Finding(
                "duplicate_import",
                route_id,
                group["segment_id"],
                group["year"],
                VERDICT_FOUND,
                "%s（%s / %s / %s）在台账里出现 %d 次，源行号 %s：扣分会被重复计算"
                % (
                    group["distress_type"],
                    group["severity"],
                    _trim(float(group["quantity"])),
                    group["quantity_unit"],
                    group["times"],
                    ",".join(str(row["source_row_no"]) for row in row_ids),
                ),
            )
        )
    if source_digest is not None:
        receipts = conn.execute(
            "SELECT receipt_id, source_file, rows_accepted FROM import_receipt WHERE source_digest = ?"
            " ORDER BY receipt_id",
            (source_digest,),
        ).fetchall()
        if len(receipts) > 1:
            findings.append(
                Finding(
                    "duplicate_import",
                    "",
                    "",
                    0,
                    VERDICT_FOUND,
                    "来源 digest %s… 被导入 %d 次（回执 %s）"
                    % (source_digest[:12], len(receipts), ",".join(str(r["receipt_id"]) for r in receipts)),
                )
            )
    return findings


# ---- 8：跨年度划分变更（只出清单与不可比标记，绝不摊分）----


def _spans(conn, route_id, year):
    # type: (sqlite3.Connection, str, int) -> Dict[str, Tuple[int, int]]
    return {
        row["segment_id"]: (int(row["start_stake_m"]), int(row["end_stake_m"]))
        for row in _segments(conn, route_id=route_id, year=year)
    }


def _covers(child, parents):
    # type: (Tuple[int, int], Sequence[Tuple[str, Tuple[int, int]]]) -> List[str]
    """若干父区间首尾相接、恰好铺满子区间时返回它们的 id（用于 merged 判定）。"""
    inside = sorted(
        [(key, span) for key, span in parents if span[0] >= child[0] and span[1] <= child[1]],
        key=lambda item: (item[1][0], item[1][1]),
    )
    if len(inside) < 2:
        return []
    cursor = child[0]
    picked = []  # type: List[str]
    for key, span in inside:
        if span[0] != cursor:
            return []
        cursor = span[1]
        picked.append(key)
    return picked if cursor == child[1] else []


def detect_partition_change(conn, route_id, year_from, year_to):
    """识别跨年度路段划分变更并写进 `partition_change` 表，同时显式标记不可比。

    变更类别（`ledger.db.CHANGE_KINDS`）：
    - `unchanged`：同 id 且边界一致 —— 不写表、不出 finding；
    - `shifted`：同 id 但起止桩号变了；
    - `split`：一个旧路段被两个以上新路段恰好铺满；
    - `merged`：两个以上旧路段恰好铺满一个新路段；
    - `new` / `disappeared`：只在一侧出现且不属于上面两种组合。
    要点：跨年度划分不一致必须显式标记为不可比，不得静默按比例摊分（题目红线）。
    """
    before = _spans(conn, route_id, year_from)
    after = _spans(conn, route_id, year_to)
    if not before and not after:
        return []
    changes = []  # type: List[Tuple[str, str, str, bool]]  (change_kind, segment_id, detail, 父侧归属)

    for segment_id in sorted(set(before) & set(after)):
        if before[segment_id] != after[segment_id]:
            detail = "%s：%s～%s → %s～%s" % (
                UNCOMPARABLE_TEXT,
                models.format_stake(before[segment_id][0]),
                models.format_stake(before[segment_id][1]),
                models.format_stake(after[segment_id][0]),
                models.format_stake(after[segment_id][1]),
            )
            changes.append(("shifted", segment_id, detail, False))

    only_before = sorted(set(before) - set(after))
    new_ids = sorted(set(after) - set(before))
    resolved_parents = set()
    resolved_children = set()

    for child_id in new_ids:
        parents = _covers(after[child_id], [(key, before[key]) for key in only_before])
        if len(parents) >= 2:
            for parent_id in parents:
                resolved_parents.add(parent_id)
            resolved_children.add(child_id)
            changes.append(
                (
                    "merged",
                    child_id,
                    "%s：由 %s 合并而来" % (UNCOMPARABLE_TEXT, "、".join(parents)),
                    False,
                )
            )

    for parent_id in only_before:
        if parent_id in resolved_parents:
            continue
        children = _covers(
            before[parent_id],
            [(key, after[key]) for key in new_ids if key not in resolved_children],
        )
        if len(children) >= 2:
            for child_id in children:
                resolved_children.add(child_id)
            resolved_parents.add(parent_id)
            changes.append(
                (
                    "split",
                    parent_id,
                    "%s：拆分为 %s" % (UNCOMPARABLE_TEXT, "、".join(children)),
                    True,
                )
            )
            for child_id in children:
                changes.append(
                    (
                        "split",
                        child_id,
                        "%s：由 %s 拆分而来" % (UNCOMPARABLE_TEXT, parent_id),
                        False,
                    )
                )

    for parent_id in only_before:
        if parent_id not in resolved_parents:
            changes.append(("disappeared", parent_id, "%s：该年度起不再存在" % UNCOMPARABLE_TEXT, True))
    for child_id in new_ids:
        if child_id not in resolved_children:
            changes.append(
                ("new", child_id, "%s：该年度新出现的路段" % UNCOMPARABLE_TEXT, False)
            )

    findings = []  # type: List[Finding]
    for change_kind, segment_id, detail, parent_side in sorted(changes):
        conn.execute(
            "INSERT OR REPLACE INTO partition_change (route_id, year_from, year_to, change_kind,"
            " segment_id, detail) VALUES (?,?,?,?,?,?)",
            (route_id, year_from, year_to, change_kind, segment_id, detail),
        )
        # 归属年度 = 该对象最后存在的年度：父侧（disappeared / split 的母段）落在 year_from，
        # 子侧（new / split 的子段 / merged 的新段 / shifted）落在 year_to。
        findings.append(
            Finding(
                "partition_change",
                route_id,
                segment_id,
                year_from if parent_side else year_to,
                VERDICT_FOUND,
                "%s → %d/%d：%s" % (change_kind, year_from, year_to, detail),
            )
        )
    conn.commit()
    return findings


# ---- 编排 ----


def set_ruleset(ruleset):
    # type: (object) -> None
    """把调用方已选好的规则集包交进来（闭合差判据与调用方用同一包，不另选一次）。"""
    global _RULESET_CACHE
    _RULESET_CACHE = ruleset


def run_all_checks(conn, year, ruleset=None, routes=None, check_partition=True, previous_year_offset=1):
    """跑一遍该年度的八类校验；划分变更按"上一年度 → 本年度"的相邻对检查。

    `ruleset` 是闭合差判据的来源（与调用方选同一包，不另选一次）；
    `routes=None` 时对该年度台账里的全部路线逐条跑。
    """
    if ruleset is not None:
        set_ruleset(ruleset)
    if routes is None:
        routes = [
            row["route_id"]
            for row in conn.execute("SELECT DISTINCT route_id FROM segment WHERE year = ? ORDER BY route_id", (year,))
        ]
    findings = []  # type: List[Finding]
    for route_id in routes:
        findings.extend(check_stake_continuity(conn, route_id, year))
        findings.extend(check_length_closure(conn, route_id, year))
        if check_partition:
            previous = year - previous_year_offset
            if _spans(conn, route_id, previous):
                findings.extend(detect_partition_change(conn, route_id, previous, year))
    findings.extend(check_distress_dictionary(conn, year))
    findings.extend(check_unit_consistency(conn, year))
    findings.extend(check_value_range(conn, year))
    findings.extend(check_duplicate_import(conn))
    return findings


def summarize(findings):
    # type: (Sequence[Finding]) -> Dict[str, object]
    """按校验项统计"检出 / 未判定"，供回执、报告与评测对账。"""
    by_kind = {}  # type: Dict[str, Dict[str, int]]
    for kind in CHECK_KINDS:
        by_kind[kind] = {VERDICT_FOUND: 0, VERDICT_UNDETERMINED: 0}
    for finding in findings:
        by_kind[finding.kind][finding.verdict] += 1
    return {
        "total": len(findings),
        "found": sum(1 for f in findings if f.verdict == VERDICT_FOUND),
        "undetermined": sum(1 for f in findings if f.verdict == VERDICT_UNDETERMINED),
        "by_kind": by_kind,
    }


def report_lines(findings, summary=None):
    # type: (Sequence[Finding], Optional[Dict[str, object]]) -> List[str]
    summary = summary or summarize(findings)
    lines = [
        "校验结论：共 %d 条（检出 %d / 待核对未判定 %d）"
        % (summary["total"], summary["found"], summary["undetermined"])
    ]
    for finding in sorted(findings, key=lambda f: (f.kind, f.route_id or "", f.year or 0, f.segment_id or "")):
        lines.append("  " + finding.report_line())
    return lines

