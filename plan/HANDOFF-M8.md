# HANDOFF · M8（批次 A/B/C 已执行并发布 `m6.3`，状态：已发布 / 人工目检仍待做）

> 用法：新对话说「继续完成 `plan/HANDOFF-M8.md`」即可续接（命令均以仓库根为当前目录）。
> 上一棒：`plan/HANDOFF-M7.md`（M7 对外动作与可选增强）。
> **本轮已发布**：tag `m6.3` → `fb7283b`，Release 三附件 + CI 四矩阵全绿（run `39702530198`）。
> 发布回执：`plan/RELEASE-M8.md`。
> 交接物：`update/00`–`update/02`、`update/98`、`update/99`、`update/执行记录.md`（`update/` 在 `.gitignore` 内）。

## 〇、本轮做了什么（按批次）

| 批次 | 内容 | 状态 |
|---|---|---|
| C | `README.md:220` 的「各 490 通过」订正为 **491**；计数门补第三种句式 `各 N 通过` + 「N 项声明式跳过」+ **算术一致性**断言 | ✅ 已落地并验红 |
| A | **DEC1 = B（承认为终态）**：README 首屏卖点从「评定与养护决策支持工具」改为「评定**框架**：带拒算契约的规则内核」，并在「为什么现在算不出分」一节写明「这是终态，不是进度」 | ✅ 已落地 |
| B | 桌面壳：`[gui]` 安装 + `--probe` exit 0 + **七页签逐页机械证据**（真文件真台账驱动表单）+ 人眼目检清单 | ✅ 机械层完成；**主观目检仍待人工**（§四） |

## 一、批次 C 实测（计数门盲区）

**缺陷**：`tests/test_readme_test_count.py` 第一版只匹配 `(\d+)\s*项守门测试` 与 `各收集\s*(\d+)\s*项`，
锁的是**收集数 495**；同一句里的「各 490 通过」（实际 491）完全裸奔。
把「各 490 通过」改成荒谬的「各 999 通过」后门**仍然 passed**。

**修法**：`_claims()` 统一取四种句式，一个测试函数里断言三件事：

1. 收集数两处自述相等；
2. 收集数 == 实际 `pytest --collect-only` 数；
3. **算术一致性**：`收集数 == 通过数 + 跳过数`（495 == 491 + 4）。

只锁"各自等于某值"会被单点改动绕过；等式同时锁住两个数字之间的关系。

**实测**：

```
# 正控（门有效）
$ pytest tests/test_readme_test_count.py -q
1 passed in 1.13s                                   EXIT=0

# 负控（把 README 的 491 改成 999）
$ pytest tests/test_readme_test_count.py -q
E  AssertionError: README 自述算术不自洽：收集 495 ≠ 通过 999 + 跳过 4（差 -508）。
E  assert 495 == (999 + 4)
FAILED                                              EXIT=1
```

两次实验后 README 已还原（备份 → `cp` 回写 → 复核 `各 491 通过` 与 `CRLF 0 / LF 317`）。

**`update/README.md:8`** 在复验轮已改为 491 passed，本轮复核一致，无需再改。

## 二、批次 A 实测（DEC1 = B，14 格系数承认为终态）

**决定**：不动 `rulesets/`，不给任何 pending 格标 verified；改的是**表述**——
首屏不再自称"能评定的工具"，而是"带拒算契约的框架"，且把"不出数"写成**终态**。

改动清单（表述一致化，四处产品面 + 一处总览）：

