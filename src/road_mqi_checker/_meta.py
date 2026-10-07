"""版本与里程碑登记表。

PLACEHOLDER_MILESTONES 是"骨架里哪些模块还是占位符"的唯一事实源：
占位符抛出 MilestoneNotImplemented 时引用这里的 key，守门测试双向对账
（注册表里的键必须真有占位符、抛出的键必须已登记），并在 plan/02 §8 里程碑表里
能找到对应模块行 —— 防止文档与代码漂移出"幽灵模块"。
"""

from typing import Dict

MILESTONE = "M4"
__version__ = "0.0.0"

# 模块路径（相对包根）→ 该模块领域逻辑的交付里程碑
PLACEHOLDER_MILESTONES = {
    "road_mqi_checker.bench.evaluation": "M5",
    "road_mqi_checker.report.exporters": "M6",
    "road_mqi_checker.gui.app": "M6",
}  # type: Dict[str, str]

# 里程碑 → 该里程碑的出口判据主文档（plan/ 下，编号见 plan/00 索引）
MILESTONE_DOCS = {
    "M0": "plan/02-开发计划与架构.md",
    "M1": "plan/03-数据字典与合成数据.md",
    "M2": "plan/05-评定与汇总算法说明.md",
    "M3": "plan/04-扣分规则集与条款映射.md",
    "M4": "plan/05-评定与汇总算法说明.md",
    "M5": "plan/06-基准与评测.md",
    "M6": "plan/07-交付与打包.md",
}  # type: Dict[str, str]

VALID_MILESTONES = ("M0", "M1", "M2", "M3", "M4", "M5", "M6")
