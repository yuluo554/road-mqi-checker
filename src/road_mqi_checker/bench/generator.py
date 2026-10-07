"""合成检测数据生成器（模块 5 的数据侧）。

按典型损坏模式生成"输入 + 真值"同源的一份数据：正常老化、局部突发损坏、
录入异常（负值/超范围/单位错）、路段划分变更。

三条纪律：
1. 真值由生成器自算，不人工填写（保证"数据错→检出"和"分数算得对"两类真值同源）；
2. 随机源只能是 `bench.rng.SplitMix64` + 固定 seed，禁用 stdlib random / 时钟 / set 迭代序；
3. 落盘的每个文件先过 `privacy.check_row` 白名单，并带 `data_class=SYNTHETIC` 标记行。

## 规模与形态（既定口径，改动即基准漂移）

3 条虚拟路线 × 4 个年度 = 12 份"路线-年度"检测表。几何（路段划分）写在 `PARTITION_PLAN`，
随机内容（破损行、实测指标）由 seed 驱动，**注入用例是显式声明的常量**（`INJECTIONS`）——
所以注入缺陷不会因为换 seed 而漂移，换 seed 只换"正常老化"部分的内容。

`SCENARIOS` 是本生成器覆盖的损坏模式词汇：
`normal_aging`（每个路段都有）、`localized_damage`（每路段额外一条"重"程度突发损坏）、
其余七个与 `INJECTED_ISSUES` 同名，由 `INJECTIONS` 声明。

## 真值语义（M1 定稿）

`TRUTH_COLUMNS` 一行 = 一个"路段 × 年度"对象。两类真值同源但口径不同：

1. **数据错 → 检出**（`injected_issue` / `injected_field`），标记落在注入所触及的对象上：
   - `gap_chain` / `overlap_chain` / `shifted`：标在**被移动边界的那个路段行**上；
   - `new` / `split` / `merged`：标在**变更产生的新对象**（拆分/合并后的新路段行）上；
   - `disappeared`：变更后的年度里它已无行可标，因此标在**它最后存在的那一年**的行上；
   - `negative_value` / `out_of_range` / `unit_error` / `duplicate_import`：标在**被污染行所属路段**的行上。

2. **同一注入隐含的其余结论**见 `INJECTION_IMPLICATIONS`（单点定义）。一条注入往往牵动别的
   校验项（例如移动边界既造成悬空，也造成跨年划分变更与闭合差不为零）。这些隐含结论
   **不在真值里手工再写一份**——列名是既定口径，手工二次结论一定会和实际数据漂移；
   校验层与测试都按本表 + 几何事实推断"应当还检出什么"。

3. **分数算得对**（`pci_truth` / `grade_truth` / `mqi_partial_truth` / `recommended_action_truth`）：
   生成器先查**规则集系数门**——本列受哪几格系数支配、那些格子是否 `computable`。
   内置包 15 格全为 pending，所以四列一律写 `pending:coeff=<key>,<key>` 令牌：
   **未核对不出数，真值也一样不出数**。M2 起数值真值由评定引擎本身给出
   （`_numeric_truth_probe` → `pci.engine.compute_pci`，与 `rmqc assess` 同一个内核），
   换上一套系数已核对的规则集包，同一 seed 重跑这两列自动变数值；
   引擎因数据异常拒算的对象仍写 `pending:engine=pci.engine.blocked`，
   所属模块还是占位符的列（M4 的 mqi / 对策）写 `pending:engine=<模块>@M4`。
   生成器内**永不另写一套扣分公式**，避免出现"真值一份公式、引擎另一份公式"的假对账。

## 落盘纪律

不带时间戳；固定 LF；同 seed 两次运行逐字节一致（`--force` 重跑 `git status` 零变化）。
"""

import hashlib
import json
import os
from typing import Dict, List, Optional, Tuple

from road_mqi_checker import privacy
from road_mqi_checker.bench.rng import SplitMix64
from road_mqi_checker.errors import InputUnavailable
from road_mqi_checker.ledger import importer, models
from road_mqi_checker.pci import engine as pci_engine
from road_mqi_checker.ruleset import loader as ruleset_loader

MODULE_KEY = "road_mqi_checker.bench.generator"
MILESTONE = "M1"

#: 损坏模式词汇（生成器的 scenarios 参数合法值）
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
ALWAYS_ON_SCENARIOS = ("normal_aging", "localized_damage")

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
FILE_MARK_LINE = "# %s=%s" % (FILE_MARK_KEY, FILE_MARK_VALUE)

DEFAULT_SEED = 20261007

#: 首期规模口径：3 条虚拟路线 × 4 个年度（M1 出口判据里的量）
DEFAULT_ROUTES = 3
DEFAULT_YEARS = 4
DEFAULT_YEAR_START = 2022

#: 路线顺序固定（决定文件与 manifest 的产出顺序，位级一致的前提之一）
ROUTE_IDS = ("S99", "X990", "Y999")

TRUTH_SUFFIX = ".truth.csv"
MANIFEST_NAME = "manifest.json"
DICTIONARY_VERSION = "1"
MANIFEST_TOP_LEVEL_KEYS = (
    "data_class",
    "dictionary_version",
    "generator",
    "seed",
    "routes",
    "years",
    "schema",
    "files",
    "totals",
    "coefficient_gate",
)

