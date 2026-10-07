"""年度检测数据入库与导入回执（模块 1 的入口）。

回执是硬要求：入库行数 / 拒入行数 / 逐条拒因（文件、行号、字段、拒因代码）。
回执对象不带时间戳（同 `ledger.db` 的字节一致纪律）。

## 两层职责（与 `ledger.checks` 的分界，M1 定稿）

本层只管**这行能不能存进台账**（结构可解析、标识符合法、同一对象内部一致、文件内不重复）：

- 拒入（行不进台账）：`R009_MALFORMED_ROW`（缺字段/数值不可解析/桩号形态非法/同一对象字段前后矛盾）、
  `R010_PRIVACY_WHITELIST`（合成数据出现真实形态标识符）、
  `R001_UNKNOWN_ROUTE`（一份检测表只覆盖一条路线，混进别的路线编号的行）、
  `R008_DUPLICATE`（文件内完全重复的破损行，以及同一份文件按 digest 重复导入）。
- 拒算但入库：负值、超范围、单位错、悬空、重叠、闭合差 —— 这些是**要被检出的对象**，
  数据库把它们挡在门外就等于把"导入回执 + 异常识别召回"这条主证据链扔了
  （`ledger.db` 的表上因此刻意不设 CHECK 约束）。它们由 `ledger.checks` 出 finding，
  并带上对应的拒因代码（见 `CHECK_KIND_TO_REJECT_CODE`），使两层用同一套词汇。

## 数据类别（隐私红线的适用面）

白名单只对**声称是合成数据**的文件强制：文件首行标记 `# data_class=SYNTHETIC` 即受白名单约束；
用户自己的真实台账用 `--data-class user` 显式声明后不走白名单。没有标记又没显式声明的文件
一律拒读（退出码 2）—— 红线不能靠"猜这是不是演示数据"来守。
"""

import hashlib
import os
from typing import Dict, List, Optional, Tuple

from road_mqi_checker import privacy
from road_mqi_checker.errors import InputUnavailable, PrivacyViolation
from road_mqi_checker.ledger import models

MODULE_KEY = "road_mqi_checker.ledger.importer"
MILESTONE = "M1"

#: 回执列名 —— 真值/评测与 GUI 展示都按这套字段（既定口径，改名要同步 plan/03 与测试）
RECEIPT_COLUMNS = (
    "source_file",
    "source_digest",
    "rows_total",
    "rows_accepted",
    "rows_rejected",
    "rejected_row_no",
    "rejected_field",
    "reject_code",
    "reject_detail",
)

#: 拒入原因代码（与 `ledger.checks.CHECK_KINDS` 的对应关系见 CHECK_KIND_TO_REJECT_CODE）
REJECT_CODES = (
    "R001_UNKNOWN_ROUTE",
    "R002_STAKE_GAP",
    "R003_STAKE_OVERLAP",
    "R004_CLOSURE_EXCEEDED",
    "R005_BAD_DICTIONARY",
    "R006_UNIT_MISMATCH",
    "R007_OUT_OF_RANGE",
    "R008_DUPLICATE",
    "R009_MALFORMED_ROW",
    "R010_PRIVACY_WHITELIST",
)

#: 校验项 → 拒因代码：两层共用一套词汇，回执与 finding 能对账
CHECK_KIND_TO_REJECT_CODE = {
    "stake_gap": "R002_STAKE_GAP",
    "stake_overlap": "R003_STAKE_OVERLAP",
    "length_closure": "R004_CLOSURE_EXCEEDED",
    "distress_dictionary": "R005_BAD_DICTIONARY",
    "unit_consistency": "R006_UNIT_MISMATCH",
    "value_range": "R007_OUT_OF_RANGE",
    "duplicate_import": "R008_DUPLICATE",
    "partition_change": "R001_UNKNOWN_ROUTE",
}

