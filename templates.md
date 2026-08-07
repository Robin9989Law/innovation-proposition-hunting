# 卡片与清单模板

执行本 skill 时，优先用下列模板落盘；文件名可按微领域调整。

---

## workflow_state.json（每个主题必须先创建）

此文件是机器执行权威。`hierarchy_status.md` 只能做它的人类可读镜像。状态改变时
先保存对应产物，再更新 gate，最后更新 `active_state`。

```json
{
  "schema_version": "1.0",
  "workflow_id": "<stable-topic-id>",
  "updated_at": "2026-08-07T00:00:00+08:00",
  "current_year": 2026,
  "recent_window": {
    "start_year": 2024,
    "end_year": 2026,
    "status": "INCOMPLETE",
    "snapshot_mode": "NOT_SET"
  },
  "output_type": "UNRESOLVED",
  "contribution_contract": "UNRESOLVED",
  "active_layer": "UNRESOLVED",
  "active_contribution": "NONE",
  "collision_round": 1,
  "active_state": "BOOT",
  "resume_state": "BOOT",
  "last_completed_state": "NONE",
  "next_required_action": "<one concrete action>",
  "search_mode": "SEARCH_OPEN | SYNTHESIS_LOCK | EXCEPTION_REOPEN",
  "compute_stage": "NOT_STARTED | S0 | S1 | S2 | S3 | S4 | STOPPED",
  "gates": {
    "scope_locked": false,
    "prior_claims_drained": false,
    "recent_frontier_complete": false,
    "literature_registry_valid": false,
    "important_fulltext_complete": false,
    "source_claims_complete": false,
    "output_claims_traced": false,
    "evidence_validated": false,
    "l1_frozen": false,
    "l2_frozen": false,
    "architecture_frozen": false,
    "n0_4_locked": false,
    "compute_authorized": false
  },
  "blocked_reasons": [],
  "artifacts": {
    "scope_lock": "scope_lock.md",
    "literature_registry": "near_neighbor_registry.json",
    "claim_registry": "literature_claim_registry.json",
    "output_support": "output_claim_support.json",
    "literature_archive": "literature_archive",
    "hierarchy_status": "hierarchy_status.md",
    "l1_card": "",
    "l2_card": "",
    "contribution_architecture": "",
    "hierarchy_novelty_audit": "",
    "validation_log": ""
  },
  "decision_log": []
}
```

约束：

- `UNRESOLVED` 只允许出现在 `BOOT`、`SCOPE_LOCK`，或恢复目标为
  `SCOPE_LOCK` 的 `BLOCKED`；通过 scope 门后必须改为正式枚举值；
- `snapshot_mode` 完成检索后只能是 `NEW_SEARCH` 或
  `REUSED_VERIFIED_SNAPSHOT`；
- `BLOCKED` 时 `blocked_reasons` 非空，`resume_state` 指向解除阻塞后恢复的原状态；
- 非 `BLOCKED` 时 `resume_state` 与 `active_state` 一致；
- `active_layer=L3` 时，博士只能使用 A/B/C，期刊只能使用 M；
- L1/L2/ARCHITECTURE 时 `active_contribution=NONE`；
- `next_required_action` 只能有一个原子动作，不写并列任务清单；
- 新碰撞先增加 `collision_round`，再进入 `PRIOR_CLAIM_DRAIN`。

---

## 目录

