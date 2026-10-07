"""基准评测：两通路 × 四态指标（模块 5，M5 交付）。

四态是这道题的诚实线：分母为 0 叫「不可判」，通路拿不到叫「不可用」，
两者都不许挤进「达标 / 未达标」。M5 把指标算出来了，但**没有把不可判算成达标**：
内置规则集的 14 格规范系数仍是 pending，交付面 assess / aggregate / 对策 / 年对比全部拒算，
任何数值类指标在内置包通路上的分母都是 0。

因此每条指标按 **通路 × 指标** 出一行，逐行显式报 `分子 / 分母 / 状态`：

- `builtin`（内置包，交付面）：通路存在但不出数 ⇒ 数值类指标一律「不可判（分母为 0）」；
  不消费系数的两项（异常召回、误报）与产物位级一致照样实测。
- `fixture`（夹具包，数值通路）：出数并可复算，数字只说明算术与口径自洽，
  **不等于**规范口径下的达标（夹具值刻意避开任何真实规范数字，`plan/02` §四）。

「等级判定准确率」在两通路都是不可判：判定通路已交付、夹具包下出等级的对象数以十计，
但等级真值由同一内核算出，没有独立的规范真值可比（分级阈值官方原文不可得，`plan/04`）。
这类「已声明的不可判」写在 `DECLARED_INDETERMINATE` 里，门禁对它们不红；
新增不可判项要显式登记，否则按数据门事故处理（退出码 2）。

状态→退出码的映射仍由 `STATE_TO_EXIT` 单点定义（锁在 `test_cli_contract.py`）；
`gate()` 在其之上叠加「名单内不可判豁免」，口径见 `plan/06` §四。
"""

import copy
import json
import os
import shutil
import tempfile
from typing import Dict, List, Optional, Sequence, Tuple

from road_mqi_checker import privacy, results as res
from road_mqi_checker.bench import generator
from road_mqi_checker.exit_codes import (
    EXIT_CODE_MEANINGS,
    EXIT_DEGRADED,
    EXIT_INPUT_UNUSABLE,
    EXIT_OK,
    EXIT_UNIMPLEMENTED,
)
from road_mqi_checker.ledger import checks as ledger_checks
from road_mqi_checker.ledger import db as ledger_db
from road_mqi_checker.ledger import importer
from road_mqi_checker.mqi import engine as mqi_engine
from road_mqi_checker.pci import engine as pci_engine
from road_mqi_checker.pci import trace as pci_trace
from road_mqi_checker.ruleset import loader as ruleset_loader
from road_mqi_checker.strategy import compare as year_compare
from road_mqi_checker.strategy import rules as action_rules

MODULE_KEY = "road_mqi_checker.bench.evaluation"
MILESTONE = "M5"

METRIC_PASS = "达标"
METRIC_FAIL = "未达标"
METRIC_INDETERMINATE = "不可判"  # 分母为 0（如数值真值格尚未出数）
METRIC_UNAVAILABLE = "不可用"  # 通路拿不到（如夹具包不在交付面上）

METRIC_STATES = (METRIC_PASS, METRIC_FAIL, METRIC_INDETERMINATE, METRIC_UNAVAILABLE)

#: 指标行 → CLI 退出码：不可判走 2（数据门），未达标走 1，不可用走 3（通路门）
STATE_TO_EXIT = {
    METRIC_PASS: EXIT_OK,
    METRIC_FAIL: EXIT_DEGRADED,
    METRIC_INDETERMINATE: EXIT_INPUT_UNUSABLE,
    METRIC_UNAVAILABLE: EXIT_UNIMPLEMENTED,
}

#: 门禁的严重度顺序：未达标 > 不可用 > 名单外新不可判
GATE_PRECEDENCE = (METRIC_FAIL, METRIC_UNAVAILABLE, METRIC_INDETERMINATE)

#: 两条通路。措辞不得互相顶替（`plan/HANDOFF-M5` §二 第 2 条）
PATH_BUILTIN = "builtin"
PATH_FIXTURE = "fixture"
PATH_ORDER = (PATH_BUILTIN, PATH_FIXTURE)
PATH_LABELS = {
    PATH_BUILTIN: "内置包（交付面）",
    PATH_FIXTURE: "夹具包（数值通路）",
}
PATH_HONESTY = {
    PATH_BUILTIN: "内置包不消费未核对系数，本通路数字只说明交付面的行为，不说明数值正确性。",
    PATH_FIXTURE: "夹具值是虚构数，本通路数字只说明算术与口径自洽，不是规范口径下的达标。",
}

#: 夹具包文件名（值只在 tests/fixtures，交付面红线见 test_release_redlines.py）
FIXTURE_ASPHALT_PACK = "m4-fixture-asphalt.json"
FIXTURE_CEMENT_PACK = "pci-fixture-cement.json"
FIXTURE_MERGED_ID = "m5-bench-fixture-both"

#: 指标清单：README 评测表与此逐行对账，顺序即表格行序
METRICS = (
    "rescore_drift",  # 评分复算误差，目标 0
    "grade_accuracy",  # 等级判定准确率
    "contribution_order",  # 扣分贡献项排序一致性
    "aggregation_consistency",  # MQI 汇总口径一致性（三级同一分母可互相复算）
    "change_contribution_order",  # 变化贡献项排序一致性
    "anomaly_recall",  # 数据异常识别召回
    "anomaly_false_alarm",  # 数据异常识别误报，目标 0
    "byte_reproducible",  # 生成器/产物位级一致
)

METRIC_NAMES = {
    "rescore_drift": "评分复算误差",
    "grade_accuracy": "等级判定准确率",
    "contribution_order": "扣分贡献项排序一致性",
    "aggregation_consistency": "MQI 汇总口径一致性",
    "change_contribution_order": "变化贡献项排序一致性",
    "anomaly_recall": "数据异常识别召回",
    "anomaly_false_alarm": "数据异常识别误报",
    "byte_reproducible": "产物位级一致",
}

