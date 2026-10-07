# HANDOFF · M4 汇总、对策与年对比

> 用法：新对话说「继续完成 `plan/HANDOFF-M4.md` 的 M4 任务」即可续接（本文件内命令均以仓库根为当前目录）。
> 上一棒：M3 规则与条款查证（2026-10-07 完成，已本地 commit ×2，未 push）。

## 〇、M3 末态基线（不得回退）

| 项 | 实测值 | 复核命令 |
|---|---|---|
| 提交 | 本地 main 一串 M0→M3 提交，工作树干净（只有一个不属于本项目的未跟踪 `.qoder-credits/`），**无 remote、未 push**；末两提交分别是 `5bb8b60`（代码+文档）与 `d8aba35`（演示数据重生成，**单独一个 commit**） | `git log --oneline -4` / `git status --porcelain` |
| 测试 | **286 项**（M3 净增 15），py3.8.8 与 py3.12.10 各 286 collected / 286 passed / 0 skip / 0 warning | `py -3.8 -X utf8 -m pytest tests` |
| 系数面 | 内置包 15 格：**生效 1 格**（`tolerance.length_closure`，用户自定 ±1 m）、**拒算 14 格**（全部规范来源格）；`selfcheck` 报"生效系数 1 格 → 系数门开" | `rmqc selfcheck` / `rmqc ruleset show` |
| 评定面 | `assess --year 2022` 对 4 个路段仍**逐个 blocked**、数值字段全空、退出码 1 —— 六格必需系数（两种路面合计 8 个 key）一格都没生效 | `rmqc --db ledger.sqlite assess --year 2022` |
| 闭合差 | 四年度 27 条 finding = **27 检出 + 0 未判定**；4 个非零闭合差（−200 / +100 m）全部转检出 `R004_CLOSURE_EXCEEDED`；用容差退回 pending 的临时包重跑，同一批回到"4 条未判定、差值照报" | `py -3.8 -X utf8 -m pytest tests/test_m1_pipeline.py -k closure -q` |
| 演示数据 | `data/raw` + `data/truth` 的 24 份 CSV **逐字节未动**（评分两列仍是 `pending:coeff=…` 令牌）；只有 `data/raw/manifest.json` 的 `coefficient_gate` 三段随系数状态更新 | `git show --stat d8aba35` |
| 依据台账 | `data/README.md` §一 现有 **9 行**：第 1 行记满 M3 渠道复核（官方页只有公告、标准平台靠脚本渲染、出版社与主编单位站点连不上、全文命中处全是文档分享站），第 9 行是用户自定容差口径；`register_ref` 全部指向真实行号 | `tests/test_ruleset_builtin.py` 逐格校验 |
| 查证留档 | `.tmp_verify/M3/{batch1,batch2,batch3,province}/manifest.tsv`（URL + HTTP 码 + 字节数 + sha1 + curl 退出码）+ `fetch.sh` + `clean_verify.sh`，**收尾不删** | `ls .tmp_verify/M3/*/manifest.tsv` |
| 干净环境 | 新 clone + 新 venv（py3.12.10）**17 步逐条符合期望退出码**：`version/selfcheck/ruleset show/ledger init/bench generate ×2/pytest/entry_module/ruleset list` = 0，`import S99-2022/assess/assess --segment` = 1，`import S99-2023` = 0；两次 `bench generate` 后 `git status --porcelain data/` 均为空 | `bash .tmp_verify/M3/clean_verify.sh`（结果看 `.tmp_verify_m3_clean/exits.tsv`） |

留给 M4 的实测教训：

1. **M4 起点仍是"无生效规范系数"**。`grade_threshold.mqi`、`mqi_weight.pavement` 与 14 格同源，
   M3 没能让它们生效（官方原文不可得，见 `plan/04` §一）。所以 M4 的汇总与对策在内置包下
   **必须同样 `blocked`、数值字段全空**，数值通路像 M2 那样用 `tests/fixtures/` 的夹具包自证。
   **不要为了"看到 MQI 数字"去造阈值** —— `plan/04` §二 那张表就是为了让下一棒知道哪格该翻哪张表。
2. **入参形态已经交接好，别另起取数路径**：`pci.engine.assess_year(conn, year, …, ruleset)` 返回
   `List[PciResult]`，直接喂给 `mqi.engine.aggregate_{segment,route,network}_mqi(conn, …, pci_results, ruleset)`
   和 `strategy.compare.compare_years(conn, segment_id, year_from, year_to, pci_results, ruleset)`；
   `result_payload()` 是 CLI `--json`、M4 汇总、M6 GUI 共用的同一份结构（`contributions` 在
   **每条 result 里**，不在 payload 顶层；blocked 时它是 `[]`）。
