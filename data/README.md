# data/ 依据查证记录与合成数据纪律

本目录存放合成检测评定数据、真值标注与评测基准。任何进入评定路径的系数（扣分比率、分项权重、分级阈值）必须先在本文件登记查证状态。

## 一、依据查证记录（逐条）

状态三态：✅已核对（附官方渠道）/ ⬜待核对（入库时核对原文）/ ❌查证失败（题目里不得用确定语气）。

| # | 依据 | 用于哪条规则 | 状态 | 核对渠道与时间 |
|---|---|---|---|---|
| 1 | JTG 5210-2018《公路技术状况评定标准》 | 破损扣分比率、分项指标（RQI/车辙/抗滑等）合成 PCI、MQI 加权、技术状况分级阈值 | ⬜ 编号与名称多源一致，但**未取到交通运输部官方公告原文页** | 2026-10-07 检索命中：百度百科条目、`nssi.org.cn` 标准条目（抓取失败，fetch error）、`guifanku.com`、`kongfz.com` 出版物页 —— 均非官方。**M3 开工前必须换到交通运输部/国家铁路局等官方标准公告页复核，否则相关系数不得生效** |
| 2 | JTG 5210-2018 的发布公告号与实施日期 | 引用格式与版本对照 | ⬜ | 同上，未取得官方公告页 |
| 3 | 是否存在替代/修订版（2026 年是否仍现行） | 防止引用废止版本 | ⬜ 待核对（截至 2026-10-07 检索，最新公开引用仍指向 2018 版，未见新版） | 检索含 2026-09 时间戳的条目仍记 2018 版；**属间接证据，需官方现行标准清单确认** |
| 4 | 《公路养护技术标准》与 JTG 5142-2019 的名称-编号对应关系 | "按评定结果安排养护工程"的养护管理锚点 | ❌ 当前查证失败 → **暂不作为锚点引用** | 冲突记录：交通运输部政策解读页 `mot.gov.cn/2023zhengcejd/202312/t20231206_3963116.html` 返回 404；同时检索到一处把 JTG 5142-2019 记为《公路沥青路面养护技术规范》。名称与编号对应关系未解决前，本题**不得**引用该标准号或名称 |
| 5 | 《公路安全保护条例》《农村公路条例》现行状态与相关条文 | 路况评定与养护义务的上位依据（仅背景引用） | ⬜ | 未查证；不得凭记忆写条号；核对不通过则从 01 文档锚点表删除 |
| 6 | 《国家公路网规划》/"十四五"综合交通运输体系规划等文件号 | 时代性加分项（不参赛，非硬锚点） | ⬜ | 未查证；核对不过直接删行 |
| 7 | 各省公路技术状况评定实施细则 / 地方扣分表差异 | versioned ruleset 的"省份包"设计动机 | ⬜ | 待按目标受众省份逐条检索官方页；**未核对者不得进入评定路径**，只能作为用户自定规则 |
| 8 | 标准原文中的算例（若有） | 黄金用例真值 | ⬜ | 取得原文后逐格核对再入库；无原文 → 只用自算用例并附推导过程 |

> 纪律重申：搜索摘要一律不采信（存在编造链接与矛盾条号）。本题风险集中在**每一格数字**上 —— 扣分表与权重若凭记忆填写必然错，所以 M3 之前所有系数字段一律为"待核对"，评定引擎先按"无生效系数"跑通结构。
> 引用纪律：01 文档中不出现任何具体阈值/权重数字，一律写"以原文核对后入库"。

## 二、开源空白查证记录（2026-10-07，`gh search repos`）

| 检索式 | 命中 | 结论 |
|---|---|---|
| `resilient modulus pavement PCI` | 0 条 | 空白 |
| `公路 技术状况` | `kekepepe/Intelligent-Road-Defect-Detection-System`(1★) | 病害图像识别方向，非"评定计算 + 台账 + 可复现基准" |
| `pavement condition assessment` 类同义检索 | 未见规则化评定工具仓库 | 空白（待 M6 前补一次检索留档） |

## 三、合成数据纪律与白名单

演示/评测数据全部程序生成，**不得出现真实路线、真实桩号点位、真实单位与人员信息**。允许形式（白名单，新增需在此登记）：