TARGETS = {
    "rescore_drift": "= 0",
    "grade_accuracy": ">= 0.95",
    "contribution_order": ">= 0.95",
    "aggregation_consistency": "三级同一分母可互相复算",
    "change_contribution_order": ">= 0.95",
    "anomaly_recall": ">= 0.95",
    "anomaly_false_alarm": "= 0",
    "byte_reproducible": "两次运行逐字节一致",
}

#: 比值类指标的显示精度（1.00 / 0.00 这一档；得分与占比口径不动，见 plan/02 §9 第 29 条）
METRIC_DECIMALS = 2

#: 值 = 分子 / 分母 的指标（阈值见 RATIO_TARGETS；aggregation_consistency 无阈值，只报相符率）
RATIO_METRICS = (
    "grade_accuracy",
    "contribution_order",
    "aggregation_consistency",
    "change_contribution_order",
    "anomaly_recall",
    "anomaly_false_alarm",
)

#: 比值类指标阈值；anomaly_false_alarm 是「越低越好」，单独处理
RATIO_TARGETS = {
    "grade_accuracy": 0.95,
    "contribution_order": 0.95,
    "change_contribution_order": 0.95,
    "anomaly_recall": 0.95,
    "anomaly_false_alarm": 0.0,
}

#: 真值注入类别 → 该由哪一项确定性校验检出（`test_m1_pipeline.py` 引用本表，单点定义）
EXPECTED_KIND_BY_ISSUE = {
    "gap_chain": "stake_gap",
    "overlap_chain": "stake_overlap",
    "unit_error": "unit_consistency",
    "negative_value": "value_range",
    "out_of_range": "value_range",
    "duplicate_import": "duplicate_import",
}
PARTITION_ISSUE = "partition_change"

#: 已声明的不可判名单（(指标, 通路)）。新增要显式登记并说明为什么；
#: 把不可判改成达标以求表格好看，等于把误报做成达标。
DECLARED_INDETERMINATE = frozenset(
    {
        # 内置包必需格未齐 ⇒ 数值类指标的分母为 0（通路存在，但没有数字可比）
        ("rescore_drift", PATH_BUILTIN),
        ("contribution_order", PATH_BUILTIN),
        ("aggregation_consistency", PATH_BUILTIN),
        ("change_contribution_order", PATH_BUILTIN),
        # 等级判定：两通路都没有独立的规范等级真值
        ("grade_accuracy", PATH_BUILTIN),
        ("grade_accuracy", PATH_FIXTURE),
    }
)

#: 真值四列（与 `generator.TRUTH_SCORE_COLUMNS` 同一套词汇）
TRUTH_LEDGER_COLUMNS = ("pci_truth", "grade_truth", "mqi_partial_truth", "recommended_action_truth")


# ---- 通路素材 ----


def fixture_dir_candidates(start=None):
    # type: (Optional[str]) -> List[str]
    """夹具包目录查找顺序：显式 start → cwd 上溯 → 包源树上溯。

    夹具值只允许待在 `tests/fixtures/`（交付面红线），打包态拿不到夹具包时这一通路
    如实报「不可用」，而不是把夹具数嵌进包里。
    """
    bases = []  # type: List[str]
    if start:
        bases.append(os.path.abspath(start))
    bases.append(os.path.abspath(os.getcwd()))
    bases.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    out = []  # type: List[str]
    seen = set()
    for base in bases:
        current = base
        for _step in range(6):
            candidate = os.path.join(current, "tests", "fixtures")
            if os.path.isdir(candidate) and candidate not in seen:
                seen.add(candidate)
                out.append(candidate)
            parent = os.path.dirname(current)
            if parent == current:
                break
            current = parent
    return out


def find_fixture_pack(name, start=None):
    # type: (str, Optional[str]) -> Optional[str]
    for directory in fixture_dir_candidates(start=start):
        path = os.path.join(directory, name)
        if os.path.isfile(path):
            return path
    return None


def _load_json(path):
    # type: (str) -> Dict[str, object]
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def merged_fixture_ruleset(start=None):
    # type: (Optional[str]) -> Optional[object]
    """沥青夹具包（含汇总 / 分级 / 对策格）+ 水泥 PCI 六格的并集，覆盖两种路面。

    不新写一套夹具数：逐格取自两份既有夹具包，只补另一套路面的 PCI 六格。
    """
    asphalt_path = find_fixture_pack(FIXTURE_ASPHALT_PACK, start=start)
    cement_path = find_fixture_pack(FIXTURE_CEMENT_PACK, start=start)
    if not asphalt_path or not cement_path:
        return None
    payload = _load_json(asphalt_path)
    cement = _load_json(cement_path)
    have = set(coef["key"] for coef in payload["coefficients"])
    for coef in cement["coefficients"]:
        if coef["key"] not in have:
            payload["coefficients"].append(copy.deepcopy(coef))
    payload["ruleset_id"] = FIXTURE_MERGED_ID
    payload["title"] = "M5 基准评测用夹具包（沥青 + 水泥，全部为夹具数）"
    return ruleset_loader.RuleSet.from_dict(payload, source_path=asphalt_path, allow_fixture=True)


def data_dirs(start=None):
    # type: (Optional[str]) -> Tuple[str, str]
    """演示数据的 raw / truth 目录（走 `data_paths` 五级优先级，含 exe 冻结分支）。"""
    from road_mqi_checker.data_paths import find_data_dir

    root = find_data_dir(start=start if start else os.getcwd())
    return os.path.join(root, "raw"), os.path.join(root, "truth")


def _read_bytes(path):
    # type: (str) -> bytes
    with open(path, "rb") as handle:
        return handle.read()


def _dir_files(root):
    # type: (str) -> Dict[str, bytes]
    out = {}  # type: Dict[str, bytes]
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            path = os.path.join(dirpath, name)
            out[os.path.relpath(path, root).replace(os.sep, "/")] = _read_bytes(path)
    return out


