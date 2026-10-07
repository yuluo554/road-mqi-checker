# HANDOFF · M6 交付、打包与发布

> 用法：新对话说「继续完成 `plan/HANDOFF-M6.md` 的 M6 任务」即可续接（本文件内命令均以仓库根为当前目录）。
> 上一棒：M5 基准与评测（2026-10-07 完成，已本地 commit，未 push）。

## 〇、M5 末态基线（不得回退）

| 项 | 实测值 | 复核命令 |
|---|---|---|
| 提交 | 本地 main 一串 M0→M5 提交（M5 末态 `3c8caa6`），工作树干净（只有不属于本项目的未跟踪 `.qoder-credits/`），**无 remote、未 push** | `git log --oneline -3` / `git status --porcelain` |
| 测试 | **410 项**（M5 净增 39），py3.8.8 与 py3.12 双通道各 410 collected / 410 passed / 0 skip / 0 warning | `py -3.8 -X utf8 -m pytest tests` |
| 系数面 | 内置包 15 格：**生效 1 格**（`tolerance.length_closure`）、**拒算 14 格**；`selfcheck` 的按路径出数判据行不变 | `rmqc --json selfcheck` 的 `path_gates` |
| 评定面 | `assess --year 2022` 对 4 个路段仍逐个 **blocked**、数值字段全空、退出码 1（M3/M4 基线未回退） | `rmqc --db ledger.sqlite assess --year 2022` |
| 汇总面 | 内置包下 `aggregate` 三级全部 **blocked**、`priority_list` 全 blocked、退出码 1；该年度无路段行 → 退出码 2 | `rmqc --db ledger.sqlite --json aggregate --year 2022` |
| 对比面 | 内置包下 `compare 2022→2023` 出 blocked + `uncomparable`（`partition_shifted`），全部不出变化率，退出码 1 | `rmqc --db ledger.sqlite --json compare --from-year 2022 --to-year 2023` |
| 基准面（新） | `rmqc bench run` 真跑：**8 指标 × 2 通路 = 16 行**，每行带分子/分母/状态/判据/说明；整体**退出码 0**（未达标 0、不可用 0、不可判 6 项全在名单内） | `rmqc bench run` / `rmqc --json bench run` |
| 基准面实测 | 内置包：数值类 4 项 + 等级判定 = 不可判（分母 0），召回 **19/19**、误报 **0/30**、位级一致 **25/25**；夹具包：复算 **144/144**（最大误差 0.0，令牌相符 24/24）、扣分重排 **214/214**、三级复算 **32/32**、变化重排 **231/231**、召回 19/19、误报 0/30、位级一致 25/25 | `rmqc --json bench run` 的 `metrics` |
| 文档同源 | README 评测表由 `evaluation.render_readme_block()` 生成，夹在 `<!-- bench-run:begin/end -->` 之间；冷跑两次 `--json` stdout 逐字节一致 | `py -3.8 -X utf8 -m pytest tests/test_m5_bench.py -q` |
| 演示数据 | `data/raw` 12 份 CSV + `manifest.json` 与 `data/truth` 12 份 **位级未动**（M5 没重生成入仓数据） | `git status --porcelain data/`（应为空） |
| 占位符 | 登记表从 3 个缩到 **2 个**（`report.exporters` M6、`gui.app` M6）；`_meta.MILESTONE = "M5"` | `tests/test_placeholder_registry.py` |
| 干净环境 | 新 clone `3c8caa6` + 新 venv（py3.12.10）**28 步逐条符合期望退出码**：0 档 18 步（含 `bench run` = 0、`bench generate` ×2、pytest 410 全过）、1 档 8 步（import 有拒入 / assess / aggregate ×3 / compare ×2 / `gui` 缺 `[gui]` extras）、2 档 2 步（无路段行 + `bench run --seed 777`）、3 档 1 步（`report`）；两次 `bench generate` 后 `git status --porcelain data/` 均为空；新 clone 里 `bench run --json` 的 `README 表 == bench run 渲染` 判真、未声明不可判 = []、不可用 = 0、scratch 已清理 | `bash .tmp_verify/M5/clean_verify.sh` → `.tmp_verify_m5_clean/exits.tsv` 与 `run.log` |

