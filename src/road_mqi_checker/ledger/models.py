"""台账数据结构：路线 → 路段 → 年度检测记录 → 破损行。

这里是契约层（字段、单位、口径），解析与校验逻辑属 M1。
长度一律用整米（int），桩号字符串形态（K12+300）到米的换算属 M1 的 station 解析。
"""

from typing import Dict, List, Optional

from road_mqi_checker.errors import InputUnavailable

SURFACE_TYPES = ("asphalt", "cement")
ADMIN_GRADES = ("高速", "一级", "二级", "三级", "四级", "等外")

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
