# 产物模板（`workflow_state.json` 为 Schema 3.0，其余产物仍为 Schema 2.0）

这里集中定义 validator 消费的字段。所有路径均为研究根目录下的 canonical relative
POSIX path；所有 SHA-256 均为 64 位小写十六进制；`validation_epoch` 必须与 state
一致。示例中的 `<...>` 必须替换，不能原样提交。研究卡片可自由扩展，但不得改写
这些机器合同。

## 1. `workflow_state.json`

```json
{
  "schema_version": "3.0",
  "workflow_id": "<stable-topic-id>",
  "updated_at": "<ISO-8601>",
  "current_year": 2026,
  "recent_window": {
    "start_year": 2024,
    "end_year": 2026,
    "status": "COMPLETE",
    "snapshot_mode": "NEW_SEARCH"
  },
  "output_type": "JOURNAL_ARTICLE",
  "contribution_contract": "ONE_MAIN_M",
  "active_contribution": "M",
  "active_state": "CLAIM_FREEZE",
  "resume_state": "CLAIM_FREEZE",
  "next_required_action": "Freeze every high-risk claim occurrence.",
  "search_mode": "SEARCH_OPEN",
  "compute_stage": "NOT_STARTED",
  "collision_round": 1,
  "blocked_reasons": [],
  "novelty_level": "N0-4C",
  "validity_level": "V0",
  "claim_profile": "MIXED",
  "validation_epoch": 1,
  "claim_bundle_sha256": "",
  "independent_audit": {},
  "gates": {
    "scope_locked": true,
    "prior_claims_drained": true,
    "recent_frontier_complete": true,
    "literature_registry_valid": true,
    "l1_frozen": true,
    "k_set_selected": true,
    "l2_frozen": true,
    "architecture_frozen": true,
    "k_fulltext_complete": true,
    "k_claims_complete": true,
    "output_claims_traced": true,
    "evidence_validated": true,
    "n0_4_locked": true,
    "compute_authorized": false
  },
  "artifacts": {
    "scope_lock": "scope_lock.md",
    "literature_registry": "near_neighbor_registry.json",
    "claim_registry": "literature_claim_registry.json",
    "current_evidence_scope": "current_evidence_scope.json",
    "output_support": "output_claim_support.json",
    "literature_archive": "literature_archive",
    "hierarchy_status": "hierarchy_status.md",
    "l1_card": "l1-card.md",
    "k_triage": "l2-triage.md",
    "l2_card": "l2-card.md",
    "contribution_architecture": "contribution-architecture.md",
    "hierarchy_novelty_audit": "novelty-audit.md",
    "validation_log": "validation.log"
  },
  "decision_log": []
}
```

`decision_log` 条目 schema（每次状态完成追加一条，不得事后回填）：

```json
{
  "at": "2026-08-10T15:26:00Z",
  "state": "SCOPE_LOCK",
  "action": "冻结 scope_lock.md 与 hierarchy_status.md；scope_locked=true。",
  "artifacts": [
    {"path": "scope_lock.md", "sha256": "<64 hex>"},
    {"path": "hierarchy_status.md", "sha256": "<64 hex>"}
  ]
}
```

- `at`：UTC ISO-8601；条目时间单调不减，且不得晚于 state 文件自身写入时刻
  （校验器以 mtime 交叉核验，未来时间或晚于写入时间即判伪造）。
- `state`：必须是状态机中的状态；BLOCKED 期间的条目用 `BLOCKED@<STATE>`。
- `artifacts`：本状态新产/变更的产物及 SHA-256；登记后内容再变即判
  `STALE_DECISION_ARTIFACT`。无产物变更的状态可省略此字段。
- gate 置真必须能在此找到对应状态的条目（gate 与状态的映射见
  `validate_workflow_state.py` 的 `GATE_COMPLETION_STATE`），否则视为自报置真。
- `updated_at` 不得早于末条目 `at`。

枚举必须与 validators 一致：

- `active_state` / `resume_state`：`BOOT | SCOPE_LOCK |
  PRIOR_CLAIM_DRAIN | RECENT_FRONTIER | LITERATURE_REGISTER | L1_FREEZE |
  L2_TRIAGE | LAYER_DECISION | K_FULLTEXT | K_CLAIM_REGISTER |
  SYNTHESIZE_COLLISION | OUTPUT_CLAIM_BIND |
  EVIDENCE_VALIDATE | N0_AUDIT | CLAIM_FREEZE | VALIDITY_AUDIT |
  INDEPENDENT_REVIEW | DIRECTION_LOCK | COMPUTE | POSTCOMPUTE_CLAIM_FREEZE |
  FINAL_VALIDITY_AUDIT | FINAL_LOCK | BLOCKED | COMPLETE`（`resume_state` 不得为
  `BLOCKED`/`COMPLETE`）
