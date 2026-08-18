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

顶层 `artifacts` 与日志中的 `artifacts` 是两个互补合同：顶层对象保存 validator
解析工件所需的稳定路径指针，日志数组保存状态完成时不可变文件的 SHA-256 锚点。
推进必须同时使用 `iph advance --set-artifact key=path --artifact path` 原子登记，
并用 `--next-action` 替换上一状态的恢复动作；日志有哈希不等于顶层已有路径。
旧版推进若因此在 post-validation 进入 STOP，只能用
`iph clear-lock --set-artifact key=path --next-action "..." --recovery-note "..."`
受控修复后重验，不得直接编辑 `workflow_state.json`。漏写机械完成门时，同一
命令可加 `--set-gate output_claims_traced=true` 或 `evidence_validated=true`，
且 decision_log 必须已有对应完成状态；不得用此入口改 `n0_4_locked`。
若外部阻塞本身已经由 operator 修复且 `active_state=BLOCKED`，必须显式使用
`iph clear-lock --resume-blocked --next-action "..." --recovery-note "..."` 原子恢复
到 `resume_state`；恢复校验失败时 CLI 会逐字节还原 state、STOP 锁与 validation log。

`recent_frontier_complete=true` 是一个复合原子门：同一次 `iph advance` 必须用
`--set-artifact literature_registry=<path>` 登记最近前沿账本。CLI 会从该账本的
`recent_window` 校验并同步 `start_year`、`end_year`、`status` 与 `snapshot_mode`；
协调 agent 不得手工猜测或直接改写这些字段。

裁决与后半程状态变化采用目标专属原子参数：

```text
EVIDENCE_VALIDATE -> N0_AUDIT:
  --novelty-level N0-1|N0-2|N0-3|N0-4C
  --set-gate n0_4_locked=false|true
CLAIM_FREEZE -> VALIDITY_AUDIT:
  --claim-bundle-manifest audit_manifest.json（CLI 派生 V1 并登记当前 epoch bundle）
VALIDITY_AUDIT -> INDEPENDENT_REVIEW: CLI 派生 V2
DIRECTION_LOCK -> COMPUTE:
  --authorize-compute --authorization-note <用户授权依据>（CLI 派生 S0）
COMPUTE -> POSTCOMPUTE_CLAIM_FREEZE:
  --compute-evidence compute_evidence.json（必须声明 S4）
POSTCOMPUTE_CLAIM_FREEZE -> FINAL_VALIDITY_AUDIT:
  --claim-bundle-manifest audit_manifest.json（manifest epoch 必须恰好 +1）
INDEPENDENT_REVIEW FAIL:
  iph reopen-validity-epoch（epoch+1，退回 CLAIM_FREEZE，N0 不变）
iph review --verdict PASS：镜像 independent_audit 并升 V3/V4
COMPUTE 内：iph advance-compute-stage --to S1|S2|S3|S4
```

N0-1/N0-2/N0-3 时 `n0_4_locked=false`；只有 N0-4C 才为 true。CLI 拒绝跳态、
拒绝把上述参数用于其他目标，并在新 epoch 切换时清空旧 independent audit，避免
出现“模型读懂了但没有合法 state 写入口”的执行死锁。

- `at`：UTC ISO-8601；条目时间单调不减，且不得晚于 state 文件自身写入时刻
  （校验器以 mtime 交叉核验，未来时间或晚于写入时间即判伪造）。
- `state`：必须是状态机中的状态；BLOCKED 期间的条目用 `BLOCKED@<STATE>`。
- `artifacts`：本状态新产/变更的产物及 SHA-256；登记后内容再变即判
  `STALE_DECISION_ARTIFACT`。无产物变更的状态可省略此字段。
- **只锚定不可变产物**：会随后续状态或 epoch 合法重写的文件
  （`independent_audit.json`、`compute_evidence.json`、`validation.log` 等）由
  state 指针对账，不登记进条目 `artifacts`——否则下一次合法重写立即触发
  `STALE_DECISION_ARTIFACT`，逼出无谓的 epoch 重建（2026-08 神经符号 epoch-2
  教训）。条目只锚定"本状态冻结后不再变"的产物。
