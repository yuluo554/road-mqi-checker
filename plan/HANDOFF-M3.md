# HANDOFF · M3 规则与条款（查证活）

> 用法：新对话说「继续完成 `plan/HANDOFF-M3.md` 的 M3 任务」即可续接（本文件内命令均以仓库根为当前目录）。
> 上一棒：M2 评定内核（2026-10-07 完成，已本地 commit，未 push）。

## 〇、M2 末态基线（不得回退）

| 项 | 实测值 | 复核命令 |
|---|---|---|
| 提交 | 本地 main 一串 M0+M1+M2 提交（骨架 → 索引对账门 → M0 台账 → M1 数据通路 → M2 评定内核），工作树干净，**无 remote、未 push**；确切条数与哈希看 `git log --oneline` | `git log --oneline` / `git status --porcelain` |
| 测试 | 271 项，py3.8.8 与 py3.12.10 各 271 collected / 271 passed / 0 skip / 0 warning | `py -3.8 -X utf8 -m pytest tests` |
| 交付面 | 内置规则集 15 格**仍全 pending、仍无一个数字**；`data/raw` `data/truth` 演示数据逐字节未动（M2 只改了 `data/README.md` 这份文档） | `rmqc ruleset show` / `git status --porcelain data/raw data/truth`（应为空） |
| 命令面 | `version/selfcheck/ruleset/ledger/import/bench generate/assess` 真跑；`aggregate/compare/bench run/report/gui` 返回 3 并指明里程碑 | `rmqc assess --year 2022` |
| 评定通路实测 | 42 个"路段×年度"对象在夹具规则集下：**ok 28 / partial 8 / blocked 6**；复算误差 **0**（真值列 vs 台账通路逐字段比对）；贡献排序一致性 **1.00**（214 次重排比较全部一致） | 复算口径：全部对象入库后，用对应路面的夹具包逐个 `compute_segment_pci`，与按同一夹具包重生成的 `data/truth` 真值列比 `pci`/`grade`；排序口径：每条贡献清单逐位旋转 + 反序后重新 `expand_contributions` 比首序列。两条都已有常驻测试（`test_m2_assess.py`、`test_m2_trace.py`），临时脚本不入库 |
| 拒算实测 | 内置包下 `assess` 对 4 个路段逐个 blocked、数值字段全空、退出码 1；M1 注入的负值/超范围/单位错共 6 个对象逐个 blocked（原因里引用校验层类别） | `py -3.8 -X utf8 -m pytest tests/test_m2_assess.py -q` |
| 黄金用例 | 沥青 `SYN-G1` → PCI **87.7**、等级 良、扣分合计 12.3；水泥 `SYN-G2` → PCI **82.8**、partial、扣分合计 17.2（手算推导写在 `plan/05` §7.1） | `py -3.8 -X utf8 -m pytest tests/test_m2_pci_engine.py -k golden -q` |
| 换算式落点 | `pci/engine.py`（六格必需系数 + 三类拒算门 + 舍入）、`pci/trace.py`（贡献折算 + 固定次级键 + 行号回指）；形态契约写在 `plan/05` §二 | `plan/05-评定与汇总算法说明.md` |
| 真值接线 | `_numeric_truth_probe` → `pci.engine.compute_pci`（spy 测试证明被调用）；内置包下四列仍全 `pending:coeff=`；M4 两列写 `pending:engine=mqi.engine@M4` / `strategy.rules@M4` | `py -3.8 -X utf8 -m pytest tests/test_m2_assess.py -k "truth" -q` |
| 占位符登记表 | `pci.engine` / `pci.trace` 已移除（双向对账 + 显式反证测试），剩 M4/M5/M6 六个模块 | `py -3.8 -X utf8 -m pytest tests/test_placeholder_registry.py -q` |

留给 M3 的实测教训：

1. **M3 是数据活，不是代码活**。换算式、舍入、拒算门都在 M2 定稿并被测试锁住；
   M3 要改的只有 `src/road_mqi_checker/rulesets/base-jtg5210-2018.json` 的
   `status` / `values` / `basis` 四件套与 `data/README.md` §一 的登记行。**不要为了"看到数字"去动引擎**——
   形状契约（`plan/05` §二）已经写死，填错形状会被引擎拒算并点名字段，那是特性不是 bug。