class PathContext(object):
    """一条通路的素材：规则集、台账、评定 / 汇总 / 对策 / 对比结果、校验检出、重生成产物。"""

    def __init__(self, path_key, ruleset, raw_dir, truth_dir, unavailable_reason=""):
        self.path_key = path_key
        self.label = PATH_LABELS[path_key]
        self.ruleset = ruleset
        self.raw_dir = raw_dir
        self.truth_dir = truth_dir
        self.unavailable_reason = unavailable_reason
        self.years = list(generator.plan_years())
        self.conn = None
        self.receipts = []
        self.all_pci = []
        self.pci_by_year = {}
        self.mqi_by_level_year = {}
        self.actions_by_year = {}
        self.compare_by_pair = {}
        self.findings = []
        self.generated = {}
        self._truth_cells = None

    # ---- 建立 ----

    def build(self):
        conn = ledger_db.connect(":memory:")
        ledger_db.initialize(conn)
        self.conn = conn
        for year in self.years:
            for route_id in generator.ROUTE_IDS:
                path = os.path.join(self.raw_dir, generator.raw_file_name(route_id, year))
                self.receipts.append(importer.import_csv(conn, path, year))
        ledger_checks.reset_ruleset_cache()
        for year in self.years:
            self.pci_by_year[year] = pci_engine.assess_year(conn, year, self.ruleset)
        self.all_pci = []
        for year in self.years:
            self.all_pci.extend(self.pci_by_year[year])
        for level in mqi_engine.AGGREGATION_LEVELS:
            self.mqi_by_level_year[level] = {}
            for year in self.years:
                self.mqi_by_level_year[level][year] = mqi_engine.aggregate_year(
                    conn, year, self.all_pci, self.ruleset, level=level
                )
        for year in self.years:
            self.actions_by_year[year] = action_rules.suggest_actions(
                conn, year, self.pci_by_year[year], self.mqi_by_level_year["segment"][year], self.ruleset
            )
        for year_from, year_to in zip(self.years, self.years[1:]):
            pair = [result for result in self.all_pci if result.year in (year_from, year_to)]
            segment_ids = year_compare.segment_ids_in_ledger(conn, year_from, year_to)
            self.compare_by_pair[(year_from, year_to)] = [
                (segment_id, year_compare.compare_years(conn, segment_id, year_from, year_to, pair, self.ruleset))
                for segment_id in segment_ids
            ]
        for year in self.years:
            self.findings.extend(ledger_checks.run_all_checks(conn, year, self.ruleset))
        ledger_checks.reset_ruleset_cache()

    def generate(self, scratch, second=False):
        """按本通路规则集重生成演示数据到 scratch。

        真值列的取值随规则集变（内置包出令牌、夹具包出数值），所以两通路各生成一份，
        复算比对的两侧才是同一本账。
        """
        tag = "second" if second else "first"
        raw_out = os.path.join(scratch, tag)
        truth_out = os.path.join(scratch, tag + "_truth")
        if not os.path.isdir(raw_out):
            os.makedirs(raw_out)
        generator.generate(
            raw_out,
            seed=generator.DEFAULT_SEED,
            ruleset=self.ruleset,
            force=True,
            truth_dir=truth_out,
        )
        files = _dir_files(raw_out)
        files.update(_dir_files(truth_out))
        self.generated[tag] = {"raw_dir": raw_out, "truth_dir": truth_out, "files": files}
        return self.generated[tag]

    def close(self):
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    # ---- 取值器 ----

    def pci_of(self, segment_id, year):
        for result in self.pci_by_year.get(year, []):
            if result.segment_id == segment_id:
                return result
        return None

    def mqi_of(self, segment_id, year):
        for result in self.mqi_by_level_year.get("segment", {}).get(year, []):
            if result.object_id == segment_id:
                return result
        return None

    def action_of(self, segment_id, year):
        for item in self.actions_by_year.get(year, []):
            if item.segment_id == segment_id:
                return item
        return None

    def route_members(self, year, route_id):
        # type: (int, str) -> List[Tuple[str, int]]
        """台账里的路段长度（桩号差，整米）—— 加权分母的唯一来源，独立取数不复用引擎助手。"""
        rows = self.conn.execute(
            "SELECT segment_id, start_stake_m, end_stake_m FROM segment WHERE year = ? AND route_id = ?"
            " ORDER BY start_stake_m, segment_id",
            (year, route_id),
        ).fetchall()
        return [(row["segment_id"], int(row["end_stake_m"]) - int(row["start_stake_m"])) for row in rows]

    def year_members(self, year):
        # type: (int) -> List[Tuple[str, int]]
        rows = self.conn.execute(
            "SELECT segment_id, route_id, start_stake_m, end_stake_m FROM segment WHERE year = ?"
            " ORDER BY start_stake_m, segment_id",
            (year,),
        ).fetchall()
        return [(row["segment_id"], int(row["end_stake_m"]) - int(row["start_stake_m"])) for row in rows]

    def truth_cells(self):
        # type: () -> List[Dict[str, object]]
        """真值格：取本通路**重生成**的那一份，才与台账通路同源可比。"""
        if self._truth_cells is not None:
            return self._truth_cells
        directory = self.generated["first"]["truth_dir"]
        cells = []  # type: List[Dict[str, object]]
        for route_id in generator.ROUTE_IDS:
            for year in self.years:
                path = os.path.join(directory, generator.truth_file_name(route_id, year))
                for row in importer.read_table(path):
                    for column in TRUTH_LEDGER_COLUMNS:
                        text = row[column]
                        pending = str(text).startswith(
                            (generator.PENDING_COEFF_PREFIX, generator.PENDING_ENGINE_PREFIX)
                        )
                        cells.append(
                            {
                                "segment_id": row["segment_id"],
                                "year": int(row["year"]),
                                "column": column,
                                "text": text,
                                "pending": pending,
                                "injected_issue": row.get("injected_issue", "none"),
                            }
                        )
        self._truth_cells = cells
        return cells

    def objects(self):
        # type: () -> List[Tuple[str, int]]
        return sorted(
            set((cell["segment_id"], cell["year"]) for cell in self.truth_cells()),
            key=lambda item: (item[1], item[0]),
        )


# ---- 指标行 ----


