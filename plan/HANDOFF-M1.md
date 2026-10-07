# HANDOFF · M1 数据先行

> 用法：新对话说「继续完成 `plan/HANDOFF-M1.md` 的 M1 任务」即可续接（本文件内命令均以仓库根为当前目录）。
> 上一棒：M0 骨架与纪律（2026-10-07 完成，已本地 commit，未 push）。

## 〇、M0 末态基线（不得回退）

| 项 | 实测值 | 复核命令 |
|---|---|---|
| 提交 | 两个本地 commit（骨架 + 索引对账守门测试），工作树干净，**无 remote、未 push** | `git log --oneline -3` / `git status --porcelain` |
| 测试 | 159 项，py3.8.8 与 py3.12.10 各 159 collected / 159 passed / 0 skip / 0 warning | `py -3.8 -X utf8 -m pytest tests` |
| 全新 clone | `.tmp_verify/clone-m0` 下 159 全绿 + `selfcheck` 返回 0；`core.autocrlf=true` 环境下 CR 门通过（LF 声明生效） | `git clone . <目录>` 后照 README 跑 |
| 系数门 | 生效 0 格 / 拒算 15 格，`selfcheck` 如实报"系数门关" | `rmqc selfcheck` |
| 命令面 | `version/selfcheck/ruleset/ledger` 真跑；其余 7 个命令返回退出码 3 并指明里程碑 | `rmqc assess --year 2025` |

两条留给下一棒的实测教训：

1. **`.gitignore` 通配会吞源码包**：写 `ledger/` 想让运行期台账不入仓，结果 `src/road_mqi_checker/ledger/`
   整个包被静默忽略 —— 开发机上跑得好好的，新 clone 直接 ImportError。已改成只忽略
   `data/local/` + `*.sqlite`，并加了 `test_every_source_and_test_file_is_git_tracked`（与 `git ls-files` 对账）。
   以后加 ignore 规则一律先 `git check-ignore -v src/...` 验一遍。
2. **M6 脱敏扫描的已知误报面**（现在就登记，省得发布期重新发现）：
   `tests/test_determinism_rng.py` 的 splitmix64 冻结向量是 19~20 位 u64 数字串，会撞身份证类正则；
   `data/README.md`、`plan/01`、`privacy.py` 里的 `19900000000` 是白名单声明的虚构号段示例。
   两者都属"合成数据白名单形态"，M6 扫描要按白名单豁免并留判定理由，不删字面也不改结论。

## 一、当前进度（M0 已交付）

- 文档：`plan/00`（索引重编号 + M0 决策记录回写）、`plan/01`（题目定稿，未改）、`plan/02-开发计划与架构.md`（选型/架构/模块映射/三态口径/CLI/守门测试清单/M0–M6 DoD/既定口径/开放项）、`data/README.md`（补 M0 落地对照与 `#N` 出处指针说明）；
- 包骨架：`src/road_mqi_checker/` 30 个文件，核心零第三方依赖；
  - 口径层：`ruleset/status.py`（三态 + 夹具档）、`ruleset/loader.py`（schema 硬门 + 版本化选取）、`rulesets/base-jtg5210-2018.json`（15 格系数全 pending）；
  - 契约层：`results.py`（拒算契约）、`privacy.py`（合成数据白名单）、`data_paths.py`（五级优先级含冻结分支）、`exit_codes.py` + `errors.py`、`_meta.py`（占位符登记表）；
  - 结构层：`ledger/models.py`（字段契约）、`ledger/db.py`（7 张表 DDL，幂等建表）；
  - 已实现的小块工具：`pci/engine.quantize`（固定舍入）、`bench/rng.py`（splitmix64）、`bench/evaluation.initial_metric_table`（四态指标表初值）、`report/disclaimer.py`、`gui/app.build_page_map`；
  - 占位符：`ledger.importer` / `ledger.checks` / `bench.generator`（M1）、`pci.engine` / `pci.trace`（M2）、`mqi.engine` / `strategy.rules` / `strategy.compare`（M4）、`bench.evaluation.gate`（M5）、`report.exporters` / `gui.app.main`（M6）；
- 交付外围：`pyproject.toml`（3.8 下限、extras 分档上界、`rmqc` 入口、package-data 收规则集）、`LICENSE`(MIT)、`.gitattributes`(eol=lf)、`.gitignore`（补 `.tmp_*/`、`data/local/`）、`.github/workflows/ci.yml`（四矩阵）、`README.md`（含四态评测表，全部标"不可用"）；
- 测试：`tests/` 14 个文件 **159 项**，py3.8.8 与 py3.12.10 双通道各 159 collected / 159 passed / 0 skip / 0 warning。

## 二、M1 待办（按顺序做，全部做完才算完）

