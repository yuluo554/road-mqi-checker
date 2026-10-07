"""合成检测数据生成器（模块 5 的数据侧，逻辑属 M1）。

按典型损坏模式生成"输入 + 真值"同源的一份数据：
正常老化、局部突发损坏、录入异常（负值/超范围/单位错）、路段划分变更。

三条纪律：
1. 真值由生成器按自算公式输出，不人工填写（保证"数据错→检出"和"分数算得对"同源）；
2. 随机源只能是 bench.rng.SplitMix64 + 固定 seed，禁用 stdlib random / 时钟 / set 迭代序；
3. 落盘的每个文件先过 privacy.check_row 白名单，并带 SYNTHETIC 标记。

真值列名与 data/README §三 的约定一致（既定口径，改列名要同步评测与文档）。
"""

from road_mqi_checker.errors import MilestoneNotImplemented

MODULE_KEY = "road_mqi_checker.bench.generator"
MILESTONE = "M1"

#: 损坏模式词汇（生成器的 scenario 参数合法值）
SCENARIOS = (
    "normal_aging",
    "localized_damage",
    "negative_value",
    "out_of_range",
    "unit_error",
    "gap_chain",
    "overlap_chain",
    "partition_change",
    "duplicate_import",
)

TRUTH_COLUMNS = (
    "segment_id",
    "route_id",
    "year",
    "surface_type",
    "pci_truth",
    "grade_truth",
    "mqi_partial_truth",
    "recommended_action_truth",
    "injected_issue",
    "injected_field",
)

#: 生成文件必须带的标记行（防"真实数据混进仓库"）
FILE_MARK_KEY = "data_class"
FILE_MARK_VALUE = "SYNTHETIC"

DEFAULT_SEED = 20261007

#: 首期规模口径：3 条虚拟路线 × 4 个年度（M1 出口判据里的量）
DEFAULT_ROUTES = 3
DEFAULT_YEARS = 4


def generate(out_dir, seed=DEFAULT_SEED, routes=DEFAULT_ROUTES, years=DEFAULT_YEARS, force=False):
    """生成 raw 检测表 + truth 真值 + manifest；同 seed 两次运行必须逐字节一致。"""
    raise MilestoneNotImplemented(MODULE_KEY, MILESTONE, what="合成检测数据与真值生成")
