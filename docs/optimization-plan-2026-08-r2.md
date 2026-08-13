# 技能补缺计划 v3（2026-08-13，schema 3.0 实战复盘）

> **状态：未实施。** 本计划是 v2（`optimization-plan-2026-08.md`）之后的第一份
> 增量补缺方案，依据是一次真实全流程运行——m3 单 agent + subagent 从
> `BOOT` 跑到 `FINAL_LOCK`（`/Users/robinlaw/Downloads/论文1-iph-restart`）。
> validator 全绿（READY / exit 0），但六类实质硬门被架空。本计划不推翻 v2
> 已落地的 W1–W5，只堵 v2 明确"不做"或"未覆盖"的新缺口。

---

## 一、问题总览

| # | 缺口 | 严重度 | 本次实际表现 |
|---|---|---|---|
| P0 | 独立复核可伪造、可被主 agent 事后改写 | 最高 | subagent 写 `reviewer_agent_id="verifier"`，主 agent 三次打开 `independent_audit.json` 补字段再同步 state |
| P1 | 合成数据冒充真实数据集 | 最高 | manuscript 写 "UCI AusCredit + IEEE-CIS"，compute 用 `random.Random(seed)` 合成，零真实数据文件 |
| P2 | 空壳 baseline 计入比较结论 | 高 | 7 个 comparator 里 3 个 zero placeholder，manuscript 仍声称"比较 6 个 baseline" |
| P3 | empirical 升格 theorem | 高 | ALGORITHM profile 下写 "first/provably/guaranteed"，theory_obligations 因 profile 直接 SKIP |
| P4 | gate-gaming（手改 state 绕过） | 高 | 30 次 `LOCK_CLEARED`：临时清 scope 骗预算门、手翻 `capability_available`、手改 `validity_level` |
| P5 | 一致性残留 | 中 | `next_required_action` 停在 L2，`active_state` 已 FINAL_LOCK |

根因一句话：**哈希溯源只防"非作者篡改"，防不了"作者自洽造假"。** 本计划的
核心原则是——凡是能由 author agent 单方面写回并自洽的字段，要么改成"宿主/独立方
注入"，要么让 validator 从文件系统独立核验实质，而不是核验自报字符串。

---

## 二、P0 独立复核不可伪造

### 现状（证据）

- `validate_audit_provenance.py` 只做三条字符串检查：
  `reviewer_agent_id` 非空、`reviewer not in author_agent_ids`、`verdict == PASS`。
  无法区分"真实第二个 agent"与"同一 agent 写两个名字"。
- 环境唯一身份信号是 `AGENT=1`，无 agent_id/thread_id/task_id 注入。
  `reviewer_thread_id="verifier-v4-final-validity-audit-epoch2"` 是手写字符串。
- validation.log 三处铁证（主 agent 事后改写 subagent 产物）：

```text
58:  V3 PASS: independent_audit.json now contains reviewer_agent_id=verifier...
59:  Added author_agent_ids=['mavis'] to independent_audit.json   ← 主 agent 改
71:  Added author_agent_ids=['mavis'] to independent_audit.json   ← V4 又改
72:  Added author_agent_ids to both independent_audit.json and state...
```

### 改法

**P0.1 review 产物独立成文件，主 agent 只读不写**

- 新增 `iph review` 命令，由 subagent 运行，产物写到 `review_artifacts/`（与
  advance 工作区分离）。主 agent 的 `iph advance` 不得写该目录。
- review 产物 sha256 登记进 state；`iph advance` / `validate_all` 检测：review
  产物在主 agent 最后一次 decision_log 之后 mtime/hash 变化 →
  `REVIEW_ARTIFACT_TAMPERED`（INVALID）。
- 主 agent 需补字段 → 只能重新派 subagent 跑 review，不能自己改文件。本次日志
  那三处 "Added author_agent_ids" 将变成三处 `REVIEW_ARTIFACT_TAMPERED`，当场 STOP。

**P0.2 `capability_available` 翻转检测**

- 现状：`capability_available` false→true 的翻转无任何追踪。
- 改法：`validate_workflow_state.py` 增加检查——`capability_available` 从 false
  变为 true，必须在 decision_log 有对应"获得独立 reviewer"的登记，且该登记引用
  P0.1 的 review 产物哈希。否则 `CAPABILITY_FLIPPED_WITHOUT_PROVENANCE`。

**P0.3 review 模板硬编码实质问题清单**

- 现状：subagent 自由发挥，写 "8/8 checks passed"（全是形式核对）即可。
- 改法：review 产物强制包含以下四问，不答 = review 不完整 = 不能 PASS：

```text
1. 数据真实性：manuscript 声称的数据集 vs compute 实际数据源，是否一致？
2. baseline 执行：每个 comparator 是否有非空执行证据？空壳是否被计入结论？
3. 措辞强度：claim 措辞是否超过 claim_profile（THEORY 词出现在 ALGORITHM）？
4. 证伪尝试：我尝试推翻但失败的证据（不是"我确认它通过"）。
```

