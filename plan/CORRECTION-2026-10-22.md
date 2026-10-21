# 更正记录：cli zip 形态修复与自述对齐（2026-10-22）

> 本文件是**新增**更正留档，不改写历史。`plan/RELEASE-M6.md`、`plan/HANDOFF-M7.md` 里
> 「`rmqc-cli-win64.zip` 12.3 MB（47 文件）」这类数字是 **tag `m6` 时点**的事实，
> 本文件记录其后发现的缺陷、修复与**资产口径变更**。

---

## 一、发现的缺陷（实测）

### D1【P1】`rmqc-cli-win64.zip` 里带了一个跑不起来的窗口壳

- **实测**（`gh release download m6` 取回原件后解包）：
  ```
  rmqc-cli-win64.zip  → 47 条目，可执行件 = ['rmqc-gui.exe', 'rmqc.exe']
  在该包里跑 ./rmqc-gui.exe --probe
    → ImportError: ...\shiboken6\libshiboken does not exist
    → road_mqi_checker.errors.OptionalDependencyMissing: 缺少可选依赖 PySide6
    → exit 1
  对照：rmqc-gui-win64.zip 里同一个 --probe → exit 0
  ```
- **根因**：cli 包 = gui 包剔除 **147 个 Qt/shiboken 文件**，但**没有剔除 `rmqc-gui.exe`**。
  一个没有 Qt 的窗口壳必然起不来。
- **两份 zip 的差异是纯 Qt 子集**（实测 `set(gui) - set(cli)` 共 147 项，**全部**是
  `pyside6` / `shiboken6` / `qt6` 路径），且两个 zip 里的 `rmqc-gui.exe`
  **字节完全相同**（1,957,339 B，sha256 前缀 `0a3512f6e0980b1b`）。
- **与自述的冲突**：
  - `README.md:150` 原写「`rmqc-cli-win64.zip`（12.3 MB，47 个文件）：`rmqc.exe` 控制台壳」——只提一个 exe；
  - `plan/RELEASE-M6.md:70` 原写「**只含控制台壳**（剥掉 Qt 相关文件）12.3 MB」——明确说"只含"。
  → 实际包内有两个 exe，其中窗口壳是坏的。

### D2【P2】三处自述已过时（发布面早已完成）

| 位置 | 原文 | 实测事实 |
|---|---|---|
| `README.md:9`（状态行） | 「M6 交付层（🟡 …；**发布面 CI 首跑 / tag / release 待授权**）」 | tag `m6` 已打、Release 已建（2026-10-08）、CI 已于 2026-10-21 跑过 4 矩阵全绿（run `39604549081`） |
| `README.md:162` | 「发布包（zip 资产）**尚未上传到任何渠道**」 | Release `m6` 上有两个 zip，`gh release download` 取回后 sha256 与 API digest 逐位一致 |
| `plan/00-README总览.md:16`、`plan/02-开发计划与架构.md:288` | 「发布面 … **待授权**」/「进行中 … 发布面待授权」 | 同上 |

---

## 二、修复动作

### 2.1 新增唯一重建入口 `packaging/pack_cli_zip.py`

此前 cli 包是**临时脚本**产出的（仓内无生成器），所以"剔除什么"只存在于当时的命令行里，无法复现、
也无法被测试。本次把它固化成脚本：

- 剔除规则：`is_qt_payload()`（`/pyside6/`、`/shiboken6/`、`qt6` 三种 token）+ **`rmqc-gui.exe`**；
- 条目元数据（`date_time` / `compress_type` / `external_attr`）**原样沿用源包**，保证可复现；
- `assert_cli_zip_shape()` 提供形态判据（无 Qt / 无窗口壳 / 仅 `rmqc.exe` / `testzip` 通过）。

用法：
```bash
python packaging/pack_cli_zip.py <gui.zip> <out-cli.zip>
```

**确定性实测**：同一输入两次重建 sha256 相同（`0a76abaa13c854e6a82b817bbb96779db3f1ddc174036f002fe181ec44706783`）。

### 2.2 新增守门测试 `tests/test_cli_zip_shape.py`（5 项）

| 用例 | 性质 |
|---|---|
| `test_build_strips_qt_and_gui_exe` | 正控：重建后只剩 `rmqc.exe`、无 Qt、保留非 Qt 依赖与内嵌数据 |
| `test_rebuild_is_deterministic` | 同输入两次重建逐字节一致 |
| `test_gate_rejects_windowed_shell` | **负控**：把 `rmqc-gui.exe` 塞回去必须报"窗口壳" |
| `test_gate_rejects_qt_payload` | **负控**：出现 Qt 载荷必须报 |
| `test_gate_rejects_missing_cli_exe` | **负控**：只有窗口壳、没有控制台壳必须报 |

→ 三条负控保证判据**可证伪**，不是"看起来有门"。

### 2.3 重建 cli 资产