#: 真值四列各自受哪几格系数支配（决定 pending 令牌里点名哪些 key）
TRUTH_GOVERNING_KEYS = {
    "pci_truth": (
        "deduct_ratio.{surface}_distress",
        "pci_component.ride_quality",
        "pci_component.rutting",
        "pci_component.skid_resistance",
        "pci_weight.{surface}",
    ),
    "grade_truth": ("grade_threshold.pci",),
    "mqi_partial_truth": ("mqi_weight.pavement",),
    "recommended_action_truth": ("action_rule.maintenance_trigger",),
}

#: 真值列的"未核对"令牌前缀（读 CSV 的人一看就知道这一列为什么没有数）
PENDING_COEFF_PREFIX = "pending:coeff="
PENDING_ENGINE_PREFIX = "pending:engine="


# ---- 几何与标识符（写成常量表：划分变更、悬空与重叠是几何事实，不由随机数决定）----

ROUTE_PROFILE = {
    "S99": {
        "route_name": "SYN-清河试验线",
        "admin_grade": "二级",
        "tech_grade": "二级",
        "adcode": "990101",
        "lane_count": 2,
        "segment_width_m": 9.0,
        "detect_org": "示例公路工程检测有限公司",
    },
    "X990": {
        "route_name": "SYN-临假水泥线",
        "admin_grade": "三级",
        "tech_grade": "三级",
        "adcode": "990102",
        "lane_count": 2,
        "segment_width_m": 9.0,
        "detect_org": "某某养护中心第 3 分部",
    },
    "Y999": {
        "route_name": "SYN-延长试验线",
        "admin_grade": "二级",
        "tech_grade": "二级",
        "adcode": "990103",
        "lane_count": 1,
        "segment_width_m": 7.5,
        "detect_org": "虚拟路况检测中心",
    },
}  # type: Dict[str, Dict[str, object]]

#: 路线起止桩号（米）按年度登记：Y999 在 2024 年里程延长，是 `new` 划分的载体
ROUTE_EXTENT = {
    ("S99", 2022): (0, 12000),
    ("S99", 2023): (0, 12000),
    ("S99", 2024): (0, 12000),
    ("S99", 2025): (0, 12000),
    ("X990", 2022): (0, 10000),
    ("X990", 2023): (0, 10000),
    ("X990", 2024): (0, 10000),
    ("X990", 2025): (0, 10000),
    ("Y999", 2022): (0, 9000),
    ("Y999", 2023): (0, 9000),
    ("Y999", 2024): (0, 11500),
    ("Y999", 2025): (0, 11500),
}  # type: Dict[Tuple[str, int], Tuple[int, int]]

#: 每个年度的路段划分 (segment_id, start_m, end_m, surface_type, panel_count)。
#: panel_count 只对水泥路面登记，是"该路段板块总数"这一数据事实（不是任何规范阈值）。
PARTITION_PLAN = {
    ("S99", 2022): (
        ("S99-A1", 0, 3000, "asphalt", None),
        ("S99-A2", 3200, 6000, "asphalt", None),  # 与 A1 之间悬空 200 m
        ("S99-A3", 6000, 9000, "asphalt", None),
        ("S99-A4", 9000, 12000, "asphalt", None),
    ),
    ("S99", 2023): (
        ("S99-A1", 0, 3000, "asphalt", None),
        ("S99-A2", 3000, 6000, "asphalt", None),
        ("S99-A3", 6000, 9000, "asphalt", None),
        ("S99-A4", 9000, 12000, "asphalt", None),
    ),
    ("S99", 2024): (
        ("S99-A1", 0, 3000, "asphalt", None),
        ("S99-A2A", 3000, 4500, "asphalt", None),  # A2 拆分为两段
        ("S99-A2B", 4500, 6000, "asphalt", None),
        ("S99-A3", 6000, 9000, "asphalt", None),
        ("S99-A4", 9000, 12000, "asphalt", None),
    ),
    ("S99", 2025): (
        ("S99-A1", 0, 3000, "asphalt", None),
        ("S99-A2A", 3000, 4500, "asphalt", None),
        ("S99-A2B", 4500, 6000, "asphalt", None),
        ("S99-A3", 5900, 9000, "asphalt", None),  # 与 A2B 重叠 100 m
        ("S99-A5", 9000, 12000, "asphalt", None),  # A4 消失、A5 新增
    ),
    ("X990", 2022): (
        ("X990-B1", 0, 4000, "cement", 380),
        ("X990-B2", 4000, 7000, "cement", 285),
        ("X990-B3", 6900, 10000, "cement", 260),  # 与 B2 重叠 100 m
    ),
    ("X990", 2023): (
        ("X990-B1", 0, 4000, "cement", 380),
        ("X990-B2", 4000, 7000, "cement", 285),
        ("X990-B3", 7000, 10000, "cement", 260),
    ),
    ("X990", 2024): (
        ("X990-B1", 0, 4000, "cement", 380),
        ("X990-B23", 4000, 10000, "cement", 480),  # B2 + B3 合并
    ),
    ("X990", 2025): (
        ("X990-B1", 0, 4000, "cement", 380),
        ("X990-B23", 4000, 10000, "cement", 480),
    ),
    ("Y999", 2022): (
        ("Y999-C1", 0, 4000, "asphalt", None),
        ("Y999-C2", 4200, 6500, "asphalt", None),  # 与 C1 之间悬空 200 m
        ("Y999-C3", 6500, 9000, "asphalt", None),
    ),
    ("Y999", 2023): (
        ("Y999-C1", 0, 4000, "asphalt", None),
        ("Y999-C2", 4000, 6500, "asphalt", None),
        ("Y999-C3", 6500, 9000, "asphalt", None),
    ),
    ("Y999", 2024): (
        ("Y999-C1", 0, 4000, "asphalt", None),
        ("Y999-C2", 4000, 6500, "asphalt", None),
        ("Y999-C3", 6500, 9000, "asphalt", None),
        ("Y999-C4", 9000, 11500, "asphalt", None),  # 里程延长后新增
    ),
    ("Y999", 2025): (
        ("Y999-C1", 0, 4100, "asphalt", None),
        ("Y999-C2", 4100, 6500, "asphalt", None),  # 与 C1 的界桩一起外移，链条仍连续
        ("Y999-C3", 6500, 9000, "asphalt", None),
        ("Y999-C4", 9000, 11500, "asphalt", None),
    ),
}  # type: Dict[Tuple[str, int], Tuple[Tuple[str, int, int, str, Optional[int]], ...]]

