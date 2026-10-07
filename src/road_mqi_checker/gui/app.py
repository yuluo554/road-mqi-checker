"""桌面壳（模块交付层，属 M6）。

页签结构现在就定下来：GUI 只消费 CLI/引擎已有的 API，绝不另起第二套行为。
PySide6 走惰性导入 —— 缺依赖时给出 extras 安装提示并降级退出，不崩栈；
基准评测与 CLI 通路必须能在零 GUI 依赖的机器上跑完。
"""

from road_mqi_checker.errors import MilestoneNotImplemented, OptionalDependencyMissing

MODULE_KEY = "road_mqi_checker.gui.app"
MILESTONE = "M6"

#: 页签顺序 = 业务链条顺序（导入→评定→汇总→对比→基准→依据→导出）
PAGE_TITLES = (
    "台账与导入",
    "路面 PCI 评定",
    "MQI 汇总与等级",
    "年对比与优先序",
    "基准评测",
    "依据登记与规则集",
    "导出与声明",
)


def build_page_map():
    # type: () -> list
    """页签 → 对应内核命令，GUI 只做转发（测试可不依赖 Qt 直接对账）。"""
    commands = (
        "rmqc import",
        "rmqc assess",
        "rmqc aggregate",
        "rmqc compare",
        "rmqc bench run",
        "rmqc ruleset list",
        "rmqc report",
    )
    return list(zip(PAGE_TITLES, commands))


def _import_qt():
    try:
        from PySide6 import QtWidgets  # noqa: F401  （惰性导入：仅交付层需要）
    except ImportError as exc:
        raise OptionalDependencyMissing("PySide6", "gui")
    return QtWidgets


def main(argv=None):
    """启动桌面壳；M6 之前即使装了 PySide6 也只有骨架窗口。"""
    _import_qt()
    raise MilestoneNotImplemented(MODULE_KEY, MILESTONE, what="PySide6 主窗口")