3. **"部分口径"是 M4 的红线**：首期只有路面分项可用，`mqi_weight.subgrade/bridge_tunnel/appurtenances`
   全 pending ⇒ 汇总值不得冒充完整 MQI，必须带 `scope_note` 点名"哪些分项未纳入"；
   分级也不得套用完整 MQI 的表述（`data/README.md` §一 第 13 行的 note 已写死这条）。
   `pci.engine.summarize_status` 已给出状态归并口径，`partial` 必带口径声明这条门在 `results.py`。
4. **M4 一旦让 `mqi_partial_truth` / `recommended_action_truth` 出数，`data/` 就要重生成并单独提交**
   （这次真的会改 `data/truth` 的两列）。连带门：
   `test_m1_generator.py::test_regeneration_of_committed_fixtures_is_byte_identical`、manifest sha1 门、
   `test_m1_generator.py::test_mqi_and_action_truth_columns_stay_pending_until_m4`
   （这条要**重写**成"必需格未齐时仍令牌 / 夹具下出数"，别删）、
   `data/README.md` §三 的"M4 两列仍点名占位符"措辞、README 评测表"等级判定准确率 = 不可用"那一行。
5. **出数判据只用 `generator.scoring_gate_pending_keys()` 这一类"必需格"口径**（`plan/02` §9 第 23 条）。
   M3 修掉的正是这个 bug：按"生效格总数"宣称会把"生效 1 格"说成"评分列已出数值"。
   M4 新增任何"能不能出数"的对外措辞（说明行、manifest、报告、GUI）都必须走必需格判据。
6. **不可比要拒变化率，不要摊分**：`partition_change` 表在 M1 就给出了不可比清单（`shifted` 等，
   detail 里明确"不可比 + 摊分"字样被测试禁止出现）；M4 的年对比消费它出 `uncomparable`，
   变化拆到贡献项用 `pci.trace.top_contributors`（次级键固定，M2 实测排序一致性 1.00）。
7. **拒算三类入口对 M4 同样适用**：系数门 / 数据门 / 检出项门（`BLOCKING_CHECK_KINDS`）。
   含异常数据的对象在汇总层也不得被"平均"进去 —— M2 的实测是 6 个注入异常对象逐个 blocked。
8. 本机环境（M0–M3 四棒实测，见 §四）：验证脚本一律写**绝对路径**日志 —— M3 的 `clean_verify.sh`
   第一版在 `cd` 进 clone 后用相对路径写日志，直接把后半程输出全丢了（跑完"看着是 0"其实啥也没记）。

## 一、M3 交付内容（已完成）

- **查证（数据活）**：换 6 类渠道复核 JTG 5210-2018，**结论是官方原文不可得**；
  14 格规范来源系数继续 pending 并逐渠道记档，抓取缓存 + manifest 留 `.tmp_verify/M3/`；
  省级差异单独一批检索（11 路，含 5 个省厅站点与标准平台地方库），结论"未检索到可采信的省级差异条款表"，
  不编造省份包；
- **唯一生效格**：`tolerance.length_closure = 1 m`（用户自定口径第 1 号），
  四件套齐全 + `register_ref` 改指台账第 9 行（原来指第 7 行"省级差异"，指错了）；
- **代码（一个真 bug）**：`bench/generator.py` 新增 `scoring_gate_pending_keys()`，
  `cli.py` 的 `bench generate` 说明行与 `manifest.coefficient_gate.truth_note` 由"生效格总数"
  改为"必需格是否全生效"；部分解锁时如实输出"必需系数还缺 8 格…本包生效系数 1 格，但未核对不进评定路径"；
- **文档**：新增 `plan/04-扣分规则集与条款映射.md`（渠道清单与逐条结论、15 格映射表、
  用户自定口径登记表、水泥车辙分项的待证结论、地方差异"未检索到"、M3 出口实测、给 M4 的四条事实）；
  `data/README.md` §一 重写 1–3 行 + 加第 9 行 + 加 M3 轮结论段、§三 真值措辞、§五 落地对照加 4 行；
  `README.md` 状态行与"为什么现在算不出分"重写、评测表与 M3 证据段、286 项口径；
  `plan/00` 里程碑 M3 打勾 + 决策记录 5 条、`plan/02` M3 段打勾 + §9 新增第 23–24 条、
  `plan/03` §五 校验结论数字（27 = 27 检出 + 0 未判定）与隐含结论、M3 行改已交付；