#: 注入用例（八类每类 ≥2 例）。行级污染写在 `payload`，几何类由 PARTITION_PLAN 承载。
INJECTIONS = (
    {
        "route_id": "S99",
        "year": 2022,
        "segment_id": "S99-A1",
        "issue": "duplicate_import",
        "field": "row",
        "detail": "同一条破损调查记录在文件内出现两次",
        "payload": {
            "distress_type": "坑槽",
            "severity": "中",
            "quantity": 6.5,
            "quantity_unit": "m2",
            "lane_no": 1,
            "twice": True,
        },
    },
    {
        "route_id": "S99",
        "year": 2022,
        "segment_id": "S99-A2",
        "issue": "gap_chain",
        "field": "seg_start_stake",
        "detail": "起点晚于上一路段终点 200 m（悬空）",
        "payload": None,
    },
    {
        "route_id": "S99",
        "year": 2024,
        "segment_id": "S99-A1",
        "issue": "out_of_range",
        "field": "rqi",
        "detail": "行驶质量指数超出该指数的定义域",
        "payload": {"rqi": 108.0},
    },
    {
        "route_id": "S99",
        "year": 2024,
        "segment_id": "S99-A2A",
        "issue": "partition_change",
        "field": "segment_id",
        "detail": "由 S99-A2 拆分而来（split）",
        "payload": None,
    },
    {
        "route_id": "S99",
        "year": 2024,
        "segment_id": "S99-A2B",
        "issue": "partition_change",
        "field": "segment_id",
        "detail": "由 S99-A2 拆分而来（split）",
        "payload": None,
    },
    {
        "route_id": "S99",
        "year": 2024,
        "segment_id": "S99-A4",
        "issue": "partition_change",
        "field": "segment_id",
        "detail": "2025 年起不再存在（disappeared），标记落在其最后存在年度",
        "payload": None,
    },
    {
        "route_id": "S99",
        "year": 2025,
        "segment_id": "S99-A2A",
        "issue": "negative_value",
        "field": "quantity",
        "detail": "坑槽面积为负",
        "payload": {
            "distress_type": "坑槽",
            "severity": "重",
            "quantity": -12.5,
            "quantity_unit": "m2",
            "lane_no": 2,
        },
    },
    {
        "route_id": "S99",
        "year": 2025,
        "segment_id": "S99-A3",
        "issue": "overlap_chain",
        "field": "seg_start_stake",
        "detail": "起点早于上一路段终点，重叠 100 m",
        "payload": None,
    },
    {
        "route_id": "S99",
        "year": 2025,
        "segment_id": "S99-A5",
        "issue": "partition_change",
        "field": "segment_id",
        "detail": "2025 年新出现的路段（new）",
        "payload": None,
    },
    {
        "route_id": "X990",
        "year": 2022,
        "segment_id": "X990-B2",
        "issue": "unit_error",
        "field": "quantity_unit",
        "detail": "坑洞按长度单位登记，量纲与其字典口径不符",
        "payload": {
            "distress_type": "坑洞",
            "severity": "中",
            "quantity": 7.0,
            "quantity_unit": "m",
            "lane_no": 1,
        },
    },
    {
        "route_id": "X990",
        "year": 2022,
        "segment_id": "X990-B3",
        "issue": "overlap_chain",
        "field": "seg_start_stake",
        "detail": "起点早于 B2 终点，重叠 100 m",
        "payload": None,
    },
    {
        "route_id": "X990",
        "year": 2023,
        "segment_id": "X990-B1",
        "issue": "out_of_range",
        "field": "quantity",
        "detail": "破碎板数超过该路段板块总数",
        "payload": {
            "distress_type": "破碎板",
            "severity": "重",
            "quantity": 999,
            "quantity_unit": "块",
            "lane_no": 1,
        },
    },
    {
        "route_id": "X990",
        "year": 2024,
        "segment_id": "X990-B1",
        "issue": "duplicate_import",
        "field": "row",
        "detail": "同一条破损调查记录在文件内出现两次",
        "payload": {
            "distress_type": "裂缝",
            "severity": "轻",
            "quantity": 18.0,
            "quantity_unit": "m",
            "lane_no": 2,
            "twice": True,
        },
    },
    {
        "route_id": "X990",
        "year": 2024,
        "segment_id": "X990-B23",
        "issue": "partition_change",
        "field": "segment_id",
        "detail": "由 X990-B2 与 X990-B3 合并而来（merged）",
        "payload": None,
    },
    {
        "route_id": "Y999",
        "year": 2022,
        "segment_id": "Y999-C1",
        "issue": "negative_value",
        "field": "quantity",
        "detail": "纵向裂缝长度为负",
        "payload": {
            "distress_type": "纵向裂缝",
            "severity": "轻",
            "quantity": -30.0,
            "quantity_unit": "m",
            "lane_no": 1,
        },
    },
    {
        "route_id": "Y999",
        "year": 2022,
        "segment_id": "Y999-C2",
        "issue": "gap_chain",
        "field": "seg_start_stake",
        "detail": "起点晚于 C1 终点 200 m（悬空）",
        "payload": None,
    },
    {
        "route_id": "Y999",
        "year": 2024,
        "segment_id": "Y999-C4",
        "issue": "partition_change",
        "field": "segment_id",
        "detail": "里程延长后新增路段（new）",
        "payload": None,
    },
    {
        "route_id": "Y999",
        "year": 2025,
        "segment_id": "Y999-C2",
        "issue": "partition_change",
        "field": "segment_id",
        "detail": "与 C1 的界桩一起外移 100 m（shifted，链条仍连续）",
        "payload": None,
    },
    {
        "route_id": "Y999",
        "year": 2025,
        "segment_id": "Y999-C3",
        "issue": "unit_error",
        "field": "quantity_unit",
        "detail": "网状裂缝按长度单位登记，量纲与其字典口径不符",
        "payload": {
            "distress_type": "网状裂缝",
            "severity": "中",
            "quantity": 24.0,
            "quantity_unit": "m",
            "lane_no": 1,
        },
    },
)

