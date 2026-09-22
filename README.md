# 创新命题狩猎

这个工具帮你把论文题目定下来，或者告诉你这个题目该停。它不跑实验，也不写论文。

人先看 [docs/给人看.md](docs/给人看.md)。那里写了你要亲自看的五个地方，以及怎么判断过程和结果对不对。只回「继续」不算看过。

最后审阅：2026-09-22

## 先分清三层

不要把「研究范围」「值得做的那一块」「准备写进论文的那一句」混成一句「新不新」。

| 文件里的名字 | 意思 |
|---|---|
| L1 | 研究范围。还不是创新点 |
| L2 | 范围里值得做的那一小块 |
| L3 | 准备写进论文的那一句。必须能被推翻。新不新只判这一句 |

博士论文要三个连得上的贡献，每个贡献里至少有这样一句。期刊论文只要一个主贡献。

范围写对了，不代表创新成立。

## 新东西从哪来，最后交什么

从哪来，三选一：

- 找别人还没承担的空当
- 把已经做熟的理论或方法再往前推一步
- 用已经做熟的方法，把一个新问题讲清楚

最后交什么，四选一：新理论，旧理论用到新地方，新算法，把已有算法做深。

每一句只能有一个主来源、一种主交付。贴个标签不算证据。

### 选定之后不能自己换

路径一经确认，后面查文献、对撞、把句子定下来，都沿着这一条走。

- 准备写成论文核心的，标成主贡献（`PRIMARY`）
- 用来解释、给界、卡住约束的，标成支持性贡献（`SUPPORTING`）
- 支持性的可以是另一种东西，但不能把主线换掉。算法优化路径中发现的定理，可以解释机制、给出界，不能因此把主创新改成新理论
- 中途换主路径、换交付形式，或者用 `MIXED` 再藏一条主线，都是 `INNOVATION_PATH_DRIFT`，必须停
- 只有你明确同意，才能显式重启。旧记录留着，回到范围锁定，这条路依赖的检查重做

发现另一条更诱人，只登记下来，不能两条一起做。

例子里会写成：主创新路径：R2，主创新形式：F4。

### Schema 3.0 双轴状态机

```text
新颖性：BOOT → SCOPE_LOCK → ... → L1_FREEZE → L2_TRIAGE
      → LAYER_DECISION → K_FULLTEXT → K_CLAIM_REGISTER
      → ... → N0_AUDIT → N0-4C
有效性：CLAIM_FREEZE → VALIDITY_AUDIT → INDEPENDENT_REVIEW
       → DIRECTION_LOCK → COMPLETE
       （题目锁定后脱离 IPH；实验与写作是独立工作）
```

先定范围，这时只看论文题目和摘要，不读全文。再圈出值得做的那一小块，全文仍要少。最后只对选中的几篇读全文、抽能改变判断的结论。

每个课题单独建一个文件夹，里面有一份 `workflow_state.json`。程序一次只做当前这一步。五个该停的地方，只回「继续」不会往下走。题目收下之后，不要再用它跑实验或写论文。

### 说「新」之前，先试着把它推翻

表格填满不算创新。说这句话还活着之前，必须写下试过哪几种推翻、为什么没推翻掉。说该停，也要写下是哪篇论文已经做了，或者怎么从旧结果推出来。两边一样严。

从论文里抽出的结论，要写它和你的候选是什么关系：已经做了、帮得上、对着干、给了边界，或者没关系。不要按章节各抄一句充数。

换一个检查者来看的时候，要回答四件事：数据是不是真的、对照有没有真跑、话说得是不是过了、试过推翻没有。这个检查结果，主程序不能回头改。

## 文献怎么对上结论

主线是范围、那一小块、那一句。文献是配上来的。范围阶段不读全文。那一句定下来之前，才对选中的论文读全文。细节见 `SKILL.md`。

每一轮对撞按这个顺序：

全局文献/观点注册表跨轮追加，继续承担 URL 完整性与证据追溯；
`current_evidence_scope.json` 只列本轮计入深证据预算的 work/claim ID。开启新轮次
时 scope 可以为空，但不得删除历史记录或把已归档全文改写成 `NOT_REQUIRED`。

