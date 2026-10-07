"""台账数据结构：路线 → 路段 → 年度检测记录 → 破损行。

这里是契约层（字段、单位、口径、字典）：解析与校验逻辑在 `ledger.importer` / `ledger.checks`。
长度一律用整米（int），桩号字符串形态（K12+300）到米的换算在本层的 `parse_stake`。

破损字典（`DISTRESS_DICTIONARY`）是**合成口径**：类型名、程度档、量纲与几何上界都在
`plan/03-数据字典与合成数据.md` 逐条登记并标"待核对"，字典里不出现任何规范阈值数字
（扣分比率、分级边界、容差一律不在此处）。
"""

import re
from typing import Dict, List, Optional, Tuple

from road_mqi_checker.errors import InputUnavailable

SURFACE_TYPES = ("asphalt", "cement")
ADMIN_GRADES = ("高速", "一级", "二级", "三级", "四级", "等外")
TECH_GRADES = ("高速", "一级", "二级", "三级", "四级", "等外")

#: 破损程度档位（顺序即由轻到重）
SEVERITY_LEVELS = ("轻", "中", "重")

#: 破损数量量纲：长度（m）、面积（m2）、板块数（块）
QUANTITY_UNITS = ("m", "m2", "块")

#: 量纲 → 几何上界的算法名（上界一律由本行自带的数据算出，不引用规范阈值）
EXTENT_KINDS = ("length", "area", "panel")

#: 破损类型字典：路面类型 → 类型名 → 量纲与量纲类别。
#: 每个类型的 unit/extent 属"待核对"口径：换算进评定路径前必须按原文核对（见 plan/03 §四）。
DISTRESS_DICTIONARY = {
    "asphalt": {
        "纵向裂缝": {"unit": "m", "extent": "length"},
        "横向裂缝": {"unit": "m", "extent": "length"},
        "斜向裂缝": {"unit": "m", "extent": "length"},
        "网状裂缝": {"unit": "m2", "extent": "area"},
        "坑槽": {"unit": "m2", "extent": "area"},
        "松散": {"unit": "m2", "extent": "area"},
        "沉陷": {"unit": "m2", "extent": "area"},
        "泛油": {"unit": "m2", "extent": "area"},
        "波浪": {"unit": "m2", "extent": "area"},
        "啃边": {"unit": "m", "extent": "length"},
    },
    "cement": {
        "破碎板": {"unit": "块", "extent": "panel"},
        "板角断裂": {"unit": "块", "extent": "panel"},
        "裂缝": {"unit": "m", "extent": "length"},
        "坑洞": {"unit": "块", "extent": "panel"},
        "错台": {"unit": "块", "extent": "panel"},
        "板边剥落": {"unit": "m", "extent": "length"},
        "接缝料损坏": {"unit": "m", "extent": "length"},
        "隆起": {"unit": "块", "extent": "panel"},
    },
}  # type: Dict[str, Dict[str, Dict[str, str]]]

#: 实测指标的定义域（不是分级阈值）：指数类指标的合法取值区间 None 表示无界。
#: 超出定义域就是"这条记录不可能是真值"，属数据自身可判的范围错。
INDICATOR_DOMAIN = {
    "rqi": (0.0, 100.0),
    "rut_depth_mm": (0.0, None),
    "skid_indicator_SFC": (0.0, 100.0),
    "skid_indicator_BPN": (0.0, 100.0),
}  # type: Dict[str, Tuple[Optional[float], Optional[float]]]

SKID_INDICATOR_KINDS = ("SFC", "BPN")

#: 年度检测表列（一份"路线-年度"的 CSV 就是这个结构；一行 = 一条破损调查记录，
#: 路段与实测指标列在该路段的各行间重复 —— 与检测单位导出的宽表形态一致）。
#: 字段名与 `privacy.check_row` 的标识符推断口径对齐，落盘前逐行过白名单。
RAW_COLUMNS = (
    "year",
    "route_id",
    "route_name",
    "admin_grade",
    "tech_grade",
    "route_start_stake",
    "route_end_stake",
    "adcode",
    "segment_id",
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
    "distress_type",
    "severity",
    "quantity",
    "quantity_unit",
    "lane_no",
    "note",
)  # type: Tuple[str, ...]