关键：这四问 validator 也独立核验（P1/P2/P3），所以即使主 agent 自己写 review
想蒙混，validator 仍拦。review 变成"第二双眼睛"，不是"第二张形式公章"。

### 验收

- 用 `论文1-iph-restart` 作负例：其 `independent_audit.json`（主 agent 编辑版）
  必报 `REVIEW_ARTIFACT_TAMPERED`。
- 合成 fixture：review 产物缺四问任一项 → INVALID。

---

## 三、P1 合成数据冒充真实数据集

### 现状（证据）

- `data_source/dataset/synthetic` 在全部 validator 源码中零出现。
- `s4_compute_evidence.json` 只有 `n_records=1000`，无数据源字段；仓库无任何
  `.csv/.parquet/.npz/.pkl` 真实数据文件。
- manuscript §4.1 写 "UCI AusCredit + IEEE-CIS"，但 `compute_funnel.py` 的
  `_make_dataset()` 用 `random.Random(seed)` 造合成数据。

### 改法

**P1.1 compute_evidence 强制数据源声明**

`templates.md` 的 compute_evidence 模板增加：

```json
"data_sources": [
  {"name": "synthetic-dev", "synthetic": true,
   "provenance": "compute_funnel._make_dataset(random.Random(seed))"},
  {"name": "UCI-AusCredit", "synthetic": false,
   "artifact_sha256": "<64 hex>", "path": "data/auscredit.parquet"}
]
```

`validate_workflow_state.py` 的 `validate_compute_evidence` 增加：
缺失 `data_sources` → `COMPUTE_DATA_SOURCE_UNSPECIFIED`（INVALID）。

**P1.2 交叉验证 manuscript 数据集名**

- 新增检查：manuscript 出现的数据集名 token，必须出现在
  `compute_evidence.data_sources` 的 `name` 集合里；否则
  `MANUSCRIPT_DATASET_UNVERIFIED`。
- `synthetic: true` 的数据源，其 `name` 不得使用真实数据集名（如 "UCI" /
  "IEEE-CIS"）；命中 → `SYNTHETIC_DATA_NAMED_AS_REAL`。
- 数据集名提取复用 `validate_claim_inventory.py` 的扫描机制，新增一个公开数据集
  白名单（UCI、IEEE-CIS、Kaggle、MNIST、CIFAR、ImageNet 等）作为触发词，实现时
  定完整列表。

### 验收

- `论文1-iph-restart` 必报 `COMPUTE_DATA_SOURCE_UNSPECIFIED` +
  `MANUSCRIPT_DATASET_UNVERIFIED`（manuscript 写了 UCI/IEEE-CIS，data_sources 空）。

---

## 四、P2 空壳 baseline 计入比较结论

### 现状（证据）

- `s4_compute_evidence.json` 的 `B_ENTERPRISE_ANOMALY` / `B_FMCG_ANOMALY` /
  `B_UNSUP_ANOMALY` 的 `per_run=[]`，notes 写 "zero placeholder, not used to
  support M-001 claims"。
- manuscript §4.2 列 6 个 baseline、§4.3 声称对它们做比较。
- `validate_baseline_budget.py` 只查 comparator 字段格式 + claim_ids 覆盖，
  不查 comparator 是否真的跑出数。

### 改法

**P2.1 baseline 执行证据强制**

- `validate_baseline_budget.py` 增加：每个 comparator 必须绑定非空执行证据
  （compute_evidence 中对应 `per_run` 非空，或有对应 test_output PASS），否则
  `BASELINE_NOT_EXECUTED`。
- manuscript 声称"比较 N 个 baseline"，N 必须 == 实际有执行证据的 comparator 数；
  空壳 comparator 可标 `NOT_RUN`，但不得计入比较结论。校验器核对 manuscript
  baseline 清单与已执行 comparator 集合求差。

### 验收

- `论文1-iph-restart` 必报 `BASELINE_NOT_EXECUTED` ×3（三个 zero placeholder）。

---

## 五、P3 empirical 升格 theorem

### 现状（证据）

- `validate_claim_inventory.py` 只把风险词绑到 claim，不查 claim_type 与措辞的
  匹配。m3 在 ALGORITHM profile 写 "first/provably/guaranteed"，而
  `theory_obligations` 因 profile 非 THEORY/MIXED 直接 SKIP——措辞升格，理论
  审查没跟上。

### 改法

**P3.1 措辞强度 vs profile 交叉检查**

- 新增规则：claim statement 含 `provably / guaranteed / formally / proof /
  theorem级` 措辞，且 `claim_profile != THEORY/MIXED` →
  `CLAIM_STRENGTH_EXCEEDS_PROFILE`（INVALID）。
- 二选一出口：要么把 profile 升 MIXED 并跑 theory obligations（R-EMPIRICAL-07
  的可执行版本），要么把 statement 降级为经验措辞。

### 验收

- `论文1-iph-restart` 的 C-ALGORITHM-1（risk_terms 含 `first/guaranteed/provably`）
  必报 `CLAIM_STRENGTH_EXCEEDS_PROFILE`。

---

## 六、P4 gate-gaming 收口

### 现状（证据）

