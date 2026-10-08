# HANDOFF · M7 发布收口与后续（M6 已完成，本文件是续接入口）

> 用法：新对话说「继续完成 `plan/HANDOFF-M7.md`」即可续接（本文件内命令均以仓库根为当前目录）。
> 上一棒：M6 交付、打包与脱敏（2026-10-07 完成，已本地 commit，**未 push、无 remote**）。
> M0–M6 是本题规划的**全部里程碑**，已走完；M7 不是新功能里程碑，而是"对外动作 + 可选增强"，
> 其中每一项都需要用户点头才做。

## 〇、M6 末态基线（不得回退）

| 项 | 实测值 | 复核命令 |
|---|---|---|
| 提交 | `origin/main` = `fa303e2`，tag `m6`（指向 `1ac8093`，代码与两份资产对应的状态）已推送；仓库 **public**：<https://github.com/yuluo554/road-mqi-checker>；工作树只剩不属于本项目的未跟踪 `.qoder-credits/` | `git log --oneline -6` / `git status --porcelain` / `gh run list --limit 1` |
| 测试 | **489 项**（M6 净增 79：486→487 是冻结态落点门，488–489 是 Windows CI 报出来的两条 locale 门），py3.8.8 与 py3.12.10 双通道各 489 collected / 489 passed / 0 skip / 0 warning | `PYTHONDONTWRITEBYTECODE=1 py -3.8 -X utf8 -m pytest tests -q` |
| 占位符 | 登记表 **空**（终态），`_meta.MILESTONE = "M6"`，`MILESTONE_DOCS["M6"] = plan/07` 且该文件真实存在（有门） | `rmqc --json selfcheck` 的 `placeholders` |
| 命令面 | **没有任何命令返回 3**；`version/selfcheck/ruleset/ledger/import/assess/aggregate/compare/bench/report/gui` 全部真跑 | `tests/test_cli_contract.py::test_no_command_in_the_surface_returns_the_unimplemented_code` |
| 导出面 | `rmqc report --year Y [--scope assessment\|plan] [--level] [--from-year] --format csv\|md\|docx --out`：内置包下 **1**（导出成功但全 blocked）、无数据年度/后缀不符/目录缺失 **2**；三格式两次导出逐字节一致；末尾两行必为 `DISCLAIMER` / `DATA_CLASS_NOTE` | `bash .tmp_verify/M6/clean_verify.sh`（或 `tests/test_m6_report.py`，51 项） |
| 桌面壳 | 七页签只转发 `cli.main`；`rmqc gui --probe`：装了 `[gui]` extras → **0**，缺 PySide6 → **1** + extras 提示；`PAGE_SPECS` 每个 flag 都能在 CLI parser 里找到（有门） | `tests/test_m6_gui.py`（23 项，含 4 项 `@gui`） |
| 打包 | `packaging/rmqc.spec` onedir 双 exe（`rmqc.exe` console / `rmqc-gui.exe` windowed，共用一份 `_internal`）；`datas` 逐条 27 条 + 构建期 glob 对账；包 ~115 MB，无 numpy/scipy/pandas/matplotlib/PIL | `py -3.12 -m PyInstaller --noconfirm --distpath dist --workpath .tmp_m6/pyi packaging/rmqc.spec` |
| 构建红线 | `packaging/verify_build.py` 五类断言全过：26 份内嵌数据逐份 sha256 一致且无多余、夹具字样 0、真实形态标识符越界 0、无 pdf/doc 与 >200KB 载荷、中立目录里 `data_dir` 指向包内 | `py -3.12 packaging/verify_build.py dist/rmqc` |
| 一键交付验证 | `.tmp_verify/M6/clean_verify.sh`：**68 步 want==got 全对**，三处 `git status --porcelain data/` 均为空；回执 `.tmp_verify/M6/exits.tsv` + `run.log` | `bash .tmp_verify/M6/clean_verify.sh` |
| 打包态评测 | 把包**拷到仓库外**后 `rmqc.exe bench run` → **3**（夹具通路 8 行不可用、内置通路 5 不可判 + 3 达标），逐字节导出与源码态一致；留在仓库树里量到的是 0（上溯分支命中 `tests/fixtures/`），那不是用户形态 | `plan/07` §3.4 |
| 脱敏 | `packaging/scan_release.py` 四步全过（返回 0）：提交身份 1 条 noreply / 交付面字面 125 份 17 处全豁免 / 数据结构 151 行 0 越界 / 构建产物本体 0 命中 | `py -3.8 -X utf8 packaging/scan_release.py` |
| M5 基线 | 未回退：410→489 是**净增**（重写门而不是删门），`bench run` 仍 16 行 + 退出码 0、内置包仍 blocked、24 份 CSV + manifest 位级未动、README 评测表仍由命令生成并逐行对账 | `tests/test_m5_bench.py` / `git status --porcelain data/` |