- `novelty_level`: `N0-1 | N0-2 | N0-3 | N0-4C`
- `validity_level`: `V0 | V1 | V2 | V3 | V4`
- `claim_profile`: `THEORY | ALGORITHM | MIXED`
- `output_type`: `UNRESOLVED | DOCTORAL_DISSERTATION | JOURNAL_ARTICLE`
- `contribution_contract`: `UNRESOLVED | THREE_ORGANIC_A_B_C | ONE_MAIN_M`
- `active_contribution`: `NONE | M | A | B | C`
- `search_mode`: `SEARCH_OPEN | SYNTHESIS_LOCK | EXCEPTION_REOPEN`
- `recent_window.status`: `COMPLETE | INCOMPLETE`；`snapshot_mode`:
  `NOT_SET | NEW_SEARCH | REUSED_VERIFIED_SNAPSHOT`（status=COMPLETE 时不得
  `NOT_SET`）
- `compute_stage`: `NOT_STARTED | S0 | S1 | S2 | S3 | S4 | STOPPED`

派生字段（不再持久化，state 中出现即 `LEGACY_FIELD_REMOVED`）：

- 活动轨道（NOVELTY / VALIDITY / COMPUTE）由 `active_state` 经状态机逆映射派生；
- 证据层级（L1 / L2 / L3）由 `active_state` 派生：L1_SCOUT 段为 L1、L2_TRIAGE 段
  为 L2，其余（含 VALIDITY/COMPUTE 轴与 COMPLETE）为 L3；BLOCKED 时从
  `resume_state` 派生；
- 最后完成状态由 `decision_log` 末条非 BLOCKED 条目派生。

Schema 3.0 变更：`L1_FREEZE` 与 `L2_TRIAGE` 为新增状态；`K_FULLTEXT` /
`K_CLAIM_REGISTER` 由原全量全文/全量观点状态改名，并重新定义为只对 K 集合运行。

当 `active_state=BLOCKED` 时，`resume_state` 指向解除后状态，`blocked_reasons` 是非空
字符串数组。否则 `resume_state == active_state` 且 `blocked_reasons=[]`。

## 2. `claim_inventory.json`

```json
{
  "schema_version": "2.0",
  "validation_epoch": 1,
  "manuscript_sources": ["manuscript.md"],
  "claims": [
    {
      "claim_id": "C-THEOREM-1",
      "statement": "<exact frozen statement>",
      "claim_type": "THEOREM",
      "locations": ["manuscript.md:42"],
      "evidence_responsibility": "<what must establish this exact claim>",
      "risk_terms": ["theorem", "exact"],
      "status": "FROZEN",
      "validation_epoch": 1,
      "occurrence_ids": ["<sha256 from the stable occurrence algorithm>"]
    }
  ]
}
```

`claim_type` 仅允许：

```text
THEOREM, LEMMA, COROLLARY, PROPOSITION, DEFINITION,
ALGORITHM, ALGORITHM_GUARANTEE, ALGORITHM_PERFORMANCE, ONLINE_ALGORITHM,
METHOD, ONLINE, PROTOCOL, EMPIRICAL, BASELINE, COMPLEXITY
```

每个 high-risk occurrence 必须恰好属于一个 claim。ID 计算为：相对路径、命中 term、
规范化所在行、同一行同 term 的 ordinal 以 NUL 拼接后做 SHA-256。规范化规则：
term 与行文本均先 `casefold()`；行文本再把连续空白折叠为单个空格
（`" ".join(line.split())`）；ordinal 从 1 起按命中顺序编号。稿件或 epoch
变化后重新扫描；V3/V4 出现未审 occurrence 视为 unaudited promotion。

## 3. `theory_obligation_registry.json`

仅 `THEORY` / `MIXED` 使用；每个 `THEOREM | LEMMA | COROLLARY` 必须恰好一项。