```
旧：rmqc-cli-win64.zip  12,865,367 B  47 条目  sha256 d051758564185744321d481eda7b89e74e45a38b18d90e3f646e20ca7876847b
新：rmqc-cli-win64.zip  11,122,875 B  46 条目  sha256 0a76abaa13c854e6a82b817bbb96779db3f1ddc174036f002fe181ec44706783
     （= 旧包剔除 rmqc-gui.exe 一个条目，其余 46 条逐字节保留）
```

**新包实测**（中立目录解包后）：
```
./rmqc.exe selfcheck      → exit 0
./rmqc.exe ruleset list   → exit 0
./rmqc.exe bench run      → exit 3（设计如此：包里无 tests/fixtures/）
ls *.exe                  → 只有 rmqc.exe
```

**`rmqc-gui-win64.zip` 未改动**：sha256 仍为 `33482ae849013e29b20522ae9ec5f754a4a06c5a08cd3622db50e85572d2d743`，
与 Release digest 一致。

### 2.4 自述对齐

| 文件 | 改动 |
|---|---|
| `README.md:9` | 状态行 M6 从「🟡 … 待授权」改为「✅ … tag `m6` + Release 双 exe 资产已发布、CI 四矩阵全绿」 |
| `README.md:150` | cli 包描述改为「11.1 MB，46 个文件：**只含 `rmqc.exe` 控制台壳**（已剥掉全部 Qt/shiboken 文件与窗口壳）」 |
| `README.md:162` | 「尚未上传到任何渠道」改为「已随 tag `m6` 发布到 GitHub Release」并给出链接 |
| `plan/00-README总览.md:16` | 「发布面 push / CI / tag 待授权」→「已交付并发布（tag `m6` + Release 双 exe 资产；CI 四矩阵全绿）」 |
| `plan/02-开发计划与架构.md:288` | 标题「（进行中 … 发布面待授权）」→「（已完成 … tag `m6` + Release 已发布）」 |

---

## 三、验证

```
$ python -m pytest tests/ -q
490 passed, 4 skipped in 22.32s     ← 原 485 passed + 4 skipped；新增 5 项

4 处 skip 全部是声明式 GUI 跳过（缺 PySide6，reason 里写明安装来源），非静默跳过。
```

> 注意：新增的 `packaging/pack_cli_zip.py` 与 `tests/test_cli_zip_shape.py` **必须 `git add`**，
> 否则既有门禁 `test_every_source_and_test_file_is_git_tracked` 会红（它要求 src/tests 下所有
> `.py`/`.json` 都被 git 跟踪）。本次已 `git add`（**未提交**）。

---

## 四、尚未做 / 需用户决定

1. **Release 附件尚未替换**。当前 Release `m6` 上挂的仍是**旧 cli zip**（含坏窗口壳）。
   是否把新包传上去，需用户决定 —— 两种做法：
   - **A. 新建 `m7` tag + 新 Release**（推荐）：不动已发布的 `m6`，符合本仓
     「不移动已公开引用」的既有纪律（见 `plan/RELEASE-M6.md:21`）；
   - **B. 原地替换 `m6` 的附件**：`gh release upload --clobber`。会改变已发布引用的内容，
     且 tag `m6` 指向的树里没有新包，**附件与 tag 不再对应**。
2. **`plan/RELEASE-M6.md` 与 `plan/HANDOFF-M7.md` 里的「12.3 MB / 47 文件」未改**：
   那是 tag 时点的历史事实，按本仓纪律不改写历史；以本文件为更正依据。
3. **桌面壳窗口交互仍未人工目检**（探针层级之外），这一条从 M6 起就登记着，本次未变。

---

## 五、追加（同日第二批）：自述测试计数漂移 + 补自指守门

### D3【P2】README 的测试项数没有门盯着，每加测试就漂一次

- **实测**：本次修复前 README 两处写「489 项」；新增 `test_cli_zip_shape.py`（5 项）后实测
  **490 passed + 4 skipped = 494 collected**；再加本批的计数守门自身后为
  **491 passed + 4 skipped = 495 collected**。
- **根因**：仓内**没有任何门**断言"README 自述计数 == 实际收集数"。本仓其他地方
  （`bench run` 指标表）有 `test_readme_metric_table_is_generated_from_bench_run` 做逐行对账，
  唯独测试计数这一处没有。

### 修复

| 动作 | 说明 |
|---|---|
| 同步 README | 两处「489」→「495 收集 / 490 通过 / 4 项声明式跳过」 |
| 新增自指守门 | `tests/test_readme_test_count.py` —— 解析 `pytest --collect-only` 的收集数，断言与 README 的 `N 项守门测试`、`各收集 N 项` 两处句式都相等 |

**门禁自身已验红**：把 README 留在 490 而实际收集 495 时，该门报
`AssertionError: README 自述 490 项，实际收集 495 项`，退出码非 0 —— 证明它不是恒绿的空门。

### 顺带修掉的一处

`README.md` 曾被我用 Python 写回时整文件转成 CRLF（317 处），触发既有门
`test_gates_eol.py::test_tracked_text_files_have_no_cr`。已归一为 LF；
`git diff` 实际内容差异仅 2 行（`--ignore-cr-at-eol` 复核）。