留给下一棒的实测教训：

1. **交付面不出数这件事没变**，M7 不许为了"发布好看"把它圆过去：14 格规范来源系数仍是 `pending`，
   报告里数值列/等级列一律留空并给拒算原因，评测表等级判定仍是"不可判（分母为 0）"。
2. **导出层与扫描器都自带闸门**，别指望上游干净：`exporters.assert_export_safe` 拦措辞/夹具/绝对路径/
   时间戳/本机用户名；`scan_release.py` 未豁免命中即非零。**留档文档不要写会被自己规则命中的字面量原样形态**
   （实测：扫描器和 RELEASE 表引用负向用例字面量时，每次都命中自己）。
3. **GUI 只做转发是可测的属性**，不是口头承诺：新增页面参数时同步改 `PAGE_SPECS`，
   并让 `test_spec_flags_all_exist_in_the_cli_parser` 继续成立；不要在页面里算数、判色、下结论。
4. **`--probe` 是唯一可以在 CI/无头环境跑的 GUI 形态**。不带探针会进事件循环等用户关窗，
   脚本里绝不允许裸跑（尤其 windowed exe：控制台不会等它，取退出码要用 `subprocess.run`）。
5. **打包态必须"拷出仓库"再量**：`fixture_dir_candidates` 与 `find_data_dir` 都会上溯，
   `dist/` 长在仓库里时量到的是开发机形态。`clean_verify.sh` 的 `$PKG/$NEUTRAL` 已固定落在
   `%LOCALAPPDATA%\Temp\rmqc-m6-delivery`，改脚本别把它挪回仓库树内。
6. **冻结态写数据的路径要避开包内副本**：`cli._bench_out_dir()` 在 `is_frozen()` 时写 cwd，
   否则 exe 会改写自己的内嵌账本，"内嵌数据=仓库数据"这条断言当场失效（有门）。
7. **exe 的 stdout 必须是 UTF-8**：spec 里给两个 EXE 内嵌 `-X utf8` 运行期选项；
   否则冻结态走控制台代码页，命令面文案里的箭头/中文字符打不出来，退出码还会掩盖真因（M6 实录：
   `bench run` 该落 3 却落 1）。
8. **指标口径要改就先登记**：`plan/02` §9 现在到第 35 条（M6 加了导出转述、无时间戳/docx、GUI 只转发三条）；
   新增不可判项要登记进 `evaluation.DECLARED_INDETERMINATE` 并在 `plan/06` §四说明理由。
9. **`applies_to` 仍缺"技术等级"这一维**（M3 暴露，M4–M6 都没动）：真要出省份规则集，这是先决条件；
   补不了就别造省份包，保持"缺口有记录"（`plan/04` §五）。

## 一、M6 交付内容（已完成，逐项有门或有回执）

- **代码**：`report/exporters.py`（三格式渲染 + `plan_rows` 字段转述 + `build_ledger_snapshot` +
  `assert_export_safe`）；`gui/app.py`（`PAGE_SPECS` / `build_argv` / `run_kernel` / `build_window` /
  `main(--probe)`）；`cli.py`（`report` 参数面与退出码、`gui --probe`、`_bench_out_dir()` 冻结分支）；
  `_meta.py`（MILESTONE→M6、登记表清空）；
- **打包与审计层**：`packaging/rmqc.spec`（双 exe + datas 白名单 + excludes + hiddenimports + `-X utf8`）、
  `entry_cli.py` / `entry_gui.py`（薄壳）、`verify_build.py`（构建后五类红线断言）、
  `scan_release.py`（脱敏四步 + 豁免台账）；