DATA_CLASS_MARK_KEY = "data_class"
DATA_CLASS_SYNTHETIC = "SYNTHETIC"
DATA_CLASS_USER = "user"
DATA_CLASSES = (DATA_CLASS_SYNTHETIC, DATA_CLASS_USER)

#: 一份检测表里的"对象级"列：同一对象各行必须一致（宽表重复列的正常形态）
ROUTE_COLUMNS = ("route_name", "admin_grade", "tech_grade", "route_start_stake", "route_end_stake", "adcode")
SURVEY_COLUMNS = (
    "segment_name",
    "seg_start_stake",
    "seg_end_stake",
    "surface_type",
    "lane_count",
    "segment_width_m",
    "panel_count",
    "rqi",
    "rut_depth_mm",
    "skid_indicator",
    "skid_indicator_kind",
    "report_no",
    "detect_org",
)
DISTRESS_COLUMNS = ("distress_type", "severity", "quantity", "quantity_unit", "lane_no")

#: 破损行的身份（用于文件内重复判定）：路段 + 年度 + 类型 + 程度 + 数量 + 量纲 + 车道
DUPLICATE_KEY_COLUMNS = ("segment_id", "year") + DISTRESS_COLUMNS


class RejectLine(object):
    __slots__ = ("row_no", "field", "code", "detail", "segment_id")

    def __init__(self, row_no, field, code, detail, segment_id=""):
        self.row_no = row_no
        self.field = field
        self.code = code
        self.detail = detail
        #: 结构化归属：回执列名是既定口径（不能为归属加列），但调用方需要知道拒的是哪个路段
        self.segment_id = segment_id

    def as_dict(self):
        # type: () -> Dict[str, object]
        return {
            "rejected_row_no": self.row_no,
            "rejected_field": self.field,
            "reject_code": self.code,
            "reject_detail": self.detail,
        }


class ImportReceipt(object):
    """一次导入的回执：汇总 + 逐条拒因。不带时间戳，可逐字节复现。"""

    def __init__(self, source_file, source_digest, data_class, rows_total):
        self.source_file = source_file
        self.source_digest = source_digest
        self.data_class = data_class
        self.rows_total = rows_total
        self.rows_accepted = 0
        self.rows_rejected = 0
        self.lines = []  # type: List[RejectLine]
        self.segments_written = 0
        self.duplicate_file = False
        self.current_segment_id = ""

    def add(self, row_no, field, code, detail):
        # type: (int, str, str, str) -> None
        if code not in REJECT_CODES:
            raise InputUnavailable("未登记的拒因代码 %r" % (code,))
        self.lines.append(RejectLine(row_no, field, code, detail, segment_id=self.current_segment_id))
        self.rows_rejected += 1

    def begin_row(self, segment_id):
        # type: (str) -> None
        """逐行处理前声明当前行属于哪个路段，让每条拒因都带结构化归属（回执列名不动）。"""
        self.current_segment_id = segment_id

    def reject_counts(self):
        # type: () -> Dict[str, int]
        counts = {}  # type: Dict[str, int]
        for line in self.lines:
            counts[line.code] = counts.get(line.code, 0) + 1
        return counts

    def reject_summary(self):
        # type: () -> str
        counts = self.reject_counts()
        return "; ".join("%s x%d" % (code, counts[code]) for code in sorted(counts))

    def to_rows(self):
        # type: () -> List[Dict[str, object]]
        """按 `RECEIPT_COLUMNS` 展开：一条拒因一行；没有拒因也给一行（回执不能空）。"""
        head = {
            "source_file": self.source_file,
            "source_digest": self.source_digest,
            "rows_total": self.rows_total,
            "rows_accepted": self.rows_accepted,
            "rows_rejected": self.rows_rejected,
        }
        if not self.lines:
            row = dict(head)
            row.update({"rejected_row_no": "", "rejected_field": "", "reject_code": "", "reject_detail": ""})
            return [row]
        rows = []
        for line in self.lines:
            row = dict(head)
            row.update(line.as_dict())
            rows.append(row)
        return rows

    def summary(self):
        # type: () -> Dict[str, object]
        return {
            "source_file": self.source_file,
            "source_digest": self.source_digest,
            "data_class": self.data_class,
            "rows_total": self.rows_total,
            "rows_accepted": self.rows_accepted,
            "rows_rejected": self.rows_rejected,
            "segments_written": self.segments_written,
            "duplicate_file": self.duplicate_file,
            "reject_counts": self.reject_counts(),
        }

    def report_lines(self):
        # type: () -> List[str]
        lines = [
            "来源 %s（digest %s…，数据类别 %s）" % (self.source_file, self.source_digest[:12], self.data_class),
            "总行 %d / 入库 %d / 拒入 %d" % (self.rows_total, self.rows_accepted, self.rows_rejected),
        ]
        if self.duplicate_file:
            lines.append("整份文件已导入过（digest 相同）→ 本次 0 入库")
        if self.segments_written:
            lines.append("路段年度记录 %d 条" % self.segments_written)
        for line in self.lines:
            lines.append(
                "  拒入 第%s行 字段[%s] %s：%s" % (line.row_no or "-", line.field or "-", line.code, line.detail)
            )
        return lines