留给 M6 的实测教训：

1. **M6 只消费命令已有的字段，不另起第二套口径**。导出与 GUI 要用的结构体是
   `pci.engine.result_payload` / `mqi.engine.result_payload` / `strategy.rules.result_payload` /
   `strategy.compare.result_payload`（M4 已备齐 `PLAN_COLUMNS` 需要的全部字段），
   评测面则直接消费 `bench run --json` 的 `metrics[] / paths{} / coverage / gate`。
   报告里如果要印"等级判定准确率"，**必须印成"不可判（分母为 0）"**并带上说明列那句
   "等级由同一内核算出，无独立规范真值"，不许印成达标。
2. **README 评测表是生成物**：改表格 = 改 `evaluation.render_readme_block()`，两者由
   `test_readme_metric_table_is_generated_from_bench_run` 逐行对账；M6 若给报告加"评测摘要"一节，
   请从同一段渲染函数出发，别复制粘贴一份文本。
3. **`bench run` 的夹具通路依赖 `tests/fixtures/`**：查找顺序是"显式 start → cwd 上溯 6 层 → 包源树上溯"
   （`evaluation.fixture_dir_candidates`），所以**源码态 / 可编辑安装**在仓库内或仓库子目录里跑都能拿到夹具包；
   而打包态（exe 内部没有 `tests/`）拿不到 ⇒ 该通路 8 行如实报 `不可用`、门禁落 **3**。这是设计不是回归
   （红线：夹具值不进交付面）。M6 的中立目录验证要按这条判；若希望 exe 也能报夹具通路，只能加显式参数
   （如 `--fixtures-dir`）并由用户指向测试树，**不要**把夹具 JSON 随包发布 —— `test_release_redlines.py` 的
   `test_fixture_channel_never_appears_in_data_or_shipped_rulesets` 会直接把内置包/data 扫红。
4. **`report` / `gui` 现在返回 3**（占位符抛 `MilestoneNotImplemented`）。转真时要**重写**这两道门而不是删：
   `test_cli_contract.py::test_placeholder_commands_return_unimplemented`（现在只剩 `report`）与
   `test_placeholder_registry.py`（登记表从 2 → 1 → 0，同时 `_meta.MILESTONE` 前进到 M6）。
5. **措辞纪律在导出路径上是硬门**：`privacy.assert_honest_wording` 禁"已确认 / 已核实 / 最终确定 / 必定"；
   `bench.evaluation._row()` 已经在构造每一行时调用它（`test_row_builder_refuses_over_claimed_wording`），
   M6 的导出层要在同一文档通路上再调一次，别指望上游拦干净。
6. **打包构建红线**（M4/M5 的位级一致经验直接复用）：onedir + spec `datas` 白名单 + 构建后递归扫描
   （夹具字样、真实形态标识符、标准全文）+ 内嵌数据与仓库逐份 sha 对账；冻结态的数据目录查找走
   `data_paths` 的五级优先级（含 exe 分支），验证要在 `%LOCALAPPDATA%\Temp` 这类中立目录跑。
7. **指标分子/分母若要改口径**（例如把准确率的分母从"全部对象"改成"已出数对象"），
   必须同步 README 表、`plan/06` 与既有门，并在 `plan/02` §9 登记（M5 新增的是第 29–32 条）。
   分母里摘掉 blocked 对象是允许的，但**必须在 `basis`/`note` 里写明**并被文档复述（§9 第 31 条）。
8. **不可判名单是代码常量** `evaluation.DECLARED_INDETERMINATE`：新增不可判项要显式登记，
   并在 `plan/06` §四说明为什么；未登记的不可判会让门禁落 2（把"通路被摘掉对象"当事故）。
9. **`applies_to` 仍缺"技术等级"这一维**（M3 省级原文暴露、M4/M5 都没动）：现有 `province / year /
   surface_type` 表达不了"二级及以上用 JTG、四级及以下用地方标准"的切换条件，缺口与落地前置条件
   记在 `plan/04` §五。M6 若要真做省份包，这是**先决条件**（结构变更：按 `plan/02` §9 登记，
   并同步 `tests/fixtures/` 每个包的 `applies_to`）；补不了就别造省份包，保持"缺口有记录"。