- **测试 410 → 489**：新增 `test_m6_report.py`（51）、`test_m6_gui.py`（23）；
  重写 `test_cli_contract.py` 的占位符命令门（3 条 → 4 条 + 冻结态落点门，净 +2）、
  `test_placeholder_registry.py`（M6 转真门 + 出口判据文档必须真实存在）；
- **文档**：`plan/07-交付与打包.md`（导出结构 / 七页签与探针 / spec 与五类断言 / 一键验证实测 / 本机坑）、
  `plan/RELEASE-M6.md`（脱敏四步实测 + 豁免台账 + 授权边界）、README 与 `plan/00`/`plan/02`/`plan/05`/`plan/06` 同步。

## 二、M7 待办（全是对外动作或可选增强，**做之前先问用户**）

1. **建仓 + push** ✅ 已完成（用户授权）：<https://github.com/yuluo554/road-mqi-checker>，已转为 public。
   实测：OAuth 令牌 scope 只有 `repo`（没有 `workflow`），HTTPS 推 workflow 文件会被拒 ——
   走 SSH 通道一次过（`git remote add origin git@github.com:yuluo554/road-mqi-checker.git`）。
2. **CI 四矩阵首跑** ✅ 全绿（ubuntu/windows × 3.8/3.12）。首跑 windows 两腿报出真缺陷
   （cp1252 代码页下中文结论抛 `UnicodeEncodeError`），修在 `cli.ensure_utf8_stream()` 并补两条诱饵门，
   结果与判据已写进 `plan/RELEASE-M6.md` §三。CI 仍只装 `.[dev]` ⇒ 4 项 GUI 标记测试声明式跳过；
   要让 CI 也跑 GUI 通路需加 `[gui]` + offscreen 与系统依赖，属**新增口径**，先与用户确认。
3. **tag + GitHub release + 免安装 exe 资产** ✅ tag `m6` + release
   <https://github.com/yuluo554/road-mqi-checker/releases/tag/m6>：
   `rmqc-cli-win64.zip` 12.3 MB（47 文件）与 `rmqc-gui-win64.zip` 48.2 MB（194 文件）。
   实测纠正了"115 MB 超上限"的担心：DEFLATE 后 48.2 MB，单资产 100 MB 限内；
   发布前 `verify_build.py` 与 `zipfile.testzip()` 都在这两份资产对应的包上跑过。
4. **桌面窗口的人工验收**：`--probe` 只证明"窗口能建、七页都转到内核"。真实双击、文件选择对话框、
   长任务下的界面响应需要人工过一遍，结论如实写进 `plan/07`（未做就别写"已验证"）。
5. **可选增强**（都不影响交付判据）：省份规则集（先补 `applies_to` 的技术等级维）、
   Web 面板、`--fixtures-dir` 让 exe 能量夹具通路、解锁 14 格系数（重试 `jtst.mot.gov.cn`，
   或走 `dbba.sacinfo.org.cn` 的地方标准全文；见 `plan/04` §五 与 `reference-cn-construction-standard-sources`）。

## 三、既定口径（动了会打挂基准）

M0–M6 累计见 `plan/02` §9 第 1–35 条。M7 最相关的：三态 + `fixture`；生效档位取最小；
条款号缺失即拒算；blocked/uncomparable 数值全空；partial 必带口径且不给等级；
出数判据 = 必需格全生效；舍入半值向上（1/3/2 位三档）；四态映射与门禁优先级；
指标 16 行两通路；阈值与词汇只来自规则集那一格；**落盘产物无时间戳**；
措辞禁"已确认/已核实/最终确定/必定"；`register_ref = data/README.md#N` 且该行真实存在；
演示数据 `data_class=SYNTHETIC` 走白名单；**导出层只转述 `result_payload()`**；
**GUI 只转发 CLI**；**夹具值不进交付面（含 exe）**。

## 四、本机环境事实与坑（M0–M6 七棒实测）

