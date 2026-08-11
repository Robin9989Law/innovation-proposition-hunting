---
name: innovation-proposition-hunting
description: >-
  Use when defining, auditing, revising, computing, or preparing to submit
  innovation propositions for dissertations or journal articles, especially
  when recent-literature coverage, dangerous near neighbors, theorem
  correctness, algorithm/protocol fidelity, evidence traceability, or research
  claim readiness must be adjudicated.
---

# 创新命题狩猎：Schema 3.0 强制协议

本技能用于把文献约束下的研究方向收敛成可证伪、可追溯、可审计的命题。它同时
审计两个正交问题：命题是否新（N 轴），以及准备声称的精确内容是否成立（V 轴）。
新颖性不能代偿正确性，实验通过不能代偿定理，格式完整不能代偿证据。

## 1. 规范词与资源路由

- **MUST / 必须**：缺失即停止。
- **MUST NOT / 不得**：禁止动作。
- **STOP**：保留已完成产物，记录唯一恢复动作；不得宣布 READY、LOCKED、CLOSED。
- **material change / 实质变更**：改变命题陈述、量词、前提、证明、协议、代码、
  测试、基线、证据解释或结论强度的变更。

冲突优先级：显式权威要求 > `workflow_state.json` > 本协议 > 资源文件 > 案例。

| 工作 | 必须完整读取 |
|---|---|
| 创建/迁移状态或任何模板产物 | [templates.md](templates.md) 对应节 |
| 判 V0–V4、G9、理论或算法责任 | [reference.md](reference.md) |
| 检索、全文、观点、证据级或重要性变化 | [evidence-pipeline.md](evidence-pipeline.md) |
| 获准计算、升级或停止 | [compute-funnel.md](compute-funnel.md) |
| 诊断已知反模式 | [case-lessons.md](case-lessons.md) |

详细字段只在 [templates.md](templates.md) 定义；本文件不复制模板字段。

### 1.1 术语词汇表（一词一义）

- **S0-SCREEN**：计算漏斗的文献链碰撞筛查阶段，只读现有工件、零数值输出；
  state `compute_stage` 枚举值仍为 `S0`（schema 兼容）。S1–S4 才是计算阶段。
- **BLOCKED（状态）**：`active_state=BLOCKED`，恢复后去 `resume_state`。
- **BLOCKED（退出码）**：校验器退出码 2，表示具体能力不可用
  （`capability.available=false` + 原因），不是失败也不是通过。
- **BLOCKED_CAPABILITY**：BLOCKED 退出码的条目形态；绝不能伪造 reviewer、
  thread 或 PASS 来绕过。
- **五种"锁"**：`scope_lock`（课题冻结文件）、`SYNTHESIS_LOCK`（search_mode，
  检索综合锁）、`DIRECTION_LOCK`（状态，只锁研究方向）、`FINAL_LOCK`（状态，
  最终锁定）、STOP 锁（`.workflow_stop.lock`，校验非零退出后落地，锁期间状态
  被推进即 INVALID）。五者互不可替代。
- **探索级证据**：`exploration_registry.json` 登记的永久探索产物；其数字不得
  进入任何冻结工件（`EXPLORATION_LEAK`），只能定性转述。

## 2. Schema 3.0 是唯一可执行合同

每个研究目录必须有 `workflow_state.json`，并满足：

```text
schema_version = 3.0
novelty_level ∈ {N0-1, N0-2, N0-3, N0-4C}
validity_level ∈ {V0, V1, V2, V3, V4}
claim_profile ∈ {THEORY, ALGORITHM, MIXED}
validation_epoch ∈ positive integers
```

原持久化的活动轨道、活动层级与最后完成状态三个字段不再持久化，由校验器从
状态与 decision_log 派生；state 里出现这些遗留字段即 `LEGACY_FIELD_REMOVED`。

缺少状态文件时，只能盘点和创建状态。`schema_version != 3.0` 时立即停止全部裁决、
审计和计算；先运行可恢复迁移：