- **测试（271 → 286，门全部重写未删除）**：`test_ruleset_builtin.py` 从"全 pending"改成
  "逐格二选一（verified+四件套 / pending+null）+ 官方渠道判据 + 生效格形状契约（`values_shape_problems`）
  + 8 个坏形状反例 + 夹具包正证 + 无 locator 反证"，并新增"评定必需格仍全未生效"门；
  `test_m1_pipeline.py` 闭合差门拆双向（内置包容差生效→4 条全检出；临时包退回 pending→4 条未判定）+
  汇总门改名 `…_after_tolerance_is_registered` 并把 `undetermined==4` 改成 `==0`；
  `test_cli_contract.py` 两条改为从包自身推导（不写死 0）；`test_m2_assess.py` 泄漏门改为
  "规范来源格一律不可算 + 必需格仍全 pending"；
- **数据**：`data/raw/manifest.json` 重生成并**单独提交**（24 份 CSV 位级未变）。

## 二、M4 待办（按顺序做，全部做完才算完）

1. **三级 MQI 汇总**：`mqi/engine.py` 的 `aggregate_segment_mqi` / `aggregate_route_mqi` /
   `aggregate_network_mqi` 转真实现，权重只从规则集 `mqi_weight.*` 取（代码里不出现规范数字），
   里程加权口径三级一致；`assign_grade` 消费 `grade_threshold.mqi` 并按原文口径处理含界与否。
   内置包下这些格仍 pending ⇒ 一律 `blocked`，数值通路用夹具包跑通并留复算证据。
2. **部分口径**：首期只有路面分项 ⇒ 汇总对象必须带 `scope_note` 点名未纳入的分项与原因，
   状态用 `partial`；不得输出"完整 MQI"表述。出口实测要给出"多少对象 ok / partial / blocked"。
3. **对策规则链**：`strategy/rules.py::suggest_actions` 落地 IF/THEN，触发条件与阈值
   **来自 `action_rule.maintenance_trigger` 那一格**（该格 pending，且上位养护规范名称-编号对应关系
   查证失败 → 内置包下不得引用那个规范号，见 `data/README.md` §一 第 4 行）；
   `rank_priority` 的次级键固定、同分稳定。
4. **年对比**：`strategy/compare.py::compare_years` 消费 `partition_change` 出 `uncomparable`
   （不可比时**拒出变化率**），`explain_change` 把变化拆到贡献项（复用 `pci/trace.py`）。
5. **命令面**：`aggregate` / `compare` 从返回 3 改为真跑（`--json`、退出码沿用 0/1/2/3 口径），
   `bench run` / `report` / `gui` 继续返回 3 并点名 M5/M6。
6. **真值两列接线**：`_numeric_truth_probe` 按列分派到 `mqi.engine` / `strategy.rules`，
   `TRUTH_ENGINE_MODULES` 与占位符登记表相应移除（登记表从 6 个模块减到 4 个），
   重写 `test_mqi_and_action_truth_columns_stay_pending_until_m4` 而不是删掉；
   `rmqc bench generate --force` 重生成 `data/truth` 两列并**单独提交**。
7. **数字与措辞同步**：README 评测表（等级判定准确率起算）、`plan/03` §五、`data/README.md` §三、
   `selfcheck` 叙述、`plan/05` 的汇总与分级部分（M2 只写了评定侧）。
8. **测试**：双向门纪律同上（内置包 blocked + 夹具包出数各一条），禁"已确认/已核实/最终确定"
   由 `privacy.assert_honest_wording` 在导出路径拦住。
9. **干净环境验证（本棒做一次）**：`bash .tmp_verify/M3/clean_verify.sh`（把 `WORK`/批次目录换成
   `_m4`），逐条退出码留档；**收尾提交先 commit 再 clone**。
10. 写 `plan/HANDOFF-M5.md`。

## 三、既定口径（动了会打挂基准，改动前先在 plan/02 §9 登记）

M0–M3 累计口径见 `plan/02` §9 第 1–24 条。M4 特别相关：