- 解释器只认 `py -3.8`（3.8.8）/ `py -3.12`（3.12.10）；`python` 是 Store 别名会静默 rc=49。
  两侧都装了 pytest/pyyaml/**PySide6 6.6.3.1/PyInstaller 6.22.3**（所以本地 GUI 测试不跳过）；
- **构建类连崩 = 先清 pyc**：干净 clone 里 PyInstaller 连崩 3 次
  `TypeError: required field "value" missing from Attribute`（modulegraph 扫描层），
  清掉 `__pycache__`（含 venv 的 `site-packages`）后一次过；`clean_verify.sh` 已把"构建前清 pyc + 3 次重试"
  写进步骤。同一族还有 `pip install -e` 崩在建隔离子进程（原样重试即过）、pytest 全绿后于退出阶段崩（139）。
  **判据是清完即恢复，别去换解释器通道或改 pin**；
- `env -i` 跑冻结 exe 要**白名单保留** `SystemRoot/TEMP/TMP/COMSPEC/USERPROFILE/APPDATA/LOCALAPPDATA/HOME`，
  PATH 缩到 System32 + 包目录（并断言里面没有解释器）；全清会让 bootloader 拿不到随机源；
- 长任务一律 `run_in_background` + 日志写**绝对路径**；验证脚本自身也用绝对路径；
  临时产物只写 `.tmp_*/`（gitignore + 扫描器跳过名单）；**别在跑着的 bash 脚本上改它自己**
  （bash 按偏移续读，会执行到错位内容 —— M6 实测踩到，只能停掉重跑）；
- `rmqc` 控制台脚本在非 UTF-8 控制台输出 GBK 字节，抓 JSON 前 `export PYTHONIOENCODING=utf-8`；
- `gh` 2.93.0 已登录 `yuluo554`；**建仓与 push 属对外动作，需用户明确授权**；
- 工作树里的 `.qoder-credits/` 未跟踪目录不属于本项目：别 `git add`，也别删。

## 五、DoD（M7 完成判据）

- [x] 用户授权后：建仓 + push + CI 四矩阵首跑全绿 ✅（含 windows 两腿报出的 cp1252 缺陷修复与两条诱饵门，实录在 `plan/RELEASE-M6.md` §三/§四）
- [x] tag + release + README 与"免安装 exe 资产"说法一致 ✅（两份资产 `gh release download` 取回后 sha256 与原件相符）
- [ ] 桌面窗口人工验收一遍并如实记录（或明确记为"未做人工验收"）
- [ ] M6 末态基线表逐项未回退（489 项、68 步 want==got、导出逐字节一致、脱敏四步 0 未豁免）
- [ ] 若新增功能：先登记 `plan/02` §9 与 `plan/00` 决策，再动代码，并配常驻门

## 六、关键命令速查

```bash
# 双通道测试（本地两侧都装了 PySide6，0 跳过）
PYTHONDONTWRITEBYTECODE=1 py -3.8  -X utf8 -m pytest tests -q -p no:cacheprovider
PYTHONDONTWRITEBYTECODE=1 py -3.12 -X utf8 -m pytest tests -q -p no:cacheprovider

# 导出三格式 + 桌面壳探针（最快回路）
export PYTHONDONTWRITEBYTECODE=1 PYTHONIOENCODING=utf-8 PYTHONPATH=src
py -3.8 -X utf8 -m road_mqi_checker --db .tmp_m6/ledger.sqlite report --year 2022 --format docx --out .tmp_m6/a.docx
py -3.8 -X utf8 -m road_mqi_checker --db .tmp_m6/ledger.sqlite report --year 2023 --scope plan --from-year 2022 --out .tmp_m6/plan.csv
QT_QPA_PLATFORM=offscreen py -3.8 -X utf8 -m road_mqi_checker gui --probe

# 打包 + 构建后红线 + 发布前脱敏
py -3.12 -m PyInstaller --noconfirm --distpath dist --workpath .tmp_m6/pyi packaging/rmqc.spec
py -3.12 packaging/verify_build.py dist/rmqc
py -3.8  -X utf8 packaging/scan_release.py

# 一键交付验证（新 clone + 新 venv + 打包 + 中立目录探针，68 步）
bash .tmp_verify/M6/clean_verify.sh
awk -F'\t' '{split($2,a,"=");split($3,b,"=");if(a[2]!=b[2])print "MISMATCH",$0}' .tmp_verify_m6_clean/exits.tsv
```

坑：`git clone` 取 **HEAD**，收尾提交必须先 commit 再验证；
脚本里的 `$PKG` / `$NEUTRAL` 必须落在仓库树外；`bench run` 在 dev 树里期望 **0**、
在仓库外的包里期望 **3**，两者都对，别把它们当成矛盾。