# ---- 读表（与生成器的写表口径对称：固定跳过 # 标记行，支持引号）----


def split_csv_line(line):
    # type: (str) -> List[str]
    cells = []  # type: List[str]
    current = []  # type: List[str]
    quoted = False
    index = 0
    while index < len(line):
        char = line[index]
        if quoted:
            if char == '"':
                if index + 1 < len(line) and line[index + 1] == '"':
                    current.append('"')
                    index += 2
                    continue
                quoted = False
            else:
                current.append(char)
        elif char == '"':
            quoted = True
        elif char == ",":
            cells.append("".join(current))
            current = []
        else:
            current.append(char)
        index += 1
    cells.append("".join(current))
    return cells


def read_mark(path):
    # type: (str) -> Dict[str, str]
    """读文件头部的 `# key=value` 标记行（data_class 就在这里）。"""
    marks = {}  # type: Dict[str, str]
    with open(path, "r", encoding="utf-8", newline="") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            if not stripped.startswith("#"):
                break
            body = stripped[1:]
            if "=" in body:
                key, value = body.split("=", 1)
                marks[key.strip()] = value.strip()
    return marks


def read_table(path):
    # type: (str) -> List[Dict[str, str]]
    """读回检测表：跳过标记注释行，返回 [{列名: 文本}]，行号从 1 开始（数据行序）。"""
    if not os.path.isfile(path):
        raise InputUnavailable("检测表文件不存在：%s" % path)
    with open(path, "r", encoding="utf-8", newline="") as handle:
        content = handle.read()
    lines = [line for line in content.replace("\r\n", "\n").split("\n") if line.strip() and not line.lstrip().startswith("#")]
    if not lines:
        raise InputUnavailable("%s 是空表" % path)
    header = split_csv_line(lines[0])
    rows = []  # type: List[Dict[str, str]]
    for number, line in enumerate(lines[1:], start=1):
        cells = split_csv_line(line)
        if len(cells) != len(header):
            raise InputUnavailable("%s 第 %d 行列数(%d)与表头(%d)不符" % (path, number, len(cells), len(header)))
        row = dict(zip(header, cells))
        row["_row_no"] = number
        rows.append(row)
    if not rows:
        raise InputUnavailable("%s 只有表头没有数据行" % path)
    return rows


def file_digest(path):
    # type: (str) -> str
    with open(path, "rb") as handle:
        return hashlib.sha1(handle.read()).hexdigest()


# ---- 解析与判定 ----


def _clean(value):
    # type: (object) -> str
    if value is None:
        return ""
    return str(value).strip()