2. **系数的 values 必须按形状填，且 pending→verified 必须同时补 values**。
   `ruleset/loader.py` 的 schema 门：自称 `verified` 但 `values` 为空 → **拒绝整包加载**；
   `pending/located` 却带数值 → 同样拒绝。所以一格只能一次改完（status + values + basis 四件套）。
   形状速查（细节见 `plan/05` §二）：
   - `deduct_ratio.<surface>_distress` → `{"ratios": {类型: {程度: 0～1 的比率}}}`，
     类型/程度名必须与 `ledger/models.py` 的 `DISTRESS_DICTIONARY` 完全一致（沥青 10 类、水泥 8 类 × 轻中重）；
   - `pci_component.ride_quality` → `{"weight": w}`（分项得分直接取 `rqi`）；
   - `pci_component.rutting` → `{"weight": w, "ideal_mm": a, "zero_mm": b}`，要求 `zero > ideal`；
   - `pci_component.skid_resistance` → `{"weight": w, "zero_value": a, "ideal_value": b}`，要求 `ideal > zero`；
   - `pci_weight.<surface>` → `{"weights": {"distress":…, "ride_quality":…, "rutting":…, "skid_resistance":…}}`，
     权重和不必 100，键名不许多出未认定分项；
   - `grade_threshold.pci` → `{"boundary": "lower_inclusive"|"lower_exclusive", "bands": [{"grade": 名, "min": 下界}]}`，
     **含界与否必须按原文确认**（这条有测试：同一分值在两种登记下必须给不同等级）；
   - `tolerance.length_closure` → `{"meters": x}`（或 `value`/`tolerance_m`），是用户自定口径，显式登记即可生效。
3. **只要六格必需系数还没全生效，`assess` 就仍然全 blocked** —— 这是 M2 的设计（缺任一格不出数）。
   所以 M3 中途"核完了三格"是没有可见数字输出的，别误判成接线坏了；
   要么核全 `surface_table_keys` 那六格，要么用 `tests/fixtures/pci-fixture-*.json` 的形状自查
   （夹具包只验形状与通路，不代表规范事实）。
4. **内置包一旦有生效系数，连带改动清单**（这几条门会红，都是"该红"，要重写而不是删除）：
   - `data/` 演示数据的真值四列会变数值 → **必须 `rmqc bench generate --force` 重生成并单独提交**
     （`test_m1_generator.py::test_regeneration_of_committed_fixtures_is_byte_identical` 与 manifest sha1 门会挂）；
   - `tests/test_ruleset_builtin.py:30`（断言内置包 `computable_coefficients() == []`）与同文件"包内无数字"的断言；
   - `tests/test_cli_contract.py:66`（`coefficient_gate.open is False`）与 `:136`（逐格 `computable is False`）；
   - `tests/test_m1_pipeline.py` 的闭合差"未判定"断言：容差格一旦生效就变检出/不报，
     `plan/03` §五 与 README 的"27 条 = 23 检出 + 4 未判定"数字同步改；
   - M2 新增的两条按内置包断言全 blocked 的测试：
     `test_m2_pci_engine.py::test_builtin_ruleset_blocks_every_object_with_numbers_all_empty`、
     `test_m2_assess.py::test_assess_with_builtin_ruleset_degrades_to_exit_one`
     （改成"用一套全 pending 的临时包断言拒算"，别整条删掉——这条门是本题的命门）；
   - README 状态行"当前 0 格生效"、`data/README.md` §三"四列现在仍一律是 pending 令牌"的措辞。
5. **查不到官方原文就留在 pending，并在台账记已查渠道**。`data/README.md` §一 第 1 行现在就是这个状态
   （多源二手、无官方公告页）。搜索摘要一律不采信；核对不过的格子不得用确定语气写进文档与报告
   （`privacy.assert_honest_wording` 在报告导出时拦"已确认/已核实/最终确定"）。
