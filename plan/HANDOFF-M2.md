# HANDOFF · M2 评定内核

> 用法：新对话说「继续完成 `plan/HANDOFF-M2.md` 的 M2 任务」即可续接（本文件内命令均以仓库根为当前目录）。
> 上一棒：M1 数据先行（2026-10-07 完成，已本地 commit，未 push）。

## 〇、M1 末态基线（不得回退）

| 项 | 实测值 | 复核命令 |
|---|---|---|
| 提交 | 本地 main 一串 M0+M1 提交（骨架 → 索引对账门 → M0 台账 → M1 数据通路），工作树干净，**无 remote、未 push**；确切条数与哈希看 `git log --oneline` | `git log --oneline` / `git status --porcelain` |
| 测试 | 213 项，py3.8.8 与 py3.12.10 各 213 collected / 213 passed / 0 skip / 0 warning | `py -3.8 -X utf8 -m pytest tests` |
| 演示数据 | 已入仓为**冻结 fixtures**：`data/raw` 12 份检测表 + manifest（13 份）、`data/truth` 12 份真值；共 139 行 raw / 42 行 truth / 19 例注入 | `git ls-files data/` |
| 位级一致 | 同 seed 重跑逐字节一致；`rmqc bench generate` 在内容一致时**不改写任何文件**（`files_changed=0`），换 seed 才需要 `--force` | `rmqc bench generate` 后 `git status --porcelain data/`（应为空） |
| 实测指标 | 异常识别召回 **1.00（19/19）**、误报 **0.00（0/32 干净对象）**；校验结论 27 条 = 23 检出 + 4 未判定（全是闭合差） | `py -3.8 -X utf8 -m pytest tests/test_m1_pipeline.py -k "recall or false_alarm" -q` |
| 命令面 | `version/selfcheck/ruleset/ledger/import/bench generate` 真跑；`assess/aggregate/compare/bench run/report/gui` 返回 3 并指明里程碑 | `rmqc assess --year 2025` |
| 台账 schema | `schema_version = 2`：7 张表，`segment` 有 `lane_count` / `segment_width_m` / `panel_count` 三个可空列 | `rmqc selfcheck` / `rmqc ledger tables` |
| 干净环境 | 新 clone + 新 venv（py3.12）按 README 逐条跑通：`pip install -U pip setuptools wheel` → `pip install -e .[dev]`（清华源 + NO_PROXY）→ `rmqc version/selfcheck/ruleset/ledger init` → `bench generate`（幂等，`git status data/` 为空）→ `import` 有拒入行 = 1 → `import --dry-run` = 0 → `assess` = 3 → `pytest` 全绿 → `python -m road_mqi_checker selfcheck` = 0。首轮跑出**三条闸门自身的环境 bug**，已修并补回归（见 §〇 教训 4） | `.tmp_*/clean_env.sh`，脚本化步骤见 §六 |

三条留给下一棒的实测教训：

1. **"未核对不出数"对真值同样成立**。M1 的真值评分四列是 `pending:coeff=<key>` 令牌，不是数字。
   M2 做评定引擎时**不要顺手去生成器里填数**：数值真值只有一个入口
   `bench.generator._numeric_truth_probe`，它必须调用评定引擎本身。在内置包 15 格全 pending 的现实下，
   重跑 `bench generate` 仍然出 pending —— 所以"引擎能算出数值"这件事只能在**夹具规则集通路**
   （`tests/fixtures/` + `allow_fixture=True`，或用户用 `RMQC_RULESET_DIR` 提供已核对包）里验证。
   别把夹具数值写进 `data/`，`test_release_redlines.py` 见到交付面出现 `fixture` 字样就红。
2. **两层判据的分界已经固化，不要合并**。导入层只拒"存不进台账"的行（`R001/R008/R009/R010`）；
   负值/超范围/单位错照常入库、由 `ledger.checks` 出 finding。M2 的评定引擎拿到的是**含异常行的台账**，
   所以它对含 `value_range`/`unit_consistency` 检出对象的正确反应是 **blocked + 数值字段全空**，
   而不是"跳过那条破损行继续算"。这是本题最容易做错的一处。
