# HANDOFF · M5 基准与评测

> 用法：新对话说「继续完成 `plan/HANDOFF-M5.md` 的 M5 任务」即可续接（本文件内命令均以仓库根为当前目录）。
> 上一棒：M4 汇总、对策与年对比（2026-10-07 完成，已本地 commit ×2，未 push）。

## 〇、M4 末态基线（不得回退）

| 项 | 实测值 | 复核命令 |
|---|---|---|
| 提交 | 本地 main 一串 M0→M4 提交，工作树干净（只有不属于本项目的未跟踪 `.qoder-credits/`），**无 remote、未 push**；末两个提交是 `ac62546`（M4 代码+测试+文档）与 `d4512d0`（演示数据重生成，**单独一个 commit**） | `git log --oneline -3` / `git status --porcelain` |
| 测试 | **371 项**（M4 净增 85），py3.8.8 与 py3.12.10 各 371 collected / 371 passed / 0 skip / 0 warning | `py -3.8 -X utf8 -m pytest tests` |
| 系数面 | 内置包 15 格：**生效 1 格**（`tolerance.length_closure`）、**拒算 14 格**；`selfcheck` 新增**按路径**的出数判据行："assess 缺 8 格不出数 / aggregate 缺 2 格不出数 / actions 缺 1 格不出数（生效格数不等于可出数）" | `rmqc selfcheck` / `rmqc --json selfcheck` 的 `path_gates` |
| 评定面 | `assess --year 2022` 对 4 个路段仍逐个 **blocked**、数值字段全空、退出码 1（M3 基线未回退） | `rmqc --db ledger.sqlite assess --year 2022` |
| 汇总面 | 内置包下 `aggregate --year 2022` 三级全部 **blocked**（`--json` 里 `mqi`/`grade`/`weighted_length_m` 全 null）、`priority_list` 4 条全 blocked，退出码 1；该年度无路段行 → 退出码 2 | `rmqc --db ledger.sqlite --json aggregate --year 2022 --level network` |
| 对比面 | 内置包下 `compare --from-year 2022 --to-year 2023` 出 4 个对象：**blocked 3 + uncomparable 1**（原因代码 `partition_shifted`），全部不出变化率，退出码 1 | `rmqc --db ledger.sqlite --json compare --from-year 2022 --to-year 2023` |
| 夹具通路实测 | 汇总路段级 42 对象 = **partial 36 / blocked 6 / ok 0**（首期只有路面分项 ⇒ 出数的一律带口径声明且不给等级）；对策清单 42 条每个对象一行；年对比 36 对次 = ok 19 / blocked 8 / **uncomparable 9**；真值两列与台账通路复算 **0 处不符**；变化贡献项重排 231 次比较逐行一致 | `py -3.8 -X utf8 .tmp_verify/M4/measure.py`（输出即 `.tmp_verify/M4/measure.log`） |
| 演示数据 | `data/raw` 的 12 份 CSV **逐字节未动**；`data/truth` 12 份只改 `mqi_partial_truth` 一列的令牌内容（补上 `grade_threshold.mqi`），四列仍全是 `pending` 令牌；`data/raw/manifest.json` 新增 `coefficient_gate.truth_gates`（逐列 required/pending/state） | `git show --stat d4512d0` |
| 位级一致 | `bench generate --force` 二次重跑改写 **0 份**，`git status --porcelain data/` 为空 | `rmqc bench generate --force` |
| 干净环境 | 新 clone `d4512d0` + 新 venv（py3.12.10）**26 步逐条符合期望退出码**：0 档 17 步、1 档 7 步（import/assess×2/aggregate×3/compare×2 中除无数据者外）、2 档 2 步（无路段行）、3 档 2 步（bench run / report）；两次 `bench generate` 后 porcelain 为空；`python -m pytest tests -q` = 0，371 全过 | `bash .tmp_verify/M4/clean_verify.sh`（结果看 `.tmp_verify_m4_clean/exits.tsv` 与 `run.log`） |
| 占位符 | 登记表从 6 个模块缩到 **3 个**（`bench.evaluation` M5、`report.exporters` M6、`gui.app` M6）；`_meta.MILESTONE = "M4"`，README 状态行随之前进 | `tests/test_placeholder_registry.py` |

留给 M5 的实测教训：