| 位置 | 改后 |
|---|---|
| `README.md:3` | 「公路技术状况评定**框架**：带拒算契约的规则内核 —— 全离线、规则优先、逐格系数挂条款号、结果可复算。」并新增一段引用块：14 格无官方原文 → 三条路径拒算 →「**这是终态，不是路线图**」 |
| `README.md` §「为什么现在算不出分」 | 补「**这是终态，不是进度**」段：M3 之后不再把"找到原文"当待办；`selfcheck`「拒算 14 格 → 系数门 开」与 `bench run`「不可判」是该终态的如实投影 |
| `src/road_mqi_checker/__init__.py` | 模块 docstring 同步为「评定框架：带拒算契约的规则内核」 |
| `src/road_mqi_checker/cli.py:54` | argparse `description` 同步（`--help` 首行） |
| `src/road_mqi_checker/gui/app.py:217` | 窗口标题 → 「公路技术状况评定**框架**（离线内核）」 |
| `pyproject.toml:8` | `description` 同步（进 wheel/sdist 元数据） |
| `plan/00-README总览.md:3` | 总览首句同步 + 注明「这是终态（DEC1=B，2026-10-22）」 |

**为什么没改 `selfcheck` / `bench`**：它们的输出本来就与新表述一致（「拒算系数 14 格 → 系数门 开」、
「生效 1 格 / 拒算 14 格」、「不可判（分母为 0）」），改它们属于动判定面，是纪律条款 ② 禁止的开后门。

**一致性证据**（实测）：

```
$ python -m road_mqi_checker selfcheck
ruleset 包: 1 个，生效系数 1 格，拒算系数 14 格 → 系数门 开
出数判据（必需格全生效）：assess 缺 8 格不出数 / aggregate 缺 2 格不出数 / actions 缺 1 格不出数
待实现模块: 0 个                                              EXIT=0

$ python -m road_mqi_checker bench run
状态分布：达标 10 / 未达标 0 / 不可判 6 / 不可用 0；已声明不可判 6 项
退出码 0（完成）                                              EXIT=0
```

**未做（按 DEC1=B 明确不做）**：不重试 `jtst.mot.gov.cn`、不碰 `data/standards/`、不改 14 格 status。

## 三、批次 B 实测（桌面壳）

### B.1 `--probe`（规则 ④/⑦ 的验收项）

```
$ pip install -e "<仓库根>[gui]"                        # 干净 venv，PySide6 6.12.0
$ cd %TEMP% && rmqc.exe gui --probe
QFontDatabase: Cannot find font directory ...\PySide6\lib\fonts.   # 仅告警，不影响退出码
EXIT=0
```

### B.2 七页签逐页机械证据（真文件 + 真台账，**由页面自己的表单控件驱动**）

台账：`%TEMP%\rm-b-e2e-*/ledger.sqlite`；数据：`data/raw/S99-2022.csv`、`X990-2022.csv`、`S99-2023.csv`。

| # | 页签 | argv（页面生成） | 退出码 | 首行 |
|---|---|---|---|---|
| 1 | 台账与导入 | `import --year 2022 --data-class SYNTHETIC` | 2 → **1**（填文件后） | 导入回执：总行 12 / 入库 11 / 拒入 1 |
| 2 | 路面 PCI 评定 | `assess --year 2022` | 2 → **1** | 7 个路段（ok 0 / partial 0 / blocked 7） |
| 3 | MQI 汇总与等级 | `aggregate --year 2022 --level network` | 2 → **1** | 共 1 个对象（blocked 1），不把未出数当 0 加权 |
| 4 | 年对比与优先序 | `compare --from-year 2022 --to-year 2023` | 2 → **1** | 7 个对象（blocked 3 / uncomparable 4） |
| 5 | 基准评测 | `bench run` | **0** | 8 指标 × 2 通路 = 16 行 |
| 6 | 依据登记与规则集 | `ruleset list` | **0** | 系数 15 格（生效 1 / 拒算 14） |
| 7 | 导出与声明 | `report --year 2022 --format md --out r.md` | 2 → **1** | 3 张表，11283 字节，**文件真实落盘** |

要点：
- **默认值空表单落 2 是设计**（必填未填 → argparse/InputUnavailable），不是崩溃；
- 页签 5/6 在**仓库外**跑会落 2（找不到数据目录），在仓库根跑落 0 —— 与 `find_data_dir` 的上溯语义一致，
  不是缺陷（与 M6「打包态必须拷出仓库再量」同族）；