6. **`register_ref` 形式必须是 `data/README.md#N` 且那一行真实存在**（`test_ruleset_builtin.py` 逐格校验）。
   M3 新增依据行要同步那张表与测试；行号变了所有系数的引用都要跟着改。
7. 本机环境：`py -3.8 -m pytest` 偶发在**全部通过之后**于解释器退出阶段崩溃（栈停在 pluggy/`_pytest.config`）。
   先看数字：271 项全绿就是绿的，重跑即可；这是本机 Python 通道故障家族（清 `__pycache__`、
   带 `PYTHONDONTWRITEBYTECODE=1`），别记成代码问题去改代码。

## 一、M2 交付内容（已完成）

- 文档：`plan/05-评定与汇总算法说明.md`（M2 出口文档：换算式四条、系数 values 形状契约、
  舍入口径、拒算条件十条清单、贡献展开与排序键、两条通路同一内核、出口实测与两个黄金用例推导）；
  `plan/00` 里程碑 M2 打勾 + 决策记录 6 条；`plan/02` §3/§5/§6/§7/§8 回写、§9 新增第 17–22 条口径；
  `plan/03` §八 M2 行改为已交付；`data/README.md` §三 数值真值说明重写、§五 落地对照加 4 行；
  `README.md` 状态行、特性、命令与退出码、评测表两行换实测值；
- 代码（两个占位符模块转真实现，占位符登记表相应移除）：
  - `pci/engine.py`：`surface_table_keys`（六格必需系数，与 `TRUTH_GOVERNING_KEYS` 一一对账）、
    `compute_pci`（换算核：破损扣分 + 三项实测换算 + 权重归一 + 等级判定）、
    `compute_segment_pci` / `assess_year` / `load_segment_input` / `blocking_findings`（台账通路）、
    `result_payload` / `summarize_status`（给 M4/M6 的结构）、`BLOCKING_CHECK_KINDS`、`SHARE_DECIMALS`；
  - `pci/trace.py`：`TRACE_COLUMNS` 末列追加 `source_row_no`、`TRACE_ORDER_KEYS` 与 `order_key`
    （扣分降序主键 + 六个固定次级键、空值排后）、`expand_contributions`、`contributions_for_cell`、
    `top_contributors`（M4 年对比直接取用）、`report_lines`；
  - `results.py`：`DeductContribution` 增加 `source_row_no` 槽位，并对破损类贡献硬性要求行号；
  - `bench/generator.py`：`_numeric_truth_probe` 改为调评定引擎（按列分派，M4 两列仍点名占位符）、
    `_probe_input`（取落盘文本 + 按 `DUPLICATE_KEY_COLUMNS` 去文件内重复行）、`generate(..., ruleset=…)` 可选注入；
  - `cli.py`：`assess` 真跑（`--year`/`--segment`/`--json`，存在 blocked/partial 落 1）；
    `bench generate` 的真值说明行改为按生效系数格数动态输出；
- 测试：`tests/` 21 个文件 **271 项**（M2 新增 `test_m2_pci_engine.py` 30 项、`test_m2_trace.py` 11 项、
  `test_m2_assess.py` 16 项 + 共用 `support_pci.py`），双解释器各 271 collected / 271 passed / 0 skip / 0 warning；
- 夹具：`tests/fixtures/pci-fixture-{asphalt,cement}.json` 两套"已核对形态"的换算夹具
  （数值刻意避开任何真实规范数字；`test_release_redlines.py` 继续反向断言 `fixture` 字样不进交付面）。

## 二、M3 待办（按顺序做，全部做完才算完）

1. **换官方渠道**：目标是一份能定位条款号与表号的 JTG 5210-2018 原文电子版（交通运输部/标准公告页、
   出版发行机构的可阅页面等）。抓取缓存落 `.tmp_verify/M3/<批次>/`，配 manifest
   （URL + HTTP 码 + 字节数 + sha1），收尾不删。取不到就如实记"仍无官方渠道"，**不要**用二手数值。
