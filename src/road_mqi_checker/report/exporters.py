"""报告导出（模块 4 的可交付物 + 全模块汇总报告，逻辑属 M6）。

导出层三条结构约束：
1. 只能通过 report.disclaimer.compose_document 拼文档 —— 免责声明必在末尾；
2. 产物不带时间戳与绝对路径、不带本机用户名（字节一致 + 脱敏双重需要）；
3. blocked/uncomparable 项必须原样出现在导出表里，不得为"报表好看"而过滤。
"""

from road_mqi_checker.errors import MilestoneNotImplemented

MODULE_KEY = "road_mqi_checker.report.exporters"
MILESTONE = "M6"

FORMATS = ("csv", "md", "docx")

#: 优先序清单的导出列（题目材料 3/4：可导出的建议计划表）
PLAN_COLUMNS = (
    "rank",
    "route_id",
    "segment_id",
    "year",
    "pci",
    "mqi_partial",
    "grade",
    "delta",
    "deterioration_rate_per_year",
    "action_class",
    "scale_band",
    "rule_id",
    "clause",
    "triggered_by",
    "status",
    "blocked_reason",
)


def export_priority_list(path, fmt, rows):
    raise MilestoneNotImplemented(MODULE_KEY, MILESTONE, what="优先序清单导出")


def export_assessment_report(path, fmt, ledger_snapshot, pci_results, mqi_results):
    raise MilestoneNotImplemented(MODULE_KEY, MILESTONE, what="评定结果报告导出")