def _resolve_data_class(path, declared):
    # type: (str, Optional[str]) -> str
    marks = read_mark(path)
    marked = marks.get(DATA_CLASS_MARK_KEY)
    if marked and declared and marked != declared:
        raise InputUnavailable(
            "%s 标记为 data_class=%s，但导入声明 data_class=%s —— 二者不一致，不做静默降级"
            % (path, marked, declared)
        )
    resolved = marked or declared
    if resolved not in DATA_CLASSES:
        raise InputUnavailable(
            "%s 没有 %s 标记行也未显式声明数据类别（--data-class %s 之一），拒绝读取"
            % (path, DATA_CLASS_MARK_KEY, "/".join(DATA_CLASSES))
        )
    return resolved


def _parse_float(text, row_no, field, receipt, accepted):
    # type: (str, int, str, ImportReceipt, List[bool]) -> Optional[float]
    if text == "":
        return None
    try:
        return float(text)
    except ValueError:
        receipt.add(row_no, field, "R009_MALFORMED_ROW", "%r 不是合法数值" % (text,))
        accepted[0] = False
        return None


def _parse_int(text, row_no, field, receipt, accepted):
    # type: (str, int, str, ImportReceipt, List[bool]) -> Optional[int]
    if text == "":
        return None
    try:
        return int(float(text))
    except ValueError:
        receipt.add(row_no, field, "R009_MALFORMED_ROW", "%r 不是合法整数" % (text,))
        accepted[0] = False
        return None


def _parse_stake(text, row_no, field, receipt, accepted):
    # type: (str, int, str, ImportReceipt, List[bool]) -> Optional[int]
    try:
        return models.parse_stake(text)
    except InputUnavailable as exc:
        receipt.add(row_no, field, "R009_MALFORMED_ROW", str(exc))
        accepted[0] = False
        return None


def _check_whitelist(row, row_no, receipt):
    # type: (Dict[str, str], int, ImportReceipt) -> bool
    """合成数据的标识符必须过白名单；不过就出拒因并让这一行真的进不了库。"""
    try:
        privacy.check_row(models.identifier_fields(row))
    except PrivacyViolation as exc:
        receipt.add(row_no, "route_id/segment_name/stake/adcode/org/report", "R010_PRIVACY_WHITELIST", str(exc))
        return False
    return True