1. **M5 的数字只有夹具通路可算**。14 格规范系数仍 pending ⇒ 交付面 assess / aggregate / 对策 / 年对比
   全部拒算，任何"准确率"类指标在内置包下分母都是 0。`bench run` 必须**两条通路分别报**
   （内置包 = 通路存在但不出数；夹具包 = 出数并可复算），**不要**把夹具通路的数字当成
   "规范口径下的达标"。判据仍走必需格：`generator.gate_pending_keys / scoring_gate_pending_keys /
   aggregation_gate_pending_keys / action_gate_pending_keys`（`plan/02` §9 第 23、28 条）。
2. **"等级判定准确率"的正确报法是 `不可判（分母为 0）`**，不是达标也不是不可用：判定通路已交付且
   夹具下 42 个对象出等级，但真值等级由同一内核算出，没有独立的规范真值可比。
   README 评测表已按这一口径写好（`STATE_TO_EXIT`：不可判 → 2）。别为了让表格好看改成"达标 1.00"。
3. **README 的评测表要能被命令逐行替换**。现在表里有 8 行（M1–M4 累积 + M4 新增两行"汇总口径一致性"
   "变化贡献项排序一致性"）。`bench run --json` 的指标清单必须与这 8 行逐行对账，
   既有门 `test_skeleton_metric_table_is_all_unavailable` 在 M5 交付时要**重写**成
   "内置包下的真实四态 + 夹具通路下的实测值"，而不是删掉。
4. **M5 已有的可复算证据基线**（`bench run` 要把它们变成命令输出，而不是另算一套）：
   评分复算误差 0（42 对象，真值列↔台账通路，`test_m2_assess.py` 与 `.tmp_verify/M4/measure.log`）；
   扣分贡献排序一致性 1.00（214 次，M2）；变化贡献排序一致性 1.00（231 次，M4）；
   召回 1.00 / 误报 0.00（八类 19 例，M1）；位级一致（改写 0 份）。
   复现脚本 `.tmp_verify/M4/measure.py` 已经把四年度全部通路跑了一遍，M5 可直接把它内部化。
5. **入参形态已交接好**（M4 消费过一遍，M5/M6 沿用同一套）：
   `pci.engine.assess_year` → `List[PciResult]`；
   `mqi.engine.aggregate_year(conn, year, pci_results, ruleset, level)` → `List[MqiResult]`；
   `strategy.rules.suggest_actions(conn, year, pci_results, mqi_results, ruleset)` +
   `rank_priority(suggestions, "pci")`；
   `strategy.compare.compare_years(conn, segment_id, year_from, year_to, pci_results, ruleset)`。
   三者的 `result_payload()` 就是 `--json` 的结构（M4 已实现），M6 的 GUI/导出**不得另起第二套字段口径**。
6. **`report.exporters.PLAN_COLUMNS` 的字段 M4 已全部备齐**（含 `mqi_partial`、`delta`、
   `deterioration_rate_per_year`、`action_class`、`scale_band`、`rule_id`、`clause`、`triggered_by`、
   `status`、`blocked_reason`）。M6 导出只要把它们填进去；`rank_priority` 只返回排序后的对象，
   `rank` 序号由导出层自己编号；`rank_key` 字段是排序口径的说明文本（`primary=pci↑|tie=…`）。
7. **不可比这一档还有判不了的**：`UNCOMPARABLE_REASONS` 里 `coefficient_change` 当前**无法判定**
   —— 台账没有逐年登记规则集版本的表，单文件规则包本身不可变，所以系数变化只能靠"换包版本"表达
   并被 `rule_version_change` 捕获（`plan/05` §10.1 末段）。M5 若要把它变成可测指标，
   需要先给台账加规则集版本记录（属 schema 变更，要按 §三 第 9 条登记并同步夹具）。
8. **拒算三类入口对 M5 同样适用**：系数门 / 数据门 / 检出项门。基准评测不得为"看到数字"
   绕过任何一道门，也不得把 blocked 对象从分母里悄悄摘掉 —— 摘了就是把误报做成达标。
9. 本机环境（M0–M4 五棒实测，见 §四）：验证脚本一律写**绝对路径**日志。
   M4 那轮 `clean_verify.sh` 一开始就按这条写，26 步全部有回执；M3 那版相对路径的坑已修好并在
   `.tmp_verify/M4/clean_verify.sh` 里固化，M5 直接复制成 `_m5` 批次即可。

