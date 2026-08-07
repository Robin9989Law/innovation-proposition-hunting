# Innovation Proposition Hunting

一个面向博士论文和期刊论文的文献约束型创新命题发现 skill。它把“寻找创新点”
转化为可恢复、可验证的状态机：先冻结研究层级和成果合同，再用真实文献、原子
观点和完整引用链支持每一次创新或关闭裁决。

本项目适合需要以下能力的研究者和 AI agent：

- 从研究工作 L1 收敛到可行创新域 L2，再形成可证伪的 L3 命题；
- 区分博士论文的三个有机主贡献 A/B/C 与一般期刊论文的单一主贡献 M；
- 在空白发现、成熟理论深挖和成熟方法论证新问题之间选择正确创新路径；
- 管理近三年近邻文献、全文、重要观点和输出结论之间的可追溯证据链；
- 阻止 agent 跳步、重复检索、伪造引用或在证据不足时过早宣布创新。

最后审阅：2026-08-08

## 核心设计

### 成果类型合同

| 成果类型 | 强制贡献结构 |
|---|---|
| `DOCTORAL_DISSERTATION` | L1 → L2 → 三个有机主贡献 A/B/C → 各贡献内至少一个主 L3 |
| `JOURNAL_ARTICLE` | L1 → L2 → 一个主贡献 M → 主 L3 与从属后果/组件 |

L1、L2 或贡献架构通过并不代表创新成立。N0 新颖性评级只用于具体 L3 命题。

### 创新路径与形式

路径说明新知识从哪里产生：

- `R1 GAP_OPENING`：寻找研究链仍未承担的知识责任；
- `R2 DEPTH_EXTENSION`：继续推进成熟理论或技术的边界、瓶颈或 maximal reach；
- `R3 NEW_PROBLEM_SUBSTANTIATION`：用成熟理论或技术正确形式化、识别和论证新问题。

形式说明最终交付什么：

- `F1 NEW_THEORY`：新理论或数学命题；
- `F2 MATURE_THEORY_NEW_DOMAIN`：成熟理论的新领域应用；
- `F3 NEW_ALGORITHM`：新算法；
- `F4 ALGORITHM_DEEPENING`：既有算法的深入优化与改进。

每个 L3 必须固定一个主路径和一个主形式。分类标签不能替代非机械性证据。

### 唯一执行状态机

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
       ├─ 新层级/新碰撞：回到 PRIOR_CLAIM_DRAIN
       ├─ L3 候选：N0_AUDIT
       ├─ N0-4 且获授权：COMPUTE
       └─ COMPLETE / BLOCKED
```

每个研究主题都必须维护 `workflow_state.json`。agent 一次只能执行一个
`active_state`，失败时停留在当前状态或进入 `BLOCKED`，用户要求“继续”时只能从
`next_required_action` 恢复。

## 文献与观点证据链

每轮新碰撞按固定顺序执行：

```text
耗尽旧观点
  → 检索当前年份及前两年的近邻文献
  → JSON 注册文献并核验身份
  → 下载 IMPORTANT/CRITICAL 全文并记录 SHA-256
  → JSON 注册重要观点、结论和方法
  → 仅用已注册观点执行碰撞综合
  → 为每条输出结论绑定观点 ID
  → 运行完整验证
```

引用必须能够完成以下追溯：

```text
output claim
  → literature claim
  → canonical work
  → 原文 locator
  → 本地全文与 SHA-256
  → DOI、出版社或官方 proceedings 入口
```

文献存在不等于其具体观点支持当前结论。预印本可以形成威胁，但不能单独承担
终局关闭。

## 安装

### 要求

- Python 3.10 或更高版本；
- Git；
- 能读取本地 Markdown/JSON 的 agent；
- 若要执行真实研究流程，还需要可验证的学术检索和合法全文访问能力。

脚本只使用 Python 标准库，不需要安装第三方依赖。

将仓库克隆到 agent 能发现的 skills 目录：

```bash
git clone \
  https://github.com/Robin9989Law/innovation-proposition-hunting.git \
  /path/to/agent/skills/innovation-proposition-hunting