2. **逐格核对入库**（按解锁面排序）：
   `deduct_ratio.asphalt_distress` → `deduct_ratio.cement_distress` →
   `pci_weight.asphalt` / `pci_weight.cement` →
   `pci_component.ride_quality` / `rutting` / `skid_resistance` →
   `grade_threshold.pci` → `grade_threshold.mqi` → `mqi_weight.pavement` →
   `action_rule.maintenance_trigger` → `tolerance.length_closure`（用户自定，显式登记即可）。
   每格：`status` 转 `verified` + `values` 按 §〇 教训 2 的形状填 + `basis` 四件套
   （`clause`/`channel`/`verified_at`/`locator`）+ `data/README.md` §一 登记行同步。
3. **水泥分项要不要车辙**：内置包里 `pci_component.rutting` 的 note 已经写了"需按原文确认"。
   原文不给水泥路面该分项就从 `pci_weight.cement` 的 weights 里**去掉这个键**（引擎会拒绝未知分项，
   去掉即不参与，不需要改代码），并把结论与条款号写进 `plan/04`。
4. **`plan/04-扣分规则集与条款映射.md`**：逐格"系数 key ↔ 标准号 ↔ 条款/表号 ↔ 渠道 ↔ 查证日期 ↔
   定位载体"一张表；地方细则差异单列一节（无差异就写"未检索到省级差异"，不要编）。
5. **重生成演示数据并单独提交**（若第 2 步让六格必需系数全生效）：`rmqc bench generate --force`
   → `data/truth` 评分两列变数值 → 与代码改动分成两个 commit，并把 §〇 教训 4 那批门逐个重写。
6. **数字同步**：README 评测表（等级判定准确率从"不可用"起算）、`plan/03` §五 校验结论数字、
   `data/README.md` §一/§三 状态与措辞、`selfcheck` 的"生效系数 N 格"叙述。
7. **测试**：`test_ruleset_builtin.py` 从"全 pending"改写成"每格要么 verified + 四件套齐全，
   要么 pending + values 为 null"（这是 M3 的门，不是删门）；新增逐格形状断言
   （比率 ∈ [0,1]、权重 > 0、`zero > ideal`、bands 下界唯一且降序可判）；
   若生效则补"内置包能算出数值"的正向用例与"部分格子仍 pending 时仍 blocked"的中间态用例。
8. **干净环境验证（本棒做一次）**：新目录 `git clone` + 新 venv，按 README 快速开始逐条跑到底
   （含 `assess`），把"新 clone 里 `bench generate` 幂等、`import` 与 `assess` 实跑"纳入脚本。
9. 写 `plan/HANDOFF-M4.md`。

## 三、既定口径（动了会打挂基准，改动前先在 plan/02 §9 登记）

M0–M2 累计口径见 `plan/02` §9 第 1–22 条。M3 特别相关：

1. 三态 + `fixture`；生效档位 = `min(系数状态, 各依据条款状态)`；**条款号缺失 = 引擎拒算**（M2 加严）；
2. `blocked`/`uncomparable` 数值字段全空；`partial` 必带 `scope_note`；
3. 舍入：半值向上，得分 1 位（`PCI_DECIMALS`）、占比 3 位（`SHARE_DECIMALS`）；
4. 评定路径必需系数集合 = `pci.engine.surface_table_keys(surface)` 六格，与真值支配格一一对账；
5. 拒算三类入口：系数门 / 数据门 / 检出项门（`BLOCKING_CHECK_KINDS` 四类）；
   悬空、重叠、闭合差、划分变更**不**阻断本段评定；
6. 百分制量程 `SCORE_SCALE`/`SCORE_FLOOR` 是结构常量，**规范阈值一律只能来自规则集**；
7. 白名单形式与 `data/README.md` §三 同步；`register_ref` = `data/README.md#N` 且该行真实存在；
8. 结论文本禁"已确认/已核实/最终确定"；落盘产物无时间戳；`.gitattributes` 强制 LF；
9. M3 若改动换算形状（新增字段、换分母定义），**必须同步两个夹具包 + 两个黄金用例的期望数字**，
   并在 §9 登记 —— 形状漂移会让"复算误差 = 0"这条指标失去意义。

## 四、本机环境事实与坑（M0/M1/M2 实测）