## 一、M4 交付内容（已完成）

- **代码（三个模块从占位符转真）**：
  - `mqi/engine.py`：三级里程加权（路段→路线→路网同一式、同一分母）、必需格门一次报全、
    部分口径声明逐分项点名、`assign_grade` 消费 `grade_threshold.mqi` 的含界口径、
    `aggregate_year` 批量入口、`result_payload`；
  - `strategy/rules.py`：`action_rule.maintenance_trigger` 的 IF/THEN 规则链（登记顺序首条命中）、
    三种拒算原因分开写、`rank_priority` 主键可配 + 固定次级键 + 空值排最后、`result_payload`；
  - `strategy/compare.py`：消费 `partition_change` 出 `uncomparable`（与登记年序无关）、
    差值与劣化速率固定符号口径、`explain_change` 把变化拆到贡献项并回指台账行号、`result_payload`；
- **接线**：`generator._numeric_truth_probe` 四列全部接引擎（一次 `compute_pci` + 一次路段级汇总，
  列间自洽）；`TRUTH_GOVERNING_KEYS` 汇总列补 `grade_threshold.mqi` 并与 `aggregation_required_keys()` 对账；
  `manifest.coefficient_gate.truth_gates` 逐列记判据；`selfcheck` 按路径说出数判据；
  `_meta.MILESTONE` → M4，占位符登记表 6 → 3；
- **契约与结构（登记在 `plan/02` §9 第 25–28 条）**：汇总分母定义（纳入成员长度和，blocked 成员连同
  里程退出）；`CompareResult.comparability_reason` 必带可归类代码 + 新增 `component_scope_mismatch`；
  批量对比对象集改并集；`partial` 不给等级；`ActionSuggestion` 增上下文字段（`CONTEXT_FIELDS`，
  故意不进 `NUMERIC_FIELDS`）；未触发条件判 blocked；
- **文档**：`plan/05` §八–§十二（三级算式与分母、部分口径模板文本、汇总拒算表、规则链契约与判定语义、
  年对比判定顺序表 9 步、数值与拆解口径、§十一 出口实测表、§十二 还欠什么）；
  `plan/02` §三 模块表三行转✅、§六 命令表两行转✅、§七 守门测试清单加三行、§八 M4 打勾 + 偏差、
  §9 第 25–28 条；`plan/00` 里程碑 M4 行 + 决策记录 5 条；`plan/03` §八 M4 行；
  `README` 状态行 / 特性三条 / 命令面 / 评测表两行改写 / M4 纪律类证据段 / 371 项口径；
  `data/README` §三 真值措辞与门表两行；
- **测试（286 → 371，净增 85，门全部重写未删除）**：新增 `test_m4_mqi.py`（26 项）、
  `test_m4_strategy.py`（37 项）、`test_m4_cli.py`（14 项）；重写
  `test_cli_contract` 占位符命令两条、`test_placeholder_registry` 两条 + 新增 M4 转真两条、
  `test_m2_assess` 的 M4 两列一条拆成正反两条、`test_results_contract` 的 compare 两条 +
  新增三条、`test_ruleset_builtin` 形状契约扩到 `mqi_weight.*` / `action_rule.*` 并新增四条；
  新增夹具包 `tests/fixtures/m4-fixture-asphalt.json`（12 格全夹具档，数值刻意避开任何规范数字）；
- **数据**：`data/truth` 12 份与 `data/raw/manifest.json` 重生成并**单独提交**（`data/raw` 的 12 份 CSV 位级未变）。

## 二、M5 待办（按顺序做，全部做完才算完）

1. **指标计算**：`bench/evaluation.py` 从占位符转真，四类指标（复算误差 / 等级判定准确率 /
   排序一致性 / 异常召回与误报）+ M4 加进 README 的两类（汇总口径一致性、变化贡献排序一致性）
   全部由命令算出；每条指标显式报 `分母 / 分子 / 状态`（四态之一），拿不到就报不可判或不可用。
2. **两条通路分别报**：内置包（交付面）与夹具包（数值通路）各一组数字，措辞不得互相顶替；
   判据一律走 `generator` 的必需格函数。
3. **门禁脚本**：只红于"未达标 / 不可用 / 名单外新不可判"；已声明的不可判名单写进代码常量，
   新增不可判项要显式登记。