1. **数据字典先行**：写 `plan/03-数据字典与合成数据.md` —— 路线表 / 路段划分表 / 年度检测表 / 破损调查表的列定义（名称、类型、单位、可空性、示例），破损类型 × 程度字典（沥青、水泥两套），真值文件与 manifest 格式。字典里**不出现任何规范阈值数字**。
2. **生成器 `bench/generator.py`**：
   - 规模口径：3 条虚拟路线 × 4 个年度（`DEFAULT_ROUTES/DEFAULT_YEARS` 已定）；
   - 随机源只用 `bench/rng.SplitMix64(seed)`；默认 seed `20261007`；
   - 输出 `data/raw/<route>-<year>.csv` + `data/truth/<route>-<year>.truth.csv`（列名用 `TRUTH_COLUMNS`）+ `data/raw/manifest.json`；
   - 每个文件带 `data_class=SYNTHETIC` 标记；每行标识符落盘前过 `privacy.check_row`；
   - 八类 `injected_issue` 每类 ≥2 个用例（含"同一注入隐含的其余结论"如何记录——定清真值语义后写进模块注释）；
   - 落盘**不带时间戳**，同 seed 两次运行逐字节一致；`--force` 重跑 `git status` 必须零变化。
3. **导入器 `ledger.importer.py`**：CSV → SQLite（7 张表已有 DDL），出回执（`RECEIPT_COLUMNS` + `REJECT_CODES`），支持 `--dry-run` 预检；重复导入按 `source_digest` 去重。
4. **校验 `ledger.checks.py`**：`CHECK_KINDS` 七类逐项实现（悬空/重叠/闭合差/字典/量纲/负值超范围/重复/划分变更），跨年度划分变更写 `partition_change` 表并**显式标记不可比**。闭合差容差从规则集 `tolerance.length_closure` 取；该格仍是 pending → 校验项输出"待核对，未判定"而不是硬判。
5. **冻结 fixtures 入仓**：生成产物整体作为演示数据提交，配"再生成位级一致"守门测试 + "跟踪文本文件无 CR"（已有）。
6. **CLI 接通**：`rmqc bench generate` / `rmqc import` / `rmqc ledger init --db` 从返回 3 变成真跑；退出码语义不变（有拒入行 = 1 降级完成）。
7. **测试**：新增生成器位级一致、真值对账、七类校验召回/误报、导入回执、划分变更不可比的测试；占位符登记表里 `bench.generator` / `ledger.importer` / `ledger.checks` 三条**移除**（`tests/test_placeholder_registry.py` 会双向对账，不移就红）。
8. **文档回写**：`plan/00` 里程碑表 M1 打勾 + 决策记录新增 M1 拍板项；`plan/02` §8 M1 DoD 勾选；README 评测表把"数据异常识别召回/误报""产物位级一致"三行从"不可用"换成实测值；写 `plan/HANDOFF-M2.md`。
9. **干净环境验证（本棒做一次）**：新目录 `git clone`（或复制树）+ 全新 venv，按 README 快速开始逐条跑 `pip install -e .[dev]` → `pytest` → `rmqc selfcheck` → `rmqc bench generate` → `rmqc import`；暴露的问题修完加回归测试。

## 三、既定口径（动了会打挂基准，改动前先在 plan/02 §9 登记）

1. 三态 `pending/located/verified` + 仅 `tests/fixtures/` 可用的 `fixture`；生效档位 = `min(系数状态, 各依据条款状态)`；
2. `blocked` / `uncomparable` 结果对象数值字段全空（不是 0 / NaN）；`partial` 必带口径声明；
3. 舍入：`pci.engine.quantize` 半值向上，`PCI_DECIMALS = 1`；
4. 随机源只有 splitmix64（冻结向量在 `tests/test_determinism_rng.py`，改实现必红）；默认 seed 20261007；规模 3 路线 × 4 年度；
5. 词汇单点定义：`INJECTED_ISSUES` / `CHECK_KINDS` / `RECEIPT_COLUMNS` / `REJECT_CODES` / `TRUTH_COLUMNS` / `SCENARIOS` / `PLAN_COLUMNS` / `COMPARE_COLUMNS` / `TRACE_COLUMNS` / `TIE_BREAK_KEYS` / `UNCOMPARABLE_REASONS` / `CHANGE_KINDS`；
6. 退出码 0/1/2/3 与基准四态映射；
7. 规则集 `schema_version = 1`、`applies_to` 三维匹配、"最具体优先 + ruleset_id 字典序次级键"；
8. `find_data_dir` 五级优先级：显式 > `RMQC_DATA_DIR` > `sys._MEIPASS/data` > exe 目录 `_internal/data` > 上溯；
9. 白名单形式必须与 `data/README.md` §三 同步；`register_ref` 必须写成 `data/README.md#N` 且该行真实存在；
10. 结论文本禁"已确认/已核实/最终确定"（`privacy.assert_honest_wording`，报告导出会调用）；
11. 落盘产物无时间戳；`.gitattributes` 强制 LF；
12. 真值必须"数据错→检出"和"分数算得对"两类同源（生成器自算，不人工填）。

