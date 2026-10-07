# RELEASE · M6 脱敏与发布回执

> 本文件记录 M6 的发布前置检查**实测结果**与判定理由。对外动作（建仓 / push / CI / tag / release）
> 需要用户明确授权，未授权前本文件只到"本地已备好"这一格，不假装已发布。
> 扫描工具：`packaging/scan_release.py`（四步一条命令跑完，未豁免命中即返回非零）。
> 回执原文：`.tmp_m6/scan_release_final3.log`（本机 scratch，不在交付面）。
> §一 是 `dist/` 就位之后的最终一轮（125 份已跟踪文本）；第一次跑（`.tmp_m6/scan_release.log`，118 份）
> 用的是同一套规则，四步结论一致。

## 一、脱敏四步实测（2026-10-07，`py -3.8 -X utf8 packaging/scan_release.py`）

| 步 | 查什么 | 实测 | 判定 |
|---|---|---|---|
| 1 提交身份 | 全历史 `%an\|%ae` 是否同一公开身份 | 身份 **1 条**：`yuluo554\|282769740+yuluo554@users.noreply.github.com`；提交 25 个；非 noreply 邮箱 **0 条** | ✅ 无需全历史改写（M0 起就是 GitHub noreply 形态） |
| 2 交付面字面 | 已跟踪文本文件的邮箱 / 手机 / 身份证形态 / 绝对路径 / 密钥 token / 真实路线编号 | 扫描 **125 份**（M6 交付面新增 `packaging/` 5 份与 `plan/07`、`plan/RELEASE-M6.md`）；命中 17 处，**未豁免 0 处**；超 200KB 的 txt/md **0 份**；已跟踪二进制 **0 份** | ✅ 通过（豁免台账见 §二） |
| 3 数据结构 | 演示数据逐字段过 `privacy` 白名单；`register_ref` 指向的行是否真存在 | 数据行 **151 条**，标识符越界 **0 处**；`manifest.data_class=SYNTHETIC`，文件数 12；`register_ref` 无出处 **0 个** | ✅ 通过 |
| 4 构建产物本体 | `dist/` 内载荷与仓库逐份 sha256 对账；无夹具字样；无 pdf/doc 原文；字面扫描同一套规则 | 包内文件 **185 份**，数据/文本载荷 **27 份**；sha 不一致 **0 份**、仓库无对应 **0 份**；含 `fixture` 的载荷 **0 份**；标准原文类二进制 **0 份**；[4b] 字面命中 **0 处** | ✅ 通过（PyInstaller onedir 双 exe 落地后再复跑一次，见 §四） |

命令面退出码：`scan_release.py` 返回 **0**。

扫描器自己的示例文本也算交付面：第一版把负向用例的字面量原样写进了 `scan_release.py` 与本文件的豁免表，
于是每次扫描都命中留档文档自己（实测 5 处未豁免 → 步骤 2 报"未通过"）。修法不是放宽规则，
而是**留档与扫描器都不写它会命中的字面量原样形态**（扫描器正则里的五连字符破折号串改写成量词写法）。
这条纪律写在这里，是为了让下一棒不必再发现一遍。

## 二、豁免台账（17 处全部有出处，删字面等于删证据）

| 命中规则 | 位置形态 | 理由 |
|---|---|---|
| 手机号 11 位（白名单外） | `tests/` | 白名单**反例**语料：这些用例断言的正是"真实号段必须被 `privacy` 闸门拒绝"（`test_m1_pipeline.py`、`test_privacy_whitelist.py`） |
| 身份证形态 18 位 | `tests/test_determinism_rng.py` | splitmix64 冻结向量是 19~20 位 u64 数字串，恰好撞 18 位形态；`plan/HANDOFF-M1` §一 第 2 条已预告该误报面 |
| 邮箱（非 GitHub noreply） | `tests/test_gates_environment.py` | 测试用的是 RFC 2606 保留示例域（example + 无效后缀），不可投递；本表不复述它的原样形态，否则扫描会命中留档文档自己 |
| 本机绝对路径 / 家目录 | `tests/` | 导出闸门 `assert_export_safe` 的负向用例：斜杠 home 形态与盘符 Users 形态的构造字符串，用来证明导出层会拒绝绝对路径 |
| 真实形态路线编号（G/S 开头） | `tests/`、`data/README.md`、`plan/`、`README.md` | 白名单反例语料与登记说明：写的是"真实国道/高速编号一律拒绝入库" |