def _row(metric, path_key, numerator, denominator, state, value, basis, note):
    # type: (str, str, Optional[int], Optional[int], str, object, str, str) -> Dict[str, object]
    row = {
        "metric": metric,
        "name": METRIC_NAMES[metric],
        "path": path_key,
        "path_label": PATH_LABELS[path_key],
        "target": TARGETS[metric],
        "state": state,
        "value": value,
        "numerator": numerator,
        "denominator": denominator,
        "basis": basis,
        "note": note,
        "declared_indeterminate": (metric, path_key) in DECLARED_INDETERMINATE,
        "exit": STATE_TO_EXIT[state],
    }
    privacy.assert_honest_wording(" ".join((row["name"], basis, note)))
    return row


def _ratio(numerator, denominator):
    # type: (int, int) -> float
    return pci_engine.quantize(numerator / float(denominator), METRIC_DECIMALS)


def _ratio_state(metric, numerator, denominator):
    # type: (str, int, int) -> str
    """分母为 0 → 不可判；否则按阈值判达标 / 未达标。"""
    if denominator == 0:
        return METRIC_INDETERMINATE
    ratio = _ratio(numerator, denominator)
    threshold = RATIO_TARGETS.get(metric)
    if threshold is None:
        return METRIC_PASS
    if metric == "anomaly_false_alarm":
        return METRIC_PASS if ratio <= threshold else METRIC_FAIL
    return METRIC_PASS if ratio >= threshold else METRIC_FAIL


def _unavailable_row(metric, path_key, reason):
    return _row(metric, path_key, None, None, METRIC_UNAVAILABLE, None, "通路未建立，无分子分母", reason)


def _trace_rows(segment_id, year, contributions):
    # type: (str, int, Sequence[object]) -> List[Tuple[str, ...]]
    return [tuple(str(v) for v in row.values()) for row in pci_trace.expand_list(segment_id, year, contributions)]


def _reorderings(items):
    # type: (List[object]) -> List[List[object]]
    """逐位旋转 + 反序：排序若依赖迭代顺序，这里就会露出来。"""
    out = [items[shift:] + items[:shift] for shift in range(1, len(items))]
    out.append(list(reversed(items)))
    return out


# ---- 1 评分复算误差 ----


def _ledger_value(ctx, column, segment_id, year):
    # type: (PathContext, str, str, int) -> object
    """台账通路对同一真值格的取值；拒算（None / 空等级 / 空类别）返回 None，与真值令牌同一档。"""
    if column == "pci_truth":
        result = ctx.pci_of(segment_id, year)
        return None if result is None or result.pci is None else result.pci
    if column == "grade_truth":
        result = ctx.pci_of(segment_id, year)
        return None if result is None or not result.grade else result.grade
    if column == "mqi_partial_truth":
        result = ctx.mqi_of(segment_id, year)
        return None if result is None or result.mqi is None else result.mqi
    if column == "recommended_action_truth":
        item = ctx.action_of(segment_id, year)
        return None if item is None or not item.action_class else item.action_class
    return None


def metric_rescore_drift(ctx):
    # type: (PathContext) -> Dict[str, object]
    """评分复算误差：真值列 ↔ 台账通路逐格比对，报最大绝对偏差。

    分母只计**两边都出数**的格（数值真值 ∩ 台账出数）；令牌格不构成误差，
    但另报「令牌与拒算相符」的格数 —— blocked 对象没有被从分母里悄悄摘掉。
    """
    compared = 0
    matched = 0
    max_error = 0.0
    token_cells = 0
    token_agreed = 0
    disagree = []  # type: List[List[object]]
    for cell in ctx.truth_cells():
        value = _ledger_value(ctx, cell["column"], cell["segment_id"], cell["year"])
        if cell["pending"]:
            token_cells += 1
            if value is None:
                token_agreed += 1
            else:
                disagree.append([cell["column"], cell["segment_id"], cell["year"], "真值是令牌、台账却出数"])
            continue
        if value is None:
            disagree.append([cell["column"], cell["segment_id"], cell["year"], "真值出数、台账拒算"])
            continue
        compared += 1
        if cell["column"] in ("pci_truth", "mqi_partial_truth"):
            error = abs(float(cell["text"]) - float(value))
            max_error = max(max_error, error)
            if error == 0.0:
                matched += 1
            else:
                disagree.append([cell["column"], cell["segment_id"], cell["year"], "偏差 %s" % error])
        elif str(cell["text"]) == str(value):
            matched += 1
        else:
            disagree.append([cell["column"], cell["segment_id"], cell["year"], "%s ≠ %s" % (cell["text"], value)])
    if compared == 0:
        state = METRIC_INDETERMINATE
        value = None
        drift = "不可判（本通路无出数格可比）"
    else:
        state = METRIC_PASS if matched == compared and not disagree else METRIC_FAIL
        value = pci_engine.quantize(max_error, pci_engine.PCI_DECIMALS)
        drift = value
    note = "最大复算误差 %s；真值令牌与台账拒算相符 %d/%d 格（拒算对象不混进误差分母，也没被摘掉）" % (
        drift,
        token_agreed,
        token_cells,
    )
    if disagree:
        note += "；不符样本 %s" % json.dumps(disagree[:3], ensure_ascii=False)
    return _row(
        "rescore_drift",
        ctx.path_key,
        matched,
        compared,
        state,
        value,
        "分子=逐字段相符的真值格数，分母=真值与台账通路两边都出数的真值格数（4 列 × 42 对象）",
        note,
    )


# ---- 2 等级判定准确率 ----


def metric_grade_accuracy(ctx):
    # type: (PathContext) -> Dict[str, object]
    """等级判定准确率：分母 = 有独立规范等级真值的对象数，本题恒为 0。

    判定通路已交付（本通路出数 / 出等级的对象数写在说明里），但等级真值由同一内核算出，
    没有独立的规范真值可比：分级阈值的官方原文不可得（`plan/04`），夹具档等级更是虚构数。
    所以这一项在两通路都如实报不可判（分母为 0），不写达标。
    """
    with_grade = sum(1 for result in ctx.all_pci if result.grade)
    with_value = sum(1 for result in ctx.all_pci if result.pci is not None)
    return _row(
        "grade_accuracy",
        ctx.path_key,
        0,
        0,
        METRIC_INDETERMINATE,
        None,
        "分子=与独立规范等级真值相符的对象数，分母=有独立规范等级真值的「路段×年度」对象数",
        "独立规范等级真值 0 份（分级阈值原文不可得，夹具档等级是虚构数）；本通路出数值 %d 个、出等级 %d 个，"
        "其等级由同一内核算出，只能自证一致、不能自证正确 ⇒ 分母为 0。" % (with_value, with_grade),
    )


