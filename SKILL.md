---
name: innovation-proposition-hunting
description: >-
  Guides literature-constrained innovation discovery for doctoral dissertations
  and journal articles, from a frozen L1 research program to an L2 feasible
  domain, an output-specific contribution architecture, and falsifiable L3
  propositions. Use for 探索L1/探索L2, 博士论文三贡献, 期刊论文主贡献, 寻找创新命题,
  空白型创新, 成熟理论或技术深挖, 成熟方法论证新问题, 理论/应用/算法创新,
  新颖性审计, 危险近邻, 近三年文献检索, 文献与观点JSON注册, 全文下载,
  可追溯引用, N0预审, or deciding whether a contribution is ready to lock.
  Enforces a machine-readable workflow state, output-type freezing, K→U→Δ
  collisions, route/form novelty gates, verified-source rejection gates,
  claim-level traceability, prior-claim draining, synthesis lock, and a
  permissioned multi-fidelity compute funnel.
---

# 创新命题狩猎：强制执行协议

本技能用于收敛式研究，不用于无约束头脑风暴。目标是得到可证伪、可追溯、可关闭
的 L3 创新命题，同时保持 L1、L2 和成果型贡献架构稳定。

## 0. 规范词与优先级

本文件中的规范词按以下方式解释：

- **MUST / 必须**：缺失即停止，不得用解释性文字代替。
- **MUST NOT / 不得**：禁止动作。
- **STOP**：保持当前状态，记录阻塞原因；不得宣布 PASS、FAIL、LOCKED、CLOSED。
- **MAY / 可以**：不影响门禁的可选动作。

发生冲突时按以下优先级执行：

```text
用户/导师/开题等显式权威要求
  > workflow_state.json 当前机器状态
  > 本 SKILL.md 强制协议
  > evidence-pipeline.md 数据合同
  > reference.md 详细判据
  > templates.md 表达模板
  > case-lessons.md 案例启发
```

案例、旧笔记和自然语言状态摘要不得覆盖机器状态或强制门禁。

## 1. 只按需读取资源

| 条件 | 必须读取 |
|---|---|
| 启动、续跑或裁决 | 本文件 |
| 新主题、新碰撞、检索、注册、下载、观点或引用处理 | [evidence-pipeline.md](evidence-pipeline.md) |
| 创建卡片、JSON 或状态文件 | [templates.md](templates.md) 对应部分 |
| 需要 E0–E4、出版资格、Gate、上钻或 100 篇锁细节 | [reference.md](reference.md) 对应部分 |
| L3 已达 N0-4 且获计算授权 | [compute-funnel.md](compute-funnel.md) |
| 命中已知反模式或需要案例诊断 | [case-lessons.md](case-lessons.md) |

不要把所有参考文件复制进当前上下文；但一旦选择某个文件，完整读取相关规范部分
后再行动。

## 2. 机器状态是执行权威

每个研究主题 MUST 在研究目录维护 `workflow_state.json`。其模板见
[templates.md](templates.md)。同时可维护 `hierarchy_status.md` 供人阅读，但两者
冲突时以 JSON 为准。

### 2.1 单状态纪律

1. 每次只允许一个 `active_state`。
2. 只执行该状态的“允许动作”；不得提前做后续状态。
3. 完成动作后先更新产物，再更新 gate，最后更新状态。
4. gate 未通过时保持原状态或进入 `BLOCKED`，不得伪造前进。
5. 用户说“继续”时，从 `next_required_action` 恢复；不得重置主题、轮次或层级。
6. 任何状态、scope、轮次或裁决改变都追加 `decision_log`，不得静默覆盖历史。

若缺少状态文件，第一步只能创建状态文件和盘点既有产物，不得开始检索或碰撞。

### 2.2 启动与续跑

按以下顺序读取现有权威产物：

```text
workflow_state.json
  → scope_lock.md
  → 当前 L1/L2/贡献架构/L3 裁决
  → 三个证据 JSON
  → 关闭库和历史 decision_log
```

然后执行：

- 核对成果类型、贡献合同、当前层级、贡献编号、轮次、年份和搜索模式；
- 检查状态声明的产物是否存在；
- 运行 `validate_workflow_state.py`；
- 若状态与产物不一致，STOP 于最早失效状态，修复后再继续；
- 不因“继续”而重新打开已冻结上层或已关闭候选。

## 3. 成果类型合同

先从权威材料识别成果类型；无法识别且选择会改变架构时才询问用户。

```text
DOCTORAL_DISSERTATION
  L1 → L2 → 三个有机主贡献 A/B/C → 各贡献内至少一个主 L3
  contribution_contract = THREE_ORGANIC_A_B_C

JOURNAL_ARTICLE
  L1 → L2 → 一个主贡献 M → 主 L3 + 从属后果/组件
  contribution_contract = ONE_MAIN_M
```