```json
{
  "schema_version": "2.0",
  "validation_epoch": 1,
  "obligations": [
    {
      "claim_id": "C-THEOREM-1",
      "exact_statement": "<byte-for-byte inventory statement>",
      "exact_statement_sha256": "<sha256 of UTF-8 exact_statement>",
      "premises": ["<premise 1>"],
      "quantifiers": ["<quantifier 1>"],
      "proof_locator": "manuscript.md:42",
      "validation_epoch": 1,
      "witnesses": [
        {
          "kind": "MINIMAL_POSITIVE",
          "expected": "PASS",
          "observed": "PASS",
          "command": "<exact command>",
          "exit_code": 0,
          "output_file": "theory_witnesses/minimal_positive.txt",
          "output_sha256": "<sha256>"
        },
        {
          "kind": "NONZERO_NUISANCE",
          "expected": "PASS",
          "observed": "PASS",
          "command": "<exact command>",
          "exit_code": 0,
          "output_file": "theory_witnesses/nonzero_nuisance.txt",
          "output_sha256": "<sha256>",
          "sensitivity_control": "<对照的 nuisance 参数取值，≥10 字符>"
        },
        {
          "kind": "BOUNDARY_OR_LIMIT",
          "expected": "PASS",
          "observed": "PASS",
          "command": "<exact command>",
          "exit_code": 0,
          "output_file": "theory_witnesses/boundary_or_limit.txt",
          "output_sha256": "<sha256>"
        },
        {
          "kind": "PREMISE_REMOVAL",
          "expected": "FAIL",
          "observed": "FAIL",
          "command": "<exact command>",
          "exit_code": 1,
          "output_file": "theory_witnesses/premise_removal.txt",
          "output_sha256": "<sha256>",
          "mechanism": "<移除前提后命题为何失败的机制解释，≥20 字符>"
        },
        {
          "kind": "RANDOM_PROPERTY",
          "expected": "PASS",
          "observed": "PASS",
          "command": "<exact command>",
          "exit_code": 0,
          "output_file": "theory_witnesses/random_property.txt",
          "output_sha256": "<sha256>"
        }
      ]
    }
  ]
}
```

见证咬合力（`WITNESS_NO_BITE`，默认 WARNING，`--strict-new-checks` 升 INVALID）：
`PREMISE_REMOVAL` 的 `mechanism` 不得是构造性恒真表述（"by construction" /
"trivially" / "by definition" / "恒真" 命中即报）；`NONZERO_NUISANCE` 的
`sensitivity_control` 必须写明对照取值。命题含 `subclaims`（可选字符串列表）时，
每条子规律必须被至少一个见证的 `addresses_subclaim` 字段（精确相等）认领，否则
逐条报 `SUBCLAIM_WITNESS_GAP`。

若 `RANDOM_PROPERTY` 数学上不适用，删除该 witness，并在同一 obligation 加
（两阶段闭合，解除 V2 死锁）：

```json
"random_property": {
  "status": "NOT_APPLICABLE",
  "mathematical_reason": "<non-empty exact reason>",
  "proposed_by_author": true,
  "independent_audit_acceptance": {
    "accepted": true,
    "reviewer_agent_id": "<same current independent reviewer>"
  }
}
```

V2 作者提出豁免（`proposed_by_author: true` + 非空 `mathematical_reason`）即可
推进，但未追认前 registry 保持未闭合（`RANDOM_PROPERTY_EXEMPTION_PENDING`，
默认 WARNING，strict 升 INVALID）；V3 独立 reviewer 追认
（`independent_audit_acceptance.accepted=true` 且 `reviewer_agent_id` 非空）后
方算闭合。作者提出不是自我赦免。

## 4. `protocol_contract.json`

仅 `ALGORITHM` / `MIXED` 使用。

```json
{
  "schema_version": "2.0",
  "validation_epoch": 1,
  "prediction_unit": "SAMPLE",
  "update_unit": "SAMPLE",
  "predict_update_order": "PREDICT_THEN_UPDATE",
  "label_availability": "AFTER_EACH_PREDICTION",
  "chronological_ordering": "STRICT_EVENT_TIME",
  "split_strategy": "CHRONOLOGICAL_HOLDOUT",
  "hyperparameter_selection_data": "TRAIN_ONLY",
  "development_data": "DEVELOPMENT_ONLY",
  "sealed_confirmation_data": "SEALED_CONFIRMATION_ONLY",
  "test_access_count": 1,
  "update_semantics": {
    "uses_test_labels": false,
    "supervised_online_adaptation": false,
    "pre_update_scoring": true,
    "operational_label_availability": true,
    "evaluation_role": "CONFIRMATORY"
  },
  "chronology_test": {
    "command": "python3 -m checks.check_online_chronology",
    "status": "PASS",
    "exit_code": 0,
    "output_file": "test_outputs/online_chronology_pass.json",
    "output_sha256": "<sha256>",
    "target_claim_ids": ["C-ALGORITHM-1"],
    "implementation_relative_path": "implementation/online_algorithm.py",
    "implementation_symbol": "evaluate_online",
    "implementation_sha256": "<sha256>"
  }
}
```