# ---- 3 扣分贡献项排序一致性 ----


def metric_contribution_order(ctx):
    # type: (PathContext) -> Dict[str, object]
    """扣分贡献项排序一致性：逐位旋转 + 反序输入后重新展开，展开视图必须逐行相同。"""
    comparisons = 0
    identical = 0
    objects = 0
    for result in ctx.all_pci:
        if len(result.contributions) < 2:
            continue
        objects += 1
        reference = _trace_rows(result.segment_id, result.year, result.contributions)
        items = list(result.contributions)
        for reordered in _reorderings(items):
            result.contributions = reordered
            again = _trace_rows(result.segment_id, result.year, result.contributions)
            comparisons += 1
            if again == reference:
                identical += 1
        result.contributions = items
    return _row(
        "contribution_order",
        ctx.path_key,
        identical,
        comparisons,
        _ratio_state("contribution_order", identical, comparisons),
        None if comparisons == 0 else _ratio(identical, comparisons),
        "分子=重排后展开视图逐行相同的比较次数，分母=全部重排比较次数（逐位旋转 + 反序）",
        "贡献项 ≥2 的对象 %d 个；展开视图逐行带系数 key、条款号与台账行号，重排输入后逐行一致 ⇒ 排序不依赖迭代顺序。" % objects,
    )


# ---- 4 MQI 汇总口径一致性 ----


def metric_aggregation_consistency(ctx):
    # type: (PathContext) -> Dict[str, object]
    """汇总口径一致性：路线级 / 路网级由路段级结果 + 台账里程独立复算，逐位比 MQI 值与分母。

    复算式与 `plan/05` §八 同一式：只把已出数成员按路段长度加权，
    分母 = 纳入成员长度和，blocked 成员连同里程退出（`plan/02` §9 第 25 条）。
    """
    comparisons = 0
    identical = 0
    no_number_objects = 0
    for year in ctx.years:
        segment_results = ctx.mqi_by_level_year["segment"][year]
        upper = ctx.mqi_by_level_year["route"][year] + ctx.mqi_by_level_year["network"][year]
        groups = [(result.object_id, ctx.route_members(year, result.object_id)) for result in ctx.mqi_by_level_year["route"][year]]
        groups.append((mqi_engine.NETWORK_OBJECT_ID, ctx.year_members(year)))
        for object_id, members in groups:
            usable = []
            for segment_id, length_m in members:
                result = next((r for r in segment_results if r.object_id == segment_id), None)
                if result is not None and result.mqi is not None:
                    usable.append((result.mqi, length_m))
            engine = next((r for r in upper if r.object_id == object_id), None)
            if not usable or engine is None or engine.mqi is None:
                no_number_objects += 1
                continue
            total_length = float(sum(length for _v, length in usable))
            recomputed = pci_engine.quantize(
                sum(value * length for value, length in usable) / total_length, pci_engine.PCI_DECIMALS
            )
            for want, got in ((recomputed, engine.mqi), (total_length, engine.weighted_length_m)):
                comparisons += 1
                if float(want) == float(got):
                    identical += 1
    return _row(
        "aggregation_consistency",
        ctx.path_key,
        identical,
        comparisons,
        _ratio_state("aggregation_consistency", identical, comparisons),
        None if comparisons == 0 else _ratio(identical, comparisons),
        "分子=复算值 / 复算分母与引擎输出逐位相等的比对次数，分母=4 年度 ×（3 路线级 + 1 路网级）×（MQI 值 + 加权里程）",
        "由路段级结果 + 台账里程独立复算三级汇总；无一出数的汇总对象 %d 个不参与复算（其拒算理由由 aggregate 通路逐格点名）。"
        % no_number_objects,
    )


# ---- 5 变化贡献项排序一致性 ----


def metric_change_contribution_order(ctx):
    # type: (PathContext) -> Dict[str, object]
    """变化贡献排序一致性：年对比变化拆解的两侧贡献各自重排后重新展开，序列必须逐行相同。"""
    comparisons = 0
    identical = 0
    pairs = 0
    for (year_from, year_to), results in sorted(ctx.compare_by_pair.items()):
        for segment_id, result in results:
            if not result.top_contributors:
                continue
            left = ctx.pci_of(segment_id, year_from)
            right = ctx.pci_of(segment_id, year_to)
            if left is None or right is None:
                continue
            pairs += 1
            reference = _trace_rows(segment_id, year_to, year_compare.explain_change(result, left, right))
            for source in (left, right):
                items = list(source.contributions)
                if len(items) < 2:
                    continue
                for reordered in _reorderings(items):
                    source.contributions = reordered
                    again = _trace_rows(segment_id, year_to, year_compare.explain_change(result, left, right))
                    comparisons += 1
                    if again == reference:
                        identical += 1
                source.contributions = items
    return _row(
        "change_contribution_order",
        ctx.path_key,
        identical,
        comparisons,
        _ratio_state("change_contribution_order", identical, comparisons),
        None if comparisons == 0 else _ratio(identical, comparisons),
        "分子=重排后变化拆解逐行相同的比较次数，分母=全部重排比较次数（逐年对 × 两侧 × 逐位旋转 + 反序）",
        "有变化贡献可拆的对次 %d 个；uncomparable 对次不出变化拆解，因此也不进本项分母（原因代码由 compare 通路报出）。"
        % pairs,
    )


# ---- 6/7 异常召回与误报 ----