- **epoch 失效后的日志重建约定**：被取代的 state 文件改名保留为
  `workflow_state.<tag>.superseded`；重建条目在 `action` 统一标注 replay 标签
  （如 `replay3`），`at` 用重建时刻的真实 UTC——不得回填虚构的历史时刻；
  重建只修复条目锚定与记账结构，不改写已冻结产物的内容与哈希。
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

route 同样可以用 `status=BLOCKED` 和完整 capability 对象诚实记录失败尝试。若不足
两条可用 independent route 或不足两种 route type，这类能力缺失会使校验 BLOCKED；
已满足 quorum 时，额外不可用 route 只作为 WARNING/coverage gap 保留，不计入成功覆盖。

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
  "review_answers": {
    "data_authenticity": "<manuscript 声称的数据集 vs compute 实际数据源，是否一致>",
    "baseline_execution": "<每个 comparator 是否有非空执行证据；空壳是否被计入结论>",
    "claim_strength": "<claim 措辞是否超过 claim_profile，THEORY 词是否出现在 ALGORITHM>",
    "falsification_attempt": "<我尝试推翻但失败的证据，不是『我确认它通过』>"
  },
  "audited_at": "<ISO-8601>"
}
```

reviewer 不能在 author list 中。能力不可用时写 `capability_available=false` 并返回
BLOCKED；不得伪造 reviewer、thread、PASS 或 bundle。

`verdict=PASS` 且 `capability_available=true` 时，`review_answers` 四个键
（`data_authenticity` / `baseline_execution` / `claim_strength` /
`falsification_attempt`）必须全部非空，缺一即 `REVIEW_ANSWERS_INCOMPLETE`。这四问
是实质复核，不是形式核对；写"已确认通过""8/8 通过"等空话等于未答。

`INDEPENDENT_REVIEW` / `FINAL_VALIDITY_AUDIT` 刚进入且 state 中
`independent_audit={}` 时表示 reviewer pending：作者 bundle 继续严格验证，但审计
provenance 暂不要求。reviewer 必须创建并封印自己的 artifact（替换审计放在
`review_artifacts/`）；`iph review` 会原子登记 state pointer、运行时 agent/thread、
artifact hash 和 V3/V4。下一状态不接受 pending。

## 10. `compute_evidence.json` 与 state pointer

S4 完成后的计算证据文件可采用：

```json
{
  "schema_version": "2.0",
  "compute_stage": "S4",
  "verdict": "PASS",
  "data_sources": [
    {"name": "UCI-AusCredit", "synthetic": false, "artifact_sha256": "<sha256 或省略>"},
    {"name": "synthetic-dev", "synthetic": true, "provenance": "<生成方式，如 compute_funnel._make_dataset>"}
  ]
}
```

`data_sources` 是**唯一权威**的数据来源声明：manuscript 出现的真实数据集名必须
能在此找到对应的非合成条目。`synthetic: true` 的源不得使用真实数据集名
（`SYNTHETIC_DATA_NAMED_AS_REAL`）。缺 `data_sources` 即
`COMPUTE_DATA_SOURCE_UNSPECIFIED`。manuscript 声称了真实数据集名但
`data_sources` 无对应非合成条目即 `MANUSCRIPT_DATASET_UNVERIFIED`。

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
经授权的实例探针数字（`instance_probe_registry.json`）同样豁免，可以进入
novelty-audit；它们不是探索级泄漏。

## 12.1 `instance_probe_registry.json`

仅 `N0_AUDIT / N0-3 / V0` 且用户已 `iph authorize-instance-probe`。最多 5 条。
不打开 `compute_authorized`。

```json
{
  "schema_version": "2.0",
  "authorization_note": "<用户允许小范围看实例的依据>",
  "authorized_at": "<ISO-8601 UTC>",
  "probes": [
    {
      "probe_id": "IP-0001",
      "purpose": "COUNTEREXAMPLE",
      "source_registry_id": "W-0007",
      "locator": "Figure 6",
      "published_text": "<已发表原句或作者给出的 informalised 句>",
      "metric": "quan_sentence_similarity",
      "value": 0.8127,
      "old_metric_verdict": "UNDEFINED",
      "success_rule": "",
      "boundary_lost": ["condition"],
      "g4_role": "OLD_STOP_STILL_SCORES",
      "output_file": "instance_probes/IP-0001.json",
      "output_sha256": "<sha256>"
    }
  ]
}
```

`old_metric_verdict=SUCCESS` 时 `success_rule` 必填，且不得把数据集总体分数 /
Figure 4 均值当成单条阈值（`INSTANCE_PROBE_MEAN_AS_THRESHOLD`）。

`g4_role` 仅允许：

```text
OLD_STOP_STILL_SCORES   旧停止规则在该实例上仍给出分数/输出
NEW_STOP_FAIL           新停止规则在该实例上失败
DESIGN_WALKTHROUGH      设计走查，不能单独支撑 N0-4C
NOT_A_THRESHOLD         已发表数字不是成功阈值（如表中 POSSIBLE）
RECONSTRUCTION          跨系统推断（如「另一方法也会接受」），不能单独支撑 N0-4C
```

N0-4C 下已登记探针必须带角色；全部为 `DESIGN_WALKTHROUGH` /
`NOT_A_THRESHOLD` / `RECONSTRUCTION` 即 `G4_WALKTHROUGH_ONLY`。
`purpose=COUNTEREXAMPLE` 不得使用 `NOT_A_THRESHOLD`。登记入口：
`iph register-instance-probe --g4-role ...`。

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

## 15. `novelty-audit.md`

N0_AUDIT 阶段的权威裁决产物。裁决一个候选是否为 N0-4C 之前，必须先完成
**证伪书（falsification ledger）**——逐条列出"我尝试杀死这个候选的方式，以及
每种方式为何失败"。证伪优先：候选存活是"证伪失败后的残留"，不是"未被注意的
空缺"。

```markdown
# Novelty Audit — <candidate-id>

