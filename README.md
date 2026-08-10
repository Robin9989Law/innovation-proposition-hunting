# 创新命题狩猎（Innovation Proposition Hunting）

一个面向博士论文和期刊论文的文献约束型创新命题发现技能（skill）。它把
“寻找创新点”
转化为可恢复、可验证的状态机：先冻结研究层级和成果合同，再用真实文献、原子
观点和完整引用链支持每一次创新或关闭裁决。

本项目适合需要以下能力的研究者和人工智能智能体（AI agent）：

- 从研究工作 L1 收敛到可行创新域 L2，再形成可证伪的 L3 命题；
- 区分博士论文的三个有机主贡献 A/B/C 与一般期刊论文的单一主贡献 M；
- 在空白发现、成熟理论深挖和成熟方法论证新问题之间选择正确创新路径；
- 将用户最初确认的创新路径与成果形式贯穿整个研究周期，阻止中途换轨；
- 管理近三年近邻文献、全文、重要观点和输出结论之间的可追溯证据链；
- 阻止智能体跳步、重复检索、伪造引用或在证据不足时过早宣布创新。

最后审阅：2026-08-10

## 核心设计

### 成果类型合同

| 成果类型 | 强制贡献结构 |
|---|---|
| `DOCTORAL_DISSERTATION` | L1 → L2 → 三个有机主贡献 A/B/C → 各贡献内至少一个主 L3 |
| `JOURNAL_ARTICLE` | L1 → L2 → 一个主贡献 M → 主 L3 与从属后果/组件 |

L1、L2 或贡献架构通过并不代表创新成立。N0 新颖性评级只用于具体 L3 命题。

### 创新路径与形式

路径说明新知识从哪里产生：

- R1 空白发现（`GAP_OPENING`）：寻找研究链仍未承担的知识责任；
- R2 深度推进（`DEPTH_EXTENSION`）：继续推进成熟理论或技术的边界、瓶颈或
  最大可达边界（maximal reach）；
- R3 新问题论证（`NEW_PROBLEM_SUBSTANTIATION`）：用成熟理论或技术正确形式化、
  识别和论证新问题。

形式说明最终交付什么：

- F1 新理论（`NEW_THEORY`）：新理论或数学命题；
- F2 成熟理论的新领域应用（`MATURE_THEORY_NEW_DOMAIN`）；
- F3 新算法（`NEW_ALGORITHM`）；
- F4 既有算法深度改进（`ALGORITHM_DEEPENING`）。

每个 L3 必须固定一个主路径和一个主形式。分类标签不能替代非机械性证据。

#### 路径锁定纪律

路径一经确认，就成为当前研究代次的主贡献合同，必须在检索、碰撞、命题冻结、
理论或算法审计、计算和最终锁定中持续贯彻：

- 每条候选声明区分主贡献（`PRIMARY`）与支持性贡献（`SUPPORTING`）；
- `PRIMARY` 必须与已确认的路径和形式一致；
- `SUPPORTING` 可以跨类型服务主贡献，但不得改变主线。例如，算法优化路径中发现的定理
  可以解释机制、给出界或保护约束，但不能据此把主创新改成新理论；
- 中途换主路径、换主形式或用 `MIXED` 包装第二条主线，均属于
  `INNOVATION_PATH_DRIFT`，必须停止；
- 只有用户明确同意后才能显式重启。重启保留旧路径记录，回到范围锁定并重做当前
  路径所依赖的新颖性、有效性、独立审计和计算授权。

发现另一条路径更有吸引力，不等于获得换轨授权。智能体应把它登记为支持性线索或
候选重启理由，而不是同时推进两条主创新。

### Schema 2.0 双轴状态机

```text
新颖性：BOOT → SCOPE_LOCK → ... → N0_AUDIT → N0-4C
有效性：CLAIM_FREEZE → VALIDITY_AUDIT → INDEPENDENT_REVIEW
       → DIRECTION_LOCK → COMPUTE → POSTCOMPUTE_CLAIM_FREEZE
       → FINAL_VALIDITY_AUDIT → FINAL_LOCK
```