硬规则：

- 博士 L2 MUST 能容纳恰好三个主贡献 A/B/C。三项至少在研究单位、主要自变量、
  目标量、关键证据、退出边界中的三项不同，并形成输入—输出依赖。
- 一般期刊默认且通常 MUST 只有一个主贡献 M。多个定理、实验或算法步骤只能是
  M 的从属结果或组件。若显式权威要求多主贡献，STOP 并登记合同冲突；在获得
  明确合同扩展前，agent 不得自行发明例外或继续套用 M。
- L1、L2、贡献架构通过都不等于创新成立。N0 只用于 L3。
- 新方法不能挽救被占据的 L3；成熟方法也不妨碍真正的新 L3。

## 4. 唯一执行状态机

```text
BOOT
  → SCOPE_LOCK
  → PRIOR_CLAIM_DRAIN
  → RECENT_FRONTIER
  → LITERATURE_REGISTER
  → IMPORTANT_FULLTEXT
  → SOURCE_CLAIM_REGISTER
  → SYNTHESIZE_COLLISION
  → OUTPUT_CLAIM_BIND
  → EVIDENCE_VALIDATE
  → LAYER_DECISION
       ├─ 新层级/新碰撞：轮次 +1，回到 PRIOR_CLAIM_DRAIN
       ├─ L3 候选：N0_AUDIT
       ├─ N0-4 且获授权：COMPUTE
       └─ 结束：COMPLETE 或 BLOCKED
```

### 4.1 状态动作与通过门

| 状态 | 唯一主要动作 | 必须产物 | 通过条件 |
|---|---|---|---|
| `BOOT` | 盘点权威文件和现有产物 | `workflow_state.json` | 字段完整、可恢复 |
| `SCOPE_LOCK` | 冻结成果类型、层级、对象、基线和边界 | `scope_lock.md` | `scope_locked=true` |
| `PRIOR_CLAIM_DRAIN` | 使用或有理由排除所有旧观点 | 三个证据 JSON | prior-round `UNUSED=0` |
| `RECENT_FRONTIER` | 完成动态近三年前沿检索或核验可复用快照 | 检索记录 | `[Y-2,Y]` COMPLETE |
| `LITERATURE_REGISTER` | 对实质相关命中逐篇注册并核验身份 | `near_neighbor_registry.json` | 注册验证通过 |
| `IMPORTANT_FULLTEXT` | 合法下载 IMPORTANT/CRITICAL 全文并核版本/哈希 | `literature_archive/` | 重要全文 100% 完成 |
| `SOURCE_CLAIM_REGISTER` | 原子化登记观点、结论、方法、条件和 locator | `literature_claim_registry.json` | 重要文献观点提取完成 |
| `SYNTHESIZE_COLLISION` | 用已注册观点形成研究链、K→U→Δ 和反证 | 碰撞卡/研究链 | 不使用未注册观点 |
| `OUTPUT_CLAIM_BIND` | 为每条实质研究结论绑定观点 ID | `output_claim_support.json` | 双向追溯完整 |
| `EVIDENCE_VALIDATE` | 运行全部校验器 | 校验日志 | 全部退出码为 0 |
| `LAYER_DECISION` | 只裁决 `active_layer` | 对应冻结/裁决卡 | 证据门通过 |
| `N0_AUDIT` | 对单个 L3 做非机械性、路径和形式审计 | L3 审计卡 | 得到 N0-1/2/3/4 |
| `COMPUTE` | 按授权执行 S0–S4 漏斗 | 计算状态与结果 | 满足逐级升级门 |
| `BLOCKED` | 记录外部阻塞和恢复条件 | `blocked_reasons` | 不做裁决性前进 |
| `COMPLETE` | 输出可复现交接 | 最终状态报告 | 无未完成必需动作 |

禁止并步。可以在同一 agent turn 连续推进多个状态，但每一步都必须先落盘产物和
更新状态，再进入下一步。

### 4.2 新碰撞定义

以下任一变化都视为新碰撞并使 `collision_round += 1`：

- 新建或实质改变 L3；
- 改变目标研究链、覆盖理论或关键比较基线；
- 改变 O/I/A/T/C/R/B 中任一实质项；
- 从 L1、L2、贡献架构或某贡献转入新的裁决对象。

只补页码、证据级、错字、版本 alias 或同一主张的精确措辞不增加轮次。新轮次
必须先进入 `PRIOR_CLAIM_DRAIN`；不得靠沿用旧轮次绕过旧观点耗尽门。

## 5. 分层裁决合同

### 5.1 L1：研究工作

冻结对象、核心矛盾、总目标、动态轴、关键基线、适用边界和连续知识链。只判断
整条研究程序是否被直接占据：

