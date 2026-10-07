# data/ 依据查证记录与合成数据纪律

本目录存放合成检测评定数据、真值标注与评测基准。任何进入评定路径的系数（扣分比率、分项权重、分级阈值）必须先在本文件登记查证状态。

## 一、依据查证记录（逐条）

状态三态：✅已核对（附官方渠道）/ ⬜待核对（入库时核对原文）/ ❌查证失败（题目里不得用确定语气）。

| # | 依据 | 用于哪条规则 | 状态 | 核对渠道与时间 |
|---|---|---|---|---|
| 1 | JTG 5210-2018《公路技术状况评定标准》 | 破损扣分比率、分项指标（RQI/车辙/抗滑等）合成 PCI、MQI 加权、技术状况分级阈值 | ❌ 查证失败（M3 轮）：**官方渠道取不到原文条款表**，相关 14 格系数一律留 `pending` | 2026-10-07 M3 换渠道复核，抓取缓存与 sha1 见 `.tmp_verify/M3/`（batch1/batch2/batch3/province）：① 陕西省交通运输厅 `jtyst.shaanxi.gov.cn/glj/kjxx/201909/t20190927_2661123.html` = HTTP 200 / 61,900 B / sha1 `39d8c5e…`，**是官方页但只转载公告**（发布/施行/废止三件事），**不含任何条款号与数值表**；② 交通运输部 `www.mot.gov.cn` = 200（首页，站内检索 `so.mot.gov.cn` 连接失败 HTTP 000），其标准公告页猜测 URL = 404；③ 全国标准信息公共服务平台 `std.samr.gov.cn` 详情/检索页 = 200 但正文由脚本填充，curl 取到的是空壳（`《》`、字段全空），无条款可定位；④ **交通运输标准化信息服务平台 `jtst.mot.gov.cn/hb/search/stdHBDetailed?id=…` = 503 ×4 次（服务暂停；URL 形态已定位 → 这条渠道没查完，只是没连通）**；⑤ 主编单位 `rioh.cn`、出版机构 `jtcbs.com.cn` = 连接失败 000；⑥ 吉林省交通运输厅 2019 年度评定通知（官方，200 / 64,311 B）以本标准号为评定依据并给出"1000 m 路段基本单元"与 MQI/SCI/PQI/BCI/TCI 指标体系，**但无数值表**；⑤ 全文命中处 `waizi.org.cn` / `nssi.org.cn`（000）/ `guifanku.com`（404）/ `max.book118.com` / `renrendoc.com` / `scribd` / `book.dangdang` 全部是文档分享站或书店，**按纪律不采信其数值**。结论：**扣分比率、分项权重、分级阈值 14 格不得转 verified**，需要纸质或正式电子原文后逐格核对 |
| 2 | JTG 5210-2018 的发布公告号与实施日期 | 引用格式与版本对照 | ⬜ 部分核对：施行/废止日期已有官方页支撑，**公告号仍只有非官方来源** | 官方页（同上 ①，sha1 `39d8c5e…`）确认"2018-12-25 发布、2019-05-01 施行、原 JTG H20—2007 同时废止、管理与解释权归交通运输部、日常解释由交通运输部公路科学研究院负责"；"交通运输部公告 2018 年第 88 号"这一编号**仅出现在 `waizi.org.cn`（非官方）**，官方页无编号 → 公告号不得写进任何交付面文字 |
| 3 | 是否存在替代/修订版（2026 年是否仍现行） | 防止引用废止版本 | ⬜ 待核对（间接证据增强，仍无官方现行清单） | 官方页 ①（2019 年陕西省交通运输厅转载）确认 2018 版替代 JTG H20—2007；新增两处官方引用：吉林省交通运输厅 2019 年度评定通知、交通运输部办公厅交办公路〔2019〕32 号/〔2021〕83 号（`xxgk.mot.gov.cn`，200）仍以 JTG 5210-2018 为评定依据 → **未见替代新版，但仍属间接证据**：权威状态位要 `jtst.mot.gov.cn`（本轮 503，URL 形态已定位）或 `std.samr.gov.cn` 行标详情页（脚本渲染空壳） |
| 4 | 《公路养护技术标准》与 JTG 5142-2019 的名称-编号对应关系 | "按评定结果安排养护工程"的养护管理锚点 | ❌ 当前查证失败 → **暂不作为锚点引用** | 冲突记录：交通运输部政策解读页 `mot.gov.cn/2023zhengcejd/202312/t20231206_3963116.html` 返回 404；同时检索到一处把 JTG 5142-2019 记为《公路沥青路面养护技术规范》。名称与编号对应关系未解决前，本题**不得**引用该标准号或名称；M3 轮未新增可采信渠道 |
| 5 | 《公路安全保护条例》《农村公路条例》现行状态与相关条文 | 路况评定与养护义务的上位依据（仅背景引用） | ⬜ | 未查证；不得凭记忆写条号；核对不通过则从 01 文档锚点表删除 |
| 6 | 《国家公路网规划》/"十四五"综合交通运输体系规划等文件号 | 时代性加分项（不参赛，非硬锚点） | ⬜ | 未查证；核对不过直接删行 |
| 7 | 各省公路技术状况评定实施细则 / 地方扣分表差异 | versioned ruleset 的"省份包"设计动机 | ✅ **拿到省级原文：差异存在但只在"农村公路/低等级"档** | 2026-10-07 经全国标准信息公共服务平台检索（留档 `.tmp_verify/M3/province/`）命中：`DB43/T 3087-2024`《农村公路技术状况评定规范》（湖南，平台标"现行"，2024-11-13 发布 / 2025-02-13 实施）、`DB12/T 1214-2023`（天津）、`DB11/T 1614-2019`（北京）、`DB14/T 3331-2025`《农村公路技术状况评定指南》（山西，状态位需逐条判读）。详情页只有书目信息、**无正文表格** ⇒ 安徽 `DB34/T 4471-2023` 全文（备案平台 200 / 17,522 B + 全文 PDF 200 / 713,467 B）原文逐字：适用于农村公路四级及以下、三级参照、**二级及以上按 JTG 5210 执行**；湖南 `DB43/T 3087-2024` 同族（扫描全文已逐页读图）。⇒ 差异是**另一套农村公路指标体系**（自设幂函数 PCI、自有权重与 90/80/70/60 边界），**不是改 JTG 的表** → 内置 14 格不得取 DB 数值，省份包仍不建（且发现前置缺口：`applies_to` 缺"技术等级"维度）。另：未检索到任何省级文件改动 JTG 在高速/国省干线的比率、权重或分级；安徽高速养护办法的"平均 MQI≥90/PQI≥92"属考核口径，不得填进分级格。详见 `plan/04` §五 |
| 8 | 标准原文中的算例（若有） | 黄金用例真值 | ⬜ | 取得原文后逐格核对再入库；无原文 → 只用自算用例并附推导过程 |
| 9 | 闭合差容差 = ±1 m（**用户自定口径，非规范值**） | `tolerance.length_closure` → 导入校验 `length_closure` 判与不判 | ✅ 生效（用户自定口径显式登记即生效；**不属于"已核对官方原文"那一档**） | 2026-10-07 显式登记。取 1 m 的理由：桩号按整米登记（`K12+300` 形态，`models.parse_stake` 只产整数米），路段长度与路线里程都由整米相减得到，口径一致的账闭合差必为 0；放宽到 1 m 只为吸收路段划分时末段取整的一米差，更大的差都是真实的账实不符。**本格改它不需要原文**，但必须在导入回执里显示当前取值与来源 |

