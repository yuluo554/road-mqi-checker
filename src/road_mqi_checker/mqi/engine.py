"""MQI 汇总与技术状况等级（模块 3，逻辑属 M4）。

三级汇总（路段→路线→路网）必须共用同一套权重来源，口径一致可复算。
纪律：分项不全时只输出"注明口径的部分指标值"，不得冒充完整 MQI 评定值。
"""

from road_mqi_checker.errors import MilestoneNotImplemented

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


def aggregate_segment_mqi(conn, segment_id, year, pci_results, ruleset):
    raise MilestoneNotImplemented(MODULE_KEY, MILESTONE, what="路段级 MQI 汇总")


def aggregate_route_mqi(conn, route_id, year, pci_results, ruleset):
    """按里程加权；权重系数未核对则返回 blocked。"""
    raise MilestoneNotImplemented(MODULE_KEY, MILESTONE, what="路线级 MQI 里程加权")


def aggregate_network_mqi(conn, year, pci_results, ruleset):
    raise MilestoneNotImplemented(MODULE_KEY, MILESTONE, what="路网级 MQI 汇总")


def assign_grade(value, threshold_key, ruleset):
    """阈值未核对 → 返回 blocked 的分级结果，等级字段为 None，不得猜档。"""
    raise MilestoneNotImplemented(MODULE_KEY, MILESTONE, what="技术状况等级判定")
