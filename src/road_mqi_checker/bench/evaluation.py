"""基准评测：指标定义与四态口径（模块 5，计算逻辑属 M5）。

四态是这道题的诚实线：分母为 0 叫"不可判"，通路拿不到叫"不可用"，
两者都不许挤进"达标/未达标"。骨架期全部基准指标都是"不可用"（内核未实现），
README 的指标表必须如实显示，不给假绿。

状态→退出码的映射现在就定死并锁进测试，M5 只是把数算出来。
"""

from road_mqi_checker.errors import MilestoneNotImplemented
from road_mqi_checker.exit_codes import (
    EXIT_DEGRADED,
    EXIT_INPUT_UNUSABLE,
    EXIT_OK,
    EXIT_UNIMPLEMENTED,
)

MODULE_KEY = "road_mqi_checker.bench.evaluation"
MILESTONE = "M5"

METRIC_PASS = "达标"
METRIC_FAIL = "未达标"
METRIC_INDETERMINATE = "不可判"  # 分母为 0（如真值样本尚未入库）
METRIC_UNAVAILABLE = "不可用"  # 通路拿不到（如内核属未来里程碑）

METRIC_STATES = (METRIC_PASS, METRIC_FAIL, METRIC_INDETERMINATE, METRIC_UNAVAILABLE)

#: 指标表 → CLI 退出码：不可判走 2（数据门），未达标走 1，不可用走 3（通路门）
STATE_TO_EXIT = {
    METRIC_PASS: EXIT_OK,
    METRIC_FAIL: EXIT_DEGRADED,
    METRIC_INDETERMINATE: EXIT_INPUT_UNUSABLE,
    METRIC_UNAVAILABLE: EXIT_UNIMPLEMENTED,
}

#: 题目要求的四类评测指标（M5 逐项实现）
METRICS = (
    "rescore_drift",              # 评分复算误差，目标 0
    "grade_accuracy",             # 等级判定准确率
    "contribution_order",         # 扣分贡献项排序一致性
    "anomaly_recall",             # 数据异常识别召回
    "anomaly_false_alarm",        # 数据异常识别误报，目标 0
    "byte_reproducible",          # 生成器/产物位级一致
)

#: 骨架期指标表的初始态：全部"不可用"，通路属未来里程碑
def initial_metric_table():
    # type: () -> list
    return [
        {
            "metric": name,
            "state": METRIC_UNAVAILABLE,
            "value": None,
            "target": TARGETS.get(name, ""),
            "note": "内核未实现（属 M1-M5），通路不可用",
        }
        for name in METRICS
    ]


TARGETS = {
    "rescore_drift": "= 0",
    "grade_accuracy": ">= 0.95",
    "contribution_order": ">= 0.95",
    "anomaly_recall": ">= 0.95",
    "anomaly_false_alarm": "= 0",
    "byte_reproducible": "两次运行逐字节一致",
}


def gate(metric_table):
    """门禁：只对"未达标 / 不可用 / 名单外的新不可判"给非零码。

    实现要等到指标能算出来（M5）；这里先固定语义。
    """
    raise MilestoneNotImplemented(MODULE_KEY, MILESTONE, what="基准指标计算与门禁")