## 四、本机环境事实与坑（全部 M0 实测）

- 解释器：`py -3.8` = 3.8.8、`py -3.12` = 3.12.10；两者都有 `pytest`（8.3.5 / 9.1.1）与 `pyyaml` 6.0.3；**PySide6 只在 3.8 有**（6.6.3.1），3.12 无 → GUI 相关测试要跑两个分支（M0 已按"装了→3 / 没装→1"双向断言）；
- `gh` 2.93.0 已登录，账号 `yuluo554`；`git config user.email` 已是 `<id>+<user>@users.noreply.github.com` 形态（发布期邮箱改写门可省一轮）；
- `core.autocrlf=true` → 一律靠 `.gitattributes` + CR 守门测试兜，**别手工用 shell 重定向往工作树里写验证文件**（Windows 下写出 CRLF 会被 EOL 门打挂）；临时产物只写 `.tmp_*/`；
- 跑脚本用 `py -X utf8`（控制台 GBK），长任务加 `PYTHONDONTWRITEBYTECODE=1`；
- `py` 启动器会绕过 venv：激活后必须用 `python -m pip`；3.8 自带 pip 装不了 pyproject-only 项目，先 `python -m pip install -U pip setuptools wheel`；
- 网络：pip 走系统代理易失败，必要时 `NO_PROXY="*" no_proxy="*" py -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple <pkg>`；
- 命令验证：**取退出码别接管道**（`pytest | tail` 拿的是 tail 的码）；测试数波动/unknown opcode 一类先清 `__pycache__` 再重跑（见 crash-loop-rescue）；
- 仓库当前**无 remote**，M0 只本地 commit；建仓与 push 属对外动作，需用户明确授权。

## 五、DoD（M1 完成判据，逐项打勾）

- [ ] `plan/03-数据字典与合成数据.md` 完成，字段表与破损字典齐备，无未核对数值
- [ ] `rmqc bench generate --seed 20261007` 两次运行产物逐字节一致，`git status` 零变化
- [ ] 演示数据整体入仓为冻结 fixtures，配"再生成位级一致"守门测试
- [ ] 八类注入缺陷每类 ≥2 用例；异常识别召回与误报有实测数字
- [ ] `rmqc import --dry-run` 与正式入库都出回执（入库/拒入行数 + 逐行拒因）
- [ ] 真实形态标识符（G25 / 110101 / 138 号段）一律被白名单拒入并有测试
- [ ] 跨年度划分变更四类有用例并显式标"不可比"（不出摊分值）
- [ ] 闭合差等依赖 pending 系数的校验项输出"待核对，未判定"，不硬判
- [ ] 占位符登记表移除 M1 三条后 `test_placeholder_registry.py` 全绿
- [ ] py3.8 + py3.12 双通道全绿，收集数一致且逐项可解释（无静默 skip）
- [ ] 干净 clone + 新 venv 按 README 逐条一次跑通
- [ ] `plan/00`、`plan/02` §8、README 评测表回写；`plan/HANDOFF-M2.md` 落盘
- [ ] 本地 commit（不 push，除非用户授权）

## 六、关键命令速查

```bash
# 双通道测试（分批也可，量小一次跑完）
PYTHONDONTWRITEBYTECODE=1 py -3.8  -X utf8 -m pytest tests -p no:cacheprovider
PYTHONDONTWRITEBYTECODE=1 py -3.12 -X utf8 -m pytest tests -p no:cacheprovider

# 收集数对照（测试多时取数用 --collect-only，别 | tail 取退出码）
py -3.8 -X utf8 -m pytest tests --collect-only -q -p no:cacheprovider

# 内核自检（断网可跑，看系数门与台账 schema）
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src py -3.8 -X utf8 -m road_mqi_checker selfcheck
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src py -3.8 -X utf8 -m road_mqi_checker --json selfcheck
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src py -3.8 -X utf8 -m road_mqi_checker ruleset show

# M1 目标命令（现在返回 3）
rmqc bench generate --seed 20261007 --out data/raw
rmqc ledger init --db ledger.sqlite
rmqc import --db ledger.sqlite --file data/raw/S99-2025.csv --year 2025 --dry-run
```

已安装包名 `road-mqi-checker`，入口 `rmqc` / `road-mqi-checker` / `python -m road_mqi_checker` 三者等价。