- 页签 7 的导出文件真存在（`file_exists: true`，11283 B），说明页面确实把参数交给了内核。

**截图**：`%TEMP%\rm-b\gui_native\01.png`–`07.png` + `e2e_07.png`。
⚠ **offscreen 平台插件下中文全是豆腐块**（`QFontDatabase: Cannot find font directory` ——
PySide6 6.12 起不再自带字体）；必须去掉 `QT_QPA_PLATFORM` 走 Windows 原生插件才能渲染出可读中文。
抓图脚本：`%TEMP%\rm-b\probe_pages_native.py`、`probe_e2e.py`。

### B.3 GUI 依赖下测试不跳过

```
$ pytest tests -q            # 干净 venv + [dev]（无 PySide6）
491 passed, 4 skipped                                          EXIT=0
$ pytest tests -q            # 同一 venv 追加 [gui]
495 passed                                                     EXIT=0
```

即 4 项 `@pytest.mark.gui` 在装了 PySide6 后**真跑**且全过（offscreen）。

## 四、仍未做：桌面窗口的**主观**目检（只能人做）

机械层已证：窗口能建、七页签在、每页把参数交给同一内核、退出码与命令行逐字一致、导出真落盘。
**机械验不到的**（请人在真实显示器上过一遍，逐项打勾后把结论写进 `plan/07`）：

- [ ] 双击启动 `rmqc.exe`（GUI 包）后窗口尺寸/字体/DPI 缩放是否正常（尤其 150% 缩放屏）
- [ ] 拖动窗口、最大/最小化、切页签时是否有残影或卡顿
- [ ] 「台账 SQLite 路径」与「年度检测表 CSV 路径」是否需要**文件选择对话框**
      （当前是纯文本输入框 —— 这是设计取舍还是缺功能，需人判断）
- [ ] 页签 5（基准评测）在真实屏幕上滚动 3500+ 字符输出时的可读性
- [ ] 底部状态栏免责声明是否可见、是否被裁切
- [ ] 长任务（导入大 CSV）期间界面是否假死

## 五、本轮负控全跑（NC1–NC6）

| # | 判据 | 实测 |
|---|---|---|
| NC1 | `pytest tests -q` 全量 | **491 passed + 4 skipped**，EXIT=0（本机 3.12.10 + 新建干净 venv 各一次） |
| NC2 | `selfcheck` | EXIT=0；「生效系数 1 格，拒算系数 14 格 → 系数门 开」；缺格 8 / 2 / 1 逐字未变 |
| NC3 | `bench run`（源码态） | EXIT=0；达标 10 / 未达标 0 / 不可判 6 / 不可用 0 |
| NC4 | `report` 无数据年度 | **EXIT=2**（`InputUnavailable: 台账里2024 年度没有路段行`），不是 0 |
| NC5 | 形态门 | 真实 Release cli zip 副本塞回 `rmqc-gui.exe` 后判据报两条违规（`cli 包含窗口壳` + `非预期可执行件`）；`tests/test_cli_zip_shape.py` 5 项 passed |
| NC6 | 计数门 | README 的 491 → 999 后 **FAILED**（见 §一） |

另：EOL 门 `tests/test_gates_eol.py` 4 项 passed（改文本后必跑，本仓有 EOL 门）。

## 六、本轮结束时的仓库状态

```
$ git status --porcelain
 M README.md
 M plan/00-README总览.md
 M plan/CORRECTION-2026-10-22.md
 M pyproject.toml
 M src/road_mqi_checker/__init__.py
 M src/road_mqi_checker/cli.py
 M src/road_mqi_checker/gui/app.py
 M tests/test_readme_test_count.py
?? plan/HANDOFF-M8.md
?? plan/RELEASE-M8.md
?? update/
```

