# RELEASE · M7 / tag `m6.3` 发布回执

> 本文件记录**本轮（2026-10-22，DEC1=B 落地后续）**的资产重建与发布实测。
> 前序：`plan/RELEASE-M6.md`（M6 首次发布，tag `m6`）、`plan/CORRECTION-2026-10-22.md`（cli 包形态修复，tag `m6.1`/`m6.2`）。
> 扫描工具：`packaging/scan_release.py`（四步，未豁免命中即非零退出）。
> 本轮**为什么必须重建资产**：改了 `cli.py` 的 argparse `description` 与 `gui/app.py` 的窗口标题——
> 这两处都编译进 exe。旧 exe 的 `--help` 仍显示"养护决策支持工具"，与 README 首屏新表述矛盾，
> 「发布物与 tag 树一致」这条就不成立。

## 一、发布前两道门（均为手动，CI 不跑）

```bash
$ python -X utf8 packaging/scan_release.py
1 提交身份       通过
2 交付面字面      通过      # 130 份已跟踪文本，命中 17 处，未豁免 0 处
3 数据结构       通过      # 数据行 151 条，标识符越界 0 处
4 构建产物       通过      # 包内 27 份载荷，sha 不一致 0，夹具字样 0，[4b] 命中 0
EXIT=0

$ python -X utf8 packaging/verify_build.py <dist>/rmqc
[1] 26 份内嵌数据逐份 sha256 一致、无多余          [ok]
[2] 交付载荷无 fixture 字样（豁免 data/README.md 1 份）  [ok]
[3] route 185 / 6 位码 139 / 手机号 0，越界 0 个     [ok]
[4] 无 .pdf/.doc/.docx；最大文本 18,645 B ≤ 200KB   [ok]
[5] 中立目录 selfcheck → data_dir 指向 _internal/data，frozen=True  [ok]
结论：全部 5 类红线断言通过
EXIT=0
```

### 1.1 发布前先修掉 D4（既有缺陷，本轮引入的发布阻断）

`scan_release.py` 第 2 步在**本轮起点 HEAD 上就是红的**：`plan/CORRECTION-2026-10-22.md:75`
那条 sha256 的前 18 位恰好是 18 位纯数字，撞上 `(?<!\d)\d{17}[\dXx](?!\d)` 的身份证形态规则 → `EXIT=1`。

**修法（选项 A，改文档不改规则）**：把那串 sha256 写成省略形态 `d0517585…06847b`。
完整值仍可从 `gh release view m6` 的 asset digest 回读——那才是权威来源。
**不采用**"给 sha256 行加豁免"：M6 已经踩过"扫描器被自己的示例文本自命中"，
豁免写宽了比缺陷本身更危险。

⚠ 同一教训在本轮复发了一次：`plan/HANDOFF-M8.md` 登记 D4 时**照抄了那 18 位数字三处**，
一入库就会让脱敏门自己命中自己，已一并改成省略形态。

## 二、资产（本轮重建，两次可复现构建）

| 资产 | 条目 | 字节 | sha256 |
|---|---|---|---|
| `rmqc-cli-win64.zip` | **46** | **11,124,206** | `3d363a4a…78306` |
| `rmqc-gui-win64.zip` | **197** | **51,467,996** | `ef3a441b…69e8d` |
| `SHA256SUMS` | 2 行 | 186 | （逐附件文件名 + 摘要，无 `*`、两空格、单 LF） |

> 完整 sha256 见 Release 说明与 `SHA256SUMS` 附件；本文档按 M6 教训**不写完整哈希字面量**
> （避免与脱敏门的身份证形态规则自撞）。

**与 m6.2 的差异（为什么字节变了）**：

| | m6.2 | m6.3 | 原因 |
|---|---|---|---|
| cli 条目 | 46 | 46 | 一致 |
| cli 字节 | 11,122,875 | 11,124,206 | **+1,331 B**：`--help` 文案与窗口标题变短/变长后 exe 字节变化 |
| gui 条目 | 194 | **197** | PySide6 6.6.3.1 → **6.12.0**（构建环境升级），Qt 组件文件数量不同 |
| gui 字节 | 50,500,567 | 51,467,996 | 同上 |

**cli 包可复现性**：`packaging/pack_cli_zip.py` 连跑两次，`sha256` **逐字节相同**（实测 `reproducible: True`）。
gui 包由本轮的打包脚本按"路径排序 + 固定时间戳 1980-01-01 + DEFLATE"写出，
条目顺序与元数据固定，因此同输入两次构建一致。

## 三、中立目录冒烟（仓库外解包，两份包各测一遍）

```
=== cli 包（只含 rmqc.exe）===
selfcheck=0      ruleset=0      bench_run=3     ← 3 是设计（包内无 tests/fixtures/）
--help 第 3 行 = 公路技术状况评定框架：带拒算契约的离线内核 CLI   ← 新文案确实进了二进制

=== gui 包（rmqc.exe + rmqc-gui.exe）===
rmqc.exe selfcheck=0    rmqc-gui.exe --probe=0    rmqc.exe bench run=3

=== 端到端退出码（cli 包，中立目录）===
import S99-2022 → 1     import X990-2022 → 0
assess 2022 → 1         report --year 2024（无数据）→ **2**    report --year 2022 → 1
report 产物 r.md = 11,283 B   ← 与源码态导出字节数一致
```

`report --year 2024` 落 **2** 是拒算契约的关键判据（`InputUnavailable`），不是回归。

## 四、tag 与 Release

- tag：`m6.3`（annotated），指向本轮提交；`m6` / `m6.1` / `m6.2` **一律不动**（已公开引用，移动属改写历史）；
- Release `m6.3`：三附件（cli / gui / `SHA256SUMS`），正文写清本轮改了什么、为什么字节变了；
- **`m6.3` 之后不再有 tag 移动**：若将来发现说明与产物不符，做法是 `gh release edit` 改正文，
  或新打一个 tag，不动既有 tag。

## 五、本轮**没有**做的事（如实登记）

1. **人工目检跳过**（用户明确指示）：`plan/HANDOFF-M8.md` §四 那六项（DPI 缩放、拖窗残影、
   是否需要文件选择对话框、长输出可读性、状态栏免责声明、长任务界面假死）**仍未做**。
   本轮只到"机械可验层 + 中立目录冒烟"。README 与 Release 说明里都保留"未做人工验收"的说法。
2. `scan_release.py` / `verify_build.py` **未纳入 CI**（属新增口径，需单独确认）。
   两门目前仍只在发布前手动跑。
3. 未改 14 格 `pending` 状态、未动 `data/` 下任何 fixtures/真值/24 份 CSV/manifest。