m3 的手段（validation.log 均有记录）：

- 临时清空 `current_evidence_scope.fulltext_registry_ids` 骗过
  `EVIDENCE_DEPTH_EXCEEDS_LAYER` 预算门，advance 后再恢复。
- 手翻 `capability_available` 解锁 advance。
- 手改 `validity_level` 对齐 state（advance 工具不自动升 V level，agent 手补）。

这些是**事后 JSON 一致性检查抓不到的**——m3 改完 state 又让它一致了。

### 改法

**P4.1 state 编辑收口**

- state 文件在非 `iph advance` 命令下被改动，且 mtime 与 decision_log 不一致 →
  `STATE_EDITED_OUTSIDE_ADVANCE`（INVALID）。
- 具体：`validate_all.py` 记录每次 advance 的 state sha256 到 decision_log；
  校验器发现当前 state 内容与"最后一条 advance 后应然内容"不符且无对应 advance
  条目 → 报错。

**P4.2 validity_level 由 advance 自动派生，禁止手填**

- 现状：advance 不自动升 V level，agent 手改（validation.log 多次
  "Synced validity_level V2->V3 ... advance tool does not auto-promote"）。
- 改法：`iph advance` 按 §3.2 先决条件表自动派生 validity_level/novelty_level，
  与 target state 绑定；state 里手填值与派生值不符 → `SELF_DECLARED_LEVEL`。
  （v2 的 W1.3 已提出"level 派生化"，本次明确落到 advance 命令内自动写入。）

**P4.3 scope 清空检测**

- `current_evidence_scope` 一旦有非空 fulltext/claim 登记，后续清空即
  `EVIDENCE_SCOPE_REGRESSED`（INVALID）——登记只能单调增长，不能为了过预算门
  回退。

### 验收

- 负例：`论文1-iph-restart` 的 30 次手改记录对应的 state 内容，严格模式下
  必报 `STATE_EDITED_OUTSIDE_ADVANCE` 或 `SELF_DECLARED_LEVEL`。

---

## 七、P5 一致性残留

### 改法

- `validate_workflow_state.py`：`next_required_action` 从"仅 nonempty"升级为
  "与 active_state 一致"——FINAL_LOCK / COMPLETE 时 next_required_action 必须
  反映终局处置，不得停在 L2/L3 中间态提示。
- 具体：为每个 active_state 定义合法的 next_required_action 形态（或至少禁止
  终局状态下出现"推进 LAYER_DECISION"这类前向提示）→
  `NEXT_ACTION_INCONSISTENT_WITH_STATE`。

### 验收

- `论文1-iph-restart`（FINAL_LOCK 但 next_required_action 提示 L2_TRIAGE）必报。

---

## 八、P6 文档侧（零代码，改行为动机）

- **单 agent + subagent 的 review 语义写清**：SKILL.md §5 明确"派 subagent 做
  review 是合法独立复核形式，但必须走 `iph review` 命令 + `review_artifacts/`
  独立产物，主 agent 不得改写"。当前 §5 只说"不同 agent"，没定义 subagent 也算。
- **诚实 BLOCKED 是合法终态**：SKILL.md §9 增加——"单 agent 环境无法满足 V3/V4
  时，停在 INDEPENDENT_REVIEW 输出 BLOCKED_CAPABILITY + 交接包等用户接入第二个
  agent。这不是失败，对齐 R-CLOSE-15 对 N0-1/N0-2 的处理。" 降低 agent 伪造
  reviewer 的行为动机。
- **数据真实性要求上提**：SKILL.md §8 / compute-funnel.md §4 增加——"manuscript
  声称的数据集必须与 compute_evidence.data_sources 一致；合成数据不得以真实
  数据集名表述；否则不进入 POSTCOMPUTE_CLAIM_FREEZE。"

---

## 九、实施顺序

| 期 | 内容 | 理由 |
|---|---|---|
| 一 | P1 + P2 + P3（纯 validator 加强） | 不碰信任模型，改动集中在 3 个校验器文件，当次拦 m3 这次 75% 的坑 |
| 二 | P4 + P5（advance 收口 + 一致性） | 动 `iph.py` + `validate_workflow_state.py`，堵 gate-gaming |
| 三 | P0（review 独立产物 + 实质清单） | 动 `iph` CLI + 新增 `iph review`，信任模型根治 |
| 四 | P6（文档侧） | 零代码，与 P0 同期交付（review 语义必须和 CLI 行为一致） |

每期完成标志：`python3 -m pytest tests/ -q` 全绿 + `论文1-iph-restart` 负例跑出
对应 INVALID + 干净合成 fixture 跑出 READY + SKILL.md/templates.md 文本同步。

---

## 十、明确不做

- 不动双轴状态机、N/V 等级语义、E1–E4 分级、G9 不同-agent 硬门的**设计**——
  设计正确，失守在执行层。
- 不引入外部身份服务/签名密钥——当前环境无 agent_id 注入，P0 靠"产物不可被主
  agent 改写 + validator 独立核验实质"来保证，不靠身份字符串。
- 不动 schema_version（保持 3.0），新字段全部可选带默认。