- **已 commit `fb7283b` → push → tag `m6.3` → Release 三附件**，CI run `39702530198` 四矩阵全绿；
- 未新增 `src/`/`tests/` 文件（只改既有），故无 `git add` 义务；
- 临时产物全在 `%TEMP%\rm-b`、`%TEMP%\rm-verify`、`%TEMP%\rm-nc4`、`%TEMP%\rm-nc5`、
  `%TEMP%\rm-b-e2e-*`、`%TEMP%\rm-m63`，仓库内未新建目录。

## 七、本轮新发现（D4，已在本轮修掉）

### D4【P2，既有缺陷，非本轮引入】`scan_release.py` 第 2 步在 HEAD 上就是红的

```
$ python -X utf8 packaging/scan_release.py
[2b] 命中 18 处，其中已豁免 17 处，未豁免 1 处
    !! 身份证形态 18 位 @ plan/CORRECTION-2026-10-22.md:75 <该 hash 的前 18 位，原样形态已从留档移除>
2 交付面字面      未通过
EXIT=1
```

**根因**：`plan/CORRECTION-2026-10-22.md:75` 里那条 sha256
（`d0517585…`）的前 18 位恰好是一串 18 位纯数字，
撞上 `(?<!\d)\d{17}[\dXx](?!\d)` 这条身份证形态规则。

**证据（不是我改坏的）**：

- 该文件与本轮起点 `HEAD` **逐字节相同**（`git diff --quiet HEAD -- plan/CORRECTION-2026-10-22.md` 无输出）；
- `git show HEAD:plan/CORRECTION-2026-10-22.md | grep -n d0517585` → 第 75 行命中；
- 本轮新增的两个文档（`plan/HANDOFF-M8.md`、`update/执行记录.md`）按同一组规则预扫：
  邮箱 0 / 手机号 0 / 身份证形态 0 / 盘符+Users 0，**未新增任何命中**。

> **本文件原先把那 18 位数字原样写了三处**（登记缺陷时照抄了字面量），
> 一入库就会让脱敏门自己命中自己 —— 这正是 M6 记下的那条教训
> 「留档文档不要写会被自己规则命中的字面量原样形态」。**已改为 `d0517585…` 省略形态。**

**处理（本轮已按选项 A 修掉）**：

- ✅ **A（改文档，已采用）**：`plan/CORRECTION-2026-10-22.md:75` 的旧 sha256 改为省略形态 `d0517585…06847b`，
  完整值仍可从 `gh release view m6` 的 asset digest 回读（那才是权威来源），
  本文档里照抄的三处也已一并改掉；
- ❌ **B（改扫描器）**：不采用。给「sha256 行」加豁免会把规则放得比缺陷本身更宽，
  而 M6 已经踩过「扫描器被自己的示例文本自命中」。

**遗留建议**：`.github/workflows/ci.yml` 仍然**没有** `scan_release.py` / `verify_build.py` 步骤，
意味着脱敏门只在发布前手动跑。把它纳入 CI 属**新增口径**（需用户确认，与 M7 §二 第 2 条同类），
本轮不做。

## 八、下一棒建议

1. **本轮已发布 `m6.3`**（`fb7283b`，CI 四矩阵全绿，三附件三值对撞一致）。
   复验方直接对着 `plan/RELEASE-M8.md` 的实测记录重跑即可。
2. §四 的六项主观目检是**唯一**仍挂着的验收项（用户已明确指示本轮跳过）；
   做完写进 `plan/07` 并把 `HANDOFF-M7.md` §五 DoD 第 4 条的 ⬜ 改成 ✅（或如实写明哪几项没做）。
3. `plan/HANDOFF-M7.md` §五 第 5 条列的「重试 `jtst.mot.gov.cn`」在 **DEC1=B 之后已不再是待办**，
   下一轮不要把它当遗留缺陷捡回来。
4. 若将来觉得首屏表述需要再动，注意 **Release 说明是 tag 时点的副本**：
   改产物就新打 tag，只改文字用 `gh release edit`，**不要移动已发布的 tag**。