10. **系数 14 格仍未解锁**：M5 收尾再探 `jtst.mot.gov.cn`（首页 / 检索页 / 详情页）三种 URL 全部 503，
    `HANDOFF-M5` §二 第 10 条的可选重试没有产出。评测表的不可判名单短期内不会缩短——
    M6 的报告与 GUI 要按"交付面不出数"来设计呈现，不要为了界面好看假装有数。
11. 本机环境（M0–M5 六棒实测，见 §四）：验证脚本一律写**绝对路径**日志；M5 的
   `.tmp_verify/M5/clean_verify.sh` 是在 M4 那份基础上加了 `bench run`（期望 0）与
   `bench run --seed 777`（期望 2）两条，M6 复制成 `_m6` 批次再把打包/导出步骤追加进去即可；
   M5 的回执与实测脚本落在 `.tmp_verify/M5/`（`exits.tsv` 28 步、`run.log`、`golden.py` +
   `golden.log`、`sync_readme.py`），收尾不删。

## 一、M5 交付内容（已完成）

- **代码（`bench/evaluation.py` 从占位符转真）**：
  - 指标清单从 6 条扩到 **8 条**（新增 `aggregation_consistency`、`change_contribution_order`，
    即 M4 加进 README 的两类），全部由命令算出，逐行报 `分子 / 分母 / 状态 / 判据 / 说明`；
  - 两条通路 `PATH_BUILTIN`（内置包，交付面）与 `PATH_FIXTURE`（夹具包，数值通路）分别报数，
    `PATH_LABELS` / `PATH_HONESTY` 把"这列数字能说明什么、不能说明什么"写进输出本身；
  - `PathContext`：一条通路一份台账 + 评定/汇总/对策/年对比 + 校验检出 + 按本通路规则集重生成的
    真值（复算比对的两侧才是同一本账）；产物一律写系统临时目录、跑完删除，不落仓库；
  - 指标：`metric_rescore_drift`（真值四列 ↔ 台账通路逐格比对，拒算格改报"令牌与拒算相符 n/n"）、
    `metric_grade_accuracy`（分母 = 独立规范等级真值数 = 0，两通路都不可判）、
    `metric_contribution_order`（逐位旋转 + 反序）、`metric_aggregation_consistency`
    （由路段级结果 + 台账里程独立复算路线级/路网级的 MQI 值与加权里程分母）、
    `metric_change_contribution_order`（年对比变化拆解两侧重排）、`metric_anomaly`（召回 + 误报）、
    `metric_byte_reproducible`（内置包比入仓产物、夹具包比两次重生成）；
  - 门禁 `gate()`：只红于「未达标(1) > 不可用(3) > 名单外新不可判(2)」，`STATE_TO_EXIT` 不变；
  - `render_readme_block()` / `readme_table()`：README 评测表的生成器（含标记行）；
- **接线**：`cli.cmd_bench` 的 `run` 分支真跑（`--json` 出结构、退出码取 `gate()["exit"]`；
  `--seed` 非默认值 → `InputUnavailable` 落 2，因为基准定义在冻结演示数据 seed=20261007 上）；
  `_meta.MILESTONE` → M5、占位符登记表 3 → 2；`evaluation.EXPECTED_KIND_BY_ISSUE` 成为
  "注入类别 → 校验项"的单点词汇，`tests/test_m1_pipeline.py` 改为引用它；
- **文档**：`plan/06-基准与评测.md`（指标定义与分子分母、两通路实测、门禁语义、五条可手算的黄金用例、
  一键复现命令、口径更正与已知不足）；`plan/02` §三 M5 行转✅、§五/§六 命令面、§七 守门清单加
  `test_m5_bench.py`、§八 M5 打勾 + 偏差、§九 新增第 29–32 条；`plan/00` 文档索引 / 里程碑 M5 行 /
  决策记录；`plan/05` 测试项数与"实测数已并入命令"的指向；`README` 状态行 / 特性一条 / 快速开始 /
  退出码段 / 评测表（由命令生成）/ M5 纪律类证据段 / 410 项口径；