```bash
# 2.0 项目
python3 <skill>/scripts/migrate_v2_to_v3.py \
  --root <研究目录> --state <研究目录>/workflow_state.json
# 1.0 项目先 migrate_v1_to_v2.py，再 migrate_v2_to_v3.py
python3 <skill>/scripts/migrate_v1_to_v2.py \
  --root <研究目录> --state <研究目录>/workflow_state.json
```

默认分别写出 `workflow_state.v2.json` / `workflow_state.v3.json`；确认后才可用
`--in-place`，该模式先保存带 UTC 时间戳的字节级旧版备份。v1 迁移必须把 validity
重置为 V0、清空 bundle/audit、关闭 `compute_authorized`，迁移后从 `CLAIM_FREEZE`
重建；v2→v3 迁移是机械映射（状态/门改名、删派生字段），原位保留进度与历史。
迁移输出存在不代表验证完成。

## 3. 双轴状态机

### 3.1 新颖性轴

先冻结成果合同和 scope，再按下列顺序执行（三段式：L1_SCOUT 段只动元数据，
L2_TRIAGE 段试读并选拔 K 集合，L3_EVIDENCE 段只对 K 集合跑全重机器）：

```text
BOOT → SCOPE_LOCK → PRIOR_CLAIM_DRAIN → RECENT_FRONTIER
→ LITERATURE_REGISTER → L1_FREEZE → L2_TRIAGE → LAYER_DECISION
→ K_FULLTEXT → K_CLAIM_REGISTER → SYNTHESIZE_COLLISION
→ OUTPUT_CLAIM_BIND → EVIDENCE_VALIDATE → N0_AUDIT
```

博士合同为 `THREE_ORGANIC_A_B_C`；期刊合同为 `ONE_MAIN_M`。L3 必须来自同一
连续研究链中的 `K → U → Δ`，并对齐 O/I/A/T/C/R/B。改变 L3、目标链、关键基线
或任一实质对齐项即开新碰撞轮次，并先耗尽 prior-round 观点。

**主线是 L1→L2→L3 的逐层构建；文献管线是辅线，证据深度按层供给。**
每个层级决策只取该层所需的证据深度，禁止提前做更深的取证
（`EVIDENCE_DEPTH_EXCEEDS_LAYER`，常驻 INVALID）：

| 当前层 | 本层裁决 | 需要的证据深度 | 默认预算（超出即 INVALID） |
|---|---|---|---|
| L1（研究工作） | 领域边界、连续簇、谁在做 | 文献元数据 + 摘要浏览；**零全文、零原子观点** | 全文 0、原子观点 0 |
| L2（可行创新域） | 近邻直接性、可创新域划分 | 重要性分级 + 摘要级观点（E1）；少量全文确认直接性 | 全文 ≤12、原子观点 0 |
| 贡献架构 | A/B/C 或 M 的划分与合同 | 同 L2；直接近邻全文 | 全文 ≤12、原子观点 0 |
| L3（具体命题） | K→U→Δ、碰撞、N0 裁决 | 全重机器：E2/E4 全文原子观点、碰撞综合、输出绑定，**只对 K 集合与必要反例运行** | 全文 ≤20、原子观点 ≤60 |

原子观点机器不是文献的读后感工厂：它只服务于"即将被裁决的命题候选集"。
L1/L2 阶段就批量下载全文、批量注册原子观点，等于在不知道问题是什么之前
先写答案的脚注——主次颠倒，且这些证据大多数在层级决策后作废。默认预算
可被课题规模证伪：确需超出时在 decision_log 逐条登记理由，而不是悄悄突破。

全局 `near_neighbor_registry.json` 仍须追加保留全部相关文献和 URL；它不等于本轮
深证据预算。复用历史注册表或开启新碰撞时，必须用
`current_evidence_scope.json` 明列本轮计费的全文 work ID 与原子 claim ID。预算只
统计该 scope；未提供 scope 时保持旧行为、统计全注册表，禁止借缺字段静默放宽。