```text
耗尽旧观点
  → 检索当前年份及前两年的近邻文献
  → JSON 注册文献并核验身份（只动元数据）
  → 冻结 L1 → 浅证据选拔 K 集合
  → 只对 K 集合下载全文并记录 SHA-256
  → 只对 K 集合 JSON 注册重要观点、结论和方法
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

把课题放在单独的文件夹里，不要写进这个仓库。对程序可以这样说：

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

第一次启动，程序应当：

1. 读 [`SKILL.md`](SKILL.md)，对人说话时改读 [`docs/给人看.md`](docs/给人看.md)；
2. 按 [`templates.md`](templates.md) 建 `workflow_state.json`；
3. 等你确认论文类型、研究范围、新东西从哪来、最后交什么、拿什么当对照；
4. 一步一步做，做到五个停点就停；
5. 下判断之前先跑检查。

## 详细用法

逐步操作、博士和期刊两条路、文献例子、出错了怎么恢复，见 [教程](docs/tutorial.md)。教程比这篇长。看不懂术语时，仍以 [给人看](docs/给人看.md) 为准。

## 验证

在研究目录中执行（标准入口是 `iph` CLI；它会自动完成校验、状态推进与交接）：

```bash
python3 /path/to/innovation-proposition-hunting/scripts/iph.py \
  validate --root /path/to/research --state /path/to/research/workflow_state.json
```

底层总校验器仍可直接调用：

```bash
python3 /path/to/innovation-proposition-hunting/scripts/validate_all.py \
  --root /path/to/research \
  --state /path/to/research/workflow_state.json
```

`validate_all.py` 会根据当前状态自动运行已经到期的检查：

| 脚本 | 检查内容 |
|---|---|
| `validate_schema_v2.py` / `validate_workflow_state.py` | Schema 3.0（旧版本转 MIGRATION）、双轴状态、阶段门、计算授权与未登记计算产物 |
| `validate_claim_inventory.py` | 高风险声明出现、类型和 inventory 绑定 |
| `validate_theory_obligations.py` | 理论命题、证明责任、见证咬合力与豁免闭合 |
| `validate_protocol_contract.py` / `validate_claim_code_trace.py` | 算法协议、实现、测试绑定和输出追溯、自证测试检测 |
| `validate_baseline_budget.py` | 基线预算（无触发词门控，comparator 与 algorithm claims 求交） |
| `validate_exploration_firewall.py` | 探索产物登记、哈希新鲜度与数字泄漏防火墙 |
| `validate_literature_registry.py` / `validate_evidence_chain.py` | 文献身份、全文、原子观点和输出支持 |
| `validate_frontier_integrity.py` | 近期前沿覆盖、作者续作实名、重要性历史和证据降级 |
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
| [`docs/给人看.md`](docs/给人看.md) | 给人看的流程：五个停点，以及怎么判断对不对 |
| [`docs/tutorial.md`](docs/tutorial.md) | 从安装到 L3/计算的端到端详细教程与提示词 |
| [`SKILL.md`](SKILL.md) | 强制执行协议、状态机和硬停止条件 |
| [`evidence-pipeline.md`](evidence-pipeline.md) | 文献—观点—输出 JSON 数据合同 |
| [`templates.md`](templates.md) | 状态文件、冻结卡、碰撞卡和审计模板 |
| [`reference.md`](reference.md) | E0–E4、出版资格、Gate、上钻和综合锁细节 |
| [`compute-funnel.md`](compute-funnel.md) | N0-4C、V3 且获授权后使用的 S0-SCREEN–S4 计算漏斗 |
| [`case-lessons.md`](case-lessons.md) | 成功上钻与失败纠偏案例（含 2026-08 事故复盘） |
| [`scripts/`](scripts) | Schema、声明、证据、审计和计算门的确定性校验脚本 |
| [`docs/optimization-plan-2026-08.md`](docs/optimization-plan-2026-08.md) | 2026-08 技能整体优化方案（已实施，含事故根因分析） |
| [`docs/archive/`](docs/archive) | 历史设计档案（仅存档，非现行规范） |

## 它做不到的事

它只把题目定下来，等你点头收下。然后就结束。它不能代替：

- 领域专家和导师的实质判断；
- 合法的全文访问权限；
- 后续实验、论文/学位论文写作、独立证明审查或正式同行评审；
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
