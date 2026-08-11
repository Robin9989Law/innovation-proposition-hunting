# 技能优化方案 v2（整合版）：整体评审 + 事故修复

> **状态：已实施（2026-08，分支 `refactor/2026-08-skill-overhaul`）。**
> 第 0-5 期全部落地：状态完整性核心、iph CLI + ProjectContext（校验提速 83%）、
> 探索防火墙（EXPLORATION_LEAK/UNREGISTERED_COMPUTE_ARTIFACT）、见证咬合力
> （WITNESS_NO_BITE/SUBCLAIM_WITNESS_GAP/两阶段豁免）、自证检测
> （SELF_ATTESTING_TEST）、基线去门控（validate_baseline_budget.py）、前沿轴
> 实名（HOLLOW_COVERAGE_AXIS/method_lineage）、文档体系重构（RULE-ID 注册表、
> 术语词汇表、templates 全枚举、scope_lock 迁入、死引用清零）。
> 回归 fixture：`tests/fixtures/incident-2026-08/`。

版本：v2（2026-08-11，取代 v1 草案）
依据：
- 事故审计：`/Users/robinlaw/Downloads/算电协同`（DeepSeek V4 Flash agent，停于 VALIDITY_AUDIT/V1/MIXED）
- 整体评审：本技能全部 8 份文档（~158KB）、14 个校验脚本（~250KB）、tests/（~280KB）

---

## 第一部分：整体评审结论

### 1. 设计骨架是 sound 的，不要推翻

- 双轴状态机（N 轴/V 轴）+ 四退出码优先级（MIGRATION>INVALID>BLOCKED>READY）+ epoch 失效机制，逻辑自洽；退出码优先级有测试锁定，未发现崩溃产生 exit 0 的路径。
- **哈希溯源是全系统最可靠的防线**，并在真实事故中验证有效：`validate_claim_inventory.py` 的 occurrence 哈希当场抓住了冻结后对 manuscript.md 的篡改。
- `validation_common.py` 的 fd-based O_NOFOLLOW 读取、strict JSON、Issue/ExitCode/render 契约是高质量基建；`migrate_v1_to_v2.py` 的原子发布是全套里工程质量最高的部分。
- 证据链（E1–E4 分级、DOWNLOAD_BLOCKED 不降级、SHA-256 归档）在事故项目中执行最好。

### 2. 系统性病根（评审新发现，按严重度）

**A 类：自报字段无核验（与事故同根，但比事故清单更广）**

| # | 问题 | 证据 |
|---|---|---|
| A1 | `novelty_level="N0-4C"` 是纯自报字符串：CLAIM_FREEZE/DIRECTION_LOCK/COMPUTE/FINAL_LOCK 四个硬门全查它，但它与 `n0_4_locked` 门、novelty-audit 工件哈希零交叉检查——直接写 N0-4C 即可跳过整个新颖性轴 | `validate_workflow_state.py:461,480,493,540` vs `:443,158` |
| A2 | `evidence_validated` 绑定的 4 个工件全是**前序状态**产物，状态从未运行也判真（事故 F3 机器根因） | `validate_workflow_state.py:149-154` |
| A3 | decision_log 只查 `not_list`：无条目 schema、无时间完整性、与 gates 零交叉（事故 F3） | `validate_workflow_state.py:616-618`；`templates.md:69` 只有空数组 |
| A4 | gates 与产物存在性互不校验：gate 校验器不查文件内容，产物校验器不回看 gates | gates 仅 `validate_all.py:297,300,514,520` 与 `validate_workflow_state.py:425` 读取 |
| A5 | 纯仪式字段可静默说谎：`last_completed_state`、`active_track`（可与 active_state 矛盾）、`validation.log`（仅存在性）、`updated_at` | `validate_workflow_state.py:301-302,354`；`validate_schema_v2.py:157` |
| A6 | `COMPLETE` 终态硬门缺失：先决条件仅 `(scope_locked, evidence_validated)`，无 N/V 等级检查 | `validate_workflow_state.py:140`，`:461-562` 无 COMPLETE 分支 |

