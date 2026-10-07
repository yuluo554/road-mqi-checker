"""养护对策规则链与优先序排序（模块 4 的规则侧，逻辑属 M4）。

规则形态固定为：IF 条件（指标 + 阈值 + 比较符）→ THEN 建议工程类别与规模档，
每条必须挂条款号或"用户自定"来源。排序键可配置但必须确定：
同分时的次级键是固定字段序列，禁止随机、禁止依赖 set/dict 迭代顺序。
"""

from road_mqi_checker.errors import MilestoneNotImplemented

MODULE_KEY = "road_mqi_checker.strategy.rules"
MILESTONE = "M4"

#: 条件比较符（规则 JSON 里的 op 字段合法值）
CONDITION_OPS = ("lt", "le", "gt", "ge", "between")

#: 同分次级键的固定顺序（既定口径：改了会让优先序表整体漂移）
TIE_BREAK_KEYS = ("route_id", "start_stake_m", "segment_id")

#: 建议类别词汇表：由规则 THEN 侧给出，具体取值待 M3 条款核对后定
ACTION_FIELDS = ("rule_id", "clause", "condition_text", "action_class", "scale_band", "triggered_by")


def suggest_actions(conn, year, pci_results, mqi_results, ruleset):
    """逐路段给出养护需求判定清单（blocked 项也要出现在清单上，标注拒算原因）。"""
    raise MilestoneNotImplemented(MODULE_KEY, MILESTONE, what="对策规则链判定")


def rank_priority(suggestions, primary_key, ascending=True):
    """按可配置主键排序，同分用 TIE_BREAK_KEYS 固定次级键，保证确定性。"""
    raise MilestoneNotImplemented(MODULE_KEY, MILESTONE, what="路线优先序排序")
