"""年对比与变化贡献（模块 4 的对比侧，逻辑属 M4）。

三段式回答：评分变了多少 → 是不是可比 → 变化由哪个指标的哪一次变化贡献。
不可比时只出 uncomparable 与原因，绝不出变化率（题目纪律）。
"""

from road_mqi_checker.errors import MilestoneNotImplemented

MODULE_KEY = "road_mqi_checker.strategy.compare"
MILESTONE = "M4"

#: 不可比原因代码（与 ledger.db.CHANGE_KINDS 对应，属既定口径）
UNCOMPARABLE_REASONS = (
    "partition_new",
    "partition_disappeared",
    "partition_merged",
    "partition_split",
    "partition_shifted",
    "coefficient_change",
    "rule_version_change",
)

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


def compare_years(conn, segment_id, year_from, year_to, pci_results, ruleset):
    """返回 CompareResult；规则集版本变化也要记为不可比因素。"""
    raise MilestoneNotImplemented(MODULE_KEY, MILESTONE, what="年度对比与劣化速率")


def explain_change(compare_result, pci_from, pci_to):
    """把评分差值拆到破损项/实测指标级别（变化贡献项）。"""
    raise MilestoneNotImplemented(MODULE_KEY, MILESTONE, what="变化贡献项拆解")
