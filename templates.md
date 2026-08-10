# Schema 2.0 产物模板

这里集中定义 validator 消费的字段。所有路径均为研究根目录下的 canonical relative
POSIX path；所有 SHA-256 均为 64 位小写十六进制；`validation_epoch` 必须与 state
一致。示例中的 `<...>` 必须替换，不能原样提交。研究卡片可自由扩展，但不得改写
这些机器合同。

## 1. `workflow_state.json`

```json
{
  "schema_version": "2.0",
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
  "active_layer": "L3",
  "active_contribution": "M",
  "active_track": "VALIDITY",
  "active_state": "CLAIM_FREEZE",
  "resume_state": "CLAIM_FREEZE",
  "last_completed_state": "N0_AUDIT",
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
    "important_fulltext_complete": true,
    "source_claims_complete": true,
    "output_claims_traced": true,
    "evidence_validated": true,
    "l1_frozen": true,
    "l2_frozen": true,
    "architecture_frozen": true,
    "n0_4_locked": true,
    "compute_authorized": false
  },
  "artifacts": {
    "scope_lock": "scope_lock.md",
    "literature_registry": "near_neighbor_registry.json",
    "claim_registry": "literature_claim_registry.json",
    "output_support": "output_claim_support.json",
    "literature_archive": "literature_archive",
    "hierarchy_status": "hierarchy_status.md",
    "l1_card": "l1-card.md",
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

- `active_track`: `NOVELTY | VALIDITY | COMPUTE`
- `novelty_level`: `N0-1 | N0-2 | N0-3 | N0-4C`
- `validity_level`: `V0 | V1 | V2 | V3 | V4`
- `claim_profile`: `THEORY | ALGORITHM | MIXED`
- `compute_stage`: `NOT_STARTED | S0 | S1 | S2 | S3 | S4 | STOPPED`
- Schema 2.0 新状态：`CLAIM_FREEZE | VALIDITY_AUDIT | INDEPENDENT_REVIEW |
  DIRECTION_LOCK | COMPUTE | POSTCOMPUTE_CLAIM_FREEZE |
  FINAL_VALIDITY_AUDIT | FINAL_LOCK`

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
规范化所在行、同一行同 term 的 ordinal 以 NUL 拼接后做 SHA-256。稿件或 epoch
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
          "output_sha256": "<sha256>"
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
          "output_sha256": "<sha256>"
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

若 `RANDOM_PROPERTY` 数学上不适用，删除该 witness，并在同一 obligation 加：

```json
"random_property": {
  "status": "NOT_APPLICABLE",
  "mathematical_reason": "<non-empty exact reason>",
  "independent_audit_acceptance": {
    "accepted": true,
    "reviewer_agent_id": "<same current independent reviewer>"
  }
}
```

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

强、fair、matched-budget、same-budget 主张至少由一个 comparator 覆盖：

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

## 7. `frontier_coverage.json`

```json
{
  "schema_version": "2.0",
  "axes": {
    "method_synonyms": ["<term>"],
    "target_tasks": ["<task>"],
    "theory_terms": ["<term>"],
    "algorithm_structures": ["<structure>"],
    "author_continuations": ["<route/result>"],
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

## 8. `audit_manifest.json`

profile 决定 entry roles：THEORY 至少含 `CLAIM_INVENTORY, MANUSCRIPT,
THEORY_OBLIGATIONS`；ALGORITHM 至少含 `CLAIM_INVENTORY, MANUSCRIPT,
PROTOCOL_CONTRACT, CLAIM_CODE_TRACE, IMPLEMENTATION, EXECUTABLE_TEST, TEST_OUTPUT`，
强基线再含 `BASELINE_CONTRACT`；MIXED 取并集。

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

Task 8 的计算证据文件可采用：

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