3. **`--force` 的语义是"允许改动已入仓产物"**，不是"覆盖文件"。`write_if_changed` 先比内容再决定，
   所以同 seed 重跑天然幂等。M2 若改了产物格式（例如给 raw 加列），入仓数据必须一起重生成并单独提交，
   不能让守门测试在"新代码 + 旧数据"上跑绿。

4. **闸门自己也会挂环境**，所以"干净环境验证"必须真跑而不是走流程。M1 首轮在 venv 里跑出三条假红：
   - 读 `git ls-files` 时用 `universal_newlines=True` 不指定编码 → Windows 按 GBK 解码中文路径
     在子线程抛 `UnicodeDecodeError`，`proc.stdout` 变 `None`，EOL 门与"源码是否被跟踪"门双双 `AttributeError`；
   - "不许有二进制样例"那条门扫的是**工作树**，于是 `.venv/Scripts/*.exe` 与本地 `ledger.sqlite`
     全被抓进来 —— 而 README 的快速开始本来就把 venv 建在仓库里；
   - 分隔符换算（git 永远输出正斜杠）被顺手丢掉过一次，靠门自己报出 55 个"未跟踪文件"才发现。
   现在三条都收在 `tests/support_git.py` 一处，回归在 `tests/test_gates_environment.py`：
   **交付面 = 已跟踪文件，不是工作树**；git 输出必须按 UTF-8 解码。M2 起再写扫树的门，一律走这个模块。

## 一、当前进度（M1 已交付）

- 文档：`plan/03-数据字典与合成数据.md`（M1 出口文档：27 列宽表字段表、两套破损字典、真值语义与
  检出两层口径、manifest 格式、实测召回/误报）；`plan/00` 里程碑与 M1 决策记录 7 条；
  `plan/02` §3/§5/§6/§8 回写、§9 新增第 12–16 条口径；`data/README.md` §三 真值与数据类别纪律、§五 落地对照；
  `README.md` 状态行、特性、快速开始、评测表三行换实测值；
- 代码（三个占位符模块转真实现，占位符登记表相应移除）：
  - `ledger/models.py`：契约层扩充 —— `RAW_COLUMNS`、`DISTRESS_DICTIONARY`（沥青 10 类 / 水泥 8 类 ×
    轻中重 × m/m2/块）、`QUANTITY_UNITS`、`INDICATOR_DOMAIN`、`parse_stake/format_stake`、
    `geometric_upper_bound`（几何上界只由本行自带数据算出）、`identifier_fields`（喂白名单的字段映射）；
  - `bench/generator.py`：`PARTITION_PLAN`（3 路线 × 4 年度 = 42 个路段年度对象）+ `INJECTIONS`（19 例，八类各 ≥2）
    + `INJECTION_IMPLICATIONS`（同一注入隐含的其余结论，单点声明）+ `TRUTH_GOVERNING_KEYS`（真值四列受哪些系数支配）
    + 幂等写盘与 manifest；
  - `ledger/importer.py`：宽表 → 四个逻辑对象；`analyse` / `import_csv` / `plan_import` 共用一份判定；
    回执对象按 `RECEIPT_COLUMNS` 展开；按 `source_digest` 整份去重（重复导入也落回执）；
    `CHECK_KIND_TO_REJECT_CODE` 是校验层与导入层唯一的词汇映射点；`DATA_CLASSES` 数据类别闸门；
  - `ledger/checks.py`：`CHECK_KINDS` 八类逐项实现，结论只有两档 `found` / `undetermined`；
    划分变更按几何分类 new/disappeared/merged/split/shifted 并写 `partition_change` 表，
    话术固定带"不可比，不做里程摊分"；`run_all_checks` + `summarize`；
  - `ledger/db.py`：schema v2（`segment` 三个可空列）；`cli.py`：`import` 与 `bench generate` 接通，
    `--data-class`、`--force` 两个新参数；`_meta.MILESTONE = "M1"`；