| 等级 | 含义 | 动作 |
|---|---|---|
| `N0-1` | 正式出版近邻直接占据 | 关闭或吸收 |
| `N0-2` | 可由已知结果机械推出 | 关闭或降级 |
| `N0-3` | 非机械性、前沿或专属门未完 | HOLD；不得计算 |
| `N0-4C` | 前沿完整且候选通过路径、形式和非机械性门 | 进入有效性轴；仍未获计算权 |

预印本只能形成威胁并保持开放，不能单独产生终局 N0-1/N0-2。

### 3.2 有效性轴

```text
N0_AUDIT → CLAIM_FREEZE → VALIDITY_AUDIT → INDEPENDENT_REVIEW
→ DIRECTION_LOCK → COMPUTE → POSTCOMPUTE_CLAIM_FREEZE
→ FINAL_VALIDITY_AUDIT → FINAL_LOCK
```

| 等级 | 必须已完成 |
|---|---|
| `V0` | 进入 `CLAIM_FREEZE`；尚无有效性准备声明 |
| `V1` | 高风险 claim inventory 已冻结并选择 claim profile |
| `V2` | G9 form audit 已通过：理论责任和/或协议、代码、测试、基线责任全部可执行 |
| `V3` | 不同 agent 对当前 epoch 的精确 claim bundle 独立复核并 PASS |
| `V4` | 计算后新 epoch 的 claim bundle 由不同 agent 再复核并 PASS |

状态先决条件不可倒置：`CLAIM_FREEZE` 要求 N0-4C；`VALIDITY_AUDIT` 要求 V1；
`INDEPENDENT_REVIEW` 要求 V2；`DIRECTION_LOCK` 要求 N0-4C 与 V3。

gate 置真以 `decision_log` 中对应状态的完成记录（含本状态产物 SHA-256 登记）
为准，不得仅凭口头声明置真；跳过状态再补 gate 判自报置真。`novelty_level` /
`validity_level` 必须与对应 gate 和登记互证，不得手填 N0-4C。

## 4. 强制 claim inventory 与 form router

扫描所有声明的 Markdown/TeX 稿件源。任何 exact、universal、bounded、guaranteed、
necessary、sufficient、online、first/首次、strong/fair/matched-budget，以及定理、
引理、推论等高风险出现，必须恰好绑定到一个 inventory claim。允许的 `claim_type`
枚举、稳定 occurrence ID 算法和完整 JSON 见 [templates.md](templates.md)。

冻结 `claim_profile` 后按表路由；不得因某类产物难做而改 profile：

| profile | V2 前必须通过 |
|---|---|
| `THEORY` | claim inventory + theory obligation registry + 四类必需见证 |
| `ALGORITHM` | claim inventory + protocol contract + claim-code trace + baseline budget（存在 ALGORITHM 类 claim 即必须，无触发词门控） |
| `MIXED` | THEORY 与 ALGORITHM 的并集，逐条 claim 路由 |

理论命题必须登记 exact statement、量词、前提、proof locator，并运行
`MINIMAL_POSITIVE`、`NONZERO_NUISANCE`、`BOUNDARY_OR_LIMIT`、
`PREMISE_REMOVAL`。后者必须预期失败、实际失败且进程非零。见证必须有咬合力
（`WITNESS_NO_BITE`）：`PREMISE_REMOVAL` 附 `mechanism` 机制解释（禁构造性
恒真表述），`NONZERO_NUISANCE` 附 `sensitivity_control` 对照取值；命题的每条
`subclaims` 子规律须被见证的 `addresses_subclaim` 认领
（`SUBCLAIM_WITNESS_GAP`）。随机性质测试只能执行，或走两阶段豁免：V2 作者
提出（`proposed_by_author` + 数学理由）后保持未闭合，V3 独立 reviewer 追认
方算闭合（`RANDOM_PROPERTY_EXEMPTION_PENDING`）。