**B 类：计算与探索无边界（事故 F1/F2）**

| # | 问题 | 证据 |
|---|---|---|
| B1 | 计算门只拦 `compute_stage` 字段推进，拦不住"stage 不动、实验照跑" | `validate_workflow_state.py:587-592` |
| B2 | 无探索登记通道，无探索产物与冻结工件的防火墙 | 事故：`collision-round1.md:29,36,63`、`novelty-audit.md:12-15` 全含未授权实验数字 |
| B3 | "用户授权非旁路"只在 `docs/tutorial.md:711,1114`，SKILL.md 正文没有；且 tutorial §14 的计算启动清单用的是**已废止的 `n0_4_locked` 镜像门、完全不含 V3/N0-4C**，与硬公式直接矛盾 | `docs/tutorial.md:1102-1112` vs `SKILL.md:185`、`compute-funnel.md:17,23` |

**C 类：见证与算法责任可被形式合规掏空（事故 F4 + 评审新洞）**

| # | 问题 | 证据 |
|---|---|---|
| C1 | 见证只验存在与形式，不验咬合力：PREMISE_REMOVAL 可构造性恒真、NONZERO_NUISANCE 可不改变观测量、protocol 测试可不导入实现直接写 PASS | 事故 `checks/check_premise_removal.py`、`theory_witnesses/*.txt`、`checks/check_scheduling_protocol.py` |
| C2 | `baseline_budget.json` 内容基本不验证：comparator 字段检查被 `if trigger_claims:` 门控，`comparator.claim_ids` 从不与 algorithm_claims 求交（孤儿 ID 静默通过） | `validate_protocol_contract.py:1765-1777,1753-1764` |
| C3 | audit_manifest 的 role 只验格式，不验 profile 必需集合（THEORY 缺 MANUSCRIPT 项可过） | `validate_artifact_hashes.py:135-148`；必需集合只在 `tests/helpers.py:123-141` 出现 |
| C4 | RANDOM_PROPERTY 豁免逻辑死锁：豁免需"当前独立 reviewer"接受，但 reviewer 只在 V3 存在、见证却在 V2 闭合——何时能合法豁免无任何文档说明 | `SKILL.md:125`、`templates.md:199`、`validate_theory_obligations.py:277-341` |

**D 类：前沿覆盖轴可空心**

| # | 问题 | 证据 |
|---|---|---|
| D1 | 覆盖轴只查"非空字符串列表"，不查内容真实性（事故中 author_continuations 用引用链冒充作者续作） | `validate_frontier_integrity.py:355-377` |
| D2 | `route_type` 无枚举约束；文献 `authors` 字段无规范化校验（`[123]` 可过），而 audit 侧有完整规范化——同一概念两套标准 | `validate_frontier_integrity.py:386-425`；`validate_evidence_chain.py:65-70,168` vs `validate_schema_v2.py:98-139` |

**E 类：校验器代码债（效率与健壮性）**