枚举：prediction `SAMPLE|BATCH|BLOCK|SEQUENCE`；update
`SAMPLE|BATCH|BLOCK|NONE`；order `PREDICT_THEN_UPDATE|PREDICT_ONLY|
BATCH_PREDICT_THEN_UPDATE|BLOCK_PREDICT_THEN_UPDATE`；label
`NEVER|TRAIN_ONLY|AFTER_EACH_PREDICTION|AFTER_BATCH|AFTER_BLOCK`；ordering
`STRICT_EVENT_TIME|INDEX_ORDER|NOT_APPLICABLE`；split
`CHRONOLOGICAL_HOLDOUT|ROLLING_ORIGIN|PREQUENTIAL|FIXED_HOLDOUT`。

若 `uses_test_labels=true`，还必须 supervised adaptation、pre-update score、现实中标签
可得且 `evaluation_role=NON_CONFIRMATORY`；否则是 INVALID。

## 5. `baseline_budget.json`

只要 claim inventory 存在 ALGORITHM 类 claim，`baseline_budget.json` 必须存在且
有效（`validate_baseline_budget.py`）。**不再依赖 "strong baseline"/"fair
comparison" 等触发词**——回避措辞不能免除基线预算义务。每个 comparator 必须有
非空唯一 `claim_ids` 且与 algorithm claims 有交集；所有 algorithm claims 必须
被至少一个 comparator 覆盖：

```json
{
  "schema_version": "2.0",
  "validation_epoch": 1,
  "comparators": [
    {
      "comparator_id": "B-COMPARATOR-A",
      "claim_ids": ["C-ALGORITHM-1"],
      "width_or_parameter_budget": "<common contract>",
      "seeds": [11, 23, 37],
      "regularization_search_space": [0.0, 0.01, 0.1],
      "tuning_data": "<same data role>",
      "label_access": "<same label contract>",
      "update_frequency": "<same frequency>",
      "compute_budget": "<same resource cap>",
      "stopping_rules": "<same stopping rule>"
    }
  ]
}
```

## 6. `claim_code_trace.json`

每个 algorithm claim 恰好一个 trace：

```json
{
  "schema_version": "2.0",
  "validation_epoch": 1,
  "traces": [
    {
      "claim_id": "C-ALGORITHM-1",
      "manuscript_location": "manuscript.md:77",
      "pseudocode_symbol": "Algorithm 1",
      "implementation_relative_path": "implementation/online_algorithm.py",
      "implementation_symbol": "evaluate_online",
      "implementation_sha256": "<sha256>",
      "executable_test_relative_path": "checks/check_online_chronology.py",
      "executable_test_sha256": "<sha256>",
      "pass_output_relative_path": "test_outputs/online_chronology_pass.json",
      "pass_output_sha256": "<sha256>"
    }
  ]
}
```

测试文件必须以静态 `TARGET_CLAIM_IDS` 精确声明它覆盖的 trace 集，并实际导入/调用
绑定实现；PASS output 必须声明相同 target IDs、命令、测试路径和测试 hash。

`SELF_ATTESTING_TEST`（默认 WARNING，`--strict-new-checks` 升 INVALID）对
protocol `chronology_test` 与 trace 绑定测试做静态核验：模块级
`TARGET_CLAIM_IDS` 字面量非空且与登记/绑定 claim_ids 有交集；AST 可证 import
登记的实现模块（允许 `sys.path.insert` 后按 stem 导入）。只断言自身硬编码期望、
不绑定任何 claim 的"检验脚本"属于自证（运动员兼裁判），不计入 claim 证据。

## 7. `frontier_coverage.json`