def analyse(conn, path, year, data_class=None):
    # type: (object, str, int, Optional[str]) -> Tuple[ImportReceipt, Dict[str, object]]
    """只判定不写库：返回 (回执, 待写对象)。`import_csv` 与 `plan_import` 共用这一份逻辑。"""
    resolved = _resolve_data_class(path, data_class)
    rows = read_table(path)
    digest_value = file_digest(path)
    receipt = ImportReceipt(os.path.basename(path), digest_value, resolved, len(rows))

    already = conn.execute(
        "SELECT receipt_id FROM import_receipt WHERE source_digest = ? LIMIT 1", (digest_value,)
    ).fetchone()
    if already is not None:
        receipt.duplicate_file = True
        receipt.rows_rejected = len(rows)
        receipt.lines.append(
            RejectLine(0, "", "R008_DUPLICATE", "整份文件此前已导入（digest %s…），本次 0 入库" % digest_value[:12])
        )
        return receipt, {"skip": True}

    header_missing = [name for name in models.RAW_COLUMNS if name not in rows[0]]
    if header_missing:
        raise InputUnavailable("%s 缺列：%s" % (path, ", ".join(header_missing)))

    routes = {}  # type: Dict[str, Dict[str, object]]
    segments = {}  # type: Dict[Tuple[str, int], Dict[str, object]]
    distress = []  # type: List[Dict[str, object]]
    seen_row_keys = set()

    for row in rows:
        row_no = row["_row_no"]
        receipt.begin_row(_clean(row.get("segment_id")))
        accepted = [True]
        if resolved == DATA_CLASS_SYNTHETIC and not _check_whitelist(row, row_no, receipt):
            continue

        row_year = _parse_int(_clean(row.get("year")), row_no, "year", receipt, accepted)
        route_id = _clean(row.get("route_id"))
        segment_id = _clean(row.get("segment_id"))
        if not route_id:
            receipt.add(row_no, "route_id", "R009_MALFORMED_ROW", "路线编号为空")
            accepted[0] = False
        if not segment_id:
            receipt.add(row_no, "segment_id", "R009_MALFORMED_ROW", "路段编号为空")
            accepted[0] = False
        if row_year is not None and row_year != year:
            receipt.add(
                row_no, "year", "R009_MALFORMED_ROW", "行内年度 %d 与导入声明年度 %d 不一致" % (row_year, year)
            )
            accepted[0] = False

        surface_type = _clean(row.get("surface_type"))
        if surface_type not in models.SURFACE_TYPES:
            receipt.add(
                row_no,
                "surface_type",
                "R009_MALFORMED_ROW",
                "路面类型 %r 非法，首期只支持 %s" % (surface_type, "/".join(models.SURFACE_TYPES)),
            )
            accepted[0] = False

        start_m = _parse_stake(_clean(row.get("seg_start_stake")), row_no, "seg_start_stake", receipt, accepted)
        end_m = _parse_stake(_clean(row.get("seg_end_stake")), row_no, "seg_end_stake", receipt, accepted)
        route_start = _parse_stake(_clean(row.get("route_start_stake")), row_no, "route_start_stake", receipt, accepted)
        route_end = _parse_stake(_clean(row.get("route_end_stake")), row_no, "route_end_stake", receipt, accepted)
        lane_count = _parse_int(_clean(row.get("lane_count")), row_no, "lane_count", receipt, accepted)
        width_m = _parse_float(_clean(row.get("segment_width_m")), row_no, "segment_width_m", receipt, accepted)
        panel_count = _parse_int(_clean(row.get("panel_count")), row_no, "panel_count", receipt, accepted)
        rqi = _parse_float(_clean(row.get("rqi")), row_no, "rqi", receipt, accepted)
        rut = _parse_float(_clean(row.get("rut_depth_mm")), row_no, "rut_depth_mm", receipt, accepted)
        skid = _parse_float(_clean(row.get("skid_indicator")), row_no, "skid_indicator", receipt, accepted)

        if accepted[0] and start_m is not None and end_m is not None and end_m <= start_m:
            receipt.add(row_no, "seg_end_stake", "R009_MALFORMED_ROW", "路段起止桩号倒置")
            accepted[0] = False

        # 一份检测表只覆盖一条路线：混进别的路线编号的行按 R001 拒入
        if accepted[0] and routes and route_id not in routes:
            receipt.add(
                row_no,
                "route_id",
                "R001_UNKNOWN_ROUTE",
                "本表覆盖路线 %s，出现不属于本表的路线 %s" % (sorted(routes)[0], route_id),
            )
            accepted[0] = False

        route_payload = {
            "route_id": route_id,
            "year": year,
            "route_name": _clean(row.get("route_name")),
            "admin_grade": _clean(row.get("admin_grade")),
            "tech_grade": _clean(row.get("tech_grade")),
            "start_stake_m": route_start,
            "end_stake_m": route_end,
            "adcode": _clean(row.get("adcode")),
            "note": _clean(row.get("note")),
        }
        if accepted[0] and route_id in routes:
            conflict = _conflict(routes[route_id], route_payload, ROUTE_COLUMNS)
            if conflict:
                receipt.add(row_no, conflict[0], "R009_MALFORMED_ROW", conflict[1])
                accepted[0] = False

        segment_payload = {
            "segment_id": segment_id,
            "route_id": route_id,
            "year": year,
            "segment_name": _clean(row.get("segment_name")),
            "start_stake_m": start_m,
            "end_stake_m": end_m,
            "surface_type": surface_type,
            "lane_count": lane_count,
            "segment_width_m": width_m,
            "panel_count": panel_count,
            "rqi": rqi,
            "rut_depth_mm": rut,
            "skid_indicator": skid,
            "skid_indicator_kind": _clean(row.get("skid_indicator_kind")),
            "report_no": _clean(row.get("report_no")),
            "detect_org": _clean(row.get("detect_org")),
            "note": _clean(row.get("note")),
        }
        segment_key = (segment_id, year)
        if accepted[0] and segment_key in segments:
            conflict = _conflict(segments[segment_key], segment_payload, SURVEY_COLUMNS)
            if conflict:
                receipt.add(row_no, conflict[0], "R009_MALFORMED_ROW", conflict[1])
                accepted[0] = False

        distress_type = _clean(row.get("distress_type"))
        severity = _clean(row.get("severity"))
        quantity_unit = _clean(row.get("quantity_unit"))
        quantity = _parse_float(_clean(row.get("quantity")), row_no, "quantity", receipt, accepted)
        lane_no = _parse_int(_clean(row.get("lane_no")), row_no, "lane_no", receipt, accepted)
        has_distress = bool(distress_type or severity or quantity_unit or quantity is not None)
        if has_distress and not (distress_type and severity and quantity_unit and quantity is not None):
            receipt.add(
                row_no,
                "distress_type/severity/quantity/quantity_unit",
                "R009_MALFORMED_ROW",
                "破损行的类型、程度、数量、量纲必须同时具备",
            )
            accepted[0] = False

        row_identity = tuple(
            _clean(row.get(name)) if name != "_row_no" else "" for name in DUPLICATE_KEY_COLUMNS
        )
        if accepted[0] and has_distress and row_identity in seen_row_keys:
            receipt.add(row_no, "row", "R008_DUPLICATE", "与前面某行完全相同（%s）" % _identity_text(row_identity))
            accepted[0] = False
        elif accepted[0] and has_distress:
            seen_row_keys.add(row_identity)

        if not accepted[0]:
            continue

        if route_id not in routes:
            routes[route_id] = route_payload
        if segment_key not in segments:
            segments[segment_key] = segment_payload
        if has_distress:
            distress.append(
                {
                    "segment_id": segment_id,
                    "year": year,
                    "distress_type": distress_type,
                    "severity": severity,
                    "quantity": quantity,
                    "quantity_unit": quantity_unit,
                    "lane_no": lane_no,
                    "source_row_no": row_no,
                    "note": _clean(row.get("note")),
                }
            )
        receipt.rows_accepted += 1

    receipt.segments_written = len(segments)
    return receipt, {"routes": routes, "segments": segments, "distress": distress, "skip": False}