1. 三态 + `fixture`；生效档位 = `min(系数状态, 各依据条款状态)`；**条款号缺失 = 引擎拒算**；
2. `blocked` / `uncomparable` 数值字段全空；`partial` 必带 `scope_note`；
3. 舍入：半值向上，得分 1 位（`PCI_DECIMALS`）、占比 3 位（`SHARE_DECIMALS`）；
4. 评定路径必需系数集合 = `pci.engine.surface_table_keys(surface)`，与真值支配格一一对账；
   **汇总路径必需格 = `mqi_weight.pavement` + `grade_threshold.mqi`**（M4 要照同样口径新增对账，
   不要把"生效格总数"当判据 —— §9 第 23 条）；
5. 拒算三类入口：系数门 / 数据门 / 检出项门；悬空、重叠、闭合差、划分变更**不**阻断本段评定；
6. 百分制量程是结构常量，**规范阈值一律只能来自规则集**；
7. `register_ref` = `data/README.md#N` 且该行真实存在（现在 9 行）；白名单形式与 §三 同步；
8. 落盘产物无时间戳；`.gitattributes` 强制 LF；交付面 = 已跟踪文件（`tests/support_git.py`）；
9. M4 若改动汇总形状（新增字段、换分母定义），**必须同步夹具包与黄金用例期望数字**并登记 §9。

## 四、本机环境事实与坑（M0–M3 实测）

- 解释器：`py -3.8` = 3.8.8、`py -3.12` = 3.12.10，两者都有 pytest 与 pyyaml；
  **PySide6 只在 3.8 有**（6.6.3.1）→ GUI 测试跑"装了→3 / 没装→1"双向断言；
- `python`（不带版本号）是 Microsoft Store 别名，**静默 rc=49 不执行**；脚本一律 `py -3.8` / `py -3.12`，
  加 `-X utf8` 与 `PYTHONDONTWRITEBYTECODE=1`；
- pytest 在 py3.8 偶发**跑完全绿后于退出阶段崩溃**（栈在 pluggy/`_pytest.config`）→ 看数字，重跑即可；
  清 `__pycache__` 是首选自救（本机 Python 通道故障家族，不是代码问题）；
- 干净环境通路 M2/M3 两轮都真跑通过：`py -3.12 -m venv` + 激活 + `python -m pip install -U pip setuptools wheel`
  + `pip install -e .[dev]`（清华源 + `NO_PROXY="*"`）；venv 里一律 `python -m pip`（`py` 启动器绕过 venv）；
  PyPI 本地缓存命中时整轮只需 ~1.5 分钟，**别因为快就以为没跑**，看 `exits.tsv`；
- `rmqc` 控制台脚本在非 UTF-8 控制台输出 GBK 字节：抓 JSON 前 `export PYTHONIOENCODING=utf-8`
  （README「已知环境问题」已记）；
- 验证脚本自身也要绝对路径（§〇 教训 8）；临时产物只写 `.tmp_*/`（已 gitignore，字节门与扫描器跳过）；
- 官方渠道实测不可达（M3 留档）：`so.mot.gov.cn`、`rioh.cn`、`jtcbs.com.cn`、`nssi.org.cn` 连接失败（000），
  `jtt.hubei.gov.cn` 返回 412（反爬），`std.samr.gov.cn` 页面 200 但正文靠脚本渲染 —— curl 取到空壳。
  M4 若还要查证，先接受"这些渠道拿不到原文"，别再花一轮重试同一批站点；
- `gh` 2.93.0 已登录，账号 `yuluo554`；仓库当前**无 remote**，M0–M3 只本地 commit；
  建仓与 push 属对外动作，需用户明确授权；
- 工作树里的 `.qoder-credits/` 未跟踪目录不属于本项目：别 `git add`，也别删。

## 五、DoD（M4 完成判据，逐项打勾）