4. **`rmqc bench run`**：从返回 3 改为真跑（`--json`、退出码沿用 0/1/2/3 与四态映射）；
   `report` / `gui` 继续返回 3 并点名 M6。
5. **`plan/06-基准与评测.md` 完成**：黄金用例（M2 的两条 + M4 的汇总/分级/变化拆解各一条可手算复核）、
   指标定义（分子分母与判据）、复现命令（一键）。
6. **README 评测表与命令输出逐行对账**：表格由 `bench run --json` 生成，测试断言两者一致；
   `test_skeleton_metric_table_is_all_unavailable` 要**重写**而不是删。
7. **数字与措辞同步**：371 项口径若增减要同步 README / `plan/02` / `plan/05`；
   M4 的实测数字（partial 36 / blocked 6 / ok 0、36 对次含 9 uncomparable、231 次重排）
   从 `.tmp_verify/M4/measure.log` 变成 `bench run` 的命令输出。
8. **测试**：双向门纪律同上；每条指标至少一个"分子分母都对"的正证 + 一个"分母为 0 时如实报不可判"
   的反证；禁"已确认/已核实/最终确定"由 `privacy.assert_honest_wording` 在导出路径拦住。
9. **干净环境验证（本棒做一次）**：复制 `.tmp_verify/M4/clean_verify.sh` 成 M5 批次（`WORK` 换
   `.tmp_verify_m5_clean`），把 `bench run` 的期望退出码加进去；**收尾提交先 commit 再 clone**。
10. （可选，成本低）**重试 `jtst.mot.gov.cn` 行业标准详情页**（M3 那轮 503，URL 形态已定位）——
    若通了，先只登记"现行/废止"状态与条款号（转 `located`、`values` 仍 null），把 14 格从
    "一无所知"推进到"知道该翻哪张表"；数值仍要拿到正文才转 `verified`。
11. **`applies_to` 缺"技术等级"维度**（M3 省级原文暴露、M4 未动）：现有 `province / year / surface_type`
    无法表达"二级及以上用 JTG、四级及以下用地方标准"这种切换。M4 不做省份包，缺口记录保留在
    `plan/04` §五；要做省份包必须先补这一维（结构变更，登记 §9 并同步夹具）。
12. 写 `plan/HANDOFF-M6.md`。

## 三、既定口径（动了会打挂基准，改动前先在 plan/02 §9 登记）

M0–M4 累计口径见 `plan/02` §9 第 1–28 条。M5 特别相关：

1. 三态 + `fixture`；生效档位 = `min(系数状态, 各依据条款状态)`；**条款号缺失 = 引擎拒算**；
2. `blocked` / `uncomparable` 数值字段全空；`partial` 必带 `scope_note`；**M4 起：`partial` 不给等级**；
3. 舍入：半值向上，得分 1 位（`PCI_DECIMALS`）、占比 3 位（`SHARE_DECIMALS`）；
   MQI 与差值、劣化速率同样 1 位；变化贡献项舍入后为 0 的条目不列；
4. 评定必需格 = `pci.engine.surface_table_keys(surface)`；**汇总必需格 = `mqi.engine.aggregation_required_keys()`**
   （= `mqi_weight.pavement` + `grade_threshold.mqi`）；**对策必需格 = `strategy.rules.action_required_keys()`**；
   三批都与真值支配格一一对账（有测试）。出数判据永远是"必需格全生效"，不是生效格总数；
5. 拒算三类入口：系数门 / 数据门 / 检出项门；悬空、重叠、闭合差、划分变更**不**阻断本段评定，
   但**阻断跨年可比**；
6. 百分制量程是结构常量，**规范阈值一律只能来自规则集**；对策类别与规模档词汇同理只能来自那一格；
7. `register_ref` = `data/README.md#N` 且该行真实存在（现在 9 行）；
8. 落盘产物无时间戳；`.gitattributes` 强制 LF；交付面 = 已跟踪文件（`tests/support_git.py`）；
9. M5 若把指标定义改分子分母（例如"准确率的分母从全部对象改成已出数对象"），
   **必须同步 README 表、`plan/06` 与既有门**并登记 §9；M6 导出消费 `result_payload()`，
   不得另起第二套字段口径；
10. 汇总分母 = 纳入汇总的路段长度和；blocked 成员连同里程退出并在口径声明里点名（§9 第 25 条）；
11. 批量年对比对象集 = 两年度**并集**；`uncomparable` 必带 `comparability_reason` 代码（§9 第 26 条）。