> 纪律重申：搜索摘要一律不采信（存在编造链接与矛盾条号）。本题风险集中在**每一格数字**上 —— 扣分表与权重若凭记忆填写必然错，所以 M3 之前所有系数字段一律为"待核对"，评定引擎先按"无生效系数"跑通结构。
> 引用纪律：01 文档中不出现任何具体阈值/权重数字，一律写"以原文核对后入库"。
>
> **M3 轮结论（2026-10-07）**：换了官方渠道再查一次，仍然**取不到能定位条款号与表号的 JTG 5210-2018 原文**
> （官方页只有公告，标准平台正文靠脚本渲染，出版社与主编单位站点连不上，全文命中处全是文档分享站）。
> 于是 14 格规范来源系数**继续留 `pending`**，交付面评定路径仍不出数；唯一转生效的是**不依赖原文的用户自定容差格**（本表第 9 行）。
> 逐格映射与已查渠道清单见 `plan/04-扣分规则集与条款映射.md`；抓取缓存与 manifest（URL + HTTP 码 + 字节数 + sha1）留在 `.tmp_verify/M3/`，收尾不删。

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
- **评分四列现在仍一律是 `pending:coeff=<系数key>` 令牌**：M3 轮官方原文仍未取到，内置包 15 格里
  生效的只有"用户自定闭合差容差"那一格，评定路径必需的六格（两种路面合计 8 个 key）全为待核对，
  "未核对不出数"对真值同样成立。真值里凭记忆填一个 PCI 等于给基准装假答案。
  **生效格数 ≠ 评分列可出数**：`bench generate` 的说明行与 `data/raw/manifest.json` 的 `truth_note`
  都按"必需格是否全部生效"说话，不拿"生效系数 1 格"当成绩。
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
| 未核对不进评定路径 | `results.py` 拒算契约 + `pci.engine` 系数门 + `cli` 系数门 + `checks` 的 `undetermined` 档 | `tests/test_results_contract.py`、`test_length_closure_never_hard_judges_while_tolerance_pending`、`test_builtin_ruleset_blocks_every_object_with_numbers_all_empty` |
| 生效格数 ≠ 可出数（M3 部分解锁后新增） | `bench/generator.py::scoring_gate_pending_keys` + `manifest.coefficient_gate.truth_note` | `test_ruleset_builtin.py::test_blocked_cells_still_cover_the_assessment_path`、`test_m2_assess.py::test_pci_and_cement_fixtures_do_not_leak_into_shipped_paths` |
| 系数逐格二选一（verified+四件套 / pending+null）+ 官方渠道判据 + 生效格形状契约 | `ruleset/loader.py` schema 门 + `tests/test_ruleset_builtin.py::values_shape_problems` | `test_every_cell_is_verified_with_provenance_or_pending_without_numbers`、`test_only_user_defined_cells_are_verified`、`test_verified_cells_satisfy_the_shape_contract`、`test_shape_contract_rejects_bad_values`（8 个坏形状反例）、`test_provenance_gate_rejects_a_verified_cell_without_locator` |
| 容差生效后闭合差真的判（用户自定口径第 1 号） | `ledger/checks.py::check_length_closure` + `rulesets/*.json` 的 `tolerance.length_closure` | `test_length_closure_is_judged_under_the_registered_builtin_tolerance`、`test_run_all_checks_summary_after_tolerance_is_registered`（与上面那条 pending 版门互为双向证据） |
| 破损字典（类型×程度×量纲） | `ledger/models.py` 的 `DISTRESS_DICTIONARY`（口径见 `plan/03` §二） | `test_distress_dictionary_is_clean_in_frozen_data_but_catches_intruders` |
| 演示数据入仓形态 | `data/raw/*.csv` + `data/truth/*.truth.csv` + `data/raw/manifest.json` | `test_regeneration_of_committed_fixtures_is_byte_identical`、`test_manifest_digests_match_committed_fixtures` |