- [ ] 三级 MQI 汇总权重全部来自规则集格，代码里不出现规范数字；内置包下如实 `blocked`
- [ ] 部分口径：未纳入分项逐一点名在 `scope_note` 里，`partial` 不带完整 MQI 表述
- [ ] 对策规则链每条挂条款依据；`action_rule.maintenance_trigger` 未核对时不引用上位规范号
- [ ] 年对比：不可比对象拒出变化率并出 `uncomparable`；变化能拆到贡献项（排序门仍绿）
- [ ] `aggregate` / `compare` 真跑（含 `--json` 与退出码），`bench run` / `report` / `gui` 仍返回 3 并点名里程碑
- [ ] 真值两列接线：夹具下出数、内置包下仍令牌；`data/truth` 重生成并**单独提交**，位级一致门在新数据上重新变绿
- [ ] 占位符登记表随 `mqi.engine` / `strategy.*` 转真而缩减，`test_placeholder_registry.py` 同步
- [ ] "出数判据 = 必需格全生效"在 M4 新增的每一处对外措辞里都成立（§〇 教训 5）
- [ ] M3 末态基线表逐项未回退（286 项口径、27 检出、assess 仍 blocked、24 份 CSV 位级一致或有单独提交说明）
- [ ] 双通道全绿，收集数一致且逐项可解释（无静默 skip）
- [ ] 干净 clone + 新 venv 按 README 逐条一次跑通（含 `aggregate` / `compare`），退出码留档
- [ ] `plan/HANDOFF-M5.md` 落盘
- [ ] 本地 commit（不 push，除非用户授权）

## 六、关键命令速查

```bash
# 双通道测试
PYTHONDONTWRITEBYTECODE=1 py -3.8  -X utf8 -m pytest tests -p no:cacheprovider
PYTHONDONTWRITEBYTECODE=1 py -3.12 -X utf8 -m pytest tests -p no:cacheprovider

# 系数面 / 门（M3 起：生效 1 格、拒算 14 格、门开但不出数）
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src py -3.8 -X utf8 -m road_mqi_checker selfcheck
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src py -3.8 -X utf8 -m road_mqi_checker ruleset show
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src py -3.8 -X utf8 -m road_mqi_checker bench generate

# 台账 + 评定（M4 的 aggregate/compare 要挂在同一台账与同一 pci_results 上）
rmqc --db ledger.sqlite ledger init
rmqc --db ledger.sqlite import --file data/raw/S99-2022.csv --year 2022   # rc=1（有拒入行）
rmqc --db ledger.sqlite assess --year 2022                                # rc=1（4 个 blocked）
rmqc --db ledger.sqlite --json assess --year 2022                         # contributions 在每条 result 里
rmqc --db ledger.sqlite aggregate --year 2022                             # M4 起真跑
rmqc --db ledger.sqlite compare --segment S99-A1 --from 2022 --to 2023    # M4 起真跑

# M3 那道"逐格二选一 + 形状契约"门（改系数 JSON 后先跑它）
PYTHONDONTWRITEBYTECODE=1 py -3.8 -X utf8 -m pytest tests/test_ruleset_builtin.py -q
```

M4 改代码时的最快回路：

```bash
PYTHONDONTWRITEBYTECODE=1 py -3.8 -X utf8 -m pytest tests/test_m2_pci_engine.py tests/test_m2_assess.py -q
```

换算式与拒算口径看 `plan/05`，字段口径与真值语义看 `plan/03`，
**每格系数的查证进度看 `plan/04` 与 `data/README.md` §一**，代码是单点定义、文档只引用。
已安装包名 `road-mqi-checker`，入口 `rmqc` / `road-mqi-checker` / `python -m road_mqi_checker` 三者等价。

### 干净环境验证的复现步骤（每棒收尾都要真跑一次，别只走流程）

```bash
bash .tmp_verify/M3/clean_verify.sh          # 脚本内 WORK 换成 .tmp_verify_m4_clean，批次目录换 M4
cat .tmp_verify_m3_clean/exits.tsv           # 17 行 want/got 全部对上才算过
grep -a "porcelain data/" .tmp_verify_m3_clean/run.log   # 两次都应为 []
```

坑：`git clone` 取 **HEAD**，收尾提交必须先 commit 再验证；venv 建在仓库里时
"交付面 = 已跟踪文件"那条门是关键（`support_git.py`）；脚本内的日志与回执路径**一律写绝对路径**。

**M3 轮已真跑（2026-10-07，新 clone `d8aba35` + 新 venv py3.12.10）**：17 步退出码逐条符合期望
（见上表"干净环境"行）；`bench generate` 两次后 `git status --porcelain data/` 均为空；
`--json assess --year 2022` 的 `counts = {blocked:4, ok:0, partial:0, uncomparable:0}`、
4 条 result 的 `pci` 全空、`contributions` 为 `[]`；`python -m pytest tests -q` = 0，286 项全过；
`python -m road_mqi_checker selfcheck` = 0（三个入口等价）。本轮**没有发现闸门自身的新环境 bug**，
但发现了 `clean_verify.sh` 第一版自己的路径 bug（已修，教训记 §〇 第 8 条）。
