# Hierarchy status — 面向算电协同的多目标调度优化研究

- research version/topic：算电协同多区域算—储—电协同多目标调度（华数杯 C 题，目标《科研管理》）
- output_type：JOURNAL_ARTICLE
- contribution_contract：ONE_MAIN_M
- active_layer：L1（已确认）
- active_contribution：NONE（L1 阶段）
- 当前裁决层级：仅 L1
- scope_lock：`scope_lock.md`（2026-08-10 冻结，用户确认 R3+F3、基线 B1–B4）

## PRIOR_CLAIM_DRAIN（round 1，2026-08-10）

- prior-round 观点数：0（首轮）；`prior_claims_drained = true`

## RECENT_FRONTIER（2024–2026，2026-08-10 完成）

- 检索源：OpenAlex（api_key）、arXiv API、Crossref、Unpaywall、web_search、**CNKI（cnki-search v2.1.0，kns8s）**；3 条独立 route（2×DISCOVERY + 1×CITATION_GRAPH）+ CNKI 检索补充
- 注册 39 篇近邻：7 CRITICAL / 28 IMPORTANT / 4 CONTEXT；2 篇 FOUNDATIONAL_BACKFILL
  - 国际 20 篇：3 CRITICAL（Han TIA 2026 / Shao EPSR 2026 / ARX-02 微电网 MILP）/ 14 IMPORTANT / 3 CONTEXT
  - 中文 19 篇（知网，2024–2026 期刊）：4 CRITICAL 调度建模族（冯洪赟/向梓旸/鲍兴川/张良）+ 11 IMPORTANT 建模族（王泽军/杨蒙综述/张硕-系统工程理论与实践/王鹏/董亚晗/刘方/凃陈/马丁/付智/梁秀壮/房方）+ 3 IMPORTANT 政策实证族（裴馨-中国人口·资源与环境/于潇宇-宏观经济研究/陈晓红-中国工程科学）+ 1 CONTEXT（李征召）
- 归档 9 份合法全文（SHA-256 核验一致）；提取 14 条原子观点（E2、locator，全部来自国际归档全文）
- 阻断：29 篇 CRITICAL/IMPORTANT 无合法全文（10 国际付费墙 + 19 知网机构订阅）→ `DOWNLOAD_BLOCKED` 保持重要性，状态 BLOCKED（resume=IMPORTANT_FULLTEXT）
- 校验：schema_v2 READY；frontier_integrity READY；literature_registry READY；workflow_state BLOCKED(2，29 blockers)；evidence_chain INVALID(1，全部源于阻断文献)

## 文件树（main 分支）

```
workflow_state.json             # schema 2.0 状态机（BLOCKED @ IMPORTANT_FULLTEXT）
scope_lock.md                   # 冻结合同（R3+F3, B1-B4）
hierarchy_status.md             # 层级状态 + 轮次记录
near_neighbor_registry.json     # 20 篇近邻（重要性、下载、出版核验）
literature_claim_registry.json  # 14 条原子观点（E2, locator）
frontier_coverage.json          # 7 轴 + 3 route
output_claim_support.json       # 输出结论绑定（空，碰撞综合时填充）
near_neighbor_url_ledger.csv    # URL 台账
validation.log                  # 校验日志
literature_archive/             # 9 份全文 PDF + SHA-256
C题 面向算电协同的多目标调度优化研究/  # 赛题材料（只读）
```

## 下一动作

取得 10 篇阻断文献的合法全文（机构访问 / 作者手稿 / OA 副本），完成 IMPORTANT_FULLTEXT 归档与观点提取，解除 BLOCKED 后进入 SOURCE_CLAIM_REGISTER → SYNTHESIZE_COLLISION。