#: 同一注入隐含的其余结论（真值只标一个 injected_issue，其余结论由本表 + 几何事实推断）。
INJECTION_IMPLICATIONS = {
    "gap_chain": (
        "移动边界使该路段与相邻年度同 id 路段边界不同 → 跨年划分变更应报 shifted",
        "路段长度和与路线里程的闭合差不为零 → length_closure 只能报'待核对，未判定'（容差 pending）",
        "该路段自身与其破损行仍可入库，评分通路不受影响（M2 前一律 blocked）",
    ),
    "overlap_chain": (
        "重叠区间被两个路段同时主张 → 里程加权会重复计账，跨年对比相应对象标 shifted 不可比",
        "闭合差为负（长度和超出里程）→ length_closure 只能报'待核对，未判定'",
    ),
    "partition_change": (
        "涉及对象跨年不可比：只出划分变更清单，不得按比例摊分",
        "disappeared 的标记落在其最后存在年度，该年度自身的其它校验项仍应干净",
    ),
    "negative_value": (
        "该行必须能入库（表上不设 CHECK 约束），由 value_range 检出",
        "负扣分不可解释 → 该路段评分通路应拒算（M2 起由 pci.engine 保证）",
    ),
    "out_of_range": (
        "超过几何上界或指标定义域 → 扣分不可解释，评分通路应拒算",
        "该行仍入库，由 value_range 检出，不被导入层丢弃",
    ),
    "unit_error": (
        "量纲与字典口径不符 → 换算所需分母不存在，评分通路应拒算",
        "该行仍入库，由 unit_consistency 检出；破损类型本身合法，distress_dictionary 不应重复报同一行",
    ),
    "duplicate_import": (
        "文件内完全重复行：第二行在导入层拒入（R008），不得进入台账",
        "同一份文件按 digest 重复导入：整份拒入、入库行数为 0",
    ),
    "none": ("八类校验项都不得报出该对象 —— 报出即为误报"),
}


# ---- 规模与计划查询 ----


def raw_file_name(route_id, year):
    # type: (str, int) -> str
    return "%s-%d.csv" % (route_id, year)


def truth_file_name(route_id, year):
    # type: (str, int) -> str
    return "%s-%d%s" % (route_id, year, TRUTH_SUFFIX)


def plan_routes(count=DEFAULT_ROUTES):
    # type: (int) -> List[str]
    if count > len(ROUTE_IDS):
        raise InputUnavailable("首期只登记了 %d 条虚拟路线，routes=%d 超出规模口径" % (len(ROUTE_IDS), count))
    return list(ROUTE_IDS[:count])


def plan_years(count=DEFAULT_YEARS, start=DEFAULT_YEAR_START):
    # type: (int, int) -> List[int]
    return [start + offset for offset in range(count)]


def injection_marks(route_id, year, enabled=None):
    # type: (str, int, Optional[Tuple[str, ...]]) -> Dict[str, Dict[str, object]]
    """该"路线-年度"格子里的注入声明：segment_id → 条目。"""
    marks = {}  # type: Dict[str, Dict[str, object]]
    for item in INJECTIONS:
        if enabled is not None and item["issue"] not in enabled:
            continue
        if item["route_id"] == route_id and item["year"] == year:
            marks[item["segment_id"]] = item
    return marks


def injection_plan(enabled=None):
    # type: (Optional[Tuple[str, ...]]) -> List[Dict[str, object]]
    """注入用例清单（测试与 manifest 都按它对账，不另抄一份）。"""
    return [
        {
            "route_id": item["route_id"],
            "year": item["year"],
            "segment_id": item["segment_id"],
            "injected_issue": item["issue"],
            "injected_field": item["field"],
        }
        for item in sorted(INJECTIONS, key=lambda i: (i["route_id"], i["year"], i["segment_id"], i["issue"]))
        if enabled is None or item["issue"] in enabled
    ]


# ---- 内容生成 ----


def _number(value, decimals=1):
    # type: (Optional[float], int) -> str
    if value is None:
        return ""
    return ("%." + str(decimals) + "f") % float(value)