- 测试：`tests/` 18 个文件 **213 项**（M1 新增 `test_m1_generator.py`、`test_m1_pipeline.py`、
  `test_gates_environment.py` + 共用 `support_git.py`），
  双解释器各 213 collected / 213 passed / 0 skip / 0 warning。

## 二、M2 待办（按顺序做，全部做完才算完）

1. **扣分换算内核 `pci/engine.py`**：破损 → 扣分比率换算（沥青、水泥两套）、分项得分合成 PCI、
   `surface_table_keys` 落地（给定路面类型 → 评定路径必需生效的系数 key 集合，缺任一即 blocked）。
   系数一律从规则集取；`pending/located` ⇒ `blocked` 且数值字段全空（`results.PciResult` 契约已有，
   别绕过 `check_contract`）。
2. **贡献展开 `pci/trace.py`**：逐条"哪条破损哪个程度扣了多少"，贡献项必挂 `coefficient_key + clause`
   （`DeductContribution.check_contract` 已经这么要求）；排序必须有固定次级键，
   并回指 `distress.source_row_no`（台账行号 → 原始文件行号，可追溯性的落点）。
3. **含异常数据时的拒算**：M1 台账里就有负值/超范围/单位错的行，M2 必须证明
   "这些对象出的是 blocked，不是被静默跳过后算出的一个数"。用真实（内置）规则集断言，夹具只在测试里。
4. **数值真值接线**：`_numeric_truth_probe` 从"pending 令牌"改为调用 `pci.engine`；
   同时保留"系数未核对 → 仍是 pending 令牌"这条门。`data/README.md` §三 那段说明要同步改。
5. **`rmqc assess --year [--segment]` 从返回 3 变真跑**；退出码语义不变（存在 blocked 项 = 1 降级完成）。
   产出结构要能被 M4 的 `aggregate` 与 M6 的 GUI 直接消费（同一内核，不另起第二套行为）。
6. **夹具档黄金用例**：`tests/fixtures/` 里加沥青/水泥各一套"已核对形态"的夹具规则集（数值刻意避开任何
   真实规范数字），让换算式本身能被数值验证；同时反向断言夹具字样不出现在 `data/` 与内置规则集（已有门）。
7. **测试**：零漂移（同数据同规则集重跑误差 0）、两套换算黄金用例、blocked 构造、贡献排序稳定、
   含异常行拒算、trace 回指文件行号；`tests/test_placeholder_registry.py` 里 `pci.engine` / `pci.trace`
   两条**移除**（双向对账，不移就红），`plan/02` §3 的"待实现"列同步。
8. **文档**：`plan/05-评定与汇总算法说明.md` 的 PCI 部分（换算式、分项合成、舍入口径、拒算条件）；
   `plan/00` 里程碑 M2 打勾 + 决策记录；`plan/02` §8 M2 DoD 勾选；README 评测表把
   "评分复算误差""扣分贡献项排序一致性"两行从"不可用"换成实测值；写 `plan/HANDOFF-M3.md`。
9. **干净环境验证（本棒做一次）**：新目录 `git clone` + 新 venv，按 README 快速开始逐条跑到底，
   并把"新 clone 里 `rmqc bench generate` 幂等、`import` 与 `assess` 实跑"纳入脚本；暴露的问题修完加回归测试。

## 三、既定口径（动了会打挂基准，改动前先在 plan/02 §9 登记）