## 证伪书（falsification ledger）

> 进入 N0-4C 前必填。逐条列出你尝试杀死该候选的方式及失败原因，至少一条。
> 每条点明证伪路径 + 目标近邻 + 失败原因。

- [证伪路径] 直接占据：<近邻 W-XXXX 为何没有直接占据候选>
- [证伪路径] 机械归约：<候选为何不能由近邻结果加约束/换分母推出>
- [证伪路径] 换名检测：<候选为何不是近邻的术语换名>

## N0 评估综合

| 近邻 ID | 距离 | N0 | 关键观察 |
|---|---|---|---|

## N0 裁决

- novelty_level = N0-4C / N0-1 / N0-2 / N0-3
- 证伪书完成度：<N 条证伪尝试，全部失败>
```

负面终局（N0-1 / N0-2）与正面终局同严：裁决为 N0-1 时，`证伪书` 节替换为
`占据证据（occupation evidence）`；裁决为 N0-2 时替换为
`归约证据（reduction evidence）`。二者同样要求标题 + 至少一条条目：

```markdown
## 占据证据（occupation evidence）

- [占据] <近邻 W-XXXX> 已在 <年份> 直接提出并验证同一候选，覆盖了 <主张>

## 归约证据（reduction evidence）

- [归约] 候选 = <近邻结果 W-XXXX> + <约束/换分母/拼接>，机械可推出
```

validator 识别标记：`证伪书`/`falsification`、`占据证据`/`occupation evidence`、
`归约证据`/`reduction evidence` 三类标题，且各自标题后至少一条对应条目。
缺对应节分别报 `FALSIFICATION_LEDGER_MISSING` / `OCCUPATION_EVIDENCE_MISSING` /
`REDUCTION_EVIDENCE_MISSING`（默认 WARNING，`--strict-new-checks` 升 INVALID）。

只改 L3 精确句、不改 L1/L2/K 时，不得 `start-collision-round`。唯一写入口：

```bash
python3 <skill>/scripts/iph.py revise-exact-statement \
  --root <研究目录> --state <研究目录>/workflow_state.json \
  --path l3-exact.rN.md --note "<改句理由>"