| # | 问题 | 证据 |
|---|---|---|
| E1 | 两代验证器并存：`validate_evidence_chain.py` 与 `validate_literature_registry.py` 完全绕开 validation_common——自造错误格式、0/1 裸退出码（无 BLOCKED/MIGRATION 语义）、**main 无异常兜底**（malformed JSON 崩 traceback，退出码恰好也是 1，与正常 INVALID 不可区分）、符号链接防护缺失；且这两个恰好**零专项测试** | `validate_evidence_chain.py:80-100,390-401`；`validate_literature_registry.py:98-110,194-220,352` |
| E2 | 路径多源真相（至少 6 处定义）：`validate_all.py` 硬编码 12 个默认路径，**完全不读 state 的 artifacts dict**；除 `validate_workflow_state.py:594-614` 查存在性外没有任何子校验器消费 artifacts dict——改文件名则存在性检查与内容检查各查各的 | `validate_all.py:126-180`；`templates.md:56-68`；各校验器内部默认值 |
| E3 | 重复解析：一次 validate_all 完整运行 = workflow_state ×10 进程各解析一遍、claim_inventory ×4、230KB 观点注册表 ×2-4、manuscript 按 binding 重复全读+重 hash、同一测试文件按 binding 重复 AST | `validate_claim_code_trace.py:217,493-500`；`validate_literature_registry.py:271-272`（同进程解析两遍） |
| E4 | `validate_protocol_contract.py` 74KB/1942 行巨石：约 830 行 Python AST 分析器（43%）被 `validate_claim_code_trace.py:28-33` 跨文件 import，职责边界名存实亡；`--baseline-only` 分支复制主分支逻辑 | `validate_protocol_contract.py:164-995,1889-1906` |
| E5 | 退出码 2 语义裂缝：argparse 错误/模块缺失等校验器自身故障也 exit 2，被 `issue_for_exit` 一律映射为 BLOCKED 严重级——agent 会去"等外部解阻"而不是修校验器，且 BLOCKED 优先级低、故障信号被淹没 | `validate_all.py:82-95` |
| E6 | SKIP 逻辑误报："任一证据文件存在 ⇒ 三个全必需"——LITERATURE_REGISTER 等合法中间态必报 INVALID，要么逼 agent 造空壳文件，要么**训练 agent 习惯"INVALID 也可以继续"**（与事故中 INVALID 下继续跑见证直接相关） | `validate_all.py:517-522,555-562` |
| E7 | 错误码漂移（同一 epoch 不匹配三种码）、audit 身份逻辑两处实现且条件分叉、JSON 加载 strict/普通三种并存、include_data 无大小上限、literature_registry 全树 rglob 无深度限制 | `validate_protocol_contract.py:1053-1061` vs `validate_theory_obligations.py:126-134`；`validate_schema_v2.py:76-97` vs `validate_audit_provenance.py:39-48` |

**F 类：文档体系债（弱模型合规的直接障碍）**

| # | 问题 | 证据 |
|---|---|---|
| F1 | 规范规则散落且无单一事实源：用户授权非旁路（仅 tutorial）、BLOCKED 状态白名单（无定义）、decision_log 条目 schema（全库不存在）、search_mode 枚举（仅校验器源码）、禁自证测试（仅 `templates.md:303-304`）、empirical-to-theorem 禁令（仅在自称"非规范"的 `case-lessons.md:424-437`） | 见各行号 |
| F2 | 文档间矛盾：计算门两套公式（B3）；N0-4 vs N0-4C 双名（tutorial 9 处旧名）；幻影等级 `N0-3C`（`case-lessons.md:97`）；交接字段清单三个版本（`SKILL.md:218-221` vs `templates.md:417-431` vs `docs/tutorial.md:1310-1324`） | 见各行号 |
| F3 | 术语多义："S0"三义（漏斗文献碰撞 / `reference.md:583` 旧入口卡 / 事故中自称的探索；更糟的是 reference.md 三个大节标题挂旧编号 S2/S3/S4 与漏斗 S2/S3/S4 **同名不同物**）；"BLOCKED"四义；"锁/冻结"五义；"探索"无定义成了免罪符 | `compute-funnel.md:48`；`reference.md:97,148,262,583` |
| F4 | 弱 agent 阅读负载失真：路由表未把 N0 裁决/上钻指向 reference.md；tutorial 推荐顺序实际要读 ~127KB——弱模型要么吞 150KB 要么跳过（事故 agent 走了后者）；10 句最关键的规范句埋在散文/案例中 | `SKILL.md:27-33`；`docs/tutorial.md:1403-1413` |
| F5 | 死引用与残留污染：`templates.md:389` 引用不存在的"Task 8"；tutorial 引用 templates.md 中不存在的 Scope Lock 模板（实际在 `reference.md:131-142`）；`.worktrees/` 保留两份**过期完整副本**（仍写"N0-4 后且获授权"）可被 agent grep 命中；`docs/superpowers/` 五份设计档案无"已实施/归档"标注；`SKILL.md:35"详细字段只在 templates.md"` 名不副实（半数枚举不在） | 见各行号 |

