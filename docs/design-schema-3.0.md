# Schema 3.0 设计：三段式状态机与派生字段

2026-08-11，用户拍板"大改"（优化方案第六部分遗留决策项）。本文是实施合同。

## 1. 要解决的结构性冲突

2.0 的状态机把 `IMPORTANT_FULLTEXT`（全部重要文献全文归档）与
`SOURCE_CLAIM_REGISTER`（全部原子观点提取）排在 `LAYER_DECISION` **之前**，
而 R-LAYER-13 的预算是"L2 ≤12 全文 / 0 原子观点"。IMPORTANT 文献超过 12 篇时
两个要求不可能同时满足——主次颠倒不是 agent 的错，是状态机逼的。

3.0 把 NOVELTY 轴重排为三段，证据深度按段供给，预算从软警告升格为硬约束。

## 2. 新状态机

```text
NOVELTY 轴
  L1_SCOUT 段（层级 L1，预算 0 全文 / 0 原子观点——只动元数据）
    BOOT → SCOPE_LOCK → PRIOR_CLAIM_DRAIN → RECENT_FRONTIER
    → LITERATURE_REGISTER → L1_FREEZE(新)
  L2_TRIAGE 段（层级 L2，预算 ≤12 全文 / 0 原子观点——试读与选拔）
    L2_TRIAGE(新，K 集合选拔，产出 k_triage) → LAYER_DECISION
  L3_EVIDENCE 段（层级 L3，预算 ≤20 全文 / ≤60 原子观点——只对 K 集合）
    K_FULLTEXT(原 IMPORTANT_FULLTEXT) → K_CLAIM_REGISTER(原 SOURCE_CLAIM_REGISTER)
    → SYNTHESIZE_COLLISION → OUTPUT_CLAIM_BIND → EVIDENCE_VALIDATE → N0_AUDIT
VALIDITY 轴（不变）
  CLAIM_FREEZE → VALIDITY_AUDIT → INDEPENDENT_REVIEW → DIRECTION_LOCK
  → (COMPUTE) → POSTCOMPUTE_CLAIM_FREEZE → FINAL_VALIDITY_AUDIT → FINAL_LOCK
COMPUTE 轴：COMPUTE；BLOCKED / COMPLETE 不变
```

关键语义变化：

- **碰撞综合移到 LAYER_DECISION 之后**。L2 冻结只依据元数据 + E1 摘要 + ≤12 篇
  试读；K 集合在 L2_TRIAGE 由浅证据选拔，L3_EVIDENCE 只对 K 集合跑全重机器。
  碰撞中发现 K 集合漏了关键近邻，允许回退到 K_FULLTEXT 补取（decision_log 记明）。
- `N0_AUDIT` 位置不变（证据验证之后），N0 裁决依旧基于完整碰撞结果。

## 3. 门（gates）变更

| 2.0 | 3.0 | 置真状态 | 必备产物 |
| --- | --- | --- | --- |
| important_fulltext_complete | **k_fulltext_complete**（语义：K 集合全文完成） | K_FULLTEXT | literature_archive |
| source_claims_complete | **k_claims_complete**（语义：K 集合观点完成） | K_CLAIM_REGISTER | claim_registry |
| —（新增） | **k_set_selected** | L2_TRIAGE | k_triage |
| l1_frozen | l1_frozen | **L1_FREEZE**（原 LAYER_DECISION） | l1_card |
| 其余 9 门不变 | | | |

门顺序蕴含链（GATE_ORDER）：
scope_locked → prior_claims_drained → recent_frontier_complete →
literature_registry_valid → l1_frozen → k_set_selected → l2_frozen →
architecture_frozen → k_fulltext_complete → k_claims_complete →
output_claims_traced → evidence_validated；n0_4_locked 需
architecture_frozen + evidence_validated。

## 4. 派生字段（不再持久化）

第五部分结论落地：以下三字段从 state 中删除，全部由校验器/工具派生——

| 删除字段 | 3.0 派生规则 |
| --- | --- |
| `active_layer` | 由 effective_state 经段映射得证据层级：L1_SCOUT 段→L1，L2_TRIAGE 段→L2，其余（含 VALIDITY/COMPUTE/COMPLETE）→L3；BLOCKED 从 resume_state 派生 |
| `active_track` | 由 effective_state 经 TRACK_STATES 逆映射；BLOCKED 从 resume_state 派生 |
| `last_completed_state` | 由 decision_log 最后一条非 BLOCKED 条目派生 |

连带效果：`TRACK_STATE_MISMATCH` / `LAST_COMPLETED_NOT_LOGGED` /
`LAYER_GATE` / `STATE_LAYER` 四个检查码失去对象，删除（字段不存在即不可能错）。
`EVIDENCE_DEPTH_EXCEEDS_LAYER` 从 NEW_CHECK_CODES 软警告毕业为常驻 INVALID
（状态机不再逼合规项目违规）。`iph advance` 不再回写 active_track（字段已删）。

## 5. 迁移（migrate_v2_to_v3.py）

机械映射，保留全部历史：

- 状态名：IMPORTANT_FULLTEXT→K_FULLTEXT，SOURCE_CLAIM_REGISTER→K_CLAIM_REGISTER
  （active_state / resume_state / decision_log 条目，含 `BLOCKED@<STATE>` 形式）。
- 门改名：important_fulltext_complete→k_fulltext_complete，
  source_claims_complete→k_claims_complete；新增 k_set_selected = 旧 l2_frozen 值
  （已过 LAYER_DECISION 的项目视为做过选拔）。
- 删除三个派生字段；schema_version 置 "3.0"。
- **预算告警**：2.0 项目若已做全量抽取（全文 >20 或观点 >60），迁移后
  EVIDENCE_DEPTH_EXCEEDS_LAYER 会常亮 INVALID——这是设计意图：全量抽取
  本身就是要被消灭的模式；迁移脚本打印醒目提示，不代为删减证据。
- k_set_selected=true 但无 k_triage 产物时，迁移只警告不伪造；校验器会报
  ARTIFACT 缺失，项目补一份 l2-triage.md 即可。

## 6. 不做的

- 不动 VALIDITY 轴、N/V 等级、G9 不同-agent 硬门、E1–E4 分级、epoch 失效协议。
- 不为 2.0 保留可执行兼容：2.0 一律 MIGRATION（单一可执行合同原则）。
- 不动预算数值本身（L2 ≤12、L3 ≤20/60 维持 R-LAYER-13 既定值）。