```

仅接受 `N0_AUDIT / N0-3 / V0`。同轮保留 L1/L2/K 门，只重置输出/证据/`n0_4_locked`，
并把 `artifacts.exact_statement` 指到新文件，状态跳回 `SYNTHESIZE_COLLISION`。
已锁定的 N0-4C 须先 `retract-novelty`。

## 16. `l3_contract.json`

ALGORITHM / MIXED 锁定 N0-4C 前必须声明：每个停止轴是哪些输入或生成物的函数。
缺文件报 `L3_CONTRACT_MISSING`；`depends_on` 不在 `inputs ∪ generated` 报
`AXIS_NOT_IN_INPUT`。`p` 是映射输出，应列入 `generated`，不得冒充输入。
exact 句出现 `p_loc` / `(src_span` 却未声明 `p`，同样报 `AXIS_NOT_IN_INPUT`。

```json
{
  "schema_version": "2.0",
  "inputs": ["s", "I"],
  "generated": ["p"],
  "stop_axes": [
    {"name": "identity", "depends_on": ["s", "I"]},
    {"name": "two_sided_certificate", "depends_on": ["s", "p"]}
  ]
}
```

身份若只写输入 `s`、却依赖词表 `I`，不得声称可执行。空输入上的恒等不得 PASS。

## 17. `composition_audit.json`

ALGORITHM / MIXED 锁定 N0-4C 前必须拆开候选，并登记三种必做接线。只杀死
「后贴标签」一种弱接线不得锁。缺文件报 `COMPOSITION_AUDIT_MISSING`；
`union_equals_candidate=true` 报 `COMPOSITION_REDUCES`。

```json
{
  "schema_version": "2.0",
  "candidate_id": "M",
  "components": [
    {
      "component_id": "source_inventory",
      "neighbor_ids": ["W-0004"],
      "neighbor_fragment": "post-hoc factuality labels on extracted triples",
      "mechanical_gap": "source-first inventory is not post-hoc labeling of extracted triples"
    }
  ],
  "wirings": [
    {
      "wiring_id": "posthoc_label",
      "kind": "POSTHOC_LABEL",
      "procedure": "run the neighbor then glue labels",
      "status": "KILLED",
      "kill_claim_ids": ["LC-0001"],
      "whole_mapping_separates": true
    },
    {
      "wiring_id": "schema_extension",
      "kind": "SCHEMA_EXTENSION",
      "procedure": "add fields to the output schema and reuse neighbor provenance",
      "status": "KILLED",
      "kill_claim_ids": ["LC-0002"],
      "whole_mapping_separates": true
    },
    {
      "wiring_id": "rename",
      "kind": "RENAME",
      "procedure": "reverse the neighbor provenance pair",
      "status": "KILLED",
      "kill_claim_ids": ["LC-0003"],
      "whole_mapping_separates": true
    }
  ],
  "strongest_remaining": "",
  "union_equals_candidate": false,
  "reduction_failed_because": "each required wiring was killed on a whole-mapping published separation"
}
```

`kind` 必做：`POSTHOC_LABEL` / `SCHEMA_EXTENSION` / `RENAME`。`status` 为
`KILLED | ALIVE | NOT_ATTEMPTED`。N0-4C 时任一种未尝试、仍活、或
`strongest_remaining` 非空，报 `WIRING_NOT_ATTEMPTED` / `WIRING_STILL_ALIVE`，
`iph advance --novelty-level N0-4C` 直接拒绝。`KILLED` 必须有非空
`kill_claim_ids` 且 `whole_mapping_separates=true`，否则 `SEPARATION_NOT_WHOLE`。
单轴 NA 或「若缺字段则 FAIL」的设计例子不算整体分离。每块仍须非空
`mechanical_gap`。只写「合取不是相同词语」不算完成。