`PASS AS RESEARCH PROGRAM / PARTIAL COLLISION / FAIL AS PROGRAM`

L1 PASS 不表示已有命题。

### 5.2 L2：可行创新域

冻结 O/I/A/V/T/B、准入/退出边界和数据计算可行性。L2 MUST 比 L1 窄、比单一
L3 宽，并能承载成果类型合同：

`PASS AS FEASIBLE MICRODOMAIN / NEEDS REBOUNDARY / FAIL AS DOMAIN`

L2 不得使用 N0。

### 5.3 贡献架构

- 博士：分别定义 A/B/C 的研究单位、主要变量、目标量、证据和退出边界，验证
  非重叠及有机依赖。
- 期刊：定义唯一主贡献 M；把其他结果降为后果/组件，检查 M 在目标篇幅内自足。

架构标题不是创新证据。

### 5.4 L3：具体知识命题

合格 L3 必须产生不可机械推出的新知识，例如充分/失效制度、必要性/converse、
保持/反转边界、可识别/不可识别边界、可实现/不可实现像、新算法保证或可证伪
预测。“更多数据”“再比较一次”“换场景”“关系复杂”均不合格。

博士 A/B/C 分别审计并各自需要至少一个主 L3 达 N0-4；期刊只锁定 M，且至少一个
主 L3 达 N0-4。不得把一个结果拆成多个虚假贡献。

## 6. 创新路径与形式：两个正交轴

每个 L3 固定一个主路径和一个主形式。标签只选择门禁，不能代替证据。

### 6.1 路径

| 路径 | 新知识责任 |
|---|---|
| `R1 GAP_OPENING` | 对齐 O/I/A/T/C/R/B 后，承担研究链仍无人承担的责任 |
| `R2 DEPTH_EXTENSION` | 推进成熟前沿的 maximal reach、像/逆、边界、瓶颈或性能前沿 |
| `R3 NEW_PROBLEM_SUBSTANTIATION` | 先冻结新问题，再建立成熟理论/技术到新对象的语义映射、识别条件和证据桥 |

### 6.2 形式

| 形式 | 最低交付物 |
|---|---|
| `F1 NEW_THEORY` | 定义、数学命题、条件/量词、证明责任、见证/反例、近邻差异 |
| `F2 MATURE_THEORY_NEW_DOMAIN` | 源理论—新对象映射、假设核验、新领域结论、适用/失效边界 |
| `F3 NEW_ALGORITHM` | 新计算规则、伪代码、复杂度/资源合同、机制、同预算强基线、消融、失败门 |
| `F4 ALGORITHM_DEEPENING` | 原算法瓶颈、修改变量、收益机制、保护约束、同预算胜出、退出条件 |

R3/F2 若只换领域名、数据或软件调用，记机械应用。F3/F4 若收益来自更多参数、
数据、算力或不公平预算，不得给 N0-4。

## 7. 碰撞与 N0

所有候选从同一连续研究链内部生成：

```text
K = 最近、最强且口径核准的已知结果
U = K 内部尚未闭合的推理、边界、识别或性能责任
Δ = 只解决 U 的最小非机械知识增量
```

必须依次执行：

1. 对齐 O/I/A/T/C/R/B；
2. 检查直接归约、变量替换、加标准约束和两篇机械拼接；
3. 构造最小反例/见证；
4. 检查信息边界和量词；
5. 若被理论 T 覆盖，执行上钻六问：结构承诺、像、逆、边界、maximal reach、
   停止理由；未经上钻不得关闭；
6. 固定主路径、主形式和明确失败条件。

N0 只用于 L3：

| 等级 | 判据 | 动作 |
|---|---|---|
| N0-1 | 直接近邻占据 | 满足终局资格后关闭 |
| N0-2 | 可由已知结果机械推出 | 吸收或关闭 |
| N0-3 | 似乎非机械但未完成前沿、见证或专属门 | HOLD，不计算 |
| N0-4 | 非机械性、证据、路径门、形式门均通过 | 锁定方向；仍不自动授权计算 |

预印本只能产生 `PREPRINT THREAT / OPEN`，不能单独产生终局 N0-1/2 关闭。

## 8. 证据协议摘要

细节和 JSON schema 以 [evidence-pipeline.md](evidence-pipeline.md) 为准。

### 8.1 强制顺序

```text
旧观点耗尽预检
  → 近三年近邻
  → JSON 注册文献
  → 下载重要全文
  → JSON 注册重要观点/结论/方法
  → 基于观点做碰撞综合
  → 输出结论绑定观点 ID
  → 全链验证
```

所有实质研究结论必须由已核验的重要观点 ID 支持，不能只挂论文或 DOI。引用链
必须为：

`output claim → literature claim → canonical work → locator → local fulltext + SHA-256 → official identity`

### 8.2 动态近三年与快照复用