1. 三态 `pending/located/verified` + 仅 `tests/fixtures/` 可用的 `fixture`；生效档位 = `min(系数状态, 各依据条款状态)`；
2. `blocked` / `uncomparable` 结果对象数值字段全空（不是 0 / NaN）；`partial` 必带口径声明；
3. 舍入：`pci.engine.quantize` 半值向上，`PCI_DECIMALS = 1`；
4. 随机源只有 splitmix64（冻结向量在 `tests/test_determinism_rng.py`）；默认 seed 20261007；规模 3 路线 × 4 年度；
   **注入用例是常量**，不随 seed 漂移；
5. 词汇单点定义：`INJECTED_ISSUES` / `CHECK_KINDS` / `RECEIPT_COLUMNS` / `REJECT_CODES` / `TRUTH_COLUMNS` /
   `SCENARIOS` / `PLAN_COLUMNS` / `COMPARE_COLUMNS` / `TRACE_COLUMNS` / `TIE_BREAK_KEYS` /
   `UNCOMPARABLE_REASONS` / `CHANGE_KINDS` / **M1 新增** `RAW_COLUMNS` / `DISTRESS_DICTIONARY` /
   `INDICATOR_DOMAIN` / `PARTITION_PLAN` / `INJECTIONS` / `INJECTION_IMPLICATIONS` /
   `TRUTH_GOVERNING_KEYS` / `MANIFEST_TOP_LEVEL_KEYS` / `CHECK_KIND_TO_REJECT_CODE` / `DATA_CLASSES` / `VERDICTS`；
6. 退出码 0/1/2/3 与基准四态映射；`import` 有拒入行 = 1，`bench generate` 幂等重跑 = 0；
7. 规则集 `schema_version = 1`、`applies_to` 三维匹配、"最具体优先 + ruleset_id 字典序次级键"；
8. `find_data_dir` 五级优先级：显式 > `RMQC_DATA_DIR` > `sys._MEIPASS/data` > exe 目录 `_internal/data` > 上溯；
9. 白名单形式必须与 `data/README.md` §三 同步；`register_ref` 必须写成 `data/README.md#N` 且该行真实存在；
10. 结论文本禁"已确认/已核实/最终确定"（`privacy.assert_honest_wording`，报告导出会调用）；
11. 落盘产物无时间戳；`.gitattributes` 强制 LF；
12. 真值必须"数据错→检出"和"分数算得对"两类同源（生成器自算，不人工填）；**数值真值只能经
    `_numeric_truth_probe` 由评定引擎产生**；
13. 台账 `schema_version = 2`；表上不设 CHECK 约束；表内不带时间戳列；
14. 导入层与校验层分界（见 §〇 教训 2），八个拒因代码全部有活用例，不许闲置也不许加新码；
15. M2 不许改 `data/` 里的演示数据，除非同时重生成并单独提交（位级一致门会挂）。

## 四、本机环境事实与坑（M0/M1 实测）

- 解释器：`py -3.8` = 3.8.8、`py -3.12` = 3.12.10；两者都有 `pytest`（8.3.5 / 9.1.1）与 `pyyaml` 6.0.3；
  **PySide6 只在 3.8 有**（6.6.3.1）→ GUI 相关测试跑两个分支（"装了→3 / 没装→1"双向断言）；
- `python`（不带版本号）在本机是 Microsoft Store 别名，会**静默返回 rc=49 且不执行**；
  长任务一律 `py -3.8` / `py -3.12`，脚本用 `py -X utf8`（控制台 GBK），并加 `PYTHONDONTWRITEBYTECODE=1`；
- 干净环境验证已跑通：`py -3.12 -m venv` + 激活 + `python -m pip install -U pip setuptools wheel` +
  `pip install -e .[dev]` 走清华源 + `NO_PROXY="*"`；激活后用 `python -m pip`（`py` 启动器会绕过 venv）；
  `rmqc` 控制台脚本在 venv 里可直接调用（M0 未实测的口子已补验）；