- **测试（371 → 410，净增 39，门全部重写未删除）**：新增 `tests/test_m5_bench.py`（38 项：清单一致性、
  两通路 16 行齐全、内置包数值类必须不可判且分母 0、等级准确率不许挤成达标、不可判必须全部已登记、
  夹具通路实测值、blocked 不从分母里悄悄摘掉、门禁三类红 + 名单内豁免、措辞纪律在行构造时把关、
  夹具包缺失时报不可用、CLI 退出码与 `--json` 一致、冷跑两次逐字节一致、README 表逐行对账）；
  重写 `test_cli_contract.py` 的骨架表门（`test_metric_table_is_four_states_with_two_paths_of_numbers`）
  与占位符命令门（`bench run` 移出未实现清单）；重写 `test_placeholder_registry.py` 的里程碑门与
  登记表断言并新增 M5 转真门；`test_m1_pipeline.py` 改为引用单点注入词汇。

## 二、M6 待办（按顺序做，全部做完才算完）

1. **`report/exporters.py` 转真**：csv / md / docx 三种格式（docx 用标准库直写 OOXML + 固定 `ZipInfo`，
   不引 python-docx）；列名走既有 `PLAN_COLUMNS`，字段一律来自 `result_payload()`；
   每份导出末尾挂 `report.disclaimer` 的固定免责声明 + 数据类别说明，未核对项走 `assert_honest_wording`。
2. **`gui/app.py` 转真**：七页签接通同一 CLI 内核（只转发，不另起行为），offscreen 测试常驻；
   缺 PySide6 的降级路径保持"装了→3 / 没装→1"的双向断言（转真后这一档改成 0/1）。
3. **打包**：PyInstaller onedir 双 exe（GUI + 控制台），spec 的 `datas` 白名单逐条列出；
   构建后**递归红线断言**：内嵌数据与仓库逐份 sha 对账、无夹具字样、无真实形态标识符、无标准全文；
   在中立目录（`%LOCALAPPDATA%\Temp`）+ `env -i` 下跑 CLI 五连与 GUI 存活探针。
4. **一键交付验证脚本**：复制 `.tmp_verify/M5/clean_verify.sh` 成 `_m6` 批次（`WORK` 换
   `.tmp_verify_m6_clean`），追加导出三格式与 exe 探针；**收尾提交先 commit 再 clone**。
5. **脱敏与发布**：脱敏四步 + 构建产物本体扫描 + 提交邮箱全历史核查，留档 `plan/RELEASE-M6.md`；
   建仓与 push 属对外动作，**需用户明确授权**；CI 四矩阵（ubuntu/windows × 3.8/3.12）首跑全绿；
   tag + release + README 状态行转正。
6. **数字与措辞同步**：410 项口径若增减要同步 README / `plan/02` / `plan/06`；
   README 的"免安装 exe（M6 之后提供）"段落在 exe 真做出来后才能兑现。
7. **文档收口**：`plan/07-交付与打包.md` 完成（GUI 结构、打包 spec、构建红线、中立目录探针）；
   `plan/00` 索引与里程碑表 M6 行、`plan/02` §三/§六/§七/§八 相应行转真；写 `plan/HANDOFF-M7.md` 或收口快照。

## 三、既定口径（动了会打挂基准，改动前先在 plan/02 §9 登记）

M0–M5 累计口径见 `plan/02` §9 第 1–32 条。M6 特别相关：

1. 三态 + `fixture`；生效档位 = `min(系数状态, 各依据条款状态)`；条款号缺失 = 引擎拒算；
2. `blocked` / `uncomparable` 数值字段全空；`partial` 必带 `scope_note`；`partial` 不给等级；
3. 出数判据永远是"必需格全生效"（`generator.scoring/aggregation/action_gate_pending_keys`），
   不是生效格总数；