## 四、本机环境事实与坑（M0–M4 实测）

- 解释器：`py -3.8` = 3.8.8、`py -3.12` = 3.12.10，两者都有 pytest 与 pyyaml；
  **PySide6 只在 3.8 有**（6.6.3.1）→ GUI 测试跑"装了→3 / 没装→1"双向断言；
- `python`（不带版本号）是 Microsoft Store 别名，**静默 rc=49 不执行**；脚本一律 `py -3.8` / `py -3.12`，
  加 `-X utf8` 与 `PYTHONDONTWRITEBYTECODE=1`；
- pytest 在 py3.8 偶发**跑完全绿后于退出阶段崩溃**（栈在 pluggy/`_pytest.config`）→ 看数字，重跑即可；
  清 `__pycache__` 是首选自救（本机 Python 通道故障家族，不是代码问题）；
- 干净环境通路 M1–M4 四轮都真跑通过：`py -3.12 -m venv` + 激活 + `python -m pip install -U pip setuptools wheel`
  + `pip install -e .[dev]`（清华源 + `NO_PROXY="*"`）；venv 里一律 `python -m pip`（`py` 启动器绕过 venv）；
  PyPI 本地缓存命中时整轮 ~1.5–2 分钟，**别因为快就以为没跑**，看 `exits.tsv`；
- `rmqc` 控制台脚本在非 UTF-8 控制台输出 GBK 字节：抓 JSON 前 `export PYTHONIOENCODING=utf-8`
  （M4 的 clean_verify.sh 里已经这么写了，照抄即可）；
- 验证脚本自身也要绝对路径；临时产物只写 `.tmp_*/`（已 gitignore，字节门与扫描器跳过）；
  **M4 的实测脚本与输出留在 `.tmp_verify/M4/`（`measure.py` + `measure.log`），收尾不删**；
- 官方渠道实测（M3 留档）：`so.mot.gov.cn`、`rioh.cn`、`jtcbs.com.cn`、`nssi.org.cn` 连接失败（000），
  `jtt.hubei.gov.cn` 412（反爬），`std.samr.gov.cn` 页面 200 但正文靠脚本渲染；
  **例外：`jtst.mot.gov.cn`（交通运输标准化信息服务平台）是 503 而不是"没这东西"**，
  详情页 URL 形态 `…/hb/search/stdHBDetailed?id=<32 位 hex>` 已定位 → 想推进 14 格系数，
  先重试这一个域名（隔几小时或换网络），其余站点别再重复扫一遍；
  地方标准 DB 号码在国标委备案平台 `dbba.sacinfo.org.cn` 能拿官方全文（M3 就是这么拿到安徽/湖南两部）；
- `gh` 2.93.0 已登录，账号 `yuluo554`；仓库当前**无 remote**，M0–M4 只本地 commit；
  建仓与 push 属对外动作，需用户明确授权；
- 工作树里的 `.qoder-credits/` 未跟踪目录不属于本项目：别 `git add`，也别删。

## 五、DoD（M5 完成判据，逐项打勾）

- [ ] `bench/evaluation.py` 转真，指标清单与 README 评测表逐行对账（8 行都在）
- [ ] 每条指标报分子/分母/状态，内置包与夹具包**两组数字分别报**，措辞不互相顶替
- [ ] 等级判定准确率如实报"不可判（分母为 0）"并解释为什么（真值由同一内核算出，无独立规范真值）
- [ ] 门禁只红于"未达标 / 不可用 / 名单外新不可判"，已声明不可判名单在代码里
- [ ] `rmqc bench run` 真跑（含 `--json` 与四态退出码映射），`report` / `gui` 仍返回 3 并点名 M6
- [ ] blocked 对象不得从指标分母里悄悄摘掉；摘了要显式声明口径并写进文档
- [ ] `plan/06-基准与评测.md` 完成（黄金用例含 M4 的汇总/分级/变化拆解各一条可手算复核 + 复现命令）
- [ ] M4 末态基线表逐项未回退（371 项口径、assess/aggregate/compare 的 blocked 事实、
  24 份 CSV 位级一致或单独提交说明、`selfcheck` 按路径的出数判据行）