每个研究主题都必须维护工作流状态文件（`workflow_state.json`）。智能体一次只能
执行一个 `active_state`，并同时报告新颖性 N0-1 至 N0-4C 与有效性 V0 至 V4。
用户要求“继续”时只能从 `next_required_action` 恢复，不得重新选择创新路径。

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
输出结论（output claim）
  → 来源观点（literature claim）
  → 规范文献实体（canonical work）
  → 原文定位符（locator）
  → 本地全文与 SHA-256
  → DOI、出版社或官方 proceedings 入口
```

文献存在不等于其具体观点支持当前结论。预印本可以形成威胁，但不能单独承担
终局关闭。

## 安装

### 要求

- Python 3.10 或更高版本；
- Git；
- 能读取本地 Markdown/JSON 的智能体（agent）；
- 若要执行真实研究流程，还需要可验证的学术检索和合法全文访问能力。

脚本只使用 Python 标准库，不需要安装第三方依赖。

将仓库克隆到智能体能发现的技能目录（skills directory）：

```bash
git clone \
  https://github.com/Robin9989Law/innovation-proposition-hunting.git \
  /path/to/agent/skills/innovation-proposition-hunting
```

不同智能体的技能根目录和显式调用语法可能不同。安装后应确认智能体能读取
仓库根目录下的 `SKILL.md`。

## 快速开始

向智能体（agent）提供成果类型、研究目录和当前目标。例如：

```text
使用 innovation-proposition-hunting。

成果类型：DOCTORAL_DISSERTATION
研究目录：/path/to/research
主创新路径：R2（DEPTH_EXTENSION）
主创新形式：F4（ALGORITHM_DEEPENING）
当前目标：从 L1 开始，建立可执行的 workflow_state.json 和 scope_lock.md。
不要开始实验；先完成状态、路径确认、近三年文献和证据注册门。
算法优化中得到的定理只作为 SUPPORTING，不得将其升级为理论主创新。
```

一般期刊论文示例：

```text
使用 innovation-proposition-hunting。

成果类型：JOURNAL_ARTICLE
当前目标：在冻结 L2 内形成唯一主贡献 M，并对其主 L3 执行 K→U→Δ 和 N0 审计。
```

首次启动时，智能体应当：

1. 读取 [`SKILL.md`](SKILL.md)；
2. 从 [`templates.md`](templates.md) 创建 `workflow_state.json`；
3. 取得用户确认并冻结成果类型、当前层级、研究范围、主创新路径、主创新形式和
   关键比较基线；
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
| `validate_schema_v2.py` / `validate_workflow_state.py` | Schema 2.0、双轴状态、阶段门和计算授权 |
| `validate_claim_inventory.py` | 高风险声明出现、类型和 inventory 绑定 |
| `validate_theory_obligations.py` | 理论命题、证明责任和可反驳见证 |
| `validate_protocol_contract.py` / `validate_claim_code_trace.py` | 算法协议、基线预算、实现、测试和输出追溯 |
| `validate_literature_registry.py` / `validate_evidence_chain.py` | 文献身份、全文、原子观点和输出支持 |
| `validate_frontier_integrity.py` | 近期前沿覆盖、重要性历史和证据降级 |
| `validate_artifact_hashes.py` / `validate_audit_provenance.py` | 当前 bundle、epoch 和独立 reviewer 来源 |

退出码为 `READY=0`、`INVALID=1`、`BLOCKED=2`、`MIGRATION_REQUIRED=3`。出现非零
退出码时不得宣布 `READY`、`LOCKED` 或 `CLOSED`，也不得启动新碰撞或昂贵计算。

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
| [`compute-funnel.md`](compute-funnel.md) | N0-4C、V3 且获授权后使用的 S0–S4 计算漏斗 |
| [`case-lessons.md`](case-lessons.md) | 成功上钻与失败纠偏案例 |
| [`scripts/`](scripts) | Schema、声明、证据、审计和计算门的确定性校验脚本 |

## 适用边界

本技能（skill）约束的是研究发现、证据注册和创新裁决过程。它不能替代：

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