def _conflict(existing, candidate, columns):
    # type: (Dict[str, object], Dict[str, object], Tuple[str, ...]) -> Optional[Tuple[str, str]]
    """同一对象（路线/路段）在不同行里必须一致；返回第一个不一致的 (字段, 说明)。"""
    for name in columns:
        before, after = existing.get(name), candidate.get(name)
        if _normalise(before) != _normalise(after):
            return (name, "同一对象的 %s 前后不一致（已登记 %r，本行 %r）" % (name, before, after))
    return None


def _normalise(value):
    # type: (object) -> str
    if value is None:
        return ""
    if isinstance(value, float):
        return "%.6g" % value
    return str(value).strip()


def _identity_text(identity):
    # type: (Tuple[str, ...]) -> str
    return " / ".join(identity)


def write(conn, payload, receipt):
    # type: (object, Dict[str, object], ImportReceipt) -> None
    """把已通过判定的对象写进七张表；重复导入的键冲突在这里兜住（不静默覆盖）。"""
    if payload.get("skip"):
        return
    for route_id in sorted(payload["routes"]):
        route = payload["routes"][route_id]
        conn.execute(
            "INSERT OR REPLACE INTO route (route_id, year, route_name, admin_grade, tech_grade,"
            " start_stake_m, end_stake_m, adcode, note) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                route["route_id"],
                route["year"],
                route["route_name"],
                route["admin_grade"],
                route["tech_grade"],
                route["start_stake_m"],
                route["end_stake_m"],
                route["adcode"],
                route["note"],
            ),
        )
    for key in sorted(payload["segments"]):
        segment = payload["segments"][key]
        conn.execute(
            "INSERT OR REPLACE INTO segment (segment_id, route_id, year, segment_name, start_stake_m,"
            " end_stake_m, surface_type, note, lane_count, segment_width_m, panel_count)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                segment["segment_id"],
                segment["route_id"],
                segment["year"],
                segment["segment_name"],
                segment["start_stake_m"],
                segment["end_stake_m"],
                segment["surface_type"],
                segment["note"],
                segment["lane_count"],
                segment["segment_width_m"],
                segment["panel_count"],
            ),
        )
        conn.execute(
            "INSERT OR REPLACE INTO survey (segment_id, route_id, year, surface_type, rqi, rut_depth_mm,"
            " skid_indicator, skid_indicator_kind, report_no, detect_org, note) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                segment["segment_id"],
                segment["route_id"],
                segment["year"],
                segment["surface_type"],
                segment["rqi"],
                segment["rut_depth_mm"],
                segment["skid_indicator"],
                segment["skid_indicator_kind"],
                segment["report_no"],
                segment["detect_org"],
                segment["note"],
            ),
        )
    conn.executemany(
        "INSERT INTO distress (segment_id, year, distress_type, severity, quantity, quantity_unit,"
        " lane_no, source_row_no, note) VALUES (?,?,?,?,?,?,?,?,?)",
        [
            (
                row["segment_id"],
                row["year"],
                row["distress_type"],
                row["severity"],
                row["quantity"],
                row["quantity_unit"],
                row["lane_no"],
                row["source_row_no"],
                row["note"],
            )
            for row in payload["distress"]
        ],
    )
    _record_receipt(conn, receipt)