- [ ] 双通道全绿，收集数一致且逐项可解释（无静默 skip）
- [ ] 干净 clone + 新 venv 按 README 逐条一次跑通（含 `bench run`），退出码留档 `.tmp_verify/M5/`
- [ ] `plan/HANDOFF-M6.md` 落盘
- [ ] 本地 commit（不 push，除非用户授权）

## 六、关键命令速查

```bash
# 双通道测试
PYTHONDONTWRITEBYTECODE=1 py -3.8  -X utf8 -m pytest tests -p no:cacheprovider
PYTHONDONTWRITEBYTECODE=1 py -3.12 -X utf8 -m pytest tests -p no:cacheprovider

# 系数门 / 逐路径出数判据（M4 起）
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src py -3.8 -X utf8 -m road_mqi_checker selfcheck
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src py -3.8 -X utf8 -m road_mqi_checker --json selfcheck

# 台账 → 评定 → 汇总 → 对比（M4 起四步都真跑，内置包下全部拒算 = 退出码 1）
rmqc --db ledger.sqlite ledger init
rmqc --db ledger.sqlite import --file data/raw/S99-2022.csv --year 2022   # rc=1
rmqc --db ledger.sqlite import --file data/raw/S99-2023.csv --year 2023   # rc=0
rmqc --db ledger.sqlite assess --year 2022                                # rc=1（4 blocked）
rmqc --db ledger.sqlite aggregate --year 2022 --level segment|route|network   # rc=1（全 blocked）
rmqc --db ledger.sqlite --json aggregate --year 2022                      # required_keys / pending_keys / priority_list
rmqc --db ledger.sqlite compare --from-year 2022 --to-year 2023           # rc=1（3 blocked + 1 uncomparable）
rmqc --db ledger.sqlite --json compare --from-year 2022 --to-year 2023    # 每条带 comparability_reason
rmqc bench run                                                            # M5 起真跑（现在 rc=3）

# M4 出口实测（夹具通路，产物在 .tmp_verify/M4/measure.log）
PYTHONDONTWRITEBYTECODE=1 py -3.8 -X utf8 .tmp_verify/M4/measure.py

# M4 那两道"改系数/改汇总形状后先跑"的门
PYTHONDONTWRITEBYTECODE=1 py -3.8 -X utf8 -m pytest tests/test_ruleset_builtin.py -q
PYTHONDONTWRITEBYTECODE=1 py -3.8 -X utf8 -m pytest tests/test_m4_mqi.py tests/test_m4_strategy.py tests/test_m4_cli.py -q
```

M5 改代码时的最快回路：

```bash
PYTHONDONTWRITEBYTECODE=1 py -3.8 -X utf8 -m pytest tests/test_m4_cli.py tests/test_cli_contract.py -q
```

算法与口径看 `plan/05`（§八–§十二 是 M4 的部分），字段口径与真值语义看 `plan/03`，
**每格系数的查证进度看 `plan/04` 与 `data/README.md` §一**，代码是单点定义、文档只引用。
已安装包名 `road-mqi-checker`，入口 `rmqc` / `road-mqi-checker` / `python -m road_mqi_checker` 三者等价。

### 干净环境验证的复现步骤（每棒收尾都要真跑一次，别只走流程）

```bash
bash .tmp_verify/M5/clean_verify.sh        # 从 M4 那份复制，WORK 换成 .tmp_verify_m5_clean
cat .tmp_verify_m5_clean/exits.tsv         # 26+ 行 want/got 全部对上才算过
grep -a "porcelain data/" .tmp_verify_m5_clean/run.log   # 两次都应为 []
```

坑：`git clone` 取 **HEAD**，收尾提交必须先 commit 再验证；venv 建在仓库里时
"交付面 = 已跟踪文件"那条门是关键（`support_git.py`）；脚本内的日志与回执路径**一律写绝对路径**。

**M4 轮已真跑（2026-10-07，新 clone `d4512d0` + 新 venv py3.12.10）**：26 步退出码逐条符合期望
（见 §〇"干净环境"行）；`compare` 在交付面上如实出 1 个 `uncomparable`（`partition_shifted`）且不出变化率；
`bench generate` 两次后 `git status --porcelain data/` 均为空；`python -m pytest tests -q` = 0，371 全过。
本轮**没有发现闸门自身的新环境 bug**（M3 那轮发现的 clean_verify.sh 路径 bug 已在本轮脚本里修好并沿用）。