算法命题必须把稿件位置和伪代码符号绑定到当前实现符号、实现哈希、可执行测试及
PASS 输出。在线主张必须冻结 prediction/update unit、顺序、标签可得性、数据角色和
访问次数；逐样本主张必须有当前 chronology test。强/公平/同预算比较必须使用共同
调参、种子、标签、更新频率、算力、停止规则和宽度/参数预算合同。

所有可执行测试必须静态声明 `TARGET_CLAIM_IDS` 并实际导入被绑定实现的符号；
禁止不触碰实现、直接断言硬编码值并写 PASS 的自证式测试。

## 5. G9 与不同 agent 硬门

G9 不是一张自评勾选表，而是 V2–V4 的绑定审计组：

1. `theory audit` 检查 exact statement、量词/前提、proof locator 和见证；
2. `protocol audit` 检查声称的评测时间线、标签和公平预算；
3. `code audit` 检查伪代码、运行时实现、可达符号、可执行测试和输出证据。

V3/V4 必须由不同 agent 完成。`reviewer_agent_id` 不得出现在
`author_agent_ids`；还必须记录 `reviewer_thread_id`、PASS verdict、相同
`validation_epoch` 和相同 `audited_bundle_sha256`。自审、缺 reviewer provenance、
或只审自然语言摘要均为 INVALID。若独立 reviewer 能力明确不可用，记录
`capability_available=false` 并返回 `BLOCKED_CAPABILITY`；不得把能力缺失伪装成
PASS，也不得因此跳过对已经存在产物的矛盾检查。

## 6. 哈希、epoch 与失效

`audit_manifest.json` 必须列出当前 profile 的全部实质 claim-bearing 产物及 SHA-256。
bundle hash 是按 path 排序后的 `{path, role, sha256}` 规范 JSON 的 SHA-256。state、
manifest 和 independent audit 必须指向同一 epoch 与 bundle。

审计后发生任何 material change 时，旧 V3/V4 立即失效：

```text
停止 COMPUTE / FINAL_LOCK
→ validation_epoch += 1
→ validity_level = V0
→ claim_bundle_sha256 = ""
→ independent_audit = {}
→ compute_authorized = false
→ 从 CLAIM_FREEZE 重建 inventory、form artifacts、manifest 与独立复核
```

只改错字、locator 或声明不变的元数据，也必须重新计算涉及文件哈希；如果它在
bundle 内，旧 audit 仍会因哈希变化失效。不得手工把旧 hash 复制到新文件。

## 7. 前沿与证据不可降级

近邻覆盖必须包含方法同义词、目标任务、理论术语、算法结构、作者续作、后向引用、
前向引用，并有至少两种独立 route type。作者续作轴的每条边必须给出真实
`shared_authors` 交集（空交集或字符串条目报 `HOLLOW_COVERAGE_AXIS`）；引用链
不是作者续作，放 `method_lineage` 轴。缺轴为 INVALID；仅当具体能力被声明为
`available=false` 且给出原因时才可 BLOCKED。

文献 `importance_history` 是追加式历史；current importance 必须等于末事件。任何
CRITICAL/IMPORTANT → CONTEXT 的降级都要有全文 E2/E4、独立 reviewer/thread 和
被审 artifact hash 的 reclassification。`DOWNLOAD_BLOCKED` 绝不能成为降级理由。
E2 必须来自 full article，E4 必须到 proof/appendix 或有覆盖证明机器的 locator。
完整数据合同见 [evidence-pipeline.md](evidence-pipeline.md)。

## 8. 计算与最终锁公式

以下公式是硬门，不是建议：

```text
COMPUTE = N0-4C AND V3 AND compute_authorized
FINAL_LOCK = N0-4C AND V4 AND current independent audit
```

