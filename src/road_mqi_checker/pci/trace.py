"""扣分贡献展开（"这段今年比去年低 6 分是哪几处坑槽扣掉的"，逻辑属 M2）。

评分变化必须能追到具体破损项 —— 这是本工具相对 Excel 模板的立身之处，
也是聊天框做不到的（它没有路段台账）。
"""

from road_mqi_checker.errors import MilestoneNotImplemented

MODULE_KEY = "road_mqi_checker.pci.trace"
MILESTONE = "M2"

#: 展开视图的列（GUI 与报告导出共用，属既定口径）
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
)


def expand_contributions(pci_result):
    """把 PciResult 展开成逐条破损/逐指标的贡献清单。"""
    raise MilestoneNotImplemented(MODULE_KEY, MILESTONE, what="扣分贡献展开")


def contributions_for_cell(pci_result, distress_type, severity):
    raise MilestoneNotImplemented(MODULE_KEY, MILESTONE, what="按破损类型×程度定位贡献")