```json
{
  "schema_version": "2.0",
  "axes": {
    "method_synonyms": ["<term>"],
    "target_tasks": ["<task>"],
    "theory_terms": ["<term>"],
    "algorithm_structures": ["<structure>"],
    "author_continuations": [
      {"edge": "<work A → work B>", "shared_authors": ["<真实交集作者>"]}
    ],
    "method_lineage": ["<route/result>"],
    "backward_citations": ["<route/result>"],
    "forward_citations": ["<route/result>"]
  },
  "routes": [
    {
      "route_id": "keyword-search",
      "route_type": "DISCOVERY",
      "independent": true,
      "details": "<bounded query and coverage>"
    },
    {
      "route_id": "citation-graph",
      "route_type": "CITATION_GRAPH",
      "independent": true,
      "details": "<backward/forward traversal>"
    }
  ]
}
```

某一轴确实能力不可用时，用对象替换数组：

```json
{"status":"BLOCKED","capability":{"name":"<capability>","available":false,"reason":"<reason>"}}
```

`author_continuations` 只收**作者续作边**：每条边必须给出 `shared_authors`
（两端 work 的真实作者交集，非空）。空交集或 legacy 字符串条目报
`HOLLOW_COVERAGE_AXIS`。引用链（A → B → C 的引文传递，无作者交集）不是
作者续作，放入可选轴 `method_lineage`。

旧项目的 legacy 字符串条目用 `scripts/migrate_frontier_coverage.py` 半自动迁移：
逐段在近邻注册表核验姓氏与年份，相邻 work 作者交集全部非空才改写为实名边；
核验不了的字符串原样降级到 `method_lineage`，绝不编造交集。先 `--dry-run`
审阅计划再落盘；迁移自动生成排他备份。迁移后若本轴为空，须人工补真实
核验过的续作边（脚本不伪造）。

## 8. `audit_manifest.json`

profile 决定 entry roles：THEORY 至少含 `CLAIM_INVENTORY, MANUSCRIPT,
THEORY_OBLIGATIONS`；ALGORITHM 至少含 `CLAIM_INVENTORY, MANUSCRIPT,
PROTOCOL_CONTRACT, CLAIM_CODE_TRACE, IMPLEMENTATION, EXECUTABLE_TEST, TEST_OUTPUT,
BASELINE_CONTRACT`；MIXED 取并集。缺失 role 报 `AUDIT_MANIFEST_ROLE_MISSING`
（`validate_artifact_hashes.py`，默认 WARNING，`--strict-new-checks` 升 INVALID）。

```json
{
  "schema_version": "2.0",
  "validation_epoch": 1,
  "claim_bundle_sha256": "<canonical bundle sha256>",
  "entries": [
    {"path":"claim_inventory.json","role":"CLAIM_INVENTORY","sha256":"<sha256>"},
    {"path":"manuscript.md","role":"MANUSCRIPT","sha256":"<sha256>"}
  ]
}
```

bundle 只从 entries 的当前 `{path, role, sha256}` 计算：按 path 排序，以 UTF-8、
`sort_keys=true`、紧凑 separators 规范化，再 SHA-256。

## 9. `independent_audit.json`

V3/V4 使用；同样的对象还要镜像到 `workflow_state.independent_audit`：

```json
{
  "schema_version": "2.0",
  "validation_epoch": 1,
  "capability_available": true,
  "author_agent_ids": ["agent-author"],
  "reviewer_agent_id": "agent-reviewer",
  "reviewer_thread_id": "thread-reviewer",
  "audited_bundle_sha256": "<same state/manifest bundle sha256>",
  "verdict": "PASS",
  "findings": [],
  "audited_at": "<ISO-8601>"
}
```

reviewer 不能在 author list 中。能力不可用时写 `capability_available=false` 并返回
BLOCKED；不得伪造 reviewer、thread、PASS 或 bundle。

## 10. `compute_evidence.json` 与 state pointer

S4 完成后的计算证据文件可采用：

```json
{
  "schema_version": "2.0",
  "compute_stage": "S4",
  "verdict": "PASS"
}
```

进入 `POSTCOMPUTE_CLAIM_FREEZE` 时，`workflow_state.json` 还必须增加 validator 实际
读取的 pointer；artifact hash 必须是上面文件的当前 SHA-256：

```json
"compute_evidence": {
  "status": "COMPLETED",
  "validation_epoch": 1,
  "artifact_path": "compute_evidence.json",
  "artifact_sha256": "<sha256>"
}
```