- `gh` 2.93.0 已登录，账号 `yuluo554`；`git config user.email` 已是 `<id>+<user>@users.noreply.github.com`；
- `core.autocrlf=true` → 靠 `.gitattributes` + CR 门兜；**别用 shell 重定向往工作树写验证文件**；
  临时产物只写 `.tmp_*/`（已 gitignore，字节门与扫描器跳过）；
- 会话崩溃家族（本机实测）：pytest 偶发 segfault / unknown opcode / 测试项数波动 →
  清 `__pycache__`（含系统 Python 目录）后分批重跑；同一命令连续失败两次就换解释器通道，别硬重试；
- 仓库当前**无 remote**，M0/M1 只本地 commit；建仓与 push 属对外动作，需用户明确授权；
- 工作树里有个不属于本项目的 `.qoder-credits/` 未跟踪目录（某工具产物），别 `git add`，也别删。

## 五、DoD（M2 完成判据，逐项打勾）

- [ ] 沥青与水泥两套破损→扣分换算各有黄金用例（夹具规则集通路），数值可手算复核
- [ ] 同一台账 + 同一规则集重跑 PCI 误差为 0（含两次进程冷启动）
- [ ] 扣分贡献可展开到"哪条破损哪个程度扣了多少"，并回指原始文件行号
- [ ] 内置规则集（15 格全 pending）下所有路段结果为 `blocked` 且数值字段全空 —— 有测试断言，不是文档承诺
- [ ] 台账里 M1 注入的异常对象（负值/超范围/单位错）出的是 blocked，而不是被跳过后算出的数
- [ ] `rmqc assess --year 2022` 真跑，存在 blocked 项时退出码 1
- [ ] 数值真值接线完成：夹具/已核对规则集下真值四列变数值，且调用的是评定引擎
- [ ] 占位符登记表移除 `pci.engine` / `pci.trace` 后 `test_placeholder_registry.py` 全绿
- [ ] py3.8 + py3.12 双通道全绿，收集数一致且逐项可解释（无静默 skip）
- [ ] `data/` 演示数据未被 M2 悄悄改动（`git status --porcelain data/` 为空）
- [ ] 干净 clone + 新 venv 按 README 逐条一次跑通
- [ ] `plan/05` PCI 部分完成；`plan/00`、`plan/02` §8、README 评测表回写；`plan/HANDOFF-M3.md` 落盘
- [ ] 本地 commit（不 push，除非用户授权）

## 六、关键命令速查

```bash
# 双通道测试
PYTHONDONTWRITEBYTECODE=1 py -3.8  -X utf8 -m pytest tests -p no:cacheprovider
PYTHONDONTWRITEBYTECODE=1 py -3.12 -X utf8 -m pytest tests -p no:cacheprovider

# 内核自检 / 系数门
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src py -3.8 -X utf8 -m road_mqi_checker selfcheck
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src py -3.8 -X utf8 -m road_mqi_checker ruleset show

# 演示数据与台账（M1 已可用）
rmqc bench generate                      # 幂等：内容一致不改写
rmqc --db ledger.sqlite ledger init
rmqc --db ledger.sqlite import --file data/raw/S99-2022.csv --year 2022 --dry-run
rmqc --db ledger.sqlite import --file data/raw/S99-2024.csv --year 2024   # 回执 + 八类校验，rc=1 若有拒入

# M2 目标命令（现在返回 3）
rmqc --db ledger.sqlite assess --year 2022
rmqc --db ledger.sqlite assess --year 2022 --segment S99-A1

# 台账里直接看注入的异常对象（M2 拒算的测试素材已经在库里）
python -c "import sqlite3; c=sqlite3.connect('ledger.sqlite'); print(c.execute('select segment_id,year,distress_type,quantity,quantity_unit from distress where quantity<0').fetchall())"
```

已安装包名 `road-mqi-checker`，入口 `rmqc` / `road-mqi-checker` / `python -m road_mqi_checker` 三者等价。
字段口径与真值语义一律看 `plan/03-数据字典与合成数据.md`，代码是单点定义、文档只引用。