- 解释器：`py -3.8` = 3.8.8、`py -3.12` = 3.12.10；两者都有 `pytest`（8.3.5 / 9.1.1）与 `pyyaml` 6.0.3；
  **PySide6 只在 3.8 有**（6.6.3.1）→ GUI 测试跑两个分支（"装了→3 / 没装→1"双向断言）；
- `python`（不带版本号）在本机是 Microsoft Store 别名，会**静默返回 rc=49 且不执行**；
  长任务一律 `py -3.8` / `py -3.12`，脚本用 `py -X utf8`（控制台 GBK），并加 `PYTHONDONTWRITEBYTECODE=1`；
- pytest 在 py3.8 偶发**跑完 271 全绿后于退出阶段崩溃**（栈在 pluggy/`_pytest.config`）→ 重跑即可（§〇 教训 7）；
- 干净环境验证通路已跑通过两棒：`py -3.12 -m venv` + 激活 + `python -m pip install -U pip setuptools wheel` +
  `pip install -e .[dev]`（清华源 + `NO_PROXY="*"`）；激活后用 `python -m pip`（`py` 启动器会绕过 venv）；
- `gh` 2.93.0 已登录，账号 `yuluo554`；`git config user.email` 已是 noreply 形态；
- `core.autocrlf=true` → 靠 `.gitattributes` + CR 门兜；**别用 shell 重定向往工作树写验证文件**；
  临时产物只写 `.tmp_*/`（已 gitignore，字节门与扫描器跳过）；
- 仓库当前**无 remote**，M0–M2 只本地 commit；建仓与 push 属对外动作，需用户明确授权；
- 工作树里有个不属于本项目的 `.qoder-credits/` 未跟踪目录（某工具产物），别 `git add`，也别删；
- 扫树的闸门一律走 `tests/support_git.py`（交付面 = 已跟踪文件，不是工作树；git 输出按 UTF-8 解码）。

## 五、DoD（M3 完成判据，逐项打勾）

- [ ] 每个转为 `verified` 的系数都有 `clause/channel/verified_at/locator` 四件套，渠道为官方页面或标准原文电子版
- [ ] 抓取缓存与 manifest（URL + HTTP 码 + 字节数 + sha1）落在 `.tmp_verify/M3/<批次>/`，收尾不删
- [ ] 核对不通过的格子留在 `pending`，并在 `data/README.md` §一 记下已查渠道与失败原因
- [ ] `plan/04-扣分规则集与条款映射.md` 完成（逐格映射 + 地方差异说明，无差异也写明）
- [ ] 内置包形状契约不破：`selfcheck` 与 `ruleset show` 如实报告生效/拒算格数，schema 门不报错
- [ ] 若六格必需系数全生效：`rmqc assess --year 2022` 出数值（`ok`/`partial`），演示数据重生成并单独提交，
      `data/` 位级一致门在新数据上重新变绿
- [ ] §〇 教训 4 列出的每一条门逐个**重写**（不是删除），README/`plan/03`/`data/README` 的数字与措辞同步
- [ ] 双通道全绿，收集数一致且逐项可解释（无静默 skip）
- [ ] 干净 clone + 新 venv 按 README 逐条一次跑通（含 `assess`）
- [ ] `plan/HANDOFF-M4.md` 落盘
- [ ] 本地 commit（不 push，除非用户授权）

## 六、关键命令速查

```bash
# 双通道测试
PYTHONDONTWRITEBYTECODE=1 py -3.8  -X utf8 -m pytest tests -p no:cacheprovider
PYTHONDONTWRITEBYTECODE=1 py -3.12 -X utf8 -m pytest tests -p no:cacheprovider

# 内核自检 / 系数门 / 规则集逐格
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src py -3.8 -X utf8 -m road_mqi_checker selfcheck
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src py -3.8 -X utf8 -m road_mqi_checker ruleset show
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src py -3.8 -X utf8 -m road_mqi_checker --json ruleset list

# 台账 + 评定（M2 起可用）
rmqc --db ledger.sqlite ledger init
rmqc --db ledger.sqlite import --file data/raw/S99-2022.csv --year 2022   # 回执 + 八类校验，rc=1 若有拒入
rmqc --db ledger.sqlite assess --year 2022                                # 全 pending → 全 blocked，rc=1
rmqc --db ledger.sqlite --json assess --year 2022                         # 结构含 contributions（TRACE_COLUMNS）
rmqc --db ledger.sqlite assess --year 2022 --segment S99-A1

# 用用户目录跑"已核对形态"（把临时包放仓库外，别把 fixture 字样写进 data/）
RMQC_RULESET_DIR=/d/tmp/rulesets rmqc ruleset show
```