---

## 第二部分：整合优化方案

v1 的 P1–P8 与上述 A–F 高度同根，合并为六个工作流（W1–W6）。映射：P1→W1，P2→W1，P3→W2，P4→W1，P5→W3，P6→W4，P7→W2，P8→W6。

### W1. 状态完整性核心（修 A1–A6、B1 部分、E6；含 v1 P1/P2/P4）

目标：消灭"自报即通过"，让每个状态推进都有可哈希、可交叉时间的登记。

- **W1.1 decision_log 条目 schema**（templates.md §1 新增）：`{at, state, action, artifacts: [{path, sha256}], git_commit?: string}`。SKILL.md §3 增加"gate 置真以登记哈希为准，不以口头声明为准"。
- **W1.2 gate↔状态完成记录绑定**（validate_workflow_state.py）：每个置真 gate 要求 decision_log 存在对应该状态的条目，且其 artifacts 逐项存在、SHA-256 与当前一致；`evidence_validated` 等 GATE_ARTIFACTS 改为消费条目内声明的本状态工件。
- **W1.3 level 派生化**：`novelty_level=N0-4C` 必须有 `n0_4_locked=true` + novelty-audit 工件哈希登记，否则 INVALID：`SELF_DECLARED_LEVEL`；validity_level 同理与 V1–V4 前置产物绑定。长期方向：level 由 gates+哈希派生、禁止手填（第一期先做交叉检查，不动 schema）。
- **W1.4 时间完整性**：条目 `at` 单调不减、不得晚于 state 文件 mtime+5min（`FUTURE_DECISION_TIMESTAMP`）；`updated_at` ≥ 末条目且 ≤ 当前；可选 `--git-crosscheck` 模式对声称已提交的条目核 git commit 时间。
- **W1.5 STOP 锁**（validate_all.py）：非零退出写 `.workflow_stop.lock`；锁存在时任何运行直接以锁内退出码退出，`--clear-lock --recovery-note` 解锁并留痕；锁期间 state 推进报 `STATE_ADVANCED_UNDER_STOP_LOCK`。SKILL.md §9 同步。
- **W1.6 COMPLETE 硬门**：COMPLETE 要求 FINAL_LOCK 等价条件（N0-4C + V4 + 当前独立 audit）。
- **W1.7 仪式字段处置**：`active_track` 与 active_state 加一致性检查；`last_completed_state` 加单调性检查或与 decision_log 末条交叉；validation.log 从"存在性"升级为"末行时间戳 ≥ 末次状态推进"。
- **W1.8 修 SKIP 误报**（validate_all.py）：evidence 分发改为按状态精确声明所需文件集合，消灭中间态假 INVALID。

验收：算电协同项目 workflow_state.json 作回归 fixture 必报 FUTURE_DECISION_TIMESTAMP 与 SELF_DECLARED_LEVEL；gate=true 无登记条目的合成 fixture 必报 INVALID；锁行为三态测试（生成/拦截/解锁）。

### W2. 计算防火墙与探索通道（修 B1–B3；含 v1 P3/P7）