- [机器状态](#workflow_statejson每个主题必须先创建)
- [S0 准入卡与 Scope Lock](#s0-准入卡)
- [L1、L2 与贡献架构冻结卡](#l1-研究工作冻结卡)
- [对象卡、近邻卡与深读碰撞卡](#对象卡四元组--条件)
- [文献—观点—输出证据门禁](#文献注册完整性检查卡)
- [结果口径表与前沿一步卡](#结果口径审计卡定义条件基线分母表格总结)
- [上钻卡、跳板卡与正反张力卡](#上钻卡ascent-card)
- [杀伤记录与量词账本](#杀伤记录s6)
- [贡献责任表与分层创新审计](#贡献责任表)
- [Frontier Gap 与关闭库](#frontier_gap_memo-四问)
- [阶段勾选清单](#微领域启动前勾选101)

---

## S0 准入卡

```markdown
# S0 Entry Card — <微领域名>

## 允许研究的核心现象（不是题目）
...

## 与目标成果主线的关系（边界，非倒推）
...

## 为何可暂时脱离旧信号/旧数据独立成立
...

## 初步连续链线索（≥3 篇直接相关）
1.
2.
3.

## 已知关闭库碰撞（若有）
...

## 当前裁决
- [ ] 准入继续 S1/S2
- [ ] 关闭（理由：）
```

---

## Scope Lock（每轮先写，禁止静默改题）

```markdown
# Scope Lock — <版本/主题/日期>

| 字段 | 当前冻结值 |
|---|---|
| 研究版本/主题 | |
| 当前碰撞轮次 | |
| 近三年窗口 | current_year-2 .. current_year；COMPLETE / INCOMPLETE |
| 成果类型 | DOCTORAL_DISSERTATION / JOURNAL_ARTICLE |
| 贡献合同 | THREE_ORGANIC_A_B_C / ONE_MAIN_M |
| 当前阶段 | L1 / L2 / 贡献架构 / L3-贡献M/A/B/C |
| 已冻结且不得静默改变的上层 | |
| 当前贡献编号 | M / A / B / C / 尚未划分 |
| 允许研究的对象/结构 | |
| 禁止混入的旧主题/旧稿 | |
| 必须保留的主线锚点 | |
| 关键比较基线 | |
| 当前只裁决的创新层 | L1 / L2 / 贡献架构 / L3 / 全部 |
| 改变 scope 的唯一触发条件 | |

## 本轮新增文献能做什么
- [ ] 更新证据
- [ ] 触发显式重开申请
- [ ] 不允许静默改写问题
```

---

## L1 研究工作冻结卡

```markdown
# L1 Research Program — <名称>

| 字段 | 冻结定义 |
|---|---|
| 成果类型 | DOCTORAL_DISSERTATION / JOURNAL_ARTICLE |
| 贡献合同 | THREE_ORGANIC_A_B_C / ONE_MAIN_M |
| 对象 O | |
| 核心矛盾 | |
| 总目标 | |
| 动态/干预轴 | |
| 主要反方 B | |
| 适用边界 | |
| 退出边界 | |
| 连续知识链 | |

## 开题与导师要求映射
...

## 直接近邻是否系统完成整条链
...

## 成果规模适配
- 博士：能否承载三个连续知识责任：
- 期刊：能否收敛为一个自足主责任：

## 裁决
- [ ] PASS AS RESEARCH PROGRAM / FROZEN
- [ ] PARTIAL COLLISION
- [ ] FAIL AS PROGRAM
```

---

## L2 可行创新域冻结卡

```markdown
# L2 Feasible Domain — <名称>

| 字段 | 冻结定义 |
|---|---|
| O 对象 | |
| I 信息/表示 | |
| A 行动/机制类 | |
| V 变化/开放性轴 | |
| T 联合结果空间 | |
| B 关键反方 | |
| 数据/计算可行性 | |
| 准入边界 | |
| 退出边界 | |

## 如何完成冻结 L1
...

## 为什么宽于单一 L3，但没有宽过目标成果
...

## 贡献架构适配
- 博士：能否容纳三个非重叠且有机联系的贡献域：
- 期刊：能否容纳一个主贡献及其从属命题/组件：

## 直接近邻整体占据审计
...

## 裁决
- [ ] PASS AS FEASIBLE MICRODOMAIN / FROZEN
- [ ] NEEDS REBOUNDARY
- [ ] FAIL AS DOMAIN

> L2 不使用 N0；PASS 不表示已有创新命题。
```

---

## 贡献架构卡

### 博士论文：三贡献

```markdown
# Three-Contribution Architecture — <L2 名称>

| 字段 | 贡献 A | 贡献 B | 贡献 C |
|---|---|---|---|
| 名称 | | | |
| 研究单位 | | | |
| 主要干预/自变量 | | | |
| 核心目标量 | | | |
| 预期知识输出 | | | |
| 关键证据/反方 | | | |
| 不负责的问题 | | | |
| 可容纳的 L3 类型 | | | |

## 有机依赖链
A 的输出：
B 如何使用：
B 的合格状态如何进入 C：
C 如何反向约束 A/B：

## 非重叠审计
- [ ] 主要研究单位不同
- [ ] 主要自变量不同
- [ ] 主要目标量不同
- [ ] 关键证据不同
- [ ] 退出边界不同
- [ ] 同一实验不会被重复计算

## 裁决
- [ ] PASS AS NON-OVERLAPPING ORGANIC ARCHITECTURE
- [ ] REPARTITION

> 三个标题不是三个已成立的创新贡献；L3 仍须分别挖掘。
```

### 一般期刊论文：一个主贡献

```markdown
# One-Main-Contribution Architecture — <L2 名称>

| 字段 | 主贡献 M |
|---|---|
| 名称 | |
| 研究单位 | |
| 主要干预/自变量 | |
| 核心目标量 | |
| 唯一主知识输出 | |
| 关键证据/反方 | |
| 自足成文边界 | |
| 不负责的问题 | |
| 可容纳的 L3 类型 | |

## 从属结果与组件

| 项目 | 依赖 M 的方式 | 地位（N0-4C/N0-3C/N0-3F） | 去掉后 M 是否仍可表述 |
|---|---|---|---|
| | | | |

## 单主贡献审计
- [ ] 可用一句话指出唯一主知识责任
- [ ] 所有从属结果服务同一主问题/对象/机制
- [ ] 没有把数据集、实验场景或算法步骤重复计为独立贡献
- [ ] 目标期刊篇幅内能够自足论证
- [ ] 多个 L3 没有被自动重计为多个主贡献

## 裁决
- [ ] PASS AS ONE-MAIN-CONTRIBUTION ARCHITECTURE / FROZEN
- [ ] REFOCUS MAIN CONTRIBUTION

> M 至少一个主 L3 达到 N0-4 才能锁定；架构通过本身不是创新证据。
```

---

## 对象卡（四元组 + 条件）

```markdown
# Object Card — <候选短名>

| 元素 | 内容 |
|---|---|
| 对象 | |
| 可观察量 | |
| 目标量 | |
| 结论类型 | |
| 结构条件/量词 | |

## 最小有限模型
...

## 若失败，关闭证据将是
...
```

---

## 近邻卡

```markdown
# Neighbor Card — <论文/理论短名>

## 证据范围
- 真实身份：VERIFIED / UNVERIFIED
- 身份核验入口：
- 重要性：CRITICAL / IMPORTANT / CONTEXT
- 下载状态：FULLTEXT_ARCHIVED / OFFICIAL_HTML_ARCHIVED / DOWNLOAD_BLOCKED / NOT_REQUIRED
- 本地全文路径与 SHA-256：
- 当前证据级：E0 / E1 / E2 / E3 / E4
- 出版状态：PUBLISHED / PUBLISHED_WITH_PREPRINT_ALIAS / ACCEPTED_NOT_PUBLISHED / PREPRINT_ONLY / SUBMISSION_ONLY / STATUS_UNVERIFIED
- 正式出版核验入口：
- 终局判死资格：QUALIFIED / NOT_QUALIFIED
- 已核验位置：摘要 / 导言 / 问题定义 / 方法或定理 / 实验基线 / 结果 / limitation / 证明附录
- 论文声称研究什么：
- 论文实际完成了什么：

## 直接性分级
- [ ] 课题直接占据
- [ ] 直接方法近邻
- [ ] 理论前驱/同构
- [ ] 方法借鉴
- [ ] 关键词近邻

## 六元组 + 实证基线对齐

| 项 | 当前候选 | 近邻 | 是否真正对齐 |
|---|---|---|---|
| O 对象/生成机制 | | | |
| I 信息集/观测 | | | |
| A 行动/协议/结构 | | | |
| T 目标/损失 | | | |
| C 条件/量词 | | | |
| R 结论形式 | | | |
| B 关键比较基线 | | | |

## 真正覆盖到哪一层
- [ ] 结论
- [ ] 证明外壳
- [ ] 元问题
- [ ] 目标对象+量词+条件+结论（整线覆盖）

## 对象 / 信息边界 / 目标量 / 主结论
...

## 绑定假设（可检验）
...

## 假设失效后仍可形式化的对象
...

## 为何不能直接代入/取极限/拼接推出候选
...

## 覆盖后是否已上钻（未上钻不得关闭）
- [ ] 已执行上钻六问（见上钻卡）
- [ ] 上钻产生 T 未回答的精确问题 → 以 T 为跳板立新候选
- [ ] 上钻穷尽，无开口 → 关闭/收窄
```

---

## 权威近邻注册表记录

```json
{
  "registry_id": "<stable-id>",
  "canonical_title": "",
  "authors": [],
  "year": null,
  "persistent_ids": {"doi": "", "openalex": "", "arxiv": ""},
  "identity_status": "VERIFIED | UNVERIFIED",
  "identity_verification_url": "",
  "identity_verified_at": "",
  "search_phase": "RECENT_FRONTIER_PASS | FOUNDATIONAL_BACKFILL",
  "importance": "CRITICAL | IMPORTANT | CONTEXT",
  "venue": "",
  "publication_status": "PUBLISHED | PUBLISHED_WITH_PREPRINT_ALIAS | ACCEPTED_NOT_PUBLISHED | PREPRINT_ONLY | SUBMISSION_ONLY | FORMAL_NON_PEER_REVIEWED | STATUS_UNVERIFIED",
  "publication_verification_url": "",
  "publication_verified_at": "",
  "peer_review_status": "PEER_REVIEWED_PUBLISHED | PEER_REVIEWED_ACCEPTED_NOT_PUBLISHED | NON_PEER_REVIEWED | PEER_REVIEW_STATUS_UNVERIFIED",
  "peer_review_verification_url": "",
  "terminal_rejection_eligibility": "QUALIFIED | NOT_QUALIFIED",
  "canonical_url": "",
  "alternate_urls": [],
  "version_relations": [],
  "first_seen": {"date": "", "source_file": "", "query": ""},
  "last_seen": {"date": "", "source_file": ""},
  "target_layers": ["L1", "L2", "M", "A", "B", "C", "L3:<id>"],
  "neighbor_role": "direct-occupier | theoretical-predecessor | mechanical-component | method-baseline | counterexample | keyword-neighbor",
  "evidence_level": "E0",
  "evidence_history": [
    {"date": "", "level": "E0", "verified_locations": [], "source_file": ""}
  ],
  "verified_locations": [],
  "collision_effect": "",
  "decision_history": [],
  "local_archive": {
    "status": "METADATA_ONLY | CARD_ARCHIVED | FULLTEXT_ARCHIVED",
    "paths": []
  },
  "download": {
    "status": "FULLTEXT_ARCHIVED | OFFICIAL_HTML_ARCHIVED | DOWNLOAD_BLOCKED | NOT_REQUIRED",
    "source_url": "",
    "local_path": "",
    "sha256": "",
    "downloaded_at": "",
    "verified_against_metadata": false,
    "block_reason": ""
  },
  "claim_extraction_status": "COMPLETE | PARTIAL | NOT_STARTED",
  "metadata_status": "RESOLVED | METADATA_UNRESOLVED",
  "notes": ""
}
```

同一论文不同入口只增加 `alternate_urls`，不得重复建记录。搜索命中但尚未精读
时也立即写 E0；后续证据升级追加 `evidence_history`。重要观点、输出结论支持
和碰撞轮次字段使用 [evidence-pipeline.md](evidence-pipeline.md) 的两个 JSON schema。

---

## 文献注册完整性检查卡

```markdown
# Literature Registration Gate — <日期/裁决轮次>

- Registry path:
- Literature claim registry path:
- Output claim support path:
- URL ledger path:
- 当前年份与近三年窗口：
- RECENT_FRONTIER_PASS：COMPLETE / INCOMPLETE
- 当前碰撞轮次：
- Canonical works:
- 本轮新增记录：
- 本轮证据升级：
- 本轮相关搜索命中：
- 明确排除的搜索噪声及理由：
- 裁决文件中未注册 URL：
- metadata unresolved：
- identity unverified：
- CRITICAL/IMPORTANT 未下载：
- 本地全文哈希或版本匹配失败：
- CRITICAL/IMPORTANT 未完成观点提取：
- 未定位观点：
- 无观点 ID 支持的输出结论：
- prior-round UNUSED 观点：
- E2/E4 缺少核验位置：
- 正式出版状态未核验：
- peer-reviewed formally published canonical works：<n>/100
- 同行评审状态未核验：
- 搜索模式：SEARCH_OPEN / SYNTHESIS_LOCK / EXCEPTION_REOPEN
- 100 篇后无例外记录的新增文献：
- 微型领域研究链数量：
- 终局负面裁决中使用的预印本：
- 机械拼接中不具出版资格的必要前提：

## 门禁
- [ ] 所有实质相关命中已登记
- [ ] 先完成 current_year-2 .. current_year 的近三年检索，再回溯旧文献
- [ ] 所有文献身份已由官方/权威入口核验，未猜测题名、作者、年份或 DOI
- [ ] 所有 CRITICAL/IMPORTANT 全文已合法下载、核对版本并保存 SHA-256
- [ ] 所有 CRITICAL/IMPORTANT 已将重要观点、结论和方法原子化写入 JSON
- [ ] 每个输出结论至少绑定一个已全文核验的观点 ID
- [ ] 每条引用可回溯到观点、文献、原文 locator、本地全文和官方入口
- [ ] prior-round UNUSED = 0，旧观点已使用或有合格排除理由
- [ ] 同一 work 的多入口已去重并保留 alias
- [ ] 裁决稿全部来源可回到 registry id
- [ ] E2/E4 的证据位置可追溯
- [ ] 所有 FAIL/REJECTED/EXHAUSTED/CLOSED 的决定性来源均正式出版
- [ ] 机械拼接的每个必要来源均正式出版
- [ ] 预印本只标记 PREPRINT THREAT / OPEN
- [ ] 只有 PEER_REVIEWED_PUBLISHED 计入 100 篇阈值
- [ ] 达到 100 篇后已进入 SYNTHESIS_LOCK
- [ ] 阈值后的每次新检索均有必要性、限定查询和停止条件
- [ ] 已用研究链而非孤立论文执行碰撞
- [ ] unregistered_relevant_hits = 0

## 裁决
- [ ] PASS，可继续层级裁决
- [ ] FAIL，先补注册，不得继续裁决
```

---

## 微型领域研究链

```markdown
# Microfield Research Chain — <链条名>

## 链条合同
- 正式对象 O：
- 信息边界 I：
- 行动/结构 A：
- 目标 T：
- 核心语义操作：

## 连续推进
| 阶段 | 同行评审正式出版工作 | 推进的条件/量词/边界 | 证据级 | 预印本旁注 |
|---|---|---|---|---|
| 起点 | | | | |
| 推进 1 | | | | |
| 反例/修复 | | | | |
| 当前正式出版前沿 | | | | |

## 当前最强结论 K
- statement：
- supporting literature claim IDs：

## 链内仍未闭合的责任 U
- statement：
- supporting/qualifying claim IDs：

## 链条边界
...
```

---

## 链条碰撞矩阵

```markdown
# Chain Collision Matrix — <命题>

| 项 | 候选命题 | 微型领域链 | 是否对齐 |
|---|---|---|---|
| O 对象 | | | |
| I 信息 | | | |
| A 行动/结构 | | | |
| T 目标 | | | |
| C 条件/量词 | | | |
| R 结论 | | | |
| B 强基线 | | | |

## 机械推出路径
- 所需链条节点：
- 每个节点是否同行评审且正式出版：
- 每个节点证据级：
- 是否存在预印本必要环节：

## 裁决
- [ ] PUBLISHED-QUALIFIED CHAIN COLLISION
- [ ] PREPRINT THREAT ONLY / KEEP OPEN
- [ ] NOT COVERED / CONTINUE K→U→Δ

## 输出结论支持
- output claim ID：
- supporting literature claim IDs：
- counter/qualifying claim IDs：
- trace status：VERIFIED / INCOMPLETE
```

---

## 检索例外重开记录

```markdown
# Search Reopen — <编号/日期>

- 当前模式：SYNTHESIS_LOCK
- 当前 peer-reviewed published：<n>
- 现有哪条链无法回答：
- 必要缺口：
- 必须进入的新领域：
- 限定查询：
- 预计新增同行评审 canonical works 上限：
- 停止条件：
- 补齐后回填的研究链：

## 裁决
- [ ] EXCEPTION_REOPEN AUTHORIZED BY NECESSITY
- [ ] NOT NECESSARY / KEEP SYNTHESIS_LOCK
```

---

## 深读碰撞卡（发现碰撞 ≠ 覆盖裁决）

```markdown
# Deep-Read Collision Card — <论文>

## E1：摘要/导言中的自我定位
...

## E2：实际完成度
- 正式对象：
- 信息边界：
- 方法/定理：
- 实验结构：
- 关键比较基线（最强单体/最好同质/同预算/oracle/其他）：
- 主要结果：
- 注册的重要观点/结论/方法 IDs：

## E3：限制与 Future Work
- 作者明确限制：
- 该限制是正文证明机器内生，还是外部新场景：

## E4：证明机器/构造
- 绑定假设：
- 像/逆/边界：
- 是否可机械推出当前候选：

## 裁决
- [ ] 只发现碰撞，证据不足以覆盖
- [ ] L1 直接占据
- [ ] L2 可行域直接占据
- [ ] 贡献域直接占据
- [ ] L3 命题同构/理论前驱/充分特例/反例
- [ ] 方法可吸收
```

---

## 结果口径审计卡（定义—条件—基线/分母—表格—总结）

```markdown
# Result-Accounting Card — <论文/关键结果>

| 项 | 原文事实 | 位置 |
|---|---|---|
| 正式术语/estimand 定义 | | |
| 实际实验条件/处理臂 | | |
| 比较基线 | | |
| 分母/归一化 | | |
| 核心表格原始数值 | | |
| 作者摘要/正文总结 | | |
| Limitations/附录限定 | | |

## 复算
- 公式：
- 代入：
- 复算结果：
- 是否与论文报告一致：

## 口径漂移检查
- [ ] 摘要与正式定义一致
- [ ] 正文结论与实际实验臂一致
- [ ] Best Individual / oracle / average / matched-budget 未混写
- [ ] representative configurations 未写成 complete factorial
- [ ] correlation 未写成 intervention/causation

## 最弱准确陈述
...

## 观点与输出映射
- literature claim IDs：
- output claim IDs：

## 对当前 L1/L2/贡献/L3 的实际影响
...
```

---

## 前沿一步卡（候选命名前必填）

```markdown
# Frontier One-Step Card — <候选>

## 最近可靠结果 K
- 已完成什么：
- supporting literature claim IDs：
- 证据口径：定义 / 条件 / 基线 / 分母 / 表格：
- 不允许扩大成什么：

## 尚未闭合推理 U
K 为什么仍不能回答：
- supporting/qualifying/counter claim IDs：

## 最小知识增量 Δ
只推进的一步：
- proposition rationale output claim ID：

## 创新路径（只选一个主路径）
- [ ] R1 GAP_OPENING：责任空白
- [ ] R2 DEPTH_EXTENSION：成熟前沿深挖
- [ ] R3 NEW_PROBLEM_SUBSTANTIATION：成熟方法论证新问题
- 主路径选择理由：
- 若有次路径，其地位：

## 创新形式（只选一个主形式）
- [ ] F1 NEW_THEORY：新理论/数学命题
- [ ] F2 MATURE_THEORY_NEW_DOMAIN：成熟理论的新领域应用
- [ ] F3 NEW_ALGORITHM：新算法
- [ ] F4 ALGORITHM_DEEPENING：既有算法深入优化
- 主形式选择理由：
- 创新责任落在问题/理论/映射/算法中的哪一项：

## 非机械性攻击
- [ ] 不能由 K 加约束/变量替换推出
- [ ] 不能通过换基线/重算公开表格得到
- [ ] 不能由两篇现成结论直接拼接
- [ ] 不是增加任务、模型、数据或接口
- 所需新关键引理/干预/可证伪预测：

## 层级归属
- 成果类型与贡献合同：
- 稳定 L1：
- 冻结 L2：
- Δ 所属贡献 M/A/B/C：
- L3 命题类型：
- 所需方法/工具（可为标准工具）：

## 失败与关闭条件
...

## 裁决
- [ ] 允许命名候选并进入 S5
- [ ] 仍过大，继续压缩 Δ
- [ ] 机械增量，关闭/吸收
```

---

## 创新路径—形式审计卡

```markdown
# Innovation Route–Form Audit — <L3 候选>

## 主路径合同

| 路径 | 必答问题 | 当前答案 |
|---|---|---|
| R1 GAP_OPENING | 对齐 O/I/A/T/C/R/B 后，哪项知识责任确实未被研究链承担？ | |
| R2 DEPTH_EXTENSION | 成熟前沿 K 的 maximal reach/瓶颈是什么，本工作沿哪条轴更深？ | |
| R3 NEW_PROBLEM_SUBSTANTIATION | 新问题为何先于工具成立，成熟工具如何被正确映射并产生新结论？ | |

- 选定主路径：R1 / R2 / R3
- 其他两条为何不是主路径：
- 路径失败条件：

## 主形式合同

| 形式 | 最低交付物 | 当前证据 |
|---|---|---|
| F1 NEW_THEORY | 定义、命题、证明责任、见证/反例、理论近邻差异 | |
| F2 MATURE_THEORY_NEW_DOMAIN | 源理论—新对象映射、假设核验、新领域知识、适用边界 | |
| F3 NEW_ALGORITHM | 新计算规则、伪代码、资源合同、机制、同预算基线、消融 | |
| F4 ALGORITHM_DEEPENING | 原算法瓶颈、修改变量、收益机制、保护约束、同预算胜出 | |

- 选定主形式：F1 / F2 / F3 / F4
- 次形式及其从属地位：
- 形式失败条件：

## 非代偿审计
- [ ] 分类标签没有替代 K→U→Δ
- [ ] R3 中成熟工具未被误报为工具创新
- [ ] F2 不是只换数据、场景或术语
- [ ] F3/F4 的收益不是更多算力、参数、数据或不公平预算造成
- [ ] 路径门与形式门均通过后才允许 N0-4

## 裁决
- [ ] PASS ROUTE + FORM GATES
- [ ] RECLASSIFY
- [ ] N0-3/HOLD
- [ ] N0-1/2/CLOSE（须满足出版资格）
```

---

## 上钻卡（Ascent Card）

```markdown
# Ascent Card — 覆盖理论 <T 短名>

## 被覆盖的候选 P
...

## T 覆盖了 P 的哪一层（结论/外壳/元问题/整线）
...

## 上钻六问

| # | 问题 | T 的回答 / 未回答 |
|---|---|---|
| Q1 | T 的证明机器真正依赖什么未被审查的结构承诺？ | |
| Q2 | T 的像是什么？像外但机器暗示可达的区域？ | |
| Q3 | T 的逆命题在哪一层断裂？断裂暴露什么？ | |
| Q4 | T 的边界情形（等号/空支撑/退化/临界）暴露什么？ | |
| Q5 | T 的关键引理能多走一步吗？maximal reach？ | |
| Q6 | T 为何停在这里？结构必然 vs 技术偶然？ | |

## 上钻产生的精确结构问题（T 自身未回答）
...

## 反模式自查
- [ ] 不是只换场景（横向平移）
- [ ] 不是 limitation 翻译（外部添加）
- [ ] 不是标准外壳加层
- [ ] 不是术语重包装
- [ ] 不是过早收窄为 P\T

## 裁决
- [ ] 以 T 为跳板立新候选（回 S5 重新压缩）
- [ ] 上钻穷尽，关闭/收窄（理由：）
```

---

## 跳板卡

```markdown
# Springboard Card — <从近邻到更深问题>

## 吸收了什么（对象/基线/技术）
...

## 浅层主张（已被杀死或降级）
...

## 精确语义断层（公式/量词/构造差异）
...

## 更深问题（必要性 / converse / image / 不可实现）
...

## 最小下一步（引理/反例/可证伪预测）
...
```

---

## 正例—反例张力卡

```markdown
# Positive–Negative Tension Card — <共同推理桥>

| 项 | 正面成果 A | 失败/反例 B | 严格特例 C |
|---|---|---|---|
| 正式对象 | | | |
| 共同推理桥 E => D | | | |
| 成立制度 | | | |
| 失败制度 | | | |
| 隐藏条件变量 | | | |
| 证据级 E0--E4 | | | |

## 内生边界问题
独立证据/条件 E 在什么条件下足以支持 D？什么条件导致排序反转、不可识别或不可实现？

## 为什么不是 limitation 翻译
...

## 最小正例、最小反例、待刻画边界
...
```

---

## 杀伤记录（S6）

```markdown
# Kill Record — <贡献 M/A/B/C / L3 候选短名>

所属冻结 L1：
所属冻结 L2：
所属贡献域：

| 攻击 | 结果 | 证据位置 |
|---|---|---|
| 直接归约 | PASS/FAIL | |
| 机械拼接 | PASS/FAIL | |
| 反例 | PASS/FAIL | |
| 信息集 | PASS/FAIL | |

## 决定性来源资格

| 文献 | 出版状态 | 证据级 | 是否为必要前提 | 判死资格 |
|---|---|---|---|---|
| | | | | |

## 原子证据链
- closure output claim ID：
- 决定性 literature claim IDs：
- 每个 claim 的 locator：
- trace status：VERIFIED / INCOMPLETE

## 裁决
- N0-?
- PUBLISHED-QUALIFIED → 关闭 / 降级 / 进入构造
- PREPRINT-THREAT-ONLY → 保持 OPEN / NEEDS PUBLISHED ANCHOR
```

---

## 量词账本

```markdown
# Quantifier Ledger — <定理/引理名>

| 位置 | 易偷换的量词 | 当前写法 | 边界/空支撑处理 |
|---|---|---|---|
| | | | |

## 开放风险
...
```

---

## 贡献责任表

```markdown
# Contribution Responsibility

成果类型与贡献合同：
贡献编号：M / A / B / C
主创新路径：R1 / R2 / R3
主创新形式：F1 / F2 / F3 / F4

| 内容 | 等级 | 地位 |
|---|---|---|
| | N0-4M / N0-4C / N0-3C / N0-3F | 主结果 / 后果 / 组件 / 冻结 |

## 去掉所有标准外壳后剩余的原创责任（一句话）
...
```

---

## 分层创新审计（博士 A/B/C 分别填写；期刊只填 M）

```markdown
# Hierarchical Novelty Audit — <贡献 M/A/B/C / L3 候选>

## 成果合同

- 成果类型：DOCTORAL_DISSERTATION / JOURNAL_ARTICLE
- 贡献合同：THREE_ORGANIC_A_B_C / ONE_MAIN_M

## L1 研究工作状态

- 冻结名称：
- 状态：PASS-FROZEN / FAIL
- 本 L3 是否越出 L1：是 / 否

## L2 可行域状态

- 冻结名称：
- 状态：PASS-FROZEN / FAIL
- 本 L3 是否越出 L2：是 / 否

## 贡献域

- 归属：M / A / B / C
- 研究单位：
- 博士与另两项的非重叠边界；期刊 M 的自足边界：
- 博士输入输出依赖；期刊从属结果如何服务 M：

## L3 具体命题

### 证据链
- output claim ID：
- supporting literature claim IDs：
- counter/qualifying claim IDs：
- 是否全部回到 locator、本地全文、SHA-256 和官方入口：

### 精确新增知识
- 充分制度：
- 失效/反转制度：
- converse/sharpness/不可实现边界：

### 机械推出攻击
- [ ] 变量替换不能推出
- [ ] 增加标准约束不能推出
- [ ] 两篇结论拼接不能推出
- [ ] 需要新关键引理/新可证伪预测：

### N0 裁决
N0-1 / N0-2 / N0-3 / N0-4

## 创新路径与形式

- 主创新路径：R1 GAP_OPENING / R2 DEPTH_EXTENSION / R3 NEW_PROBLEM_SUBSTANTIATION
- 路径专属门禁如何通过：
- 主创新形式：F1 NEW_THEORY / F2 MATURE_THEORY_NEW_DOMAIN /
  F3 NEW_ALGORITHM / F4 ALGORITHM_DEEPENING
- 形式最低交付物如何满足：
- [ ] 路径标签与形式标签未替代非机械性证据
- [ ] 路径门和形式门均通过后才给 N0-4

## 方法/技术支持

### 所需工具
...

### 哪些是标准吸收件
...

### 承担 L3 的不可替代机制（若有）
...

### 裁决
- [ ] 方法本身有创新责任
- [ ] 标准工具，服务 L3，不单列贡献
- [ ] 仅工程改造

## 是否发生层级代偿
- [ ] 未用方法新包装 L3 失败
- [ ] 未用 L1/L2 宽范围包装 L3 为空
- [ ] 博士未用三个标题代替三个存活命题；期刊未把 M 拆成多个虚假贡献
- [ ] 未把一个 L3 主结果拆成多个虚假贡献

## 总裁决
...
```

---

## frontier_gap_memo 四问

```markdown
# Frontier Gap Memo — <微领域>

1. 现有连续链精确完成了哪一步？
2. 下一步为何对该链本身必要，而非引入新场景？
3. 最危险的当年近邻为何不能推出该步？
4. 最小可尝试的引理、反例或可证伪预测是什么？

## 出处（原文定义/定理/证明位置）
...

## 裁决
- [ ] 作为 L3 候选进入 N0 预审
- [ ] 关闭本微领域考察
```

---

## 关闭库条目

```markdown
# Closure — <方向短名>

1. 原始对象及最自然表述：
2. 主要危险近邻与前沿版本：
3. 决定性正式出版文献与出版入口：
4. 关闭类型：直接覆盖 | 机械拼接 | 反例 | 不识别 | 终点不可判定 | 工程基线等价
5. 不允许的换名重启方式：
6. 唯一可能的重开条件：
```

---

## 微领域启动前勾选（10.1）

- [ ] 已写 scope lock；成果类型、贡献合同、版本、主题和贡献编号未串线
- [ ] 已登记当前碰撞轮次和动态近三年窗口
- [ ] 2026 年运行时已先完成 2024–2026 近邻检索；其他年份按 current_year-2 滚动
- [ ] 上一轮重要观点已全部 USED 或 EXCLUDED_WITH_REASON；prior-round UNUSED = 0
- [ ] 已说明与目标成果主线关系，未由现有结果倒推题目
- [ ] 已查阅关闭库
- [ ] ≥3 篇直接相连核心论文（非关键词相似）
- [ ] ≥1 篇动态近三年窗口内的前沿工作
- [ ] 已写出共同对象、信息边界、目标量、结论类型

## 核读时勾选（10.2）

- [ ] 每个命中已先写入 near_neighbor_registry.json 并核验真实身份
- [ ] CRITICAL/IMPORTANT 全文已下载，版本与元数据一致，SHA-256 已登记
- [ ] 摘要/导言只用于发现碰撞，没有直接判死
- [ ] 核读定义、信息集、定理/算法、实验结构、关键基线、结果、证明关键步骤、限制段
- [ ] 记录预印本/会议/期刊差异
- [ ] 已核验每篇决定性近邻的正式出版状态；仅预印本不用于判死
- [ ] 沿引用、作者续作、同义词追至当年
- [ ] 每篇写出绑定假设与失败边界
- [ ] 核心结果已完成定义—条件—基线/分母—表格—总结审计
- [ ] 可从表格复算的 gap/ratio/improvement 已复算
- [ ] 不以摘要/搜索/“未检到”做新颖性判断
- [ ] 重要观点、结论、方法、假设和反例已原子化写入 literature_claim_registry.json
- [ ] 每条观点都有 source work ID、精确 locator、条件、证据级和使用状态

## 形成候选前勾选（10.3）

- [ ] 当前输出的每条事实/综合/比较/创新判断已登记 output claim ID
- [ ] 每个 output claim 至少绑定一个已全文核验的 literature claim ID
- [ ] SYNTHESIS/CONTRAST/INFERENCE 已写明推理关系，不是只列文献
- [ ] 引用链已通过 OC → LC → W → locator → local fulltext → official identity 验证
- [ ] 六元组比对完成
- [ ] 实证比较基线 B 已对齐（强单体/最好同质/同预算/oracle）
- [ ] 最强近邻已纳入基线
- [ ] 已至少尝试构造正例—反例共同推理桥，而非从 future work 直接生题
- [ ] 已冻结最近可靠结果 K，并写出 K 尚未闭合的推理 U
- [ ] 只提出一个 K 不能机械推出的最小知识增量 Δ
- [ ] L1 与 L2 均保持冻结，未被单个 Δ 拖成窄命题
- [ ] 已明确 Δ 属于贡献 M/A/B/C 中哪一个
- [ ] 已选择一个主创新路径 R1/R2/R3，并通过对应路径门
- [ ] 已选择一个主创新形式 F1/F2/F3/F4，并列齐对应最低交付物
- [ ] R3 的新问题先于工具冻结；成熟工具未被误报为创新
- [ ] F2 已核验跨域语义映射和理论假设，不是只换数据/场景
- [ ] F3/F4 已冻结同预算强基线、收益机制、消融和失败条件
- [ ] **被覆盖时已对覆盖理论执行上钻六问，突破口来自 T 内部而非 T 旁边**
- [ ] 已给最小有限模型
- [ ] 已做四种优先攻击（+上钻第五向量）
- [ ] 已说明失败时的具体关闭证据

## 进入实质研究前勾选（10.4）

- [ ] `validate_all.py` 返回 `validation_suite_failures=0`
- [ ] `validate_workflow_state.py` 零错误
- [ ] `validate_literature_registry.py` 与 `validate_evidence_chain.py` 均零错误
- [ ] 身份未核验、重要全文未下载、未定位观点、无观点支持输出均为 0
- [ ] 新碰撞启动门 `prior_round_claims_drained = true`
- [ ] L1 研究工作已冻结
- [ ] L2 可行创新域已冻结
- [ ] 博士三贡献架构已通过非重叠与有机联系审计；期刊单主贡献架构已通过自足审计
- [ ] 每个有效贡献域内至少一个 L3 候选达到 N0-4（博士 A/B/C；期刊 M）
- [ ] L3 含不可由近邻推出的新关键引理或可证伪预测
- [ ] L3 的主创新路径门与主创新形式门均已通过
- [ ] 独立敌对新颖性审计
- [ ] 理论/实验/系统主张各自证据边界明确
- [ ] 不会用新增模型/数据/工程复杂度掩盖对象重复