用户授权只是 `compute_authorized=true` 的必要条件，**不构成硬门旁路**：N0-4C
与 V3 仍必须先满足，"用户指定/导师要求"不能替代其中任何一项。COMPUTE 门
之前禁止任何产生数值输出的实验，包括自称"探索""可行性检验""预实验"的计算；
探索性数据分析必须按 [compute-funnel.md](compute-funnel.md) 登记为永久探索级
证据，其数值不得进入任何碰撞、审计或冻结工件。

`DIRECTION_LOCK` 只锁方向。计算按 S0-SCREEN–S4 逐级升级；只有 S4 完成且 state 中的
`compute_evidence` 指向当前 epoch、当前哈希的计算证据，才能进入
`POSTCOMPUTE_CLAIM_FREEZE`。计算结果改变主张、强度或适用边界时必须新开 epoch；
随后完成 `FINAL_VALIDITY_AUDIT`，由不同 agent 对新 bundle 复核，才可 `FINAL_LOCK`。

## 9. 校验器与四个退出码

每次续跑、证据更新、裁决、计算前后都运行：

```bash
python3 <skill>/scripts/validate_all.py \
  --root <研究目录> --state <研究目录>/workflow_state.json
```

统一退出语义：

```text
READY = 0
INVALID = 1
BLOCKED = 2        # 对外状态常显示 BLOCKED_CAPABILITY
MIGRATION_REQUIRED = 3
```

优先级为 MIGRATION > INVALID > BLOCKED > READY。任一非零退出都 STOP；不得 PASS、
LOCKED、CLOSED、启动新碰撞或计算。BLOCKED 时仍验证所有已有产物；不得因后续门
不可执行而打印虚假 READY。

非零退出时 `validate_all.py` 会在研究目录写入 `.workflow_stop.lock`：此后状态
未变的运行直接以锁内退出码拦截，锁期间推进状态判
`STATE_ADVANCED_UNDER_STOP_LOCK`。唯一解锁路径是完成唯一恢复动作后以
`--clear-lock --recovery-note "<动作>"` 复跑（留痕于 validation.log）；修复后
复跑 READY 会自动清锁。新增检查默认以 WARNING 输出、不改变退出码，
`--strict-new-checks` 将其升为 INVALID；评审与交接一律以 strict 模式结果为准。

BLOCKED 期间仅允许三件事：验证所有已有产物、记录唯一恢复动作、登记用户直接
提供的解阻材料。禁止撰写新综合、禁止任何计算、禁止新增冻结工件。

## 10. 每次交接

交接必须从机器状态和刚运行的验证结果生成，至少报告：成果合同、active track/state、
N level、V level、claim profile、validation epoch、bundle hash、frontier/全文/观点计数、
独立 reviewer provenance、四退出码中的最终值、blocked reasons 和唯一
`next_required_action`。避免“基本完成”“大致有效”等非状态词。标准动作：
`iph handover`（从机器状态自动生成交接报告）；本清单是唯一权威版本，其他文档
引用本节，不复制。

> 核心纪律：先证明候选达到 N0-4C，再冻结准备声称的 exact claim；用 form-sensitive
> audit 证明它可被反驳和复现，用不同 agent 审精确 bundle；只有 V3 才能计算，计算
> 后必须新 epoch 达 V4，才允许最终锁定。

## 11. 规则注册表（RULE-ID）

每条规范句只在一处定义（权威节），本表是唯一索引；资源文件与 tutorial 引用
RULE-ID，不复制规则文本。新检查码默认 WARNING、`--strict-new-checks` 升
INVALID（§9）。