```

不同 agent 的 skills 根目录和显式调用语法可能不同。安装后应确认 agent 能读取
仓库根目录下的 `SKILL.md`。

## 快速开始

向 agent 提供成果类型、研究目录和当前目标。例如：

```text
使用 innovation-proposition-hunting。

成果类型：DOCTORAL_DISSERTATION
研究目录：/path/to/research
当前目标：从 L1 开始，建立可执行的 workflow_state.json 和 scope_lock.md。
不要开始实验；先完成状态、近三年文献和证据注册门。
```

一般期刊论文示例：

```text
使用 innovation-proposition-hunting。

成果类型：JOURNAL_ARTICLE
当前目标：在冻结 L2 内形成唯一主贡献 M，并对其主 L3 执行 K→U→Δ 和 N0 审计。
```

首次启动时，agent 应当：

1. 读取 [`SKILL.md`](SKILL.md)；
2. 从 [`templates.md`](templates.md) 创建 `workflow_state.json`；
3. 冻结成果类型、当前层级、scope 和关键比较基线；
4. 按状态机逐步生成证据产物；
5. 在裁决或新碰撞前运行总校验器。

## 详细使用教程

完整的逐状态操作、博士/期刊路径、证据 JSON 示例、提示词库、错误恢复和完成
判据见：

- [Innovation Proposition Hunting 详细使用教程](docs/tutorial.md)

## 验证

在研究目录中执行：

```bash
python3 /path/to/innovation-proposition-hunting/scripts/validate_all.py \
  --root /path/to/research \
  --state /path/to/research/workflow_state.json
```

`validate_all.py` 会根据当前状态自动运行已经到期的检查：

| 脚本 | 检查内容 |
|---|---|
| `validate_workflow_state.py` | 状态、成果合同、层级、gate、计算授权和产物存在性 |
| `validate_literature_registry.py` | 文献身份、出版状态、URL 注册、去重和综合锁 |
| `validate_evidence_chain.py` | 全文哈希、原子观点、输出支持、双向追溯和旧观点耗尽门 |

出现非零退出码时，不得宣布 `PASS`、`FAIL`、`LOCKED`、`CLOSED`，也不得启动
新碰撞或昂贵计算。

## 研究目录的核心产物

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

随着层级推进，还会产生 L1/L2 冻结卡、贡献架构、研究链、碰撞卡、N0 审计和
计算状态文件。

## 文档导航

| 文件 | 用途 |
|---|---|
| [`docs/tutorial.md`](docs/tutorial.md) | 从安装到 L3/计算的端到端详细教程与提示词 |
| [`SKILL.md`](SKILL.md) | 强制执行协议、状态机和硬停止条件 |
| [`evidence-pipeline.md`](evidence-pipeline.md) | 文献—观点—输出 JSON 数据合同 |
| [`templates.md`](templates.md) | 状态文件、冻结卡、碰撞卡和审计模板 |
| [`reference.md`](reference.md) | E0–E4、出版资格、Gate、上钻和综合锁细节 |
| [`compute-funnel.md`](compute-funnel.md) | N0-4 后且获授权时使用的 S0–S4 计算漏斗 |
| [`case-lessons.md`](case-lessons.md) | 成功上钻与失败纠偏案例 |
| [`scripts/`](scripts) | 四个确定性校验脚本 |

## 适用边界

本 skill 约束的是研究发现、证据注册和创新裁决过程。它不能替代：

- 领域专家和导师的实质判断；
- 合法的全文访问权限；
- 独立证明审查、实验复现或正式同行评审；
- 对“首次提出”或“无人研究”的绝对保证。

## Contributing

欢迎通过 Issue 或 Pull Request 提交问题、案例和校验规则改进。修改状态机或 JSON
合同后，请同步更新模板、参考文档和校验脚本，并运行：

```bash
python3 scripts/validate_all.py --help
python3 scripts/validate_workflow_state.py --help
python3 scripts/validate_literature_registry.py --help
python3 scripts/validate_evidence_chain.py --help
```

## License

本仓库目前尚未添加开源许可证。在许可证明确之前，请勿假定拥有复制、修改或分发
权限。
