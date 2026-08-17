# 创新命题狩猎（Innovation Proposition Hunting）详细使用教程

本教程面向第一次使用该技能（skill）的研究者、导师和人工智能智能体
（AI agent）操作者。它不重复
`SKILL.md` 的全部规范，而是解释如何把规范落实为一个可运行、可中断、可恢复的
研究流程。

示例日期为 2026 年，因此近三年窗口写作 2024–2026。实际运行时永远使用
`current_year-2 .. current_year`。

术语约定：正文以中文术语为主，英文原名在首次出现时放在括号中。文件名、JSON
字段、状态枚举、错误码和命令参数必须保留英文原值，否则校验器无法识别。例如：
范围锁定（`SCOPE_LOCK`）、门禁（gate）、原文定位符（locator）、开发数据集
（development dataset）和封存确认数据集（sealed confirmation dataset）。

## 目录

1. [使用后应该得到什么](#1-使用后应该得到什么)
2. [开始前的准备](#2-开始前的准备)
3. [先理解四个研究层级](#3-先理解四个研究层级)
4. [成果类型怎么选](#4-成果类型怎么选)
5. [第一次调用智能体](#5-第一次调用智能体agent)
6. [工作流状态文件怎么用](#6-工作流状态文件workflow_statejson怎么用)
7. [状态机逐步教程](#7-状态机逐步教程)
8. [博士论文完整路径](#8-博士论文完整路径)
9. [一般期刊论文完整路径](#9-一般期刊论文完整路径)
10. [三种创新路径怎么选](#10-三种创新路径怎么选)
11. [文献、观点和输出三层注册示例](#11-文献观点和输出三层注册示例)
12. [新碰撞、断点续跑和年份变化](#12-新碰撞断点续跑和年份变化)
13. [100 篇综合锁](#13-100-篇综合锁)
14. [计算验证怎么启动](#14-计算验证怎么启动)
15. [常见校验错误与恢复](#15-常见校验错误与恢复)
16. [可直接复制的提示词库](#16-可直接复制的提示词库)
17. [最常见的错误用法](#17-最常见的错误用法)
18. [完成判据](#18-完成判据)
19. [推荐阅读顺序](#19-推荐阅读顺序)

---

## 1. 使用后应该得到什么

这个技能（skill）的目标不是输出一串“可能的创新点”，而是逐层得到：

1. 一个冻结的 L1 研究工作；
2. 一个位于 L1 内、能够执行的 L2 可行创新域；
3. 与成果类型匹配的贡献架构：
   - 博士论文：三个非重叠且有依赖的主贡献 A/B/C；
   - 一般期刊论文：一个主贡献 M；
4. 每个有效贡献域内至少一个可证伪、不可机械推出的 L3 命题；
5. 从输出结论回到原文位置和官方入口的完整证据链；
6. 一个明确状态：继续、阻塞、关闭、锁定或进入经授权的计算验证。

如果最终结果是“候选被正式出版近邻覆盖，因此关闭”，流程仍然成功。这个技能
把及时关闭错误方向视为有效研究产出。

---

## 2. 开始前的准备

### 2.1 安装技能（skill）

```bash
git clone \
  https://github.com/Robin9989Law/innovation-proposition-hunting.git \
  /path/to/agent/skills/innovation-proposition-hunting
```

确认你的智能体（agent）能发现仓库根目录下的 `SKILL.md`。不同智能体的技能目录
（skills directory）和显式调用语法不同，但执行协议相同。

### 2.2 环境要求

- Python 3.10 或更高版本；
- Git；
- 一个独立的研究目录；
- 智能体（agent）对研究目录具有读写权限；
- 可验证的学术检索能力；
- 合法的全文访问方式。

校验脚本只使用 Python 标准库。

### 2.3 建立独立研究目录

每个研究主题使用独立目录，不要让两个主题共享注册表：

```text
research-topic/
├── workflow_state.json
├── scope_lock.md
├── hierarchy_status.md
├── near_neighbor_registry.json
├── near_neighbor_url_ledger.csv
├── literature_claim_registry.json
├── output_claim_support.json
└── literature_archive/
```

博士论文中不同版本或完全不同主题也应拆开目录。历史材料可以引用，但不能让旧
主题和新主题共用同一个 `workflow_state.json`。

### 2.4 准备权威输入

启动前尽量提供：

- 成果类型：博士论文或一般期刊论文；
- 开题报告、导师要求或目标期刊范围；
- 当前研究版本和明确排除的旧版本；
- 已知数据、算力、时间和全文访问限制；
- 已有文献库、论文草稿、实验资产和关闭记录；
- 当前希望裁决的层级。
- 已倾向的主创新路径 R1/R2/R3 与主创新形式 F1/F2/F3/F4；若尚未决定，要求
  智能体先比较责任门并等待用户确认，不能自行锁定。

成果类型不清楚时，智能体只能盘点材料和询问，不得自行选择博士或期刊合同。

---

## 3. 先理解四个研究层级

### 3.1 L1：研究工作

L1 是整条研究程序，回答：

- 研究什么对象？
- 核心矛盾是什么？
- 总体知识目标是什么？
- 哪条动态、干预或变化轴贯穿全文？
- 最关键的替代解释或比较基线是什么？

L1 可以较宽，但必须是一条连续研究链，不是若干热门关键词的集合。

### 3.2 L2：可行创新域

L2 是 L1 内的可执行微领域，必须明确：

- `O`：研究对象；
- `I`：信息或表示；
- `A`：行动、机制或结构；
- `V`：允许变化的轴；
- `T`：目标和联合结果空间；
- `B`：必须排除的关键反方或强基线；
- 数据、计算、访问和退出边界。

L2 比 L1 窄，但必须宽于某一个具体定理、算法或实验命题。

### 3.3 贡献架构

博士论文：

```text
L2
├── 贡献 A：独立知识责任
├── 贡献 B：独立知识责任
└── 贡献 C：独立知识责任
```

A/B/C 至少在研究单位、主要自变量、目标量、关键证据、退出边界中的三项不同，
并形成输入—输出依赖。三个标题、三个数据集或三个算法步骤不等于三个贡献。

一般期刊论文：

```text
L2
└── 主贡献 M
    ├── 主 L3
    ├── 从属后果
    └── 支持组件
```

多个定理或实验必须服务同一个主知识责任，不能把一个贡献拆成几个虚假主贡献。

### 3.4 L3：具体创新命题

L3 是真正接受 N0 新颖性审计的单位。合格形式包括：

- 充分条件和失效条件；
- 必要性、逆命题（converse）或紧致性（sharpness）；
- 排序保持与排序反转边界；
- 可识别和不可识别边界；
- 可实现像和严格不可实现像；
- 新算法保证；
- 可证伪实验预测。

“多测几个数据集”“把方法用于新场景”“结果关系复杂”通常不是 L3。

---

## 4. 成果类型怎么选

### 4.1 博士论文模式

在 `workflow_state.json` 中使用：

```json
{
  "output_type": "DOCTORAL_DISSERTATION",
  "contribution_contract": "THREE_ORGANIC_A_B_C"
}
```

只有进入具体 L3 时，`active_contribution` 才能是 `A`、`B` 或 `C`。

### 4.2 一般期刊模式

```json
{
  "output_type": "JOURNAL_ARTICLE",
  "contribution_contract": "ONE_MAIN_M"
}
```

进入 L3 时，`active_contribution` 必须是 `M`。

### 4.3 不要混用

以下情况会被状态校验器阻止：

- 期刊论文使用 A/B/C；
- 博士论文只定义 M；
- L1、L2 或贡献架构阶段提前填写 M/A/B/C；
- 成果类型未解决却进入文献碰撞或计算。

---

## 5. 第一次调用智能体（agent）

建议使用下面的启动提示词：

```text
使用 innovation-proposition-hunting。

研究目录：/absolute/path/to/research-topic
成果类型：DOCTORAL_DISSERTATION
当前层级：L1
权威材料：<开题报告、导师要求或草稿路径>
允许研究的对象：<范围>
禁止混入的旧主题：<范围>
关键比较基线：<基线>

请先完整读取 SKILL.md，并按需读取 templates.md 和 evidence-pipeline.md。
第一步只创建并验证 workflow_state.json，随后创建 scope_lock.md。
一次只推进一个 active_state；每完成一步先落盘产物、更新门禁（gate），再改变状态。
不要开始实验、模型调用或无界检索。
```

如果是期刊论文，把成果类型改为 `JOURNAL_ARTICLE`。

---

## 6. 工作流状态文件（`workflow_state.json`）怎么用

从 [`templates.md`](../templates.md) 复制完整模板。首次启动使用：

```text
active_state = BOOT
resume_state = BOOT
output_type = UNRESOLVED 或已确认的成果类型
active_contribution = NONE
collision_round = 1
```

活动轨道、证据层级和最后完成状态是派生字段，由校验器从当前状态与
decision_log 推得，不在 state 中持久化，也不用手工维护。

### 6.1 三个最重要字段

| 字段 | 用途 |
|---|---|
| `active_state` | 当前唯一允许执行的状态 |
| `next_required_action` | 下一项原子动作；只能写一件事，例如“核验成果类型”，不能写“搜索、下载并综合文献” |
| `gates` | 已经通过的机器门禁（gate）；只有对应产物真实存在且检查完成时才能设为 `true` |

### 6.2 更新顺序

每次推进都使用相同顺序：先执行当前状态动作并保存产物，确认对应门禁（gate）
条件真实满足，然后用 iph CLI 推进：

```bash
python3 scripts/iph.py validate --root . --state workflow_state.json
python3 scripts/iph.py advance --root . --state workflow_state.json \
  --to <STATE> \
  --note "<一行决策说明>" \
  --set-gate <gate>=true \
  --set-artifact <artifact_key>=<relative_path> \
  --artifact <relative_path> \
  --next-action "<推进后的唯一动作>"
```

`iph advance` 会先跑完整校验，READY 后才写 decision_log（真实 UTC 时间戳）并
原子更新 state（含门禁、active_state、resume_state 和
next_required_action；证据层级与最后完成状态由校验器派生，不写回 state）；
校验不过不推进。`validate_all.py` 仍是底层校验器
（`iph validate` 即调用它），但常规推进一律走 iph CLI，不手动编辑
`workflow_state.json` 或手动追加 decision_log。

`--set-artifact key=path` 写顶层路径指针，`--artifact path` 把同一不可变文件的
哈希锚定到 decision_log；二者用途不同。某个 gate 依赖多个工件时分别重复传入。
目录只登记路径指针，不作为单文件哈希参数传入。

不要先把门禁（gate）改成 `true`，再补文件。

### 6.3 `BLOCKED` 的使用

遇到外部阻塞时：

```text
active_state = BLOCKED
resume_state = 原本正在执行的状态
blocked_reasons = 精确原因列表
next_required_action = 解除阻塞所需的唯一动作
```

例如重要论文被付费墙阻断：

```text
active_state = BLOCKED
resume_state = K_FULLTEXT
blocked_reasons = ["W-0042 has no legally accessible full text"]
next_required_action = "Provide a lawful author manuscript or institutional access for W-0042"
```

阻塞解除后回到 `resume_state`，不能跳到后续状态。

---

## 7. 状态机逐步教程

> **主线与辅线**：主线是 L1→L2→L3 的逐层构建（先知道"研究什么、在哪创新、
> 命题是什么"）；文献收集、全文下载、原子观点注册是辅线，证据深度按层供给——
> L1 只要元数据（零全文、零原子观点），L2 到摘要级观点与少量全文（≤12），
> 全重机器（E2/E4 原子观点、碰撞、输出绑定）只对 L3 候选 K 集合运行
> （全文 ≤20、原子观点 ≤60）。超出预算报 `EVIDENCE_DEPTH_EXCEEDS_LAYER`
> （R-LAYER-13，见 SKILL.md §3.1）。不要把"注册了多少文献"当作进度——
> 进度是层级决策，不是证据堆积。
>
> 复用历史项目时，全局注册表仍保留全部旧文献、URL、下载状态和观点；另建
> `current_evidence_scope.json`，只把当前轮次实际试读/深读的 work ID 与提取的
> claim ID 加入数组。没有 scope 时校验器仍按全注册表计数，不会静默放宽。

### 7.1 启动（`BOOT`）

输入：

- 研究目录；
- 权威材料；
- 既有研究文件。

允许动作：

- 盘点文件；
- 确认是否已有状态、注册表和关闭记录；
- 创建 `workflow_state.json`。

不得做：

- 检索文献；
- 提出创新点；
- 启动实验。

通过信号：

```text
workflow_state_errors=0
```

下一状态：`SCOPE_LOCK`。

### 7.2 范围锁定（`SCOPE_LOCK`）

使用 [`templates.md`](../templates.md) 的 `scope_lock.md` 节模板，冻结：

- 当前版本和主题；
- 成果类型与贡献合同；
- 当前层级；
- 允许对象和禁止旧主题；
- 主线锚点；
- 关键比较基线；
- 经用户确认的主创新路径和主创新形式；
- 哪类产物是主贡献、哪类只能作为支持性贡献；
- 改变研究范围（scope）的授权条件。

建议提示词：

```text
当前 active_state=SCOPE_LOCK。
请读取权威材料，只生成 scope_lock.md。
列出成果类型、贡献合同、当前层级、允许对象、禁止旧主题、关键基线、主创新路径、
主创新形式和退出边界。没有用户确认时只给选择依据，不得替用户锁定。
发现冲突时保持 SCOPE_LOCK 或进入 BLOCKED，不得自行选一个版本。
```

通过条件：

```text
scope_locked = true
证据层级 = L1（由当前状态派生）
active_contribution = NONE
```

下一状态：`PRIOR_CLAIM_DRAIN`。

### 7.3 旧观点耗尽（`PRIOR_CLAIM_DRAIN`）

首轮通常没有旧观点，可以直接记录：

```text
prior_round UNUSED = 0
prior_claims_drained = true
```

第 2 轮及以后，检查所有 `discovered_round < current_collision_round` 的观点。
每条必须是：

- `USED`：用于输出、碰撞、反证、限定、方法吸收或关闭；
- `EXCLUDED_WITH_REASON`：重复、越界、被更强证据取代或身份失败。

不能因为观点不利于当前候选而排除。

建议提示词：

```text
当前 active_state=PRIOR_CLAIM_DRAIN。
列出所有 prior-round UNUSED 观点。逐条决定 USED 或 EXCLUDED_WITH_REASON，
写明 output/collision 反向链接或合格排除理由。
在 UNUSED=0 前禁止搜索新文献和创建新候选。
```

下一状态：`RECENT_FRONTIER`。

### 7.4 近期前沿（`RECENT_FRONTIER`）

先搜索当前年份和前两年。2026 年运行时窗口为：

```text
2024–2026
```

搜索至少覆盖：

- 核心对象和正式问题；
- 同义术语；
- 最强基线；
- 关键作者及续作；
- 版本链；
- 引用和被引关系；
- 相邻理论或算法名称。

保存每条查询的数据库、查询式、过滤条件、日期和命中数。

#### 何时可以复用快照

只有以下全部不变才可复用：

- 研究范围（scope）；
- 当前年份；
- 查询覆盖；
- 版本链状态。

复用时登记：

```text
snapshot_mode = REUSED_VERIFIED_SNAPSHOT
```

否则重新进行有界近期检索并登记：

```text
snapshot_mode = NEW_SEARCH
```

近三年完成前，不得用旧经典文献替代，也不得进入碰撞。

下一状态：`LITERATURE_REGISTER`。

### 7.5 文献注册（`LITERATURE_REGISTER`）

每个实质相关命中立即写入 `near_neighbor_registry.json`。不要先积累一批链接，
准备“以后统一录入”。

一篇规范文献实体（canonical work）只建一条记录：

```text
W-0001
```

预印本、会议版、期刊版和镜像链接通过版本关系和别名链接（alias URL）连接，
不重复建立文献实体（work）。

必须核验：

- 规范题名；
- 作者；
- 年份；
- DOI 或官方持久标识；
- 版本关系；
- 正式出版状态；
- 同行评审状态；
- 官方核验入口。

重要性分级：

| 等级 | 用途 |
|---|---|
| `CRITICAL` | 最危险直接近邻、决定性反例、覆盖来源或关键理论前驱 |
| `IMPORTANT` | 研究链关键推进、主要方法/基线、支持 K/U/Δ 的核心工作 |
| `CONTEXT` | 背景或关键词近邻 |

`CONTEXT` 不能直接支持最终输出结论。

下一状态：`L1_FREEZE`。

### 7.6 L1 冻结（`L1_FREEZE`）

L1 段只依据元数据与摘要浏览（零全文、零原子观点）。把研究工作冻结成 L1 卡
（产物登记为 `l1_card`，如 l1-card.md）：

- 领域边界与连续簇；
- 谁在做、最强研究链；
- `l1_frozen=true`。

L1 冻结只回答"这条研究程序值得继续"，不回答"创新点是什么"。

下一状态：`L2_TRIAGE`。

### 7.7 K 集合选拔（`L2_TRIAGE`）

用浅证据（元数据 + E1 摘要 + ≤12 篇全文试读，仍不提取原子观点）从注册文献中
选拔 K 集合——后续全重机器只对 K 集合运行。产出 `k_triage`（如 l2-triage.md）：

- K 集合成员及选拔理由；
- 落选重要文献的处理方式；
- `k_set_selected=true`。

碰撞综合中发现 K 集合漏了关键近邻时，允许回退到 `K_FULLTEXT` 补取，并在
decision_log 记明。

下一状态：`LAYER_DECISION`。

### 7.8 层级裁决（`LAYER_DECISION`）

一次只裁决当前证据层级（由当前状态派生）：

| 层级 | 允许裁决 |
|---|---|
| L1 | `PASS AS RESEARCH PROGRAM`、`PARTIAL COLLISION`、`FAIL AS PROGRAM` |
| L2 | `PASS AS FEASIBLE MICRODOMAIN`、`NEEDS REBOUNDARY`、`FAIL AS DOMAIN` |
| ARCHITECTURE | 博士三贡献通过/重分，或期刊单主贡献通过/重聚焦 |
| L3 | 进入 N0 审计，不用上层口号代替命题证据 |

如果进入新层级或新候选：

1. `collision_round += 1`；
2. 设置新的 `active_contribution`（证据层级随状态推进自动派生）；
3. `active_state = PRIOR_CLAIM_DRAIN`；
4. 先耗尽旧观点。

不要直接从 L1 PASS 跳到 L3。

下一状态：`K_FULLTEXT`。

### 7.9 K 集合全文归档（`K_FULLTEXT`）

只对 K 集合中的文献（L2_TRIAGE 选拔、LAYER_DECISION 冻结 L2 与架构之后
运行，不是全部 CRITICAL/IMPORTANT）：

1. 合法下载 PDF 或官方 HTML；
2. 核对文件内题名、作者和版本；
3. 保存到 `literature_archive/`；
4. 记录来源 URL、本地相对路径、下载时间；
5. 计算并登记 SHA-256；
6. 设置 `verified_against_metadata=true`。

校验哈希示例：

```bash
shasum -a 256 /path/to/research/literature_archive/W-0001.pdf
```

付费墙阻断时使用 `DOWNLOAD_BLOCKED`，不能绕过访问控制。该文献在取得合法全文前
不能进入 E2/E4 或支持最终结论。

下一状态：`K_CLAIM_REGISTER`。

### 7.10 K 集合观点注册（`K_CLAIM_REGISTER`）

只对 K 集合文献提取原子观点。在 `literature_claim_registry.json` 中，一条记录
只保存一个可判断观点：

```text
LC-0001
```

不要复制整篇摘要。每条至少写：

- 准确释义；
- 对象和研究范围（scope）；
- 条件和量词；
- 证据等级；
- 页、节、段、定理、表、图或算法的原文定位符（locator）；
- 判断类型（对候选存活判断的关系）；
- 发现轮次；
- 使用状态。

观点判断类型（`claim_type`，已取代旧 `support_role`）：

```text
OCCUPIES    候选主张被近邻直接占据
CONTRADICTS 近邻结论与候选冲突 / 证伪候选
BOUNDS      近邻给候选划定边界 / 失效条件
ENABLES     近邻提供候选可用的前提 / 方法 / 基线
NEUTRAL     与候选无关（一般不登记）
```

深读顺序建议：

1. 正式定义；
2. 问题设置和信息边界；
3. 方法、定理或算法；
4. 实验条件；
5. 强基线和分母；
6. 结果表；
7. 限制；
8. 证明或附录。

摘要只能帮助发现碰撞，不能承担覆盖或终局关闭。

下一状态：`SYNTHESIZE_COLLISION`。

### 7.11 碰撞综合（`SYNTHESIZE_COLLISION`）

先把文献组织成连续研究链，而不是逐篇写摘要：

```text
原始问题
  → 条件放松或结论强化
  → 反例、修复或边界
  → 当前最强正式出版结果
  → 尚未闭合的结构责任
```

然后写：

```text
K = 最近、最强且结果口径已核准的已知结果
U = K 内部尚未闭合的推理、边界、识别或性能责任
Δ = 只解决 U 的最小非机械知识增量
```

#### 七项对齐

对候选与最危险研究链比较：

| 字段 | 含义 |
|---|---|
| O | 对象或生成机制 |
| I | 信息集或观测 |
| A | 行动、协议或结构 |
| T | 目标、损失或 estimand |
| C | 条件与量词 |
| R | 结论形式 |
| B | 关键强基线 |

#### 非机械性攻击

必须尝试：

- 变量替换；
- 加标准约束；
- 直接特例化；
- 两篇结果拼接；
- 换分母或重算公开表格；
- 使用现成软件或成熟外壳；
- 构造最小反例。

如果覆盖理论 T 已经覆盖自然候选，不能立即换场景或收窄。使用上钻六问：

1. T 的证明依赖什么未审查结构承诺？
2. T 的像是什么？
3. T 的逆命题在哪里断裂？
4. 边界、等号、空支撑或退化情形暴露什么？
5. 关键引理的最大可达边界（maximal reach）是什么？
6. T 为什么停在这里？

建议提示词：

```text
当前 active_state=SYNTHESIZE_COLLISION。
只使用 literature_claim_registry.json 中已核验观点。
先复述用户已确认的主创新路径和主创新形式；所有候选必须在该合同内解释。
先构建连续研究链，再写一个 K、一个 U 和一个最小 Δ。
完成 O/I/A/T/C/R/B 对齐、机械推出攻击、最小反例和失败条件。
如果被理论 T 覆盖，执行上钻六问；不得用换场景逃避。
```

**碰撞三段式 + 逐近邻强制证伪（R-REVIEW-20）**：碰撞结论不能只写"候选很新"。
碰撞类结论（`NOVELTY_VERDICT`/`CLOSURE`/`METHOD_COMPARISON`）必须三段式——
`evidence`（我读到了什么：数值锚点或 locator）→ `reasoning`（如何推出）→
`statement`（结论），先证据后结论。逐近邻回答三条证伪（直接占据？机械推出？
换名？），每条"不能"都要有可验证理由。写完碰撞结论后逐条追问"这条和原文
一致吗？删掉它裁决会变吗？"——追问是产物的一部分。

下一状态：`OUTPUT_CLAIM_BIND`。

### 7.12 输出结论绑定（`OUTPUT_CLAIM_BIND`）

把每条实质研究结论登记为：

```text
OC-0001
```

包括：

- 研究链总结；
- 覆盖或差异判断；
- K/U/Δ；
- 创新性判断；
- N0 裁决；
- 方法比较；
- 关闭理由。

每条输出至少绑定一个已全文核验的重要观点 ID：

```text
OC-0001
  → LC-0001
    → W-0001
      → 原文定位符（locator）
        → local fulltext + SHA-256
          → official identity URL
```

如果输出是综合、对照或推理，必须写 `reasoning`，明确哪些是来源事实、哪些是
自己的推导。

碰撞类结论（`NOVELTY_VERDICT`/`CLOSURE`/`METHOD_COMPARISON`）还必须写
`evidence` 字段——数值锚点或 locator（如"N 的表 3 报告 AUPRC=0.288"）。缺
evidence 或无数值锚点即 `ATOMIC_COLLISION_NO_ANCHOR`。

下一状态：`EVIDENCE_VALIDATE`。

### 7.13 证据校验（`EVIDENCE_VALIDATE`）

运行（`iph validate` 是对底层 `validate_all.py` 的封装，输出相同）：

```bash
python3 scripts/iph.py validate --root . --state workflow_state.json
```

预期：

```text
workflow_state_errors=0
publication_metadata_errors=0
evidence_chain_errors=0
validation_suite_failures=0
```

只有全部为 0 才能进入 N0 审计。

下一状态：`N0_AUDIT`。

### 7.14 新颖性预审（`N0_AUDIT`）

N0 只用于单个 L3：

| 等级 | 含义 | 动作 |
|---|---|---|
| N0-1 | 被直接近邻占据 | 正式出版资格满足后关闭 |
| N0-2 | 可机械推出 | 吸收或关闭 |
| N0-3 | 似乎非机械但证据、见证或专属门未闭合 | HOLD，不计算 |
| N0-4C | 非机械性、证据、路径和形式门全部通过 | 锁定方向 |

N0-4C 不自动授权实验。仍需用户明确授权并满足计算门。

**证伪书（falsification ledger，R-N0-17）**：裁决任何候选为 N0-4C 之前，
`novelty-audit.md` 必须先写证伪书——逐条列出"我尝试杀死这个候选的方式及为何
失败"（直接占据、机械归约、换名检测至少各一条，确无某类路径时逐条登记理由）。
候选存活是证伪失败后的残留，不是未被注意的空缺。证伪书写不出或站不住，候选
不得前进。负面终局与正面终局同价同严：N0-1 须有占据证据（occupation
evidence），N0-2 须有归约证据（reduction evidence）。

---

## 8. 博士论文完整路径

### 8.1 阶段一：冻结 L1

目标：证明整条研究程序值得继续，而不是证明已有三个创新。

输出：

- L1 研究工作冻结卡；
- 直接近邻是否系统完成整条链的审计；
- `l1_frozen=true`。

### 8.2 阶段二：冻结 L2

目标：在 L1 内找到一个既能执行、又足以支撑博士规模的微领域。

输出：

- O/I/A/V/T/B；
- 准入和退出边界；
- 数据与计算可行性；
- `l2_frozen=true`。

### 8.3 阶段三：划分 A/B/C

使用三贡献架构卡。逐项检查：

| 检查项 | A | B | C |
|---|---|---|---|
| 研究单位 | 不同 | 不同 | 不同 |
| 主要自变量 | | | |
| 目标量 | | | |
| 关键证据 | | | |
| 退出边界 | | | |

再写有机依赖：

```text
A 的输出如何成为 B 的输入
B 的合格状态如何进入 C
C 如何反向约束 A/B
```

通过后设置 `architecture_frozen=true`。

### 8.4 阶段四：分别寻找 A/B/C 的 L3

顺序示例：

```text
L3-A round
  → prior claim drain
  → evidence pipeline
  → N0 audit

L3-B round
  → prior claim drain
  → evidence pipeline
  → N0 audit

L3-C round
  → prior claim drain
  → evidence pipeline
  → N0 audit
```

每个贡献至少需要一个主 L3 达到 N0-4C。A 的命题不能在 B 或 C 中再次计数。

### 8.5 博士模式提示词

```text
使用 innovation-proposition-hunting 的博士模式。
成果合同固定为 THREE_ORGANIC_A_B_C。

当前在 LAYER_DECISION（架构划分阶段）。
请从冻结 L2 划分 A/B/C：
1. 分别定义研究单位、主要自变量、目标量、关键证据和退出边界；
2. 至少证明三项差异；
3. 写出 A→B→C 的输入输出依赖；
4. 识别重复计算和伪贡献；
5. 不得把贡献标题写成已经成立的创新；
6. 架构通过后，只进入一个贡献的 L3，不并行宣称三个 N0-4C。
```

---

## 9. 一般期刊论文完整路径

### 9.1 冻结 L1 和 L2

期刊也需要 L1/L2，但范围必须能收敛到一篇文章的单一责任。

### 9.2 定义主贡献 M

M 必须回答：

- 唯一主问题是什么？
- 唯一主知识输出是什么？
- 关键反方或强基线是什么？
- 哪些结果只是 M 的后果？
- 哪些算法、数据或实验只是支持组件？
- 在目标篇幅内能否自足？

### 9.3 防止伪多贡献

以下通常不是第二个主贡献：

- 新数据集；
- 一个消融实验；
- 算法实现细节；
- 主定理的直接推论；
- 同一结果换一个指标描述；
- 为主命题服务的证明工具。

### 9.4 期刊模式提示词

```text
使用 innovation-proposition-hunting 的一般期刊模式。
成果合同固定为 ONE_MAIN_M。

请在冻结 L2 内定义唯一主贡献 M：
1. 用一句话写唯一主知识责任；
2. 将所有定理、实验和算法分为主 L3、从属后果或支持组件；
3. 删除隐藏的第二条并列主线；
4. 检查目标篇幅内能否自足；
5. 只对 M 的主 L3 执行 K→U→Δ 和 N0；
6. 不得把多个 L3 自动重计为多个主贡献。
```

---

## 10. 三种创新路径怎么选

### 10.1 R1：空白发现（`GAP_OPENING`）

适用：

- 研究链已明确；
- O/I/A/T/C/R/B 已对齐；
- 仍存在无人承担的关键知识责任。

必须证明：

- 不是因为检索词不对而“没搜到”；
- 不是直接翻译未来工作（future work）；
- 不是换数据、换接口或换领域名；
- Δ 对研究链本身必要。

常见形式：R1+F1、R1+F3。

### 10.2 R2：深度推进（`DEPTH_EXTENSION`）

适用：

- K 已成熟且可靠；
- 仍有最大可达边界（maximal reach）、像/逆、边界、瓶颈、紧致性
  （sharpness）或性能前沿未闭合。

必须证明：

- 不是普通调参；
- 不是标准特例；
- 需要新的关键引理、反例、识别条件或收益机制；
- 推进轴和失败门明确。

常见形式：R2+F1、R2+F4。

### 10.3 R3：新问题论证（`NEW_PROBLEM_SUBSTANTIATION`）

适用：

- 新问题先于工具独立成立；
- 成熟理论需要新的语义映射、假设核验或识别桥才能进入新对象。

必须交付至少一项：

- 新问题的可检验形式化；
- 源理论假设在新领域中的成立、修正或失效证明；
- 源理论不能直接读出的新领域结论；
- 新识别设计、测量桥或反事实证据；
- 新领域特有的适用和退出边界。

最常见形式：R3+F2。

### 10.4 四种创新形式

| 编号 | 中文术语（英文原名） | 最低交付物 |
|---|---|---|
| F1 | 新理论（`NEW_THEORY`） | 定义、命题、证明责任、见证或反例 |
| F2 | 成熟理论的新领域应用（`MATURE_THEORY_NEW_DOMAIN`） | 语义映射、假设核验、新领域结论和边界 |
| F3 | 新算法（`NEW_ALGORITHM`） | 新计算规则、复杂度、同预算强基线和消融 |
| F4 | 既有算法深度改进（`ALGORITHM_DEEPENING`） | 原瓶颈、修改变量、收益机制、保护约束和退出门 |

### 10.5 快速选择表

| 问题 | 是 | 否 |
|---|---|---|
| 对齐研究链后仍有责任无人承担？ | 优先 R1 | 继续下一问 |
| 已有成熟 K，但其边界、像/逆或瓶颈未闭合？ | 优先 R2 | 继续下一问 |
| 新问题独立成立，成熟工具需要新映射和证据桥？ | 优先 R3 | 候选可能只是应用或工程包装 |

### 10.6 路径锁定贯穿全过程

路径和形式不是每轮碰撞都可重新选择的标签。用户确认后，它们构成当前研究代次的
主贡献合同，并贯穿检索、候选排序、命题冻结、G9 审计、计算和最终锁定。

#### 主贡献与支持性贡献

- `PRIMARY`：论文准备作为核心创新声称的知识责任，必须符合已锁定形式；
- `SUPPORTING`：证明、解释、界定、实现或验证主贡献的结果，可以来自另一种类型，
  但不得取得主线地位。

典型例子：用户选择 R2+F4 的算法优化路径后，研究中可能得到收敛界、保护定理或
机制引理。这些属于支持性理论，可以提高算法创新的理论厚度；智能体不得转向理论创新，
不得把 F1 新理论改写为新的主目标，也不得用 `MIXED` 为中途换轨背书。

#### 每一步如何贯彻

1. 每次恢复任务先复述锁定的路径、形式和当前代次；
2. 新文献只用于检验或深化当前路径，不因出现其他机会而自动改写目标；
3. 每个 claim 标明 `PRIMARY` 或 `SUPPORTING`；
4. 交接时说明本轮产物如何服务锁定主贡献；
5. 发现主 claim、贡献架构或计算目标偏离时，报告 `INNOVATION_PATH_DRIFT` 并停止。

#### 什么时候允许改变

只有用户明确确认改变主路径或主形式时才允许显式重启。重启不是在原流程内改一个
标签，而是建立新一代路径：保留旧选择和重启理由，回到 `SCOPE_LOCK`，重新确认
scope、候选、声明角色、前沿证据、有效性审计和计算授权。用户未确认时，新的方向
只能记录为支持性线索或未来重启候选，不能并行成为第二条主创新。

---

## 11. 文献、观点和输出三层注册示例

以下仅展示关系，完整字段以
[`evidence-pipeline.md`](../evidence-pipeline.md) 和
[`templates.md`](../templates.md) 为准。

### 11.1 文献记录

```json
{
  "registry_id": "W-0001",
  "canonical_title": "<已核验题名>",
  "identity_status": "VERIFIED",
  "importance": "IMPORTANT",
  "download": {
    "status": "FULLTEXT_ARCHIVED",
    "local_path": "literature_archive/W-0001.pdf",
    "sha256": "<hash>",
    "verified_against_metadata": true
  },
  "claim_extraction_status": "COMPLETE"
}
```

### 11.2 原子观点

```json
{
  "claim_id": "LC-0001",
  "source_registry_id": "W-0001",
  "claim_type": "ENABLES",
  "normalized_statement": "在条件 C 下，方法 A 相对基线 B 改善目标 T。",
  "locator": {
    "page": "7",
    "section": "4.2",
    "table": "2"
  },
  "conditions": ["C"],
  "evidence_level": "E2",
  "verification_status": "VERIFIED_FULLTEXT",
  "use_status": "USED",
  "used_by_output_claim_ids": ["OC-0001"]
}
```

### 11.3 输出结论

```json
{
  "output_claim_id": "OC-0001",
  "statement": "<当前研究链结论>",
  "claim_kind": "SYNTHESIS",
  "supporting_claim_ids": ["LC-0001"],
  "inference_type": "SYNTHESIS",
  "reasoning": "解释 LC-0001 如何在其条件范围内支持本结论。",
  "trace_status": "VERIFIED"
}
```

碰撞类结论（如 N0 裁决、关闭、方法比较）额外写 `evidence` 数值锚点：

```json
{
  "output_claim_id": "OC-0002",
  "statement": "候选 M 的 risk 侧非机械推出。",
  "claim_kind": "NOVELTY_VERDICT",
  "evidence": "N 的表 3 报告 AUPRC=0.288（单任务），加 5pp 仍需联合实验",
  "supporting_claim_ids": ["LC-0001"],
  "inference_type": "INFERENCE",
  "reasoning": "单任务基线 + 联合候选需要新实验，非变量替换可得。",
  "trace_status": "VERIFIED"
}
```
完整链：

```text
OC-0001 → LC-0001 → W-0001 → page 7/table 2
→ literature_archive/W-0001.pdf → SHA-256 → official URL
```

---

## 12. 新碰撞、断点续跑和年份变化

### 12.1 什么算新碰撞

以下变化使 `collision_round += 1`：

- 新建或实质改变 L3；
- 改变目标研究链；
- 改变覆盖理论；
- 改变关键比较基线；
- 改变 O/I/A/T/C/R/B；
- 转入新的层级或贡献。

普通新碰撞不能改变已经锁定的创新路径或形式。需要换轨时使用第 10.6 节的显式
重启规则；不能用增加 `collision_round` 冒充路径重启。

若当前是 `N0_AUDIT / N0-4C`，而复核认为实例见证、近邻覆盖或非机械性不足，
先运行 `iph retract-novelty --to N0-3`（登记新的 novelty-audit），再开新碰撞。
不得手改 `novelty_level`，也不得在已证伪的 N0-4C 上进入 `CLAIM_FREEZE`。

只补页码、证据级、版本别名（alias）或措辞不增加轮次。

### 12.2 用户只说“继续”时

智能体（agent）必须：

1. 读取 `workflow_state.json`；
2. 核对声明产物是否存在；
3. 运行当前应到期的校验；
4. 从 `next_required_action` 继续；
5. 复述锁定的主创新路径、形式和贡献角色；
6. 不重置研究范围（scope）、路径、形式、层级、贡献编号或轮次。

续跑提示词：

```text
继续当前 innovation-proposition-hunting 任务。
先读取 workflow_state.json、scope_lock.md 和三个证据 JSON。
报告 active_state、由状态派生的证据层级、active_contribution、collision_round、
三个关键门禁（gate）和 next_required_action。
只执行 next_required_action；不得重新启动检索或改变冻结上层。
```

### 12.3 当前年份变化

例如从 2026 进入 2027：

1. `current_year` 改为 2027；
2. 近三年窗口改为 2025–2027；
3. `recent_window.status=INCOMPLETE`；
4. `snapshot_mode=NOT_SET`；
5. 重新执行有界近期检索；
6. 将不再属于近期窗口的旧记录重新归入历史回填（foundational backfill），
   并保留原检索历史；
7. 验证通过后再恢复碰撞。

年份刷新本身不必改变研究问题；只有 O/I/A/T/C/R/B 等实质范围变化才开启新碰撞。

---

## 13. 100 篇综合锁

同一主题达到 100 篇去重、实质相关、正式发表且同行评审的规范文献实体
（canonical works）后：

```text
search_mode = SYNTHESIS_LOCK
```

此时：

- 禁止继续通用横向搜索；
- 必须按正式对象和语义操作构建微型领域研究链；
- 碰撞单位从孤立论文改为完整研究链；
- 预印本继续登记，但不计入 100。

只有以下情况允许 `EXCEPTION_REOPEN`：

- 存活命题进入现有链外的新正式对象；
- 终局裁决缺正式出版锚点；
- 关键版本链或作者续作未核清；
- 上钻需要必要外部理论前提。

每次重开必须写精确查询、限定领域、预计补齐内容和停止条件，完成后立即回锁。

---

## 14. 计算验证怎么启动

（本节涉及的有效性轴 V0–V4 与状态 CLAIM_FREEZE → FINAL_LOCK，
定义见 [SKILL.md](../SKILL.md) §3.2 双轴状态机。）

以下公式是硬门，不是建议：

```text
COMPUTE = N0-4C AND V3 AND compute_authorized
FINAL_LOCK = N0-4C AND V4 AND current independent audit
```

`compute_authorized=true` 必须来自用户或权威授权，但用户授权只是它的必要条件，
不构成硬门旁路：智能体不能因为 N0-4C 自行开启，"用户指定/导师要求"也不能替代
N0-4C 与 V3 中的任何一项。COMPUTE 门之前禁止任何产生数值输出的实验，包括自称
"探索""预实验"的计算；S0-SCREEN 阶段确需数值预实验时，产物必须当天登记
`exploration_registry.json`（`iph register-exploration`），其数字不得进入任何
冻结工件。

计算按 [`compute-funnel.md`](../compute-funnel.md) 执行：

| 阶段 | 作用 |
|---|---|
| S0-SCREEN | 文献链和优化动作复核 |
| S1 | 使用已有工件筛查效应和识别性 |
| S2 | 最小开发集微型效果试验 |
| S3 | 中型验证效果、保护和强基线 |
| S4 | 预注册后的封存确认 |

S0-SCREEN 是该阶段的语义名；state 的 `compute_stage` 枚举值仍为 `S0`。

计算授权提示词：

```text
当前 L3 已达到 N0-4C。先运行：
python3 scripts/iph.py validate --root . --state workflow_state.json
只有全部零错误且我明确授权后，才设置 compute_authorized=true 并用 iph advance
推进。先填写 S0-SCREEN/S1 阶段卡、资源上限、最低效果、保护门、同预算匹配
（matched-budget）基线和无效性停止条件。不得直接进入 S4。
```

---

## 15. 常见校验错误与恢复

### 状态门禁错误（`STATE_GATE`）

含义：当前状态依赖的门禁（gate）还没有通过。

处理：

- 回到错误中指出的最早门禁（gate）；
- 补产物并重新校验；
- 不手工删除错误或强行把门禁改为 `true`。

### 成果合同或贡献错误（`CONTRACT` / `CONTRIBUTION`）

含义：博士/期刊合同与 M/A/B/C 不匹配。

处理：

- 核对 `output_type`；
- 核对 `contribution_contract`；
- 非 L3 阶段设置 `active_contribution=NONE`。

### 全文下载错误（`DOWNLOAD`）

含义：重要全文缺失、路径越界、版本不匹配或 SHA-256 不一致。

处理：

- 检查合法全文；
- 核对元数据；
- 重新计算哈希；
- 无法访问时进入 BLOCKED，不得降级伪装。

### 来源观点错误（`CLAIM` / `CLAIM_EXTRACTION`）

含义：重要文献没有原子观点、证据等级不足或条件缺失。

处理：

- 深读正式定义、方法/定理、实验和结果；
- 拆分复合观点；
- 补研究范围（scope）、条件（conditions）和原文定位符（locator）。

### 引用追溯错误（`TRACE`）

含义：OC、LC、W 或反向链接不完整。

处理：

- 从输出结论向下逐层展开；
- 补 `supporting_claim_ids`；
- 在观点中补 `used_by_output_claim_ids`；
- 核验本地全文和官方入口。

### 碰撞门禁错误（`COLLISION_GATE`）

含义：以前轮次仍有 `UNUSED` 观点。

处理：

- 返回 `PRIOR_CLAIM_DRAIN`；
- 使用或有理由排除每条旧观点；
- 禁止用新搜索逃避旧证据。

### 出版资格错误（`PUBLICATION_ERROR`）

含义：出版状态、同行评审状态、官方入口或终局资格不一致。

处理：

- 回到出版社卷期、文章号或官方 proceedings；
- 不从 venue 名称猜同行评审状态；
- 预印本保持 `PREPRINT_ONLY`；
- 不能核验时使用 `STATUS_UNVERIFIED` 并保持开放。

### 未注册链接错误（`UNREGISTERED`）

含义：研究文件出现了学术链接（URL），但没有映射到规范文献注册表
（canonical registry）。

处理：

- 找到对应 work；
- 新建或链接已有 `registry_id`；
- 保留别名链接（alias URL）；
- 刷新 URL ledger。

### 创新路径漂移（`INNOVATION_PATH_DRIFT`）

含义：主 claim、贡献架构、计算目标或 `claim_profile` 偏离用户最初确认的创新路径
与形式，或者智能体把支持性发现升级成了第二条主创新。

处理：

- 立即停止候选晋级、计算和最终锁定；
- 保持当前路径不变，把跨路径发现降回 `SUPPORTING`；
- 如果确实需要改变主方向，说明代价并取得用户明确确认；
- 确认后建立新一代路径并回到 `SCOPE_LOCK`，不得原地改标签或复用旧审计。

### 诚实判断错误（证伪书 / 实质检查）

本次技能强化后新增的检查码，默认 WARNING，`--strict-new-checks` 升 INVALID；
评审与交接一律以 strict 结果为准：

- `FALSIFICATION_LEDGER_MISSING` / `OCCUPATION_EVIDENCE_MISSING` /
  `REDUCTION_EVIDENCE_MISSING`：`novelty-audit.md` 缺与 novelty_level 对应的
  裁决证据（N0-4C 缺证伪书、N0-1 缺占据证据、N0-2 缺归约证据）。处理：先写
  证据节再推进，正面负面同价同严。
- `ATOMIC_CLAIM_NO_ANCHOR`：原子观点是"Paper W-XXXX proposes..."这类文献元
  描述套壳。处理：重写为五要素（条件/方法/基线/指标/数值）的可证伪断言，或
  理论类观点补 theorem/lemma locator。
- `ATOMIC_COLLISION_NO_ANCHOR`：碰撞类结论缺 evidence 数值锚点。处理：补
  `evidence` 字段（表号/定理号 + 可复算数值），先证据后结论。
- `COMPUTE_DATA_SOURCE_UNSPECIFIED` / `SYNTHETIC_DATA_NAMED_AS_REAL` /
  `MANUSCRIPT_DATASET_UNVERIFIED`：计算数据源未声明、合成数据冒用真实数据集名、
  manuscript 声称的数据集无对应非合成条目。处理：在 compute_evidence 补
  `data_sources`，合成数据标 `synthetic: true` 且不得用真实数据集名。
- `BASELINE_NOT_EXECUTED`：baseline_budget 声明的 comparator 在 compute_evidence
  里 per_run 为空。处理：补实际执行证据，或把该 comparator 明确标为 NOT_RUN
  且不得计入比较结论。
- `CLAIM_STRENGTH_EXCEEDS_PROFILE`：ALGORITHM profile 下经验 claim 用了
  provably/guaranteed/theorem 等定理级措辞。处理：升 profile 到 MIXED 并跑
  theory obligations，或把措辞降级为经验表述。
- `REVIEW_ANSWERS_INCOMPLETE`：独立 reviewer 的 PASS 缺实质四问。处理：重新
  派 subagent 跑 `iph review`，补全四问（数据真实性/baseline 执行/措辞强度/
  证伪尝试），不得写"已确认通过"。
- `REVIEW_ARTIFACT_TAMPERED`：review 产物被主 agent 事后改写。处理：重新派
  subagent 生成 review 产物并重新 `iph review` 登记 hash。
- `CAPABILITY_FLIPPED_WITHOUT_PROVENANCE`：capability_available 翻 true 但无
  review 产物 hash 登记。处理：走 `iph review` 登记产物 hash。
- `EVIDENCE_SCOPE_REGRESSED`：K 全文门已过后 scope 被清空。处理：恢复 scope，
  登记只能单调增长。
- `NEXT_ACTION_INCONSISTENT_WITH_STATE`：终局态下 next_required_action 滞留
  中间态。处理：更新为终局处置。
- `ARTIFACT <key>:missing_or_unsafe_path` 且文件已经存在：旧版推进只登记了
  decision_log 哈希，遗漏顶层路径指针。STOP 期间使用
  `iph clear-lock --set-artifact key=path --next-action "<下一动作>" \
  --recovery-note "补登记遗漏的 artifact 指针"` 受控修复并重验；不得手改 state
  或直接删除 `.workflow_stop.lock`。

---

## 16. 可直接复制的提示词库

### 16.1 查看状态，不推进

```text
使用 innovation-proposition-hunting，只做状态审计，不推进。
读取 workflow_state.json 和已声明产物。
报告状态与产物不一致、未通过门禁（gate）、以前轮次未使用观点
（prior-round UNUSED）和唯一恢复动作。
不要修改文件、搜索文献或提出新候选。
```

### 16.2 深读一篇重要近邻

```text
当前 active_state=K_CLAIM_REGISTER。
对 W-<id> 执行 E2/E4 深读：
1. 核对正式定义；
2. 核对信息边界、方法/定理、实验臂、强基线、分母和结果表；
3. 复算可复算指标；
4. 提取原子观点、结论、方法、假设、限制和反例；
5. 每条写来源观点编号（LC ID）、条件（conditions）、研究范围（scope）、
   原文定位符（locator）和判断类型（claim_type：占据/使能/矛盾/边界/无关）；
6. 不得把摘要宣传句当成完成度。
```

### 16.3 生成 K→U→Δ

```text
当前 active_state=SYNTHESIZE_COLLISION。
只使用已核验 LC 观点：
1. 构建连续研究链；
2. 写当前最强 K；
3. 找 K 内部尚未闭合的 U；
4. 提出只解决 U 的最小 Δ；
5. 对齐 O/I/A/T/C/R/B；
6. 执行变量替换、特例化、机械拼接、换分母和最小反例攻击；
7. 固定一个主创新路径和一个主创新形式；
8. 将新定理、算法或实验标为 PRIMARY 或 SUPPORTING；
9. 若候选不属于锁定路径，报告 INNOVATION_PATH_DRIFT，不得自动换轨；
10. 写明确关闭条件；
11. 逐近邻回答三条证伪（直接占据？机械推出？换名？），每条"不能"都要有
    可验证理由；碰撞类结论先写 evidence 数值锚点再下结论。
```

### 16.4 被近邻覆盖后上钻

```text
候选 P 被理论 T 覆盖。不要换场景或立刻收窄。
请进入 T 的证明机器并回答：
Q1 结构承诺；
Q2 像；
Q3 逆命题断裂；
Q4 边界/退化情形；
Q5 关键引理的最大可达边界（maximal reach）；
Q6 停止理由。
只有产出 T 自身未回答的精确结构问题时，才建立新候选；
六问闭合后才允许关闭。
```

### 16.5 执行 N0 审计

```text
当前 active_state=N0_AUDIT。
只审计 active_contribution 的单个 L3。
检查正式出版资格、E2/E4、研究链、K→U→Δ、最小见证、机械推出攻击、
主路径门、主形式门和失败条件。
先写证伪书（falsification ledger）：逐条列出"我尝试杀死候选的方式及为何失败"
（直接占据、机械归约、换名检测）。N0-1/N0-2 分别写占据证据/归约证据。
输出 N0-1/2/3/4C 及唯一动作。
预印本只能形成 PREPRINT THREAT，不得终局关闭。
```

### 16.6 结束本轮并交接

交接清单的权威版本见 SKILL.md §10；状态推进的标准动作是 `iph advance`（自动完成
validate → 写 decision_log → 原子更新 state）。

### 16.7 发现另一条更有吸引力的路径

```text
当前任务已经锁定主创新路径和主创新形式。
请先判断新发现是服务当前主贡献的 SUPPORTING 结果，还是要求更换 PRIMARY 的路径漂移。
如果只是支持结果，保持原路径并说明其作用；如果需要换主路径，报告
INNOVATION_PATH_DRIFT，列出重启收益、损失和必须失效的审计或计算授权。
除非我明确确认重启，否则不得修改主路径、主形式或 claim_profile，也不得并行推进。
```

---

## 17. 最常见的错误用法

1. 一开始就让智能体（agent）“列十个创新点”。
2. 没有 `workflow_state.json` 就开始检索。
3. 把 L1、L2 和 L3 混成一个“新不新”。
4. 博士用三个标题冒充三个贡献。
5. 期刊把一个 M 拆成几个主贡献。
6. 只保存论文列表，不保存原子观点。
7. 输出只引用 DOI，不绑定 LC。
8. 从摘要判断论文已经覆盖候选。
9. 把未来工作（future work）直接翻译成自己的创新。
10. 被覆盖后换场景逃跑，而不进入覆盖理论内部上钻。
11. 当前轮次旧观点未处理就继续搜索。
12. 用预印本做终局关闭。
13. N0-4C 后自动运行昂贵实验。
14. 用户说“继续”时重新启动整个流程。
15. 用更多参数、数据或算力包装算法创新。
16. 选择算法优化后，因发现一个定理就中途改做理论创新。
17. 用 `MIXED`、新碰撞轮次或措辞变化掩盖主创新路径漂移。

---

## 18. 完成判据

### L1 完成

- 对象、核心矛盾、总目标、动态轴和强基线已冻结；
- 直接近邻没有系统完成整条研究程序；
- 裁决由观点级证据支持。

### L2 完成

- O/I/A/V/T/B 和边界清楚；
- 数据、算力和访问可行；
- 比 L1 窄、比 L3 宽；
- 能承载博士 A/B/C 或期刊 M。

### 贡献架构完成

- 博士 A/B/C 非重叠且有机；
- 或期刊唯一 M 自足；
- 没有用标题、数据集或算法步骤伪造贡献。

### L3 N0-4C 完成

- 当前前沿追至当年；
- K/U/Δ 精确；
- Δ 不可机械推出；
- 有最小见证、反例或可证伪预测；
- 主创新路径和形式门通过；
- 路径从用户确认到当前锁定代次保持一致，所有跨类型结果均明确标为支持性贡献；
- 所有实质结论完成观点级追溯；
- 校验器全部为 0；
- 明确失败和关闭条件。

### 全流程完成

- `active_state=COMPLETE`；
- 没有未完成的必需动作；
- 没有 prior-round UNUSED；
- 最终交接与 `workflow_state.json` 一致；
- 没有把内部成功写成外部同行确认。

---

## 19. 推荐阅读顺序

第一次使用：

1. 本教程；
2. [`SKILL.md`](../SKILL.md)；
3. [`templates.md`](../templates.md) 的工作流状态（workflow state）和当前卡片；
4. [`evidence-pipeline.md`](../evidence-pipeline.md)；
5. 需要详细判据时查 [`reference.md`](../reference.md)；
6. N0-4C 且获授权后才读 [`compute-funnel.md`](../compute-funnel.md)；
7. 遇到反模式时读 [`case-lessons.md`](../case-lessons.md)。

熟练后每次运行只需读取主协议、当前状态和当前状态需要的参考部分，不必把全部
文档一次性装入智能体（agent）上下文。
