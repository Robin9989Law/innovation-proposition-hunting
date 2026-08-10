---
name: innovation-proposition-hunting
description: >-
  Use when defining, auditing, revising, computing, or preparing to submit
  innovation propositions for dissertations or journal articles, especially
  when recent-literature coverage, dangerous near neighbors, theorem
  correctness, algorithm/protocol fidelity, evidence traceability, or research
  claim readiness must be adjudicated.
---

# 创新命题狩猎：Schema 2.0 强制协议

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
| 创建/迁移状态或任何 Schema 2.0 产物 | [templates.md](templates.md) 对应节 |
| 判 V0–V4、G9、理论或算法责任 | [reference.md](reference.md) |
| 检索、全文、观点、证据级或重要性变化 | [evidence-pipeline.md](evidence-pipeline.md) |
| 获准计算、升级或停止 | [compute-funnel.md](compute-funnel.md) |
| 诊断已知反模式 | [case-lessons.md](case-lessons.md) |

详细字段只在 [templates.md](templates.md) 定义；本文件不复制模板字段。

## 2. Schema 2.0 是唯一可执行合同

每个研究目录必须有 `workflow_state.json`，并满足：

```text
schema_version = 2.0
active_track ∈ {NOVELTY, VALIDITY, COMPUTE}
novelty_level ∈ {N0-1, N0-2, N0-3, N0-4C}
validity_level ∈ {V0, V1, V2, V3, V4}
claim_profile ∈ {THEORY, ALGORITHM, MIXED}
validation_epoch ∈ positive integers
```

缺少状态文件时，只能盘点和创建状态。`schema_version != 2.0` 时立即停止全部裁决、
审计和计算；先运行可恢复迁移：

```bash
python3 <skill>/scripts/migrate_v1_to_v2.py \
  --root <研究目录> --state <研究目录>/workflow_state.json
```

默认写出 `workflow_state.v2.json`；确认后才可用 `--in-place`，该模式先保存带 UTC
时间戳的字节级 v1 备份。迁移必须把 validity 重置为 V0、清空 bundle/audit、关闭
`compute_authorized`。迁移输出存在不代表验证完成；迁移后仍从 `CLAIM_FREEZE` 重建。

## 3. 双轴状态机

### 3.1 新颖性轴

先冻结成果合同和 scope，再按下列顺序执行：

```text
BOOT → SCOPE_LOCK → PRIOR_CLAIM_DRAIN → RECENT_FRONTIER
→ LITERATURE_REGISTER → IMPORTANT_FULLTEXT → SOURCE_CLAIM_REGISTER
→ SYNTHESIZE_COLLISION → OUTPUT_CLAIM_BIND → EVIDENCE_VALIDATE
→ LAYER_DECISION → N0_AUDIT
```

博士合同为 `THREE_ORGANIC_A_B_C`；期刊合同为 `ONE_MAIN_M`。L3 必须来自同一
连续研究链中的 `K → U → Δ`，并对齐 O/I/A/T/C/R/B。改变 L3、目标链、关键基线
或任一实质对齐项即开新碰撞轮次，并先耗尽 prior-round 观点。

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

## 4. 强制 claim inventory 与 form router

扫描所有声明的 Markdown/TeX 稿件源。任何 exact、universal、bounded、guaranteed、
necessary、sufficient、online、first/首次、strong/fair/matched-budget，以及定理、
引理、推论等高风险出现，必须恰好绑定到一个 inventory claim。允许的 `claim_type`
枚举、稳定 occurrence ID 算法和完整 JSON 见 [templates.md](templates.md)。

冻结 `claim_profile` 后按表路由；不得因某类产物难做而改 profile：

| profile | V2 前必须通过 |
|---|---|
| `THEORY` | claim inventory + theory obligation registry + 四类必需见证 |
| `ALGORITHM` | claim inventory + protocol contract + claim-code trace；命中强/公平/同预算主张时加 baseline budget |
| `MIXED` | THEORY 与 ALGORITHM 的并集，逐条 claim 路由 |

理论命题必须登记 exact statement、量词、前提、proof locator，并运行
`MINIMAL_POSITIVE`、`NONZERO_NUISANCE`、`BOUNDARY_OR_LIMIT`、
`PREMISE_REMOVAL`。后者必须预期失败、实际失败且进程非零。随机性质测试只能执行，
或由当前独立 reviewer 明确接受数学上的不适用理由。

算法命题必须把稿件位置和伪代码符号绑定到当前实现符号、实现哈希、可执行测试及
PASS 输出。在线主张必须冻结 prediction/update unit、顺序、标签可得性、数据角色和
访问次数；逐样本主张必须有当前 chronology test。强/公平/同预算比较必须使用共同
调参、种子、标签、更新频率、算力、停止规则和宽度/参数预算合同。

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
前向引用，并有至少两种独立 route type。缺轴为 INVALID；仅当具体能力被声明为
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

`DIRECTION_LOCK` 只锁方向。计算按 S0–S4 逐级升级；只有 S4 完成且 state 中的
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

## 10. 每次交接

交接必须从机器状态和刚运行的验证结果生成，至少报告：成果合同、active track/state、
N level、V level、claim profile、validation epoch、bundle hash、frontier/全文/观点计数、
独立 reviewer provenance、四退出码中的最终值、blocked reasons 和唯一
`next_required_action`。避免“基本完成”“大致有效”等非状态词。

> 核心纪律：先证明候选达到 N0-4C，再冻结准备声称的 exact claim；用 form-sensitive
> audit 证明它可被反驳和复现，用不同 agent 审精确 bundle；只有 V3 才能计算，计算
> 后必须新 epoch 达 V4，才允许最终锁定。