def _aging_distress(rng, surface_type, length_m, lane_count, panel_count, width_m):
    # type: (SplitMix64, str, int, int, Optional[int], float) -> List[Dict[str, object]]
    """正常老化：类型随机、数量落在几何上界内（保证干净行不会被判成超范围）。"""
    pool = sorted(models.DISTRESS_DICTIONARY[surface_type].keys())
    picked = rng.sample_without_replacement(pool, 1 + rng.next_below(3))
    rows = []  # type: List[Dict[str, object]]
    for distress_type in picked:
        entry = models.DISTRESS_DICTIONARY[surface_type][distress_type]
        extent = entry["extent"]
        upper = models.geometric_upper_bound(extent, length_m, lane_count, width_m, panel_count)
        if extent == "panel":
            quantity = float(1 + rng.next_below(max(1, int(panel_count or 1) // 10)))
        elif extent == "area":
            quantity = pci_engine.quantize(rng.next_float() * 12.0 + 0.5, 1)
        else:
            quantity = pci_engine.quantize(rng.next_float() * length_m * 0.02 + 1.0, 1)
        if upper is not None and quantity > upper * 0.9:
            quantity = pci_engine.quantize(upper * 0.4, 1)
        rows.append(
            {
                "scenario": "normal_aging",
                "distress_type": distress_type,
                "severity": rng.choice(list(models.SEVERITY_LEVELS)),
                "quantity": quantity,
                "quantity_unit": entry["unit"],
                "lane_no": 1 + rng.next_below(lane_count),
            }
        )
    return rows


def _burst_distress(rng, surface_type, length_m, lane_count, panel_count, width_m):
    # type: (SplitMix64, str, int, int, Optional[int], float) -> Dict[str, object]
    """局部突发损坏：一条"重"程度的破损行，数量控制在几何上界以内（否则干净数据会被判超范围）。"""
    pool = sorted(models.DISTRESS_DICTIONARY[surface_type].keys())
    distress_type = rng.choice(pool)
    entry = models.DISTRESS_DICTIONARY[surface_type][distress_type]
    upper = models.geometric_upper_bound(entry["extent"], length_m, lane_count, width_m, panel_count)
    if entry["extent"] == "panel":
        quantity = float(1 + rng.next_below(max(1, min(8, int(panel_count or 1) // 20))))
    elif entry["extent"] == "area":
        ceiling = 200.0 if upper is None else min(200.0, upper * 0.2)
        quantity = pci_engine.quantize(rng.next_float() * (ceiling - 2.0) + 2.0, 1)
    else:
        ceiling = min(float(length_m) * 0.2, 60.0 + rng.next_float() * 40.0)
        quantity = pci_engine.quantize(rng.next_float() * ceiling + 1.0, 1)
    if upper is not None and quantity > upper:
        quantity = pci_engine.quantize(upper * 0.25, 1)
    return {
        "scenario": "localized_damage",
        "distress_type": distress_type,
        "severity": "重",
        "quantity": quantity,
        "quantity_unit": entry["unit"],
        "lane_no": 1 + rng.next_below(lane_count),
    }


def _indicators(rng, surface_type):
    # type: (SplitMix64, str) -> Dict[str, object]
    """实测指标：只保证落在自身定义域内，取值与任何规范分级无关。"""
    return {
        "rqi": pci_engine.quantize(60.0 + rng.next_float() * 39.0, 1),
        "rut_depth_mm": None if surface_type == "cement" else pci_engine.quantize(1.5 + rng.next_float() * 8.0, 1),
        "skid_indicator": pci_engine.quantize(40.0 + rng.next_float() * 55.0, 1),
        "skid_indicator_kind": "SFC",
    }


def _apply_payload(indicators, distress_rows, payload):
    # type: (Dict[str, object], List[Dict[str, object]], Optional[Dict[str, object]]) -> None
    """把注入声明落到行上：行级污染是常量声明，不受 seed 影响。"""
    if not payload:
        return
    if "rqi" in payload:
        indicators["rqi"] = payload["rqi"]
        return
    row = {
        "scenario": payload.get("issue", "injected"),
        "distress_type": payload["distress_type"],
        "severity": payload["severity"],
        "quantity": float(payload["quantity"]),
        "quantity_unit": payload["quantity_unit"],
        "lane_no": payload["lane_no"],
    }
    if payload.get("twice"):
        distress_rows.append(dict(row))
        distress_rows.append(dict(row))
    else:
        distress_rows.append(row)


def _segment_name(route_id, segment_id, start_m, end_m):
    # type: (str, str, int, int) -> str
    tail = segment_id.split("-", 1)[1]
    return "SYN-%s%s段 %s～%s" % (route_id, tail, models.format_stake(start_m), models.format_stake(end_m))


def ruleset_pending_keys(ruleset, templates, surface_type):
    # type: (object, Tuple[str, ...], str) -> List[str]
    """模板展开后仍未核对（或规则集根本没登记）的系数 key，按字典序返回。"""
    pending = []  # type: List[str]
    for template in templates:
        key = template.format(surface=surface_type)
        coef = ruleset.find(key)
        if coef is None:
            pending.append(key + "(未登记)")
        elif not coef.computable:
            pending.append(key)
    return sorted(pending)


def _score_truth(surface_type, ruleset, probe_input):
    # type: (str, object, Dict[str, object]) -> Dict[str, str]
    """真值四列：先过系数门，未核对一律出 pending 令牌（未核对不出数，真值也不出数）。"""
    out = {}  # type: Dict[str, str]
    for column in TRUTH_SCORE_COLUMNS:
        pending = ruleset_pending_keys(ruleset, TRUTH_GOVERNING_KEYS[column], surface_type)
        if pending:
            out[column] = PENDING_COEFF_PREFIX + ",".join(pending)
        else:
            out[column] = _numeric_truth_probe(column, surface_type, ruleset, probe_input)
    return out


#: 真值四列 → 该列数值由哪个模块给出（该模块还是占位符时，这一列如实标 pending:engine=…@Mx）
TRUTH_ENGINE_MODULES = {
    "pci_truth": "road_mqi_checker.pci.engine",
    "grade_truth": "road_mqi_checker.pci.engine",
    "mqi_partial_truth": "road_mqi_checker.mqi.engine",
    "recommended_action_truth": "road_mqi_checker.strategy.rules",
}
TRUTH_SCORE_COLUMNS = ("pci_truth", "grade_truth", "mqi_partial_truth", "recommended_action_truth")
PCI_TRUTH_COLUMNS = ("pci_truth", "grade_truth")


def _probe_float(text):
    # type: (object) -> object
    """落盘文本 → 评定核要的数值；解析不了就把原样交给引擎（引擎按"不是数值"拒算）。"""
    if text is None or text == "":
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return text


def _probe_input(base, cell_rows, length_m, panel_count, first_row_index):
    # type: (Dict[str, object], List[Dict[str, object]], int, Optional[int], int) -> Dict[str, object]
    """拼出评定核的输入：**取已经落盘的文本值**，真值因此是"引擎对那份 CSV 的算法结果"。

    `source_row_no` 用该行在 raw 表里的数据行序（与 `ledger.importer.read_table` 同一套编号），
    贡献展开于是能从真值一路指回原始检测表的具体行。
    """
    distress_rows = []  # type: List[Dict[str, object]]
    seen_identities = set()  # type: set
    for offset, row in enumerate(cell_rows, start=first_row_index + 1):
        if not row.get("distress_type") and not row.get("quantity"):
            continue  # 无破损调查记录的行（NO_DISTRESS_VALUES），不参与扣分
        identity = tuple(str(row.get(name)) for name in importer.DUPLICATE_KEY_COLUMNS)
        if identity in seen_identities:
            # 导入层的 R008 会把这份文件里第二次出现的同一行拒在台账外，
            # 真值必须描述"进了台账的那本账"，否则真值与评定通路的输入就不是同一份数据
            continue
        seen_identities.add(identity)
        distress_rows.append(
            {
                "distress_type": row.get("distress_type"),
                "severity": row.get("severity"),
                "quantity": _probe_float(row.get("quantity")),
                "quantity_unit": row.get("quantity_unit"),
                "lane_no": row.get("lane_no"),
                "source_row_no": offset,
            }
        )
    return {
        "segment_id": base["segment_id"],
        "route_id": base["route_id"],
        "year": base["year"],
        "surface_type": base["surface_type"],
        "length_m": length_m,
        "lane_count": base["lane_count"],
        "segment_width_m": _probe_float(base["segment_width_m"]),
        "panel_count": panel_count,
        "skid_indicator_kind": base["skid_indicator_kind"],
        "indicators": {
            "rqi": _probe_float(base["rqi"]),
            "rut_depth_mm": _probe_float(base["rut_depth_mm"]),
            "skid_indicator": _probe_float(base["skid_indicator"]),
        },
        "distress_rows": distress_rows,
        "has_survey": True,
    }


def _numeric_truth_probe(column, surface_type, ruleset, probe_input):
    # type: (str, str, object, Dict[str, object]) -> str
    """数值真值通路：必须由评定引擎本身给出（同源），引擎未就位或拒算则如实标 pending。

    系数门已经在上游放行（`_score_truth` 先查 `TRUTH_GOVERNING_KEYS`），到这里还剩两种可能：
    所属模块仍是占位符（M4/M5 的 mqi、对策列）→ 点名模块与里程碑；
    评定引擎对该对象拒算（台账含异常行）→ 仍不出数，因为"未核对不出数"对真值同样成立。
    """
    from road_mqi_checker import _meta, results as res

    module_key = TRUTH_ENGINE_MODULES[column]
    short_name = module_key.replace("road_mqi_checker.", "")
    if module_key in _meta.PLACEHOLDER_MILESTONES:
        return PENDING_ENGINE_PREFIX + "%s@%s" % (short_name, _meta.PLACEHOLDER_MILESTONES[module_key])
    if column not in PCI_TRUTH_COLUMNS:
        return PENDING_ENGINE_PREFIX + "%s.no_truth_hook" % short_name
    pci_result = pci_engine.compute_pci(probe_input, ruleset)
    if pci_result.status in (res.STATUS_BLOCKED, res.STATUS_UNCOMPARABLE):
        return PENDING_ENGINE_PREFIX + "pci.engine.blocked"
    if column == "pci_truth":
        return _number(pci_result.pci, pci_engine.PCI_DECIMALS)
    return pci_result.grade


def build_cell(route_id, year, rng, ruleset, enabled=None):
    # type: (str, int, SplitMix64, object, Optional[Tuple[str, ...]]) -> Tuple[List[Dict[str, object]], List[Dict[str, object]], List[str], Dict[str, Dict[str, object]]]
    """一个"路线-年度"格子：返回 (raw 行, truth 行, 覆盖的损坏模式, 注入声明)。"""
    profile = ROUTE_PROFILE[route_id]
    route_start, route_end = ROUTE_EXTENT[(route_id, year)]
    marks = injection_marks(route_id, year, enabled=enabled)
    lane_count = int(profile["lane_count"])
    width_m = float(profile["segment_width_m"])
    raw_rows = []  # type: List[Dict[str, object]]
    truth_rows = []  # type: List[Dict[str, object]]
    scenarios = set(ALWAYS_ON_SCENARIOS)
    for seq, spec in enumerate(PARTITION_PLAN[(route_id, year)], start=1):
        segment_id, start_m, end_m, surface_type, panel_count = spec
        length_m = end_m - start_m
        indicators = _indicators(rng, surface_type)
        distress_rows = _aging_distress(rng, surface_type, length_m, lane_count, panel_count, width_m)
        distress_rows.append(_burst_distress(rng, surface_type, length_m, lane_count, panel_count, width_m))
        mark = marks.get(segment_id)
        if mark is not None:
            scenarios.add(str(mark["issue"]))
            if mark["payload"] is not None:
                payload = dict(mark["payload"])
                payload["issue"] = str(mark["issue"])
                _apply_payload(indicators, distress_rows, payload)
        first_row_index = len(raw_rows)
        base = {
            "year": year,
            "route_id": route_id,
            "route_name": profile["route_name"],
            "admin_grade": profile["admin_grade"],
            "tech_grade": profile["tech_grade"],
            "route_start_stake": models.format_stake(route_start),
            "route_end_stake": models.format_stake(route_end),
            "adcode": profile["adcode"],
            "segment_id": segment_id,
            "segment_name": _segment_name(route_id, segment_id, start_m, end_m),
            "seg_start_stake": models.format_stake(start_m),
            "seg_end_stake": models.format_stake(end_m),
            "surface_type": surface_type,
            "lane_count": lane_count,
            "segment_width_m": _number(width_m, 1),
            "panel_count": "" if panel_count is None else panel_count,
            "rqi": _number(indicators["rqi"], 1),
            "rut_depth_mm": _number(indicators["rut_depth_mm"], 1),
            "skid_indicator": _number(indicators["skid_indicator"], 1),
            "skid_indicator_kind": indicators["skid_indicator_kind"],
            "report_no": "SYN-LG-%d-%04d" % (year, seq),
            "detect_org": profile["detect_org"],
            # 输入数据里不写注入说明：真值只落在 truth/ 与 manifest，避免把答案泄漏进检测表
            "note": "",
        }
        if not distress_rows:
            row = dict(base)
            row.update(models.NO_DISTRESS_VALUES)
            raw_rows.append(row)
        else:
            for distress in distress_rows:
                row = dict(base)
                row["distress_type"] = distress["distress_type"]
                row["severity"] = distress["severity"]
                row["quantity"] = _number(distress["quantity"], 1)
                row["quantity_unit"] = distress["quantity_unit"]
                row["lane_no"] = distress["lane_no"]
                raw_rows.append(row)
        truth = {
            "segment_id": segment_id,
            "route_id": route_id,
            "year": year,
            "surface_type": surface_type,
            "injected_issue": (str(mark["issue"]) if mark else "none"),
            "injected_field": (str(mark["field"]) if mark else ""),
        }
        truth.update(
            _score_truth(
                surface_type,
                ruleset,
                _probe_input(base, raw_rows[first_row_index:], length_m, panel_count, first_row_index),
            )
        )
        truth_rows.append(truth)
    return raw_rows, truth_rows, sorted(scenarios), marks


# ---- 序列化（固定 LF、固定列序、固定引号规则）----


def _csv_cell(value):
    # type: (object) -> str
    if value is None:
        return ""
    text = value if isinstance(value, str) else str(value)
    if any(ch in text for ch in (",", '"', "\n")):
        return '"%s"' % text.replace('"', '""')
    return text


def render_csv(columns, rows, mark=True):
    # type: (Tuple[str, ...], List[Dict[str, object]], bool) -> str
    header = ("%s\n" % FILE_MARK_LINE) if mark else ""
    lines = [header + ",".join(columns)]
    for row in rows:
        lines.append(",".join(_csv_cell(row.get(column, "")) for column in columns))
    return "\n".join(lines) + "\n"


def render_json(payload):
    # type: (Dict[str, object]) -> str
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def digest(text):
    # type: (str) -> str
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def write_text(path, text):
    # type: (str, str) -> None
    """固定 LF 落盘：不经平台换行，Windows 上也写不出 CRLF。"""
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def write_if_changed(path, text, force):
    # type: (str, str, bool) -> bool
    """内容一致就不重写：重跑同一 seed 是幂等的，`git status` 自然零变化。

    只有"真的要改动已入仓的演示数据"时才需要显式 `--force` —— 这比"文件存在就拒绝"更有用：
    既让 README 里的重生成命令在干净 clone 上直接可跑，又守得住冻结 fixtures 不被误改。
    """
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8", newline="") as handle:
            if handle.read() == text:
                return False
        if not force:
            raise InputUnavailable(
                "%s 已入仓且内容与本次生成结果不同：演示数据是冻结 fixtures，覆盖要显式 --force" % path
            )
    write_text(path, text)
    return True


def truth_dir_for(out_dir):
    # type: (str) -> str
    parent = os.path.dirname(out_dir.rstrip("/\\"))
    return os.path.join(parent if parent else ".", "truth")


def generate(out_dir, seed=DEFAULT_SEED, routes=DEFAULT_ROUTES, years=DEFAULT_YEARS, force=False, truth_dir=None, scenarios=None, ruleset=None):
    """生成 raw 检测表 + truth 真值 + manifest；同 seed 两次运行必须逐字节一致。

    - `ruleset=None` 时按内置/用户目录选取（交付面走的就是这条），测试可显式注入夹具包；
    - 落盘前逐行过 `privacy.check_row`，白名单外一律不落盘（宁可不出文件）；
    - `force=False` 时目标文件已存在即拒绝，避免误改冻结 fixtures；
    - `scenarios` 只用于取损坏模式的子集（默认全量），不改规模口径。
    """
    if seed is None or seed < 0:
        raise InputUnavailable("seed 必须是非负整数，收到 %r" % (seed,))
    enabled = None  # type: Optional[Tuple[str, ...]]
    if scenarios is not None:
        unknown = sorted(set(scenarios) - set(SCENARIOS))
        if unknown:
            raise InputUnavailable("未知损坏模式 %s，合法值见 SCENARIOS" % ", ".join(unknown))
        enabled = tuple(sorted(set(scenarios)))
    route_ids = plan_routes(routes)
    year_values = plan_years(years)
    for route_id in route_ids:
        for year in year_values:
            if (route_id, year) not in PARTITION_PLAN:
                raise InputUnavailable(
                    "生成计划缺少 %s/%d 格子：规模口径与 PARTITION_PLAN 不一致" % (route_id, year)
                )
    out_dir = out_dir.rstrip("/\\") or "."
    truth_out = truth_dir if truth_dir else truth_dir_for(out_dir)

    ruleset = ruleset_loader.select_ruleset() if ruleset is None else ruleset
    rng = SplitMix64(seed)
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(truth_out, exist_ok=True)

    manifest_files = []  # type: List[Dict[str, object]]
    written = 0
    totals = {"raw_rows": 0, "truth_rows": 0, "injected_cases": 0, "by_issue": {}, "clean_cells": []}
    for route_id in route_ids:
        for year in year_values:
            raw_rows, truth_rows, scenarios_in_cell, marks = build_cell(
                route_id, year, rng, ruleset, enabled=enabled
            )
            for row in raw_rows:
                privacy.check_row(models.identifier_fields(row))
            for row in truth_rows:
                privacy.check_row({"route_id": row["route_id"]})

            raw_text = render_csv(models.RAW_COLUMNS, raw_rows)
            truth_text = render_csv(TRUTH_COLUMNS, truth_rows)
            raw_path = os.path.join(out_dir, raw_file_name(route_id, year))
            truth_path = os.path.join(truth_out, truth_file_name(route_id, year))
            for path, text in ((raw_path, raw_text), (truth_path, truth_text)):
                if write_if_changed(path, text, force):
                    written += 1

            issues = sorted({str(row["injected_issue"]) for row in truth_rows if row["injected_issue"] != "none"})
            for row in truth_rows:
                if row["injected_issue"] != "none":
                    key = str(row["injected_issue"])
                    totals["injected_cases"] += 1
                    totals["by_issue"][key] = totals["by_issue"].get(key, 0) + 1
            if not issues:
                totals["clean_cells"].append("%s-%d" % (route_id, year))
            manifest_files.append(
                {
                    "data_class": FILE_MARK_VALUE,
                    "raw_file": os.path.basename(raw_path),
                    "truth_file": os.path.basename(truth_path),
                    "route_id": route_id,
                    "year": year,
                    "raw_rows": len(raw_rows),
                    "truth_rows": len(truth_rows),
                    "raw_sha1": digest(raw_text),
                    "truth_sha1": digest(truth_text),
                    "scenarios": scenarios_in_cell,
                    "injected_issues": issues,
                    "injections": [
                        {
                            "segment_id": segment_id,
                            "injected_issue": str(mark["issue"]),
                            "injected_field": str(mark["field"]),
                            "detail": str(mark["detail"]),
                        }
                        for segment_id, mark in sorted(marks.items())
                    ],
                }
            )
            totals["raw_rows"] += len(raw_rows)
            totals["truth_rows"] += len(truth_rows)

    summary = ruleset.summary()
    manifest = {
        "data_class": FILE_MARK_VALUE,
        "dictionary_version": DICTIONARY_VERSION,
        "generator": MODULE_KEY,
        "seed": seed,
        "routes": route_ids,
        "years": year_values,
        "schema": {"raw_columns": list(models.RAW_COLUMNS), "truth_columns": list(TRUTH_COLUMNS)},
        "files": manifest_files,
        "totals": totals,
        "coefficient_gate": {
            "ruleset_id": summary["ruleset_id"],
            "active": summary["computable"],
            "blocked": summary["blocked"],
            "truth_note": "生效系数 0 格时真值四列一律为 pending 令牌：未核对不出数",
        },
    }
    assert sorted(manifest) == sorted(MANIFEST_TOP_LEVEL_KEYS), "manifest 顶层键与 plan/03 登记的格式不一致"
    manifest_path = os.path.join(out_dir, MANIFEST_NAME)
    if write_if_changed(manifest_path, render_json(manifest), force):
        written += 1
    return {
        "raw_dir": out_dir,
        "truth_dir": truth_out,
        "manifest": manifest_path,
        "files_written": len(manifest_files) * 2 + 1,
        "files_changed": written,
        "totals": totals,
    }
