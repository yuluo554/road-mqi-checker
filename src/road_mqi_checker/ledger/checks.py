"""台账确定性校验（模块 1 的校验引擎，逻辑属 M1）。

七类校验各自独立可测，全部只报"应核实"级别的发现（finding），不静默修数据。
"""

from road_mqi_checker.errors import MilestoneNotImplemented

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


def check_stake_continuity(conn, route_id, year):
    raise MilestoneNotImplemented(MODULE_KEY, MILESTONE, what="桩号悬空/重叠校验")


def check_length_closure(conn, route_id, year, tolerance_coefficient_key="tolerance.length_closure"):
    raise MilestoneNotImplemented(MODULE_KEY, MILESTONE, what="路段长度与路线里程闭合差校验")


def check_distress_dictionary(conn, year, ruleset):
    raise MilestoneNotImplemented(MODULE_KEY, MILESTONE, what="破损类型与程度字典合法性校验")


def check_unit_consistency(conn, year):
    raise MilestoneNotImplemented(MODULE_KEY, MILESTONE, what="量纲一致性校验")


def check_value_range(conn, year):
    raise MilestoneNotImplemented(MODULE_KEY, MILESTONE, what="负值与超范围值识别")


def check_duplicate_import(conn, source_digest):
    raise MilestoneNotImplemented(MODULE_KEY, MILESTONE, what="重复导入识别")


def detect_partition_change(conn, route_id, year_from, year_to):
    """返回划分变更与"不可比"标记。

    要点：跨年度划分不一致必须显式标记为不可比，不得静默按比例摊分（题目红线）。
    """
    raise MilestoneNotImplemented(MODULE_KEY, MILESTONE, what="跨年度路段划分变更识别")


def run_all_checks(conn, year, ruleset):
    raise MilestoneNotImplemented(MODULE_KEY, MILESTONE, what="全量校验编排")