def _record_receipt(conn, receipt):
    # type: (object, ImportReceipt) -> None
    conn.execute(
        "INSERT INTO import_receipt (source_file, source_digest, rows_total, rows_accepted,"
        " rows_rejected, reject_summary) VALUES (?,?,?,?,?,?)",
        (
            receipt.source_file,
            receipt.source_digest,
            receipt.rows_total,
            receipt.rows_accepted,
            receipt.rows_rejected,
            receipt.reject_summary(),
        ),
    )
    conn.commit()


def import_csv(conn, path, year, data_class=None, dry_run=False):
    """把一份年度检测表导入台账并返回回执；`dry_run=True` 只判定不写库。

    整份文件按 digest 重复时也要落一条回执（入库 0 行）—— "重复导入被去重"必须留下证据，
    而不是静默什么都不发生。
    """
    receipt, payload = analyse(conn, path, year, data_class=data_class)
    if dry_run:
        return receipt
    if receipt.duplicate_file:
        _record_receipt(conn, receipt)
        return receipt
    write(conn, payload, receipt)
    return receipt


def plan_import(conn, path, year=None, data_class=None):
    """只读预检：返回将要入库/拒入的行数与逐条拒因，不落库（GUI 导入向导先跑这一步）。

    `year=None` 时按表内 year 列分组预检（一份表只覆盖一个年度，混年度会被拒）。
    """
    rows = read_table(path)
    if year is None:
        values = sorted({_clean(row.get("year")) for row in rows} - {""})
        if len(values) != 1:
            raise InputUnavailable("表内年度不唯一（%s），必须显式给出 --year" % ", ".join(values or ["（无）"]))
        year = int(values[0])
    receipt, _payload = analyse(conn, path, year, data_class=data_class)
    return receipt