M3 只改 JSON 与文档时，最快的自查回路：

```bash
# 1) 改完内置包先过 schema 门（拒绝整包加载就是形状/四件套不对，错误会点名系数与字段）
PYTHONPATH=src py -3.8 -X utf8 -m road_mqi_checker ruleset show
# 2) 再跑受影响的门
PYTHONDONTWRITEBYTECODE=1 py -3.8 -X utf8 -m pytest tests/test_ruleset_builtin.py tests/test_m2_pci_engine.py -q
```

已安装包名 `road-mqi-checker`，入口 `rmqc` / `road-mqi-checker` / `python -m road_mqi_checker` 三者等价。
换算式与拒算口径看 `plan/05`，字段口径与真值语义看 `plan/03`，代码是单点定义、文档只引用。

### 干净环境验证的复现步骤（每棒收尾都要真跑一次，别只走流程）

```bash
WORK=.tmp_verify_m3 && rm -rf "$WORK" && mkdir -p "$WORK"
git clone . "$WORK/repo" && cd "$WORK/repo"
py -3.12 -m venv .venv && source .venv/Scripts/activate
export NO_PROXY="*" no_proxy="*"
python -m pip install -U pip setuptools wheel -i https://pypi.tuna.tsinghua.edu.cn/simple
python -m pip install -e ".[dev]" -i https://pypi.tuna.tsinghua.edu.cn/simple

rmqc selfcheck && rmqc ruleset show && rmqc --db ledger.sqlite ledger init
rmqc bench generate                    # 期望 0，且 git status --porcelain data/ 为空
rmqc --db ledger.sqlite import --file data/raw/S99-2022.csv --year 2022   # 期望 1（有拒入行）
rmqc --db ledger.sqlite import --file data/raw/S99-2023.csv --year 2023   # 期望 0
rmqc --db ledger.sqlite assess --year 2022        # 全 pending → 1；六格生效 → 数值 + 0/1
python -m pytest tests -q              # 期望全绿、0 skip
python -m road_mqi_checker selfcheck   # 入口等价性
```

坑：`git clone` 取的是 **HEAD**，所以收尾提交必须先 commit 再验证；
`py` 启动器会绕过 venv，激活后一律 `python -m pip`；venv 建在仓库里会让"交付面 = 已跟踪文件"
那条门成为关键（`support_git.py` 就是为这件事写的）。

**M2 首轮已真跑（2026-10-07，新 clone + 新 venv，py3.12.10）**，逐条实测退出码：
`version/selfcheck/ruleset show/ledger init` 全 0；`bench generate` 两次都 0 且
`git status --porcelain data/` 空（幂等门成立）；`import S99-2022` = 1（有拒入行）、
`import S99-2023` = 0；`assess --year 2022` = 1（4 个路段逐个 blocked）、
`--segment S99-A1` = 1、`--json assess --year 2023` = 1 且 payload 结构完整
（`counts`/`results[]`/`contributions[]` 用 `TRACE_COLUMNS`）；`python -m pytest tests -q` = 0，271 项全过；
`python -m road_mqi_checker selfcheck` = 0（三个入口等价）。**本轮没有发现闸门自身的新环境 bug。**
唯一要提醒下棒的：`rmqc` 控制台脚本在非 UTF-8 控制台输出的是 GBK 字节，
把 stdout 重定向成文件再按 UTF-8 解析会报 `UnicodeDecodeError` —— 抓 JSON 时加 `PYTHONIOENCODING=utf-8`
（README「已知环境问题」已记这条）。