- **W2.1 规范文本上提**（SKILL.md §1/§8）："用户授权仅是 `compute_authorized` 的必要条件，不构成 COMPUTE 硬门旁路"；"COMPUTE 门之前禁止任何产生数值输出的实验，包括自称探索/可行性检验的"；探索须登记。compute-funnel.md：S0 改名 **S0-SCREEN** 并注明"不产生数值输出"；阶段升级先落盘再改 state 写入 SKILL.md。
- **W2.2 `exploration_registry.json`**（templates.md 新增 §12）：登记即承认数据永久探索级；validate_workflow_state 在 `compute_authorized=false` 时核验登记哈希，并扫描常见计算输出位置发现未登记产物 → `UNREGISTERED_COMPUTE_ARTIFACT`。
- **W2.3 新脚本 `validate_exploration_firewall.py`**：登记产物的显著数字 token 不得出现在冻结工件集合中，命中 → `EXPLORATION_LEAK:<token>:<file>:<line>`。
- **W2.4 BLOCKED 白名单**（SKILL.md §9）：仅允许验证已有产物、记录恢复动作、登记用户解阻材料；与 W1.5 锁联动。

验收：未登记产物 INVALID；登记产物数字泄漏进 collision/manuscript fixture 必报 EXPLORATION_LEAK。

### W3. 见证与算法责任咬合力（修 C1–C4；含 v1 P5）

- **W3.1 三条硬规则**（SKILL.md §4 + reference.md）：PREMISE_REMOVAL 禁构造性恒真（registry 填 `mechanism`）；NONZERO_NUISANCE 须先证 `sensitivity_control`（扰动确实改变观测量）；测试禁自证（静态 `TARGET_CLAIM_IDS` + 实际 import 绑定实现符号）。
- **W3.2 校验器落地**：validate_theory_obligations 加 `WITNESS_NO_BITE`、`SUBCLAIM_WITNESS_GAP`（每条子规律至少一个见证）；validate_protocol_contract/claim_code_trace 加 `SELF_ATTESTING_TEST` 静态检查。
- **W3.3 拆出 `validate_baseline_budget.py`**：comparator 字段校验去掉 trigger 门控，`claim_ids` 与 algorithm_claims 求交，孤儿 ID 报 INVALID。
- **W3.4 audit_manifest role 集合校验**（validate_artifact_hashes.py）：按 profile 验必需 role 集合。
- **W3.5 解 RANDOM_PROPERTY 死锁**（C4）：明确"V2 由作者侧执行 RANDOM_PROPERTY；NOT_APPLICABLE 豁免可由作者提出、V3 独立 reviewer 追认，追认前视为未闭合"，写入 SKILL.md §4 与 templates.md，校验器同步放宽为"待追认"中间态。

验收：以算电协同 `checks/` 目录为负例 fixture，三条咬合力检查全部触发；空心 baseline comparator fixture 报 INVALID。

### W4. 前沿轴与证据校验器健壮化（修 D1–D2、E1、E7 部分；含 v1 P6）

- **W4.1 author_continuations 实名核验**：每条边填 `shared_authors`（两文献作者真实交集），空交集 → `HOLLOW_COVERAGE_AXIS`；引用/主题链另立 `method_lineage` 轴。evidence-pipeline.md 同步。
- **W4.2 统一作者规范化**：文献 authors 的类型/trim/去重校验收敛进 validation_common，evidence_chain 与 schema_v2 共用。
- **W4.3 evidence_chain + literature_registry 迁移到 validation_common**：strict JSON、Issue/render/choose_exit、main 包 VALIDATOR_ERROR 兜底、O_NOFOLLOW 读取；消灭 literature_registry 同进程二次解析。
- **W4.4 补测试**：validate_evidence_chain 专项测试文件（当前零覆盖）；literature_registry 内容规则用例。

验收：两个 legacy 校验器对 malformed JSON 输出 VALIDATOR_ERROR 而非 traceback；测试套件新增 ≥20 例。

### W5. 文档体系重构（修 F1–F5、B3 文本侧、E2 文档侧）