def _expected_anomaly_sets(ctx):
    # type: (PathContext) -> Tuple[set, set, set, int]
    """期望集从真值文件的 `injected_issue` 独立推出（不拿校验层输出自证）。"""
    expected_cells = set()
    partition_marks = set()
    cell_marked = set()
    for cell in ctx.truth_cells():
        if cell["column"] != "pci_truth":
            continue
        issue = cell["injected_issue"]
        key = (cell["segment_id"], cell["year"])
        if issue in EXPECTED_KIND_BY_ISSUE:
            expected_cells.add((EXPECTED_KIND_BY_ISSUE[issue], cell["segment_id"], cell["year"]))
            cell_marked.add(key)
        elif issue == PARTITION_ISSUE:
            partition_marks.add(key)
    return expected_cells, partition_marks, cell_marked, len(ctx.objects())


def _detected_sets(ctx):
    # type: (PathContext) -> Tuple[set, set]
    cell_kinds = set(EXPECTED_KIND_BY_ISSUE.values())
    detected_cells = set(
        (finding.kind, finding.segment_id, int(finding.year))
        for finding in ctx.findings
        if finding.verdict == ledger_checks.VERDICT_FOUND and finding.kind in cell_kinds
    )
    for receipt in ctx.receipts:
        year = int(receipt.source_file.split("-")[1].split(".")[0])
        for line in receipt.lines:
            if line.code == "R008_DUPLICATE" and line.segment_id:
                detected_cells.add(("duplicate_import", line.segment_id, year))
    detected_partition = set(
        (finding.segment_id, int(finding.year))
        for finding in ctx.findings
        if finding.kind == PARTITION_ISSUE and finding.verdict == ledger_checks.VERDICT_FOUND
    )
    return detected_cells, detected_partition


def metric_anomaly(ctx):
    # type: (PathContext) -> Tuple[Dict[str, object], Dict[str, object]]
    """召回与误报：校验层不消费未核对系数，因此两通路都出实测数（措辞仍各说各的通路）。"""
    expected_cells, partition_marks, cell_marked, total_objects = _expected_anomaly_sets(ctx)
    detected_cells, detected_partition = _detected_sets(ctx)
    hit_cells = expected_cells & detected_cells
    hit_partition = partition_marks & detected_partition
    receipt_evidence = sum(
        1
        for receipt in ctx.receipts
        for line in receipt.lines
        if line.code == "R008_DUPLICATE" and line.segment_id
    )
    numerator = len(hit_cells) + len(hit_partition)
    denominator = len(expected_cells) + len(partition_marks)
    recall = _row(
        "anomaly_recall",
        ctx.path_key,
        numerator,
        denominator,
        _ratio_state("anomaly_recall", numerator, denominator),
        None if denominator == 0 else _ratio(numerator, denominator),
        "分子=命中的注入用例数，分母=真值 injected_issue 声明的注入用例数（格级 + 划分变更标记）",
        "期望 %d 例（格级 %d + 划分变更标记 %d），命中格级 %d（其中 %d 例的证据是导入回执 R008）、划分变更 %d；"
        "划分变更另有 %d 条检出是生成器 INJECTION_IMPLICATIONS 声明过的隐含结论（父侧与子侧同报），"
        "既不算漏报也不另计进分母。"
        % (
            denominator,
            len(expected_cells),
            len(partition_marks),
            len(hit_cells),
            receipt_evidence,
            len(hit_partition),
            len(detected_partition - partition_marks),
        ),
    )
    false_positive = sorted(detected_cells - expected_cells)
    clean_objects = total_objects - len(cell_marked)
    alarm = _row(
        "anomaly_false_alarm",
        ctx.path_key,
        len(false_positive),
        clean_objects,
        _ratio_state("anomaly_false_alarm", len(false_positive), clean_objects),
        None if clean_objects == 0 else _ratio(len(false_positive), clean_objects),
        "分子=未被格级注入标记的对象上的格级六类检出数，分母=未被格级注入标记的「路段×年度」对象数",
        "干净对象 %d 个（总 %d 减格级标记 %d）上的格级六类检出 %d 处；划分变更标记对象留在分母里"
        "（它们本就不该有格级检出），其划分检出另按生成器声明计，不重复计入本项。"
        % (clean_objects, total_objects, len(cell_marked), len(false_positive)),
    )
    return recall, alarm


# ---- 8 产物位级一致 ----


def _byte_state(identical, total):
    # type: (int, int) -> str
    """位级一致的判据：一份文件都没比出来叫不可判，不是达标也不是未达标。"""
    if total == 0:
        return METRIC_INDETERMINATE
    return METRIC_PASS if identical == total else METRIC_FAIL


def metric_byte_reproducible(ctx):
    # type: (PathContext) -> Dict[str, object]
    """位级一致：内置包比对入仓产物；夹具包真值列出数、与入仓数据本就不同，改比对两次重生成。"""
    left = ctx.generated["first"]["files"]
    if ctx.path_key == PATH_BUILTIN:
        right = _dir_files(ctx.raw_dir)
        right.update(_dir_files(ctx.truth_dir))
        basis_note = "同 seed 重生成与入仓演示数据逐份比对（raw + truth + manifest，含 EOL 与时间戳形态）"
    else:
        right = ctx.generated["second"]["files"]
        basis_note = "夹具包真值列出数，与入仓数据（pending 令牌）本就不同 ⇒ 比对同一规则集的两次重生成"
    names = sorted(set(left) | set(right))
    # 目录占位文件（`.gitkeep` 一类）不是生成器的产物，不进比对分母
    names = [name for name in names if not os.path.basename(name).startswith(".")]
    identical = sum(1 for name in names if left.get(name) == right.get(name))
    return _row(
        "byte_reproducible",
        ctx.path_key,
        identical,
        len(names),
        _byte_state(identical, len(names)),
        None,
        "分子=逐字节一致的文件数，分母=参与比对的文件数（raw + truth + manifest）",
        basis_note + "。",
    )


# ---- 汇总 / 门禁 ----