| 类别 | 白名单形式 | 示例 |
|---|---|---|
| 路线编号 | 虚构字母+9 系列 | `S99`、`X990`、`Y999`、`Z9901` |
| 行政区划代码 | 保留/虚构段 | `990000`、`9901xx` |
| 桩号 | 明显虚构区间 | `K0+000`～`K99+999`，并在 README 声明为虚构 |
| 路段名 | `SYN` 前缀 + 虚构地名 | `SYN-清河县东段 K12+300～K16+500` |
| 单位名 | 虚构且明显非实名 | `示例公路工程检测有限公司`、`某某养护中心第 3 分部` |
| 手机号 | 199 保留号段 | `19900000000`～`19900009999` |
| 报告/委托编号 | `SYN-LG-2026-0001` 式 | — |
| DOI / 文献 | 保留前缀 | `10.9999/SYN.0001` |
| 日期 | 允许虚构年度（如 2021～2026 评定年度） | — |

真值文件约定（M1 落地，列名以 `bench/generator.py` 的 `TRUTH_COLUMNS` 为唯一事实源）：

```
segment_id, route_id, year, surface_type,
pci_truth, grade_truth, mqi_partial_truth, recommended_action_truth,
injected_issue, injected_field
```

- `surface_type ∈ {asphalt, cement}`；破损类型与程度字典见 `plan/03` §二（代码落点 `ledger/models.py`）；
- `injected_issue ∈ {gap_chain, overlap_chain, partition_change, negative_value, out_of_range, unit_error, duplicate_import, none}`；
- **评分四列现在仍一律是 `pending:coeff=<系数key>` 令牌**：内置规则集 15 格系数全为待核对，
  "未核对不出数"对真值同样成立。真值里凭记忆填一个 PCI 等于给基准装假答案。
  数值真值的唯一入口是 `generator._numeric_truth_probe`，**M2 起它调用评定引擎本身**
  （`pci.engine.compute_pci`，与 `rmqc assess` 同一个内核），生成器里没有第二套扣分公式。
  于是同一 seed 重跑：换上一套系数已核对的规则集包，`pci_truth` / `grade_truth` 两列自动变数值或等级名，
  且与台账通路逐字段相同（`tests/test_m2_assess.py` 逐个对象对账）。
  剩下两列 `mqi_partial_truth` / `recommended_action_truth` 属 M4，仍写 `pending:engine=mqi.engine@M4` /
  `pending:engine=strategy.rules@M4`（如实点名所属模块与里程碑，不放一个凑出来的数）。
  系数齐了但评定引擎对该对象拒算（台账含异常行）时，这两列写 `pending:engine=pci.engine.blocked` ——
  **引擎拒算的对象真值也不出数**，两边口径一致；
- 真值取的是**即将落盘的那份 CSV 的文本值**，并按导入层 `R008` 的同一身份列去掉文件内重复行：
  真值描述"进了台账的那本账"，与评定通路的输入是同一份数据（`plan/02` §9 第 21 条）；
- 注入用例是声明的常量（`generator.INJECTIONS` / `PARTITION_PLAN`），不随 seed 漂移；
  同一注入隐含的其余结论见 `generator.INJECTION_IMPLICATIONS`，不在真值里手工再写一份；
- 生成器必须支持固定随机种子（基准可复现的前提），随机源只能是 `src/road_mqi_checker/bench/rng.py` 的 splitmix64。

数据类别纪律（M1 落地，与 `ledger/importer.py` 的 `DATA_CLASSES` 同步）：

| 类别 | 触发方式 | 白名单是否强制 |
|---|---|---|
| `SYNTHETIC` | 文件首行标记 `# data_class=SYNTHETIC` | **强制**：真实形态标识符逐行拒入（拒因 `R010_PRIVACY_WHITELIST`） |
| `user` | 导入时 `--data-class user` 显式声明，且文件无标记 | 不施加：这是用户自己的真实检测台账，本工具的用途就是管它 |

- 无标记又无声明 → 拒读（退出码 2）；标记与声明冲突 → 也拒读，不做静默降级；
- 理由：白名单是**演示数据**的红线（本题不许出现真实路线/行政代码/号段），不是把工具锁死到不能管真实账；
  但"是不是演示数据"必须由数据自己声明，不能靠读侧猜。

> 本文件 §一 的表格行号 `#N` 是系数的**出处指针**：内置规则集每格系数的 `register_ref` 写成
> `data/README.md#N`，由 `tests/test_ruleset_builtin.py` 校验该行存在且内容确实提到所引用的标准。
> 增删本表行要同步规则集 JSON 与该测试。