| RULE-ID | 规则 | 权威节 |
|---|---|---|
| R-AUTH-01 | 用户授权只是 `compute_authorized` 的必要条件，不构成硬门旁路：N0-4C 与 V3 仍须先满足 | §8 |
| R-COMPUTE-02 | COMPUTE 门前禁止任何数值输出实验；S0-SCREEN 数值预实验必须当天登记 `exploration_registry.json`，其数字不得进入冻结工件（`UNREGISTERED_COMPUTE_ARTIFACT` / `EXPLORATION_LEAK`） | §8、compute-funnel §2、templates §12 |
| R-BLOCKED-03 | BLOCKED 期间仅允许：验证已有产物、记录唯一恢复动作、登记用户直接提供的解阻材料 | §9 |
| R-LOG-04 | 每次状态完成必须追加 decision_log 条目（真实 UTC 时间、单调、gate 置真有对应条目）；标准动作是 `iph advance`，禁止手工回填 | §2、templates §1 |
| R-SEARCH-05 | `search_mode` 三态：`SEARCH_OPEN` → `SYNTHESIS_LOCK`（100 篇自动综合锁）→ `EXCEPTION_REOPEN`（例外重开须登记） | templates §1、reference §5.1 |
| R-SELFTEST-06 | 禁自证：测试必须静态声明 `TARGET_CLAIM_IDS` 且 AST 可证 import 被绑定实现；只断言自身硬编码期望的脚本不计入证据（`SELF_ATTESTING_TEST`） | §4、templates §6 |
| R-EMPIRICAL-07 | empirical 不得升格为 theorem：实证结果不能改写成全称命题，命题强度以实际支持的最弱形式重建 epoch | §6、compute-funnel §2 |
| R-PERSIST-08 | 先落盘再升级：每次阶段/状态升级先保存产物与哈希，再改 `compute_stage`/`active_state`（`iph advance` 内置此顺序） | compute-funnel §1、§2 |
| R-KEY-09 | API key 卫生：密钥只进环境变量或本地未跟踪配置，绝不写进任何 tracked 工件、decision_log 或交接报告 | evidence-pipeline、reference §5.0 |
| R-WITNESS-10 | 见证咬合力：PREMISE_REMOVAL 附非恒真 `mechanism`、NONZERO_NUISANCE 附 `sensitivity_control`、子规律须 `addresses_subclaim` 认领；RANDOM_PROPERTY 豁免两阶段闭合 | §4、templates §3 |
| R-FRONTIER-11 | 前沿七轴缺一不可；作者续作边须真实 `shared_authors`（`HOLLOW_COVERAGE_AXIS`），引用链放 `method_lineage` | §7、templates §7 |
| R-BASELINE-12 | ALGORITHM 类 claim 存在即必须有 baseline_budget；comparator.claim_ids 与 algorithm claims 求交，无触发词门控 | §4、templates §5 |
| R-LAYER-13 | 主线是 L1→L2→L3 逐层构建，证据深度按层供给；全局注册表保留历史，本轮预算由 `current_evidence_scope.json` 计费；原子观点机器只服务 L3 候选集（K 集合），超层取证报 `EVIDENCE_DEPTH_EXCEEDS_LAYER` | §3.1 |
| R-SKILL-14 | 项目 agent 修改技能仓库后必须提交、测试全绿、文档同步且风格一致；留未提交半成品或红测试即流程违规 | §12 |

## 12. 修改技能仓库的自律规则

项目 agent 在实战中允许修改本技能仓库（修 bug、补检查、加迁移助手），但修改
按技能自身的工程纪律执行（2026-08 三项目实战复盘的教训：某 agent 留下未提交
的功能半成品与风格不一的英文 docstring，靠人工评审兜底才收敛）：

- **不留未提交改动**：修改完成后必须 commit 并推送（或明确移交用户处理）；
  工作区残留半成品即流程违规，下一个续跑者不得在此基础上继续。
- **测试全绿是提交门槛**：`python3 -m pytest tests/ -q` 全过才可提交；红测试
  不得进入 main。
- **文档同步同 commit**：行为变更必须在同一提交内更新 SKILL.md、templates.md
  及相关资源文件；实现、测试、文档不齐视为未完成。
- **风格跟随所在文件**：docstring、注释、段落的语言与格式跟既有内容一致
  （本仓库正文为中文），不引入新风格。
- **动机留痕**：commit message 写明是哪个项目实战暴露的问题、修复策略与
  已知残余风险，便于后续审计。