def build_context(path_key, start=None, raw_dir=None, truth_dir=None):
    # type: (str, Optional[str], Optional[str], Optional[str]) -> PathContext
    if raw_dir is None or truth_dir is None:
        default_raw, default_truth = data_dirs(start=start)
        raw_dir = default_raw if raw_dir is None else raw_dir
        truth_dir = default_truth if truth_dir is None else truth_dir
    if path_key == PATH_BUILTIN:
        ruleset = ruleset_loader.select_ruleset()
        reason = ""
    elif path_key == PATH_FIXTURE:
        ruleset = merged_fixture_ruleset(start=start)
        reason = (
            ""
            if ruleset is not None
            else "夹具包（%s / %s）不在通路上，数值通路无法建立 ⇒ 本通路指标不可用"
            % (FIXTURE_ASPHALT_PACK, FIXTURE_CEMENT_PACK)
        )
    else:
        raise ValueError("未知通路 %r，合法值 %s" % (path_key, "/".join(PATH_ORDER)))
    return PathContext(path_key, ruleset, raw_dir, truth_dir, unavailable_reason=reason)


def path_gates(ruleset):
    # type: (Optional[object]) -> Optional[Dict[str, List[str]]]
    """逐路径出数判据：只走 generator 的必需格函数，不自建第二套判据（§9 第 23 / 28 条）。"""
    if ruleset is None:
        return None
    return {
        "assess": generator.scoring_gate_pending_keys(ruleset),
        "aggregate": generator.aggregation_gate_pending_keys(ruleset),
        "actions": generator.action_gate_pending_keys(ruleset),
    }


def _status_counts(items):
    # type: (Sequence[object]) -> Dict[str, int]
    """对策建议的状态分布：四态词汇取自 `results.ALL_RESULT_STATUSES`（不自建第二套词汇）。"""
    counts = dict((status, 0) for status in res.ALL_RESULT_STATUSES)
    for item in items:
        counts[item.status] = counts.get(item.status, 0) + 1
    return counts


def run(paths=PATH_ORDER, start=None, keep_scratch=False):
    # type: (Sequence[str], Optional[str], bool) -> Dict[str, object]
    """两通路各算一组指标，每条指标显式报分子 / 分母 / 状态；产物写系统临时目录，不落仓库。"""
    scratch = tempfile.mkdtemp(prefix="rmqc-bench-")
    payload = {"milestone": MILESTONE, "paths": {}, "metrics": [], "coverage": {}, "scratch_dir": scratch}
    try:
        raw_dir, truth_dir = data_dirs(start=start)
        for path_key in paths:
            ctx = build_context(path_key, start=start, raw_dir=raw_dir, truth_dir=truth_dir)
            path_scratch = os.path.join(scratch, path_key)
            os.makedirs(path_scratch)
            info = {
                "label": PATH_LABELS[path_key],
                "honesty": PATH_HONESTY[path_key],
                "ruleset": None if ctx.ruleset is None else ctx.ruleset.summary(),
                "path_gates": path_gates(ctx.ruleset),
                "unavailable_reason": ctx.unavailable_reason,
            }
            if ctx.ruleset is None:
                rows = [_unavailable_row(metric, path_key, ctx.unavailable_reason) for metric in METRICS]
            else:
                ctx.build()
                ctx.generate(path_scratch)
                if path_key == PATH_FIXTURE:
                    ctx.generate(path_scratch, second=True)
                recall, alarm = metric_anomaly(ctx)
                computed = {
                    "rescore_drift": metric_rescore_drift(ctx),
                    "grade_accuracy": metric_grade_accuracy(ctx),
                    "contribution_order": metric_contribution_order(ctx),
                    "aggregation_consistency": metric_aggregation_consistency(ctx),
                    "change_contribution_order": metric_change_contribution_order(ctx),
                    "anomaly_recall": recall,
                    "anomaly_false_alarm": alarm,
                    "byte_reproducible": metric_byte_reproducible(ctx),
                }
                rows = [computed[metric] for metric in METRICS]
                info["objects"] = len(ctx.objects())
                info["pci_counts"] = _status_counts(ctx.all_pci)
                info["aggregate_counts"] = _status_counts(
                    [result for year in ctx.years for result in ctx.mqi_by_level_year["segment"][year]]
                )
                info["action_counts"] = _status_counts(
                    [item for year in ctx.years for item in ctx.actions_by_year[year]]
                )
                info["compare_counts"] = year_compare.summarize_status(
                    [result for pair in ctx.compare_by_pair.values() for _sid, result in pair]
                )
                info["generated_files"] = len(ctx.generated["first"]["files"])
                ctx.close()
            payload["paths"][path_key] = info
            payload["metrics"].extend(rows)
        payload["coverage"] = coverage(payload["metrics"])
        payload["gate"] = gate(payload["metrics"])
    finally:
        if not keep_scratch:
            shutil.rmtree(scratch, ignore_errors=True)
            payload["scratch_dir"] = None
    return payload


def coverage(rows):
    # type: (Sequence[Dict[str, object]]) -> Dict[str, object]
    counts = dict((state, 0) for state in METRIC_STATES)
    undeclared = []
    for row in rows:
        counts[row["state"]] = counts.get(row["state"], 0) + 1
        if row["state"] == METRIC_INDETERMINATE and not row["declared_indeterminate"]:
            undeclared.append("%s/%s" % (row["metric"], row["path"]))
    return {
        "rows": len(rows),
        "by_state": counts,
        "undeclared_indeterminate": sorted(undeclared),
        "declared_indeterminate": sorted_declared(),
    }


def sorted_declared():
    # type: () -> List[str]
    return sorted("%s/%s" % pair for pair in DECLARED_INDETERMINATE)


def gate(rows):
    # type: (Sequence[Dict[str, object]]) -> Dict[str, object]
    """门禁：只红于「未达标 / 不可用 / 名单外的新不可判」。

    名单内的不可判不红 —— 那是系数门的诚实状态，不是事故；名单外的不可判按数据门事故
    处理（2），因为分母为 0 通常意味着有对象被从通路上摘掉了。
    """
    for state in GATE_PRECEDENCE:
        issues = []
        for row in rows:
            if row["state"] != state:
                continue
            if state == METRIC_INDETERMINATE and row["declared_indeterminate"]:
                continue
            issues.append(
                "%s/%s：%s（分子 %s / 分母 %s）%s"
                % (row["metric"], row["path"], state, row["numerator"], row["denominator"], row["note"])
            )
        if issues:
            return {
                "exit": STATE_TO_EXIT[state],
                "triggered_by": state,
                "issues": issues,
                "declared_indeterminate": sorted_declared(),
            }
    return {"exit": EXIT_OK, "triggered_by": "", "issues": [], "declared_indeterminate": sorted_declared()}