## 四、目录约定

```
data/
  raw/            合成年度检测数据（不入库真实检测数据）
  truth/          真值标注（.truth.csv，与 raw 同名配对）
  golden/         黄金用例与期望结果、复现命令
  standards/      自己整理的条款摘录笔记（禁止提交标准全文/扫描件）
```

规则集系数不在 `data/` 下，而在包内随发布走：`src/road_mqi_checker/rulesets/*.json`
（用户自定/地方细则包放仓库外，用环境变量 `RMQC_RULESET_DIR` 指定目录覆盖）。
理由：exe 内嵌数据要能与仓库逐份对账（M6 构建红线），数据文件与规则系数分两处会漏检。

`data/standards/*.pdf` 已在 `.gitignore` 中排除，避免版权风险；`data/raw/real_*` 亦排除，
真实检测数据不得进仓库。会话内查证与验证的临时产物只落 `.tmp_*/`（已被忽略且字节门跳过）。

## 五、落地对照（截至 M2，2026-10-07）

| 本文件的约定 | 代码落点 | 由哪条测试守住 |
|---|---|---|
| 三态核对状态 | `ruleset/status.py`（`pending/located/verified` + 夹具档 `fixture`） | `tests/test_ruleset_status.py` |
| 每格系数登记来源 | `rulesets/base-jtg5210-2018.json` 的 `basis` + `register_ref` | `tests/test_ruleset_builtin.py` |
| 真值文件列约定 | `bench/generator.py` 的 `TRUTH_COLUMNS`（单点定义） | `tests/test_m1_generator.py`（位级一致 + manifest 自描述） |
| 真值评分四列不出数（内置包） | `generator._score_truth` + `_numeric_truth_probe` | `test_truth_score_columns_refuse_to_emit_numbers`、`test_cement_truth_stays_pending_under_the_asphalt_fixture` |
| 数值真值由评定引擎产生（M2 接线） | `generator._numeric_truth_probe` → `pci.engine.compute_pci` | `test_truth_probe_delegates_to_the_assessment_engine`（spy 证明被调用）、`test_truth_columns_are_numeric_and_match_the_ledger_path`、`test_cement_fixture_produces_cement_truth` |
| 含异常对象拒算而非跳过破损行 | `pci.engine.BLOCKING_CHECK_KINDS` + `blocking_findings` | `test_every_abnormal_object_in_the_frozen_data_is_refused` |
| M4 两列仍点名未就位模块 | `generator.TRUTH_ENGINE_MODULES` | `test_mqi_and_action_truth_columns_stay_pending_until_m4` |
| `injected_issue` 词汇 | `ledger/models.py` 的 `INJECTED_ISSUES` | `test_each_injected_issue_has_at_least_two_cases` |
| 白名单形式 | `privacy.py` 的 `PATTERNS` + `WHITELIST_HINTS` | `tests/test_privacy_whitelist.py`、`test_committed_data_identifiers_all_pass_the_whitelist` |
| 数据类别（SYNTHETIC / user） | `ledger/importer.py` 的 `DATA_CLASSES` + 文件首行标记 | `test_unmarked_file_refuses_without_declaration`、`test_mark_conflicting_with_declaration_is_refused` |
| 固定随机种子 | `bench/rng.py` splitmix64 + 冻结向量 | `tests/test_determinism_rng.py`、`test_injections_are_seed_independent` |
| 未核对不进评定路径 | `results.py` 拒算契约 + `pci.engine` 系数门 + `cli` 系数门 + `checks` 的 `undetermined` 档 | `tests/test_results_contract.py`、`test_length_closure_never_hard_judges_while_pending`、`test_builtin_ruleset_blocks_every_object_with_numbers_all_empty` |
| 破损字典（类型×程度×量纲） | `ledger/models.py` 的 `DISTRESS_DICTIONARY`（口径见 `plan/03` §二） | `test_distress_dictionary_is_clean_in_frozen_data_but_catches_intruders` |
| 演示数据入仓形态 | `data/raw/*.csv` + `data/truth/*.truth.csv` + `data/raw/manifest.json` | `test_regeneration_of_committed_fixtures_is_byte_identical`、`test_manifest_digests_match_committed_fixtures` |