判定口径：**白名单内的虚构标识符不算命中**（`S99` / `X990` / `Y999` / `Z9901`、`99` 开头行政代码、
`1990000` 保留号段、`SYN-` 前缀、`10.9999/` DOI）—— 扫描器直接复用 `privacy.PATTERNS` 做反查，
不在这套代码里另写一份白名单，避免两处口径漂移。

## 三、本地已固化的发布面（不需要授权的那部分）

- `.gitattributes` 强制 LF + EOL 门；`.gitignore` 覆盖 `_private/`、`data/raw/real_*`、
  `data/standards/*.pdf`、`.env`、`dist/`、`build/`、`.tmp_*/`；
- CI 四矩阵（ubuntu/windows × py3.8/3.12）的 workflow YAML 已有可解析门（`test_gates_workflow.py`）；
  CI 只装 `.[dev]` ⇒ 需要 PySide6 的 4 条桌面壳测试在 CI 上**声明式跳过**（不是静默跳过，
  `pip install road-mqi-checker[gui]` 写在 reason 里）。GUI 通路的真跑证据来自本机双通道
  （两侧都有 PySide6 6.6.3.1，487 项全过 0 跳过）与干净环境脚本里 `pip install -e ".[gui]"` 之后的复跑；
- 品牌隔离：仓库内不提及任何其他工程类工具项目。

## 四、待办与授权边界

| 项 | 状态 | 前置 |
|---|---|---|
| onedir 双 exe + `packaging/rmqc.spec` `datas` 白名单 | ✅ 已构建：`dist/rmqc/rmqc.exe` + `rmqc-gui.exe` 共用一份 `_internal`，`datas` 逐条列出 27 条（12 raw + manifest + 12 truth + `data/README.md` + 内置规则集），构建期与仓库 `glob` 对账 |
| `packaging/verify_build.py` 构建后红线断言 | ✅ 五类断言全过（回执 `.tmp_m6/verify_build.log`）：26 份内嵌数据逐份 sha256 一致且无多余、夹具字样 0、真实形态标识符越界 0、无 pdf/doc 与 >200KB 载荷、中立目录里 `data_dir` 指向包内 |
| 中立目录（仓库外）CLI 五连 + GUI 存活探针 | ✅ 真跑：**68 步 want==got 全对**（回执 `.tmp_verify/M6/exits.tsv` + `run.log`），exe 三格式导出与源码态逐字节一致，`rmqc-gui.exe --probe` 落 0，打包态 `bench run` 落 3 |
| CI 四矩阵首跑全绿 | ⬜ | **需 push 授权** |
| 建仓 / push / tag / GitHub release | ⬜ | **需用户明确授权**（本轮默认只本地 commit） |
| README「免安装 exe」段落转正 | ⬜ | exe 真做出来并验过之后才改 |

**决定与理由（不留悬案）**：
1. 提交邮箱不改写 —— 全历史只有一条 GitHub noreply 身份，本身即公开身份，无个人信息泄漏面；
2. 本地目录名 `10-7-road-mqi-checker` 与第三方标准站点名保留在 `plan/` 与 `data/README.md` 里 ——
   前者是工程自用编号（不含用户名），后者是查证渠道的**事实记录**，删掉会让"系数为什么是 pending"
   失去出处。`plan/02` §十 第 8 条登记的复核项就此结案；
3. 演示数据、夹具与真值一律不随 exe 之外的形式发布（`tests/fixtures/` 不进包是常驻红线，
   由 `test_release_redlines.py` 与 `scan_release.py` 第 4 步双向把关）。