窗口永远是 `[current_year-2,current_year]`；2026 年即 2024–2026。只有 scope、
年份、查询覆盖和版本链均未变化，且快照已通过验证时，才可复用并在状态中记录
`REUSED_VERIFIED_SNAPSHOT`。否则执行新的有界近期检索。

检索工具不得硬编码。优先使用当前 agent 可调用的学术数据库/API/连接器；
OpenAlex 可用时优先用于发现，再回官方出版社、期刊或 proceedings 核验。通用
网页搜索只作补漏。能力不可用时 STOP 为 `BLOCKED_CAPABILITY`，不得编造工具、
文献、DOI、作者、年份或全文内容。

### 8.3 100 篇综合锁

同一主题达到 100 篇去重、实质相关、正式发表且同行评审的 canonical works 后：

`search_mode = SYNTHESIS_LOCK`

此后禁止通用横向检索，必须按研究链综合。只有新正式对象、缺正式出版锚点、未清
版本链或上钻所需外部前提可建立有界 `EXCEPTION_REOPEN`；补齐后立即回锁。
同范围同年份的已验证近三年快照可直接满足近期门，不得借近期门绕过综合锁。

## 9. 硬停止条件

| 条件 | 必须动作 |
|---|---|
| 成果类型或 scope 无法可靠确定 | STOP；只做只读盘点或询问 |
| prior-round `UNUSED > 0` | STOP 于 `PRIOR_CLAIM_DRAIN`；禁止新搜索和新碰撞 |
| 近三年窗口不完整 | STOP 于 `RECENT_FRONTIER`；不得历史回溯或碰撞 |
| 文献身份未核验 | 保持 E0/E1；不得支持结论 |
| IMPORTANT/CRITICAL 全文无法取得 | 标记阻塞；不得用该文献做 E2/E4 或终局裁决 |
| 观点无 locator 或输出无观点 ID | STOP；不得综合或裁决 |
| 任一校验器非零退出 | STOP；不得 PASS、FAIL、LOCKED、CLOSED 或开新碰撞 |
| 决定性来源仅为预印本 | 保持 OPEN；不得终局判死 |
| 上层未冻结 | 不得裁决下层 |
| N0 < 4 或未获计算授权 | 不得启动新实验、模型调用或昂贵计算 |
| 新证据只影响下层 | 不得静默改写已冻结上层 |

阻塞不等于失败。记录已完成工作、精确缺口、恢复条件和唯一下一动作。

## 10. 计算授权

只有同时满足下列条件才读取并执行 [compute-funnel.md](compute-funnel.md)：

- L1、L2 和对应贡献架构已冻结；
- 当前 L3 为 N0-4；
- 证据校验全部通过；
- `compute_authorized=true` 且授权来源已记录；
- 已写估算对象、基线、效应方向、失败条件和资源预算。

N0-4 只允许进入计算 S0/S1，不自动允许完整确认 S4。逐级升级；无效或低信息时
立即停止。不得扩大到命题量词之外的模型、数据、边或 seeds。

## 11. 必需产物与验证

研究目录至少包含：

```text
workflow_state.json
scope_lock.md
near_neighbor_registry.json
near_neighbor_url_ledger.csv
literature_claim_registry.json
output_claim_support.json
literature_archive/
hierarchy_status.md
```

分层推进时再加入 L1、L2、贡献架构、研究链、碰撞卡和 N0 审计产物。

每次续跑、每次证据更新、每次裁决和每次新碰撞前运行：

```bash
python3 <skill>/scripts/validate_all.py \
  --root <研究目录> \
  --state <研究目录>/workflow_state.json
```

总校验器按 `active_state` 自动决定哪些检查已到期；早期状态不会要求尚未产生的
证据文件。从 `EVIDENCE_VALIDATE` 起，状态、文献注册和证据链三项必须全部为零
错误。只在定位错误时单独运行三个子校验器。

## 12. 每次交接的固定输出

结束一个 turn 前报告：

```text
成果类型与贡献合同：
active_state / active_layer / active_contribution：
collision_round：
本轮完成状态与产物：
近三年窗口与复用/检索状态：
文献/重要全文/观点/输出追溯计数：
prior-round UNUSED：
搜索模式：
分层裁决与 N0：
三个校验器结果：
BLOCKED 原因（如有）：
next_required_action（唯一下一动作）：
```

报告必须与 `workflow_state.json` 一致；不得用“基本完成”“大致可行”等模糊词
替代 gate 值。

> 核心纪律：先锁成果合同和 scope；每轮先耗尽旧观点，再完成近三年—文献—
> 全文—观点—输出的可追溯链；只在冻结层级内，从 K 推进一个不可机械推出的
> Δ；博士落实 A/B/C 三个有机主贡献，期刊收敛为一个主贡献 M。