同时 `compute_stage=S4` 且 `gates.compute_authorized=true`。随后提升 epoch，重建
post-compute claim inventory/bundle，完成 `FINAL_VALIDITY_AUDIT`；旧 pointer 不能替代
新 epoch 的独立 audit。

## 11. Claim freeze / material-change Markdown 记录

```markdown
# Claim Freeze — epoch <n>

- novelty level: N0-4C
- validity level: V1 / V2 / V3 / V4
- claim profile: THEORY / ALGORITHM / MIXED
- inventory: claim_inventory.json
- bundle: audit_manifest.json / <sha256>
- authors: <agent IDs>
- independent reviewer/thread: <ID / thread>
- material changes since prior epoch: <none or exact list>
- invalidated prior audit: <yes/no and reason>
- validator exit: READY / INVALID / BLOCKED / MIGRATION_REQUIRED
- unique next action: <one action>
```

## 12. `exploration_registry.json`

S0-SCREEN 之前（`gates.compute_authorized=false`）只允许不产生数值输出的文献
筛查。任何数值预实验产物（脚本、扫描结果、报告）必须当天登记为**永久探索级**，
否则报 `UNREGISTERED_COMPUTE_ARTIFACT`。登记入口：`iph register-exploration
--path <相对路径> --desc <说明>`（改动产物后必须重新登记，否则
`EXPLORATION_ARTIFACT_STALE`）。

```json
{
  "schema_version": "2.0",
  "explorations": [
    {
      "id": "exp-001",
      "path": "s0_delta2_report.md",
      "sha256": "<sha256 of UTF-8 file>",
      "registered_at": "<ISO-8601 UTC>",
      "data_role": "EXPLORATION_PERMANENT",
      "description": "<非空：探索内容与结论性质>"
    }
  ]
}
```

登记产物的显著数字 token（小数，有效位 ≥3）不得出现在任何冻结工件（根级
Markdown、claim 相关 JSON、manuscript）中，即使注明"探索"也不行——冻结工件
只允许定性转述。违反报 `EXPLORATION_LEAK`（`validate_exploration_firewall.py`）。
有 E1/E2 出处的文献数字（出现在 `near_neighbor_registry.json` /
`literature_claim_registry.json` 中的 token）豁免，因为其 provenance 独立。

## 13. `scope_lock.md`

每轮开始固定（防版本与主题串线）：

```text
研究版本/主题：
成果类型（DOCTORAL_DISSERTATION/JOURNAL_ARTICLE）：
贡献合同（THREE_ORGANIC_A_B_C/ONE_MAIN_M）：
当前阶段（L1/L2/贡献架构/L3-贡献编号）：
现行贡献编号（M/A/B/C；不要复用历史命题编号）：
允许对象与结构：
禁止混入的旧主题/旧稿：
关键比较基线：
当前只裁决 L1/L2/贡献架构/L3 中哪一层：
改变 scope 的触发条件与授权人：
```

检索发现只能更新证据或触发显式重开，不能静默改变课题。不同主题必须使用不同
连续簇、注册表和权威裁决文件。

## 14. `current_evidence_scope.json`

全局文献与观点注册表追加保留所有轮次；本文件只声明当前 `collision_round` 实际
消耗证据深度预算的 ID。空数组表示本轮尚未读取全文或提取原子观点，不表示历史
证据不存在。列入的 work 必须在全局文献注册表中且全文已归档；列入的 claim 必须
在全局观点注册表中。重复、悬空 ID 或轮次不一致均为 INVALID。

```json
{
  "schema_version": "2.0",
  "collision_round": 2,
  "fulltext_registry_ids": ["W-0001"],
  "atomic_claim_ids": ["LC-0001"]
}
```

缺少该 artifact 时，校验器为防止静默放宽，继续按全注册表计数。复用已有研究
目录或开启新碰撞时，应在进入 `RECENT_FRONTIER` 前创建当前轮次的 scope，并在
state `artifacts.current_evidence_scope` 中登记。

scope 文件可按阶段演进：新碰撞以空 scope 开始；K 全文门后换入列有本轮全文的
scope，K 观点门后再换入完整 scope——通过重指 `artifacts.current_evidence_scope`
实现（如 `current_evidence_scope_k_fulltext.json` → `_k_claims.json`）。历史
scope 文件保留不删，作为本轮取证轨迹的审计证据；每个被指向的 scope 仍须通过
全部一致性校验（轮次匹配、ID 存在、全文已归档）。