# ---- README 评测表（由 bench run --json 生成，README 里那段是它的产物）----


def row_key(row):
    # type: (Dict[str, object]) -> str
    return "%s|%s" % (row["metric"], row["path"])


def format_value(row):
    # type: (Dict[str, object]) -> str
    """指标值的显示文本：比值类固定两位小数（1.00 / 0.00），误差类按得分口径 1 位。"""
    if row["state"] in (METRIC_INDETERMINATE, METRIC_UNAVAILABLE) or row["value"] is None:
        return ""
    if row["metric"] in RATIO_METRICS:
        return "%.*f" % (METRIC_DECIMALS, float(row["value"]))
    return "%s" % row["value"]


def state_text(row):
    # type: (Dict[str, object]) -> str
    """「当前」列的状态措辞：不可判一定带分母为 0，避免被读成达标。"""
    if row["state"] == METRIC_INDETERMINATE:
        return "不可判（分母为 0）"
    return row["state"]


def current_cell(rows_by_key, metric):
    # type: (Dict[str, Dict[str, object]], str) -> str
    parts = []
    for path_key in PATH_ORDER:
        row = rows_by_key["%s|%s" % (metric, path_key)]
        value = format_value(row)
        parts.append("%s %s%s" % (PATH_LABELS[path_key], state_text(row), " %s" % value if value else ""))
    return " ／ ".join(parts)


def readme_note(rows_by_key, metric):
    # type: (Dict[str, Dict[str, object]], str) -> str
    """说明列：两通路各自的分子 / 分母与实测结论，措辞不互相顶替。

    分子分母的**定义**（判据）只在 `--json` 与 `bench run` 的文本输出里逐行给，
    表格只放数，避免 README 一行长成段落。
    """
    parts = []
    for path_key in PATH_ORDER:
        row = rows_by_key["%s|%s" % (metric, path_key)]
        parts.append("%s：分子 %s / 分母 %s，%s" % (row["path_label"], row["numerator"], row["denominator"], row["note"]))
    return " ".join(parts)


def readme_table(payload):
    # type: (Dict[str, object]) -> List[str]
    """README 评测表的表格体（不含表头与分隔行）：由指标清单逐行生成。"""
    rows_by_key = dict((row_key(row), row) for row in payload["metrics"])
    out = []
    for metric in METRICS:
        out.append(
            "| %s | %s | %s | %s |"
            % (METRIC_NAMES[metric], TARGETS[metric], current_cell(rows_by_key, metric), readme_note(rows_by_key, metric))
        )
    return out


TABLE_HEADER = "| 指标 | 目标 | 当前 | 说明 |"
TABLE_DIVIDER = "|---|---|---|---|"
TABLE_BEGIN = "<!-- bench-run:begin -->"
TABLE_END = "<!-- bench-run:end -->"


def render_readme_block(payload):
    # type: (Dict[str, object]) -> str
    """评测表完整 markdown（含标记行）：README 里这一段由它逐字节替换。"""
    return "\n".join([TABLE_BEGIN, TABLE_HEADER, TABLE_DIVIDER] + readme_table(payload) + [TABLE_END])


def exit_meaning(code):
    # type: (int) -> str
    return EXIT_CODE_MEANINGS.get(code, str(code))


def report_lines(payload):
    # type: (Dict[str, object]) -> List[str]
    lines = ["基准评测：%d 指标 × %d 通路 = %d 行" % (len(METRICS), len(PATH_ORDER), len(payload["metrics"]))]
    for path_key in PATH_ORDER:
        info = payload["paths"][path_key]
        summary = info["ruleset"]
        head = "〔%s〕" % info["label"]
        if summary:
            head += "规则集 %s v%s（生效 %d 格 / 拒算 %d 格）" % (
                summary["ruleset_id"],
                summary["version"],
                summary["computable"],
                summary["blocked"],
            )
        else:
            head += "规则集不可得：%s" % info["unavailable_reason"]
        lines.append(head)
        lines.append("  诚实线：%s" % info["honesty"])
        gates = info["path_gates"]
        if gates:
            lines.append(
                "  出数判据："
                + " / ".join(
                    "%s %s" % (name, "可出数" if not keys else "缺 %d 格不出数" % len(keys))
                    for name, keys in sorted(gates.items())
                )
            )
        for row in payload["metrics"]:
            if row["path"] != path_key:
                continue
            value = format_value(row)
            lines.append(
                "  - %s：%s%s（分子 %s / 分母 %s）目标 %s"
                % (
                    row["name"],
                    state_text(row),
                    " %s" % value if value else "",
                    row["numerator"],
                    row["denominator"],
                    row["target"],
                )
            )
            lines.append("      判据：%s" % row["basis"])
            lines.append("      说明：%s" % row["note"])
    counts = payload["coverage"]["by_state"]
    lines.append(
        "状态分布：达标 %d / 未达标 %d / 不可判 %d / 不可用 %d；已声明不可判 %d 项"
        % (
            counts[METRIC_PASS],
            counts[METRIC_FAIL],
            counts[METRIC_INDETERMINATE],
            counts[METRIC_UNAVAILABLE],
            len(payload["coverage"]["declared_indeterminate"]),
        )
    )
    for issue in payload["gate"]["issues"]:
        lines.append("门禁：%s" % issue)
    lines.append("退出码 %d（%s）" % (payload["gate"]["exit"], exit_meaning(payload["gate"]["exit"])))
    lines.append("注：blocked / uncomparable 对象不从指标分母里悄悄摘掉，摘与不摘都在「判据」行写明。")
    return lines