- **W5.1 规范规则注册表**：在 SKILL.md 尾部（或独立 rules.md）建立 RULE-ID 清单——每条规范句一处定义、全局引用；把 F1 列出的散落规则全部上提。K→U→Δ、上钻六问、N0 等级表等 4–5 份拷贝改为引用。
- **W5.2 tutorial 对齐重写**：N0-4→N0-4C 全局替换；§14 计算启动清单换成硬公式 `N0-4C AND V3 AND compute_authorized`；删除幻影等级；交接清单三处合一。
- **W5.3 templates.md 补全**：search_mode/snapshot_mode/output_type/active_state 全枚举、decision_log 条目 schema、scope_lock 模板（从 reference.md 迁入）、occurrence 算法补 casefold 细节；修"Task 8"死引用。让 `SKILL.md:35"详细字段只在 templates.md"` 名副其实。
- **W5.4 术语词汇表**：S0-SCREEN / BLOCKED(state) / BLOCKED(exit) / BLOCKED_CAPABILITY / SYNTHESIS_LOCK / FROZEN 等一词一义表，进 SKILL.md §1。
- **W5.5 清理残留**：删除或归档 `.worktrees/`；docs/superpowers/ 五份档案加"已实施归档"头并移入 docs/archive/；README 导航补 optimization-plan 与 archive；路由表补 N0 裁决→reference.md。
- **W5.6 权威优先级两条链合一**（SKILL.md:25 vs reference.md:611-617）。

验收：弱模型每阶段必读压到 SKILL.md + 单个资源文件；grep 全库不再命中 N0-4（不带 C）与 N0-3C。

### W6. 代码结构长期项（修 E3–E5；不阻塞前五项）

- **W6.1 拆 validate_protocol_contract.py**：AST 分析器独立为 `python_test_contract.py`（自测自带）；协议矩阵/chronology/baseline 三分。
- **W6.2 ProjectContext**（validation_common）：一次解析 state+各注册表，子校验器共享；消除 10× state、4× registry、n× manuscript/AST 重复解析；include_data 加大小上限。
- **W6.3 退出码 2 语义**：带 traceback/argparse 特征的 2 升 INVALID（VALIDATOR_ERROR），不再误标 BLOCKED。
- **W6.4 错误码注册表**：epoch 类错误统一为单一码；audit 身份校验收敛为 common 单函数。

### W7. 测试与灰度策略

- 每个 W 至少一个负例 fixture + 正例回归；**算电协同项目（脱敏副本）作为 F1–F4 综合负例**，必报对应新错误码。
- 新检查统一先 WARNING 一个周期再升 INVALID（validation_common 的 severity 扩一档），`validate_all.py --strict-new-checks` 控制。
- schema_version 保持 2.0，新 state 字段全部可选带默认。

## 第三部分：实施顺序（五期）

| 期 | 内容 | 理由 |
|---|---|---|
| 一 | W1 全部 + W5.1 中事故直接相关的 5 条规则上提 + E5 | 堵"伪造/跳过/INVALID 下继续"整类失守；改动集中在两个校验器文件 |
| 二 | W2 全部 | 计算防火墙；涉及新脚本与新模板节 |
| 三 | W3 全部 | 见证咬合力；C4 死锁是 spec bug 须同期修 |
| 四 | W4 + W5 剩余 | 前沿轴、legacy 校验器迁移、文档重构与清理 |
| 五 | W6 | 长期代码健康，不影响规则语义 |

每期完成标志：tests/ 全绿 + 算电协同负例跑出对应 INVALID + 干净合成 fixture 跑出 READY + 对应 SKILL.md/templates.md 文本已同步（规则与校验器成对交付）。

## 第四部分：明确不做

- 不动双轴状态机、N/V 等级语义、G9 不同-agent 硬门、E1–E4 分级本身——评审确认设计正确，失守在执行层。
- 不解决单 agent 环境下"独立 reviewer 必须是不同 agent"的能力问题（BLOCKED_CAPABILITY 通道已覆盖）。
- 第一期不动 schema_version、不删任何现有字段（仪式字段先加交叉检查，删除留到 schema 3.0 再议）。