4. 舍入：半值向上；得分 / MQI / 差值 1 位（`PCI_DECIMALS`）、占比 3 位（`SHARE_DECIMALS`）、
   评测比值 2 位（`evaluation.METRIC_DECIMALS`）；
5. 四态映射 `STATE_TO_EXIT`（不可判→2）与门禁优先级 `GATE_PRECEDENCE`（未达标 > 不可用 > 名单外不可判）；
   已声明不可判名单是代码常量，新增要登记；
6. 指标行 = `METRICS × PATH_ORDER`（16 行），两通路措辞不得互相顶替；blocked 对象不得从分母里悄悄摘掉；
7. 规范阈值与词汇只能来自规则集那一格（对策类别、规模档、分级阈值、权重、容差）；
8. 落盘产物无时间戳（`bench run --json` 两次冷跑逐字节一致已被测试锁住）；`.gitattributes` 强制 LF；
   交付面 = 已跟踪文件（`tests/support_git.py`）；
9. 结论文本禁"已确认 / 已核实 / 最终确定 / 必定"，未核对项只能写"应核实 / 待核对"；
10. `register_ref` = `data/README.md#N` 且该行真实存在；演示数据带 `data_class=SYNTHETIC` 且走白名单。

## 四、本机环境事实与坑（M0–M5 实测）

- 解释器：`py -3.8` = 3.8.8、`py -3.12` = 3.12.10，两者都有 pytest 与 pyyaml；
  **PySide6 只在部分环境有** → GUI 测试跑"装了→3 / 没装→1"双向断言；
- `python`（不带版本号）是 Microsoft Store 别名，**静默 rc=49 不执行**；脚本一律 `py -3.8` / `py -3.12`，
  加 `-X utf8` 与 `PYTHONDONTWRITEBYTECODE=1`；
- pytest 在 py3.8 偶发**跑完全绿后于退出阶段崩溃**（栈在 pluggy/`_pytest.config`），也偶发收集期
  `AttributeError/TypeError` 的假错（本机 Python 通道故障家族）→ **看数字、清 `__pycache__`、重跑**，
  不要在假错上改代码；多个 pytest 进程并发时这类抖动明显增多（M5 收尾实测：并发跑时一次 segfault，
  串行重跑 410/410 全绿）；
- 干净环境通路 M1–M5 五轮都真跑通过：`py -3.12 -m venv` + 激活 + `python -m pip install -U pip setuptools wheel`
  + `pip install -e .[dev]`（清华源 + `NO_PROXY="*"`）；venv 里一律 `python -m pip`（`py` 启动器绕过 venv）；
  本地缓存命中时整轮 ~1.5–2 分钟，**别因为快就以为没跑**，看 `exits.tsv`；
- `rmqc` 控制台脚本在非 UTF-8 控制台输出 GBK 字节：抓 JSON 前 `export PYTHONIOENCODING=utf-8`；
- 验证脚本自身也要绝对路径；临时产物只写 `.tmp_*/`（已 gitignore，字节门与扫描器跳过）；
  **M5 的实测脚本与输出留在 `.tmp_m5/` 与 `.tmp_verify/M5/`（`clean_verify.sh` + `sync_readme.py` + `golden.py` / `golden.log`，均为本机 scratch，不在交付面），收尾不删**；
- 官方渠道实测（M3 留档）：`so.mot.gov.cn`、`rioh.cn`、`jtcbs.com.cn`、`nssi.org.cn` 连接失败（000），
  `jtt.hubei.gov.cn` 412（反爬），`std.samr.gov.cn` 页面 200 但正文靠脚本渲染；**例外**：
  `jtst.mot.gov.cn` 是 503 而不是不存在，详情页 URL 形态 `…/hb/search/stdHBDetailed?id=<32 位 hex>` 已定位
  → 想让评测面的系数格转 `verified`，重试这一个域名；地方标准 DB 号码在 `dbba.sacinfo.org.cn` 能拿官方全文；
  **M5 收尾再探（2026-10-07）：首页、检索页、详情页三种 URL 全 503**（`HANDOFF-M5` §二 第 10 条的可选重试
  因此没有产出；14 格系数仍是"一无所知"，评测面的不可判名单短期内不会缩短）；
