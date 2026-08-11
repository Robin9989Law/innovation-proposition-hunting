# 文献—观点—输出证据流水线

本文件定义近邻检索、真实性核验、全文归档、观点注册、输出结论支持和碰撞轮次
之间的强制数据合同。配合 [SKILL.md](SKILL.md) 使用。

## 目录

1. [固定执行顺序](#1-固定执行顺序)
2. [近三年前沿窗口](#2-近三年前沿窗口)
3. [文献真实性与下载](#3-文献真实性与下载)
4. [近邻文献 JSON](#4-near_neighbor_registryjson-增补字段)
5. [重要观点 JSON](#5-literature_claim_registryjson)
6. [输出结论支持 JSON](#6-output_claim_supportjson)
7. [可追溯引用链](#7-可追溯引用链)
8. [旧观点耗尽门](#8-旧观点耗尽门)
9. [验证命令](#9-验证命令)

本文件中的三个 JSON 注册表均使用 `schema_version: "2.0"`。旧 1.x 注册表不能
通过 Schema 3.0 的 workflow_state readiness；必须先迁移状态并重建当前 epoch
的证据合同。

## 1. 固定执行顺序

每个新主题和每轮新碰撞严格按下列顺序执行，不得并步或倒置。旧观点耗尽是
**开轮预检**，不是本轮末尾的善后动作：

```text
P0 读取 workflow_state.json；耗尽所有 prior-round 旧观点
  → P1 近三年近邻检索，或核验同 scope/同年份的已验证快照
  → P2 near_neighbor_registry.json 即时注册并核验真实身份
  → P3 下载 IMPORTANT/CRITICAL 近邻全文并校验文件
  → P4 literature_claim_registry.json 原子化注册观点/结论/方法
  → P5 仅用已注册观点构建研究链、K→U→Δ 和碰撞综合
  → P6 output_claim_support.json 逐条绑定输出结论
  → P7 验证机器状态与完整引用链
  → P8 完成本轮裁决并更新 workflow_state.json
  → 若开启下一轮，collision_round +1 并返回 P0
```

首轮没有更早观点时，P0 以 `prior_round_claims_drained=true` 通过。任何一步失败，
停留在当前步。不得以“之后补录”进入下一轮碰撞，也不得先搜索新文献再回头处理
旧观点。

## 2. 近三年前沿窗口

设当前年份为 (Y)，强制首轮窗口为 `[Y-2, Y]`，包含上下界。当前为 2026 年，
窗口就是 2024–2026。年份变化时动态滚动，不把 2024–2026 永久写死。

规则：

- 每个主题先完成 `RECENT_FRONTIER_PASS`，再向更早年份回溯基础工作；
- scope、当前年份、查询覆盖和版本链均未变化，且既有快照已通过验证时，可记录
  `REUSED_VERIFIED_SNAPSHOT` 并复用；任一项变化都必须做有界刷新；
- 旧文献不能替代近三年检索；只有近期文献指向的理论前驱、必要定义、版本链或
  决定性证明，才进入 `FOUNDATIONAL_BACKFILL`；
- 当前年度尚未正式出版的相关预印本仍登记，但保持预印本资格，不承担终局判死；
- 保存查询式、数据库、过滤条件、执行日期和命中数；
- `recent_window.status != COMPLETE` 时，不得开始候选碰撞。

`near_neighbor_registry.json` 顶层保存：

```json
{
  "schema_version": "2.0",
  "current_year": 2026,
  "recent_window": {
    "start_year": 2024,
    "end_year": 2026,
    "status": "COMPLETE",
    "completed_at": "2026-08-07",
    "queries": [
      {"database": "OpenAlex", "query": "...", "filters": "from:2024,to:2026", "hit_count": 0}
    ]
  },
  "current_collision_round": 1,
  "records": []
}
```

## 3. 文献真实性与下载

### 3.1 真实性核验

每篇文献只有同时满足以下条件才标记 `identity_status = VERIFIED`：

- 规范题名、作者、年份一致；
- DOI、出版社文章页、官方 proceedings ID、PubMed ID 或 arXiv ID 至少有一个
  可验证标识；
- `identity_verification_url` 指向官方或权威元数据入口；
- 预印本、会议版、期刊版关系已显式记录；
- 未从搜索摘要猜测作者、年份、卷期、DOI 或同行评审状态。

`STATUS_UNVERIFIED` 文献可以暂存为线索，但不能支持最终输出结论、N0 裁决或
关闭决定。无法核验的记录不得静默删除，须保留失败原因。

### 3.2 重要性分级与下载

```text
CRITICAL：最危险直接近邻、决定性反例、终局覆盖或关键理论前驱
IMPORTANT：研究链关键推进、主要方法/基线、支持 K/U/Δ 的核心工作
CONTEXT：背景或关键词近邻
```

`CRITICAL/IMPORTANT` 必须下载合法可访问的 PDF 或官方 HTML 到
`literature_archive/`。下载后：

- 核对文件内题名、作者和版本与 registry 记录一致；
- 保存下载来源、时间、本地相对路径和 SHA-256；
- 标记 `FULLTEXT_ARCHIVED` 或 `OFFICIAL_HTML_ARCHIVED`；
- 付费墙或权限阻断时标记 `DOWNLOAD_BLOCKED` 并记录原因，不绕过访问控制；
- `DOWNLOAD_BLOCKED` 的重要文献不能进入 E2/E4，也不能支持最终结论；找到合法
  作者稿或官方 HTML 后再升级同一记录。

### 3.3 source artifact kind 与 evidence level

每条 literature claim 必须明确它实际读取的 artifact，不得把 work 的最佳可用版本
冒充本条 claim 的来源：

| `source_artifact_kind` | 可承担的证据 |
|---|---|
| `OFFICIAL_METADATA` | 身份、出版和版本信息；仅 E0 |
| `OFFICIAL_ABSTRACT` | 自我定位与碰撞发现；至多 E1 |
| `FULL_ARTICLE_HTML` | 完整正文；可到 E2，带 proof locator 时可到 E4 |
| `FULL_ARTICLE_PDF` | 完整正文；可到 E2，带 proof locator 时可到 E4 |
| `PROOF_OR_APPENDIX` | 证明/附录的直接 artifact；可到 E4 |

E2 只能来自 `FULL_ARTICLE_HTML | FULL_ARTICLE_PDF`。E4 必须来自
`PROOF_OR_APPENDIX`，或来自 full article 且 `proof_locator` 明确覆盖证明机器。
metadata/abstract 即使内容看似完整，也不得标 E2/E4。

## 4. `near_neighbor_registry.json` 增补字段

在既有 canonical work 记录中加入：

```json
{
  "registry_id": "W-0001",
  "canonical_title": "...",
  "authors": ["..."],
  "year": 2026,
  "persistent_ids": {"doi": "", "openalex": "", "arxiv": ""},
  "identity_status": "VERIFIED | UNVERIFIED",
  "identity_verification_url": "https://...",
  "identity_verified_at": "2026-08-07",
  "search_phase": "RECENT_FRONTIER_PASS | FOUNDATIONAL_BACKFILL",
  "importance": "CRITICAL | IMPORTANT | CONTEXT",
  "importance_history": [
    {"importance": "CRITICAL", "at": "2026-08-07", "reason": "direct neighbor"}
  ],
  "reclassifications": [],
  "download": {
    "status": "FULLTEXT_ARCHIVED | OFFICIAL_HTML_ARCHIVED | DOWNLOAD_BLOCKED | NOT_REQUIRED",
    "source_url": "https://...",
    "local_path": "literature_archive/W-0001.pdf",
    "sha256": "...",
    "downloaded_at": "2026-08-07",
    "verified_against_metadata": true,
    "block_reason": ""
  },
  "claim_extraction_status": "COMPLETE | PARTIAL | NOT_STARTED"
}
```

要求：

- `year` 落入近三年窗口时，`search_phase` 必须是 `RECENT_FRONTIER_PASS`；
- `importance_history` 是 append-only；当前 `importance` 必须等于最后一项；
- `CRITICAL/IMPORTANT` 必须身份已核验、全文已归档且观点提取完成；
- `CONTEXT` 可以只保留元数据，但不能越级支持最终输出结论；
- 论文记录只证明“哪篇文献存在”，不直接替代观点证据。

任何 `CRITICAL | IMPORTANT → CONTEXT` 降级都必须在 history 追加新事件，并有
且仅有一个 matching `reclassifications` 记录：

```json
{
  "from_importance": "CRITICAL",
  "to_importance": "CONTEXT",
  "at": "2026-08-08",
  "fulltext_artifact_id": "ART-W-0001-FULLTEXT",
  "evidence_level": "E2",
  "reviewer_agent_id": "<different agent>",
  "reviewer_thread_id": "<thread id>",
  "audited_artifact_sha256": "<sha256>"
}
```

`fulltext_artifact_id` 必须指向同一 work 已注册、证据级一致的 fulltext claim
artifact；reviewer 不得是 state 的 author。`DOWNLOAD_BLOCKED` 或能力不足绝不能作为
降级理由：保持原 importance 并返回 BLOCKED。

## 5. `literature_claim_registry.json`

一条记录只承载一个可判断的原子观点。不要把整篇摘要复制成一个观点，也不要把
多个条件和结论混成一条。

```json
{
  "schema_version": "2.0",
  "current_collision_round": 1,
  "records": [
    {
      "claim_id": "LC-0001",
      "source_registry_id": "W-0001",
      "source_artifact_id": "ART-W-0001-FULLTEXT",
      "source_artifact_kind": "FULL_ARTICLE_PDF",
      "claim_type": "VIEWPOINT | CONCLUSION | METHOD | ASSUMPTION | LIMITATION | COUNTEREXAMPLE",
      "normalized_statement": "在条件 C 下，方法 A 相对基线 B 改善目标 T。",
      "source_excerpt": "可选的短原文片段",
      "locator": {
        "page": "7",
        "section": "4.2",
        "paragraph": "3",
        "theorem": "",
        "table": "2",
        "figure": "",
        "algorithm": ""
      },
      "conditions": ["C"],
      "scope": "对象、信息边界与实验条件",
      "evidence_level": "E2",
      "proof_locator": "",
      "verification_status": "VERIFIED_FULLTEXT | VERIFIED_OFFICIAL_HTML | ABSTRACT_ONLY | UNVERIFIED",
      "support_role": "SUPPORTS | CONTRADICTS | QUALIFIES | METHOD_FOR",
      "importance": "CRITICAL | IMPORTANT",
      "discovered_round": 1,
      "use_status": "UNUSED | USED | EXCLUDED_WITH_REASON",
      "used_by_output_claim_ids": [],
      "used_in_collision_ids": [],
      "exclusion_reason": ""
    }
  ]
}
```

硬约束：

- `source_registry_id` 必须存在于文献注册表；
- `VERIFIED_FULLTEXT/VERIFIED_OFFICIAL_HTML` 必须有精确 locator；
- 方法记录须写输入、输出、关键步骤、比较基线或适用条件，不能只写方法名；
- 结论记录须保留条件、量词、分母和基线，不能把相关性扩大为因果；
- `ABSTRACT_ONLY/UNVERIFIED` 只能发现碰撞，不能支持最终输出结论；
- 原文短引只作定位，主要保存准确释义，避免大段复制。

## 6. `output_claim_support.json`

“输出结论”包括：研究链总结、覆盖判断、差异判断、K/U/Δ、创新性判断、N0
裁决、方法比较、关闭理由和最终回答中的事实性结论。

```json
{
  "schema_version": "2.0",
  "current_collision_round": 1,
  "output_claims": [
    {
      "output_claim_id": "OC-0001",
      "statement": "...",
      "output_location": "L3_novelty_audit.md#...",
      "claim_kind": "FACT | SYNTHESIS | METHOD_COMPARISON | NOVELTY_VERDICT | CLOSURE | PROPOSITION_RATIONALE",
      "supporting_claim_ids": ["LC-0001"],
      "counter_claim_ids": [],
      "inference_type": "DIRECT | SYNTHESIS | CONTRAST | INFERENCE",
      "reasoning": "说明这些来源观点如何推出本结论，而不是只列文献。",
      "caveats": "",
      "trace_status": "VERIFIED | INCOMPLETE"
    }
  ],
  "collision_gate": {
    "prior_round_claims_drained": true,
    "unused_prior_claim_ids": [],
    "checked_at": "2026-08-07"
  }
}
```

硬约束：

- 每个输出结论至少绑定一个 `supporting_claim_id`，只有 work ID 或引用列表不合格；
- `SYNTHESIS/CONTRAST/INFERENCE` 必须填写 reasoning，区分来源事实与自己的推理；
- 不得让来源观点承担超出其条件、对象、量词或证据级的结论；
- 有直接反证或限定观点时登记到 `counter_claim_ids` 并写 caveat；
- `trace_status = VERIFIED` 只有在全部观点和文献链可回溯时成立。

## 7. 可追溯引用链

每条最终引用必须能机械展开为：

```text
OC-输出结论
  → LC-来源观点/结论/方法
    → W-canonical 文献记录
      → locator（页/节/段/定理/表/图/算法）
        → literature_archive 本地全文及 SHA-256
          → DOI/出版社/proceedings/arXiv 官方身份入口
```

禁止：

- 输出只挂一个 DOI，却没有指出支持它的具体观点；
- 观点没有 locator；
- 本地 PDF 与文献元数据不一致；
- 引用二手综述来冒充原始结论，除非输出明确只讨论综述观点；
- 使用不存在、题名拼接、作者错配或 DOI 无法核验的文献。

## 8. 旧观点耗尽门

“新碰撞”指新建或实质改变候选 L3、目标研究链、覆盖理论、关键比较基线，或对
新的 O/I/A/T/C/R/B 组合执行覆盖判断。仅补同一候选的页码、证据等级或措辞不
增加轮次。不得通过保留旧轮次编号绕过耗尽门。

启动碰撞轮次 `r` 前，所有 `discovered_round < r` 且仍在当前 scope 内的重要观点
必须满足以下之一：

- `USED` 且至少关联一个 `used_by_output_claim_id` 或 `used_in_collision_id`；
- `EXCLUDED_WITH_REASON` 且说明重复、越界、被更高等级证据取代或身份核验失败。

不得把“不利于当前候选”作为排除理由。只要存在一个 prior-round `UNUSED` 观点，
`prior_round_claims_drained` 必须为 false，新碰撞不得开始。新搜索不能用来逃避旧
观点的综合、反证或吸收。

旧观点“已使用”不等于必须写入正文；作为反证、限定、方法吸收、关闭依据或明确
排除均算处理，但必须留有 ID 和理由。

## 9. 验证命令

每次续跑、检索、观点提取、输出更新、裁决以及新碰撞前运行：

```bash
python3 scripts/validate_all.py \
  --root <研究目录> \
  --state <研究目录>/workflow_state.json
```

总校验器自动按状态运行 `validate_workflow_state.py`、
`validate_literature_registry.py` 和 `validate_evidence_chain.py` 中已经到期的
检查。从 `EVIDENCE_VALIDATE` 起三项必须全部零错误。任一应运行脚本非零退出时，
不得给出 PASS、FAIL、LOCKED、CLOSED 或启动新碰撞。