#: 无破损调查记录时，破损四列留空（区别于"破损行缺失"这种结构错）
NO_DISTRESS_VALUES = {"distress_type": "", "severity": "", "quantity": "", "quantity_unit": "", "lane_no": ""}

_STAKE_RE = re.compile(r"^K(\d+)\+(\d{3})$")


def parse_stake(value):
    # type: (str) -> int
    """桩号字符串 → 整米；形态非法即 InputUnavailable（导入期的 R009 之一）。"""
    if value is None:
        raise InputUnavailable("桩号为空")
    match = _STAKE_RE.match(str(value).strip())
    if not match:
        raise InputUnavailable("桩号 %r 形态非法，应为 K<公里号>+<三位米数>" % (value,))
    return int(match.group(1)) * 1000 + int(match.group(2))


def format_stake(meters):
    # type: (int) -> str
    return "K%d+%03d" % (int(meters) // 1000, int(meters) % 1000)


def distress_entry(surface_type, distress_type):
    # type: (str, str) -> Optional[Dict[str, str]]
    """破损类型在某路面类型字典里的条目；不在字典内返回 None（由校验层判 R005）。"""
    return DISTRESS_DICTIONARY.get(surface_type, {}).get(distress_type)


def geometric_upper_bound(extent, length_m, lane_count, segment_width_m, panel_count):
    # type: (str, int, Optional[int], Optional[float], Optional[int]) -> Optional[float]
    """由本行自带数据算出的物理上界（超出即"这条记录不可能是真值"）。

    - length：单条破损的累计长度不超过"路段长度 × 车道数"；
    - area：破损面积不超过路段平面面积；
    - panel：破损板数不超过该路段板块总数。
    算不出上界（缺车道数/宽度/板数）时返回 None，调用方必须判"未判定"而不是判合格。
    """
    if extent == "length":
        if not length_m or not lane_count:
            return None
        return float(length_m * lane_count)
    if extent == "area":
        if not length_m or not segment_width_m:
            return None
        return float(length_m) * float(segment_width_m)
    if extent == "panel":
        if not panel_count:
            return None
        return float(panel_count)
    return None


def indicator_domain(name, skid_indicator_kind=None):
    # type: (str, Optional[str]) -> Optional[Tuple[Optional[float], Optional[float]]]
    if name == "skid_indicator":
        key = "skid_indicator_%s" % (skid_indicator_kind or "")
        return INDICATOR_DOMAIN.get(key)
    return INDICATOR_DOMAIN.get(name)


def identifier_fields(row):
    # type: (Dict[str, object]) -> Dict[str, object]
    """挑出需要过白名单的标识符字段，并把列名映射到 `privacy` 认识的类别名。

    路段桩号（seg_start_stake/seg_end_stake）是落盘行的实际标识符，映射到 stake 类别。
    """
    return {
        "route_id": row.get("route_id"),
        "adcode": row.get("adcode"),
        "segment_name": row.get("segment_name"),
        "start_stake": row.get("seg_start_stake"),
        "end_stake": row.get("seg_end_stake"),
        "detect_org": row.get("detect_org"),
        "report_no": row.get("report_no"),
    }

#: 注入缺陷类别（真值文件与导入回执共用这套词汇，见 data/README §三）
INJECTED_ISSUES = (
    "none",
    "gap_chain",
    "overlap_chain",
    "partition_change",
    "negative_value",
    "out_of_range",
    "unit_error",
    "duplicate_import",
)


class _Validated(object):
    REQUIRED = ()  # type: tuple

    def validate(self):
        missing = [name for name in self.REQUIRED if getattr(self, name) in (None, "")]
        if missing:
            raise InputUnavailable(
                "%s 缺必填字段：%s" % (self.__class__.__name__, ", ".join(missing))
            )


class Route(_Validated):
    """路线基本信息。"""

    REQUIRED = ("route_id", "route_name", "admin_grade", "tech_grade", "start_stake_m", "end_stake_m")

    def __init__(
        self,
        route_id,
        route_name,
        admin_grade,
        tech_grade,
        start_stake_m,
        end_stake_m,
        adcode="",
        note="",
    ):
        self.route_id = route_id
        self.route_name = route_name
        self.admin_grade = admin_grade
        self.tech_grade = tech_grade
        self.start_stake_m = start_stake_m
        self.end_stake_m = end_stake_m
        self.adcode = adcode
        self.note = note

    @property
    def declared_length_m(self):
        # type: () -> int
        return self.end_stake_m - self.start_stake_m

    def validate(self):
        super(Route, self).validate()
        if self.end_stake_m <= self.start_stake_m:
            raise InputUnavailable("路线 %s 起止桩号倒置" % self.route_id)
        return self


class Segment(_Validated):
    """某年度划分下的路段（跨年划分变更就是本表的变化）。"""

    REQUIRED = ("segment_id", "route_id", "year", "segment_name", "start_stake_m", "end_stake_m", "surface_type")

    def __init__(
        self,
        segment_id,
        route_id,
        year,
        segment_name,
        start_stake_m,
        end_stake_m,
        surface_type,
        note="",
    ):
        self.segment_id = segment_id
        self.route_id = route_id
        self.year = year
        self.segment_name = segment_name
        self.start_stake_m = start_stake_m
        self.end_stake_m = end_stake_m
        self.surface_type = surface_type
        self.note = note

    @property
    def length_m(self):
        # type: () -> int
        return self.end_stake_m - self.start_stake_m

    def validate(self):
        super(Segment, self).validate()
        if self.surface_type not in SURFACE_TYPES:
            raise InputUnavailable(
                "路段 %s 的路面类型 %r 非法，首期只支持 %s" % (self.segment_id, self.surface_type, "/".join(SURFACE_TYPES))
            )
        if self.end_stake_m <= self.start_stake_m:
            raise InputUnavailable("路段 %s 起止桩号倒置" % self.segment_id)
        return self


class DistressRow(_Validated):
    """一条路面破损调查记录（破损类型 × 程度 × 数量 × 量纲）。"""

    REQUIRED = ("segment_id", "year", "distress_type", "severity", "quantity", "quantity_unit")

    def __init__(
        self,
        segment_id,
        year,
        distress_type,
        severity,
        quantity,
        quantity_unit,
        area_m2=None,
        lane_no=None,
        note="",
    ):
        self.segment_id = segment_id
        self.year = year
        self.distress_type = distress_type
        self.severity = severity
        self.quantity = quantity
        self.quantity_unit = quantity_unit
        self.area_m2 = area_m2
        self.lane_no = lane_no
        self.note = note

    def validate(self):
        super(DistressRow, self).validate()
        return self


class SurveyRecord(_Validated):
    """一个路段某年度的检测记录：实测指标 + 破损行集合。

    实测指标一律 Optional[float]：缺测就是 None，不得填 0 —— 0 会被加权当成真值。
    """

    REQUIRED = ("segment_id", "route_id", "year", "surface_type")

    def __init__(
        self,
        segment_id,
        route_id,
        year,
        surface_type,
        rqi=None,
        rut_depth_mm=None,
        skid_indicator=None,
        skid_indicator_kind="",
        distress_rows=None,
        report_no="",
        detect_org="",
        note="",
    ):
        self.segment_id = segment_id
        self.route_id = route_id
        self.year = year
        self.surface_type = surface_type
        self.rqi = rqi
        self.rut_depth_mm = rut_depth_mm
        self.skid_indicator = skid_indicator
        self.skid_indicator_kind = skid_indicator_kind
        self.distress_rows = distress_rows if distress_rows is not None else []  # type: List[DistressRow]
        self.report_no = report_no
        self.detect_org = detect_org
        self.note = note

    def measured_indicators(self):
        # type: () -> Dict[str, Optional[float]]
        return {
            "rqi": self.rqi,
            "rut_depth_mm": self.rut_depth_mm,
            "skid_indicator": self.skid_indicator,
        }

    def validate(self):
        super(SurveyRecord, self).validate()
        for row in self.distress_rows:
            if row.segment_id != self.segment_id or row.year != self.year:
                raise InputUnavailable(
                    "破损行属于路段 %s/%s 年，却挂在检测记录 %s/%s 年下"
                    % (row.segment_id, row.year, self.segment_id, self.year)
                )
        return self