- `gh` 2.93.0 已登录，账号 `yuluo554`；仓库当前**无 remote**，M0–M5 只本地 commit；
  建仓与 push 属对外动作，需用户明确授权；
- 工作树里的 `.qoder-credits/` 未跟踪目录不属于本项目：别 `git add`，也别删。

## 五、DoD（M6 完成判据，逐项打勾）

- [ ] `report.exporters` 转真：csv / md / docx 三格式，字段全部来自 `result_payload()`，导出必带免责声明
- [ ] 导出路径拦得住过强结论（`privacy.assert_honest_wording`）与夹具污染（红线扫描）
- [ ] `gui.app` 七页签接通 CLI 通路，offscreen 测试常驻，不另起第二套行为
- [ ] onedir 双 exe + spec `datas` 白名单 + 构建后递归红线断言（内嵌数据与仓库逐份 sha 对账）
- [ ] 中立目录 + `env -i` 下 CLI 五连 + GUI 存活探针真跑，退出码留档 `.tmp_verify/M6/`
- [ ] M5 末态基线表逐项未回退（410 项口径、`bench run` 的 16 行与退出码 0、内置包 blocked 事实、
      24 份 CSV + manifest 位级一致、README 评测表与命令逐行对账）
- [ ] 双通道全绿，收集数一致且逐项可解释（无静默 skip）
- [ ] 脱敏四步 + 构建产物本体扫描 + 提交邮箱全历史核查，`plan/RELEASE-M6.md` 留档
- [ ] `plan/07-交付与打包.md` 完成；README 状态行与"免安装 exe"段落与事实一致
- [ ] 建仓 + push + CI 四矩阵首跑全绿 + tag / release（**均需用户授权**）
- [ ] 本地 commit（不 push，除非用户授权）

## 六、关键命令速查

```bash
# 双通道测试
PYTHONDONTWRITEBYTECODE=1 py -3.8  -X utf8 -m pytest tests -p no:cacheprovider
PYTHONDONTWRITEBYTECODE=1 py -3.12 -X utf8 -m pytest tests -p no:cacheprovider

# 基准评测（M5 已真跑）
PYTHONDONTWRITEBYTECODE=1 PYTHONIOENCODING=utf-8 PYTHONPATH=src py -3.8 -X utf8 -m road_mqi_checker bench run
PYTHONDONTWRITEBYTECODE=1 PYTHONIOENCODING=utf-8 PYTHONPATH=src py -3.8 -X utf8 -m road_mqi_checker --json bench run
PYTHONDONTWRITEBYTECODE=1 PYTHONIOENCODING=utf-8 PYTHONPATH=src py -3.8 -X utf8 -m road_mqi_checker bench run --seed 777   # rc=2

# README 评测表重新生成（改指标/改文案后跑它，再跑对账门）
PYTHONDONTWRITEBYTECODE=1 py -3.8 -X utf8 .tmp_verify/M5/sync_readme.py
PYTHONDONTWRITEBYTECODE=1 py -3.8 -X utf8 -m pytest tests/test_m5_bench.py -q

# M6 改代码时的最快回路
PYTHONDONTWRITEBYTECODE=1 py -3.8 -X utf8 -m pytest tests/test_cli_contract.py tests/test_release_redlines.py -q
```

### 干净环境验证的复现步骤（每棒收尾都要真跑一次，别只走流程）

```bash
bash .tmp_verify/M6/clean_verify.sh      # 从 M5 那份复制，WORK 换成 .tmp_verify_m6_clean
cat .tmp_verify_m6_clean/exits.tsv       # want/got 全部对上才算过（M5 是 28 步）
grep -a "porcelain data/" .tmp_verify_m6_clean/run.log   # 两次都应为 []
```

坑：`git clone` 取 **HEAD**，收尾提交必须先 commit 再验证；venv 建在仓库里时
"交付面 = 已跟踪文件"那条门是关键（`support_git.py`）；脚本内的日志与回执路径**一律写绝对路径**；
`bench run` 在 clone 根目录跑才有夹具通路（见 §二 第 3 条）。
