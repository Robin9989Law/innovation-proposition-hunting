# L3 多保真计算漏斗

## 目录

1. 原则
2. S0-SCREEN–S4 阶段
3. 无效性停止门
4. 数据与确认完整性
5. 工程执行规则
6. 阶段卡模板

## 1. 原则

计算入口公式是：

```text
COMPUTE = N0-4C AND V3 AND compute_authorized
```

因此 `workflow_state.json` 必须同时满足 `schema_version=3.0`、
`active_state=COMPUTE`、`novelty_level=N0-4C`、`validity_level=V3`、
`gates.compute_authorized=true`，且当前 epoch/bundle 的 different-agent audit 为
PASS。旧 `n0_4_locked` gate 只是兼容性镜像，不能代替 N0-4C、V3 或当前 audit。
否则返回主状态机，不启动实验、模型调用或昂贵计算。每次阶段升级先落盘结果，
再更新 `compute_stage`。

合法计算入口由状态事务登记，而不是手改 gate：

```bash
iph advance --to COMPUTE \
  --authorize-compute --authorization-note "<用户明确授权依据>" ...
```

CLI 仍会先验证 N0-4C 与当前 V3 audit；授权参数不能旁路硬门。事务成功后
`compute_authorized=true` 且 `compute_stage=S0`。S4 完成后以
`--compute-evidence <path>` 进入 `POSTCOMPUTE_CLAIM_FREEZE`，随后以
`--claim-bundle-manifest <path>` 进入 `FINAL_VALIDITY_AUDIT` 并原子切换新 epoch。

把计算当作逐级获得的权限，不把完整确认实验当作探索工具。每个候选先使用
成本最低、最容易推翻它的证据。多数候选应在 S0-SCREEN–S2 关闭；S4 同一研究
周期只服务一个最终幸存候选。

固定科学顺序：

```text
效果是否存在
→ 旧功能是否可守
→ 是否超过最简单同预算基线
→ 机制量是否提供额外解释
→ 必要时再检验方向性、状态依赖和污染控制
```

导师要求优化效果时，不得先完成大规模机制、方向和动态实验，最后才检查算法
是否有真实增益。

## 2. S0-SCREEN–S4 阶段

| 阶段 | 目的 | 默认数据/模型规模 | 默认时间上限 | 允许结论 |
|---|---|---|---:|---|
| S0-SCREEN 文献链碰撞筛查 | 排除直接覆盖、机械归约、旧命题改名和无优化动作；**不产生任何数值输出** | 现有注册表、关闭库、研究链；零计算 | 2 小时 | `CLOSE/HOLD/ALLOW S1` |
| S1 现有工件筛查 | 检查最小效应信号与实验可识别性 | 已有缓存、面板、检查点；零新前向 | 1 小时 | `FUTILITY/ALLOW S2` |
| S2 微型效果试验 | 检查实现是否可能产生目标收益 | 约 2 receivers × 2 donors × 2 tasks × 2 seeds；只用 development | 3 小时 | `REFINE/CLOSE/ALLOW S3` |
| S3 中型验证 | 检查效果、保护和关键基线是否共同可达 | 约 2 receivers × 3 donors × 3 tasks × 3 seeds | 8 小时 | `CLOSE/LOCK S4 DESIGN` |
| S4 正式确认 | 一次性裁决最终候选 | 由命题量词决定；完整预注册控制与封存 held-out | 单独预算 | `PASS/FAIL` |

默认规模只是上限模板。命题若只声称两个 receiver 家族上的效果，不得为了“更
完整”自动运行全部有向边；命题若不主张方向性，不运行双向角色互换；单步效果
未通过时，不运行多轮状态实验。

### S0-SCREEN 门

要求候选给出成果类型/贡献合同、O/I/A/T/C/R/B、K→U→Δ、主创新路径、主创新
形式、实际优化变量和 matched-budget 失败门。
缺任一项时留在 S0-SCREEN，不启动计算。

S0-SCREEN 只读现有工件，**不产生任何数值输出**（无脚本、无扫描、无预实验
数据）。确需数值预实验时，产物必须当天登记 `exploration_registry.json`（永久
探索级，见 templates.md §12，`iph register-exploration`），其数字不得进入任何
冻结工件；未登记的数值产物视为未授权计算
（`UNREGISTERED_COMPUTE_ARTIFACT`）。

N0-3 HOLD 若只需要查看少量已发表原文上的反例/支撑实例，不得伪装成 S0 预实验，
也不得打开 COMPUTE。使用：

```bash
iph authorize-instance-probe --note "<用户明确允许小范围看实例>"
iph register-instance-probe --probe-id IP-0001 ...
```

上限 5 条；每条必须有已发表原文、locator 和度量定义；`old_metric_verdict=SUCCESS`
必须给出不是数据集均值的 `success_rule`。登记后的数字可以进入 novelty-audit。

注：`workflow_state.json` 的 `compute_stage` 枚举保留 `S0` 值（schema 3.0
枚举保持该值）；S0-SCREEN 是该阶段的语义名，强调"筛查、零数值产出"。

### S1 门

优先读取既有逐单元面板，检查：

- 是否存在与候选目标同口径的稳定正向单元；
- 核心自变量是否有足够方差；
- 目标量是否能在现有样本量下识别；
- 候选是否只是调低旧阈值、重新切片或对已看 held-out 救参；
- 最简单基线是否已经达到或超过候选可实现上界。

S1 只能生成探索证据。已打开的 test/held-out 不得因换命题而恢复确认资格。

### S2 门

先运行 actual、receiver-only 和一个最危险同预算基线；完整干预对照留到 S3。
seed 采用递增策略，例如 `2 → 3 → 5`。S2 只有在两个初始 seed 上方向一致、
没有重复灾难性退化且效应量接近最终最低收益时才升级。

### S3 门

同时检查：

1. 主收益有实际正向幅度，而非只改善诊断分数；
2. 每项旧功能保护可行；
3. 至少超过 receiver-only 和最简单 matched-budget 基线；
4. 核心机制量非退化且有区分度；
5. 最终成功比例在统计上仍可达。

只有 S3 通过后才写 S4 预注册。S3 只许点名封存来源，不得把封存 AST 写进
开发 runner。S4 必须使用独立 `sealed_runner`，每条 sealed `per_run` 必须带
8–64 字符标识符指纹（该词令须在 sealed runner 内、按词令边界未见）、非空
`inventory_atoms`，并打中已声明的一条 FAIL-* 合取。ALGORITHM 冻结句未声明
合取不得确认。空清单上的多余原子失败不算确认。终态窗口协议仍写
`NOT_YET_ACCESSED` 是常驻 INVALID。完整硬门见 hard-gates.md。

### S4 后的强制回路

S4 PASS 不直接产生最终主张或 FINAL_LOCK。先保存 `compute_evidence.json`，并在 state
中写入当前 epoch 的 `compute_evidence` pointer（`status=COMPLETED`、
`validation_epoch`、`artifact_path`、`artifact_sha256`），然后：

```text
S4 + current compute evidence
  → POSTCOMPUTE_CLAIM_FREEZE
  → validation_epoch += 1
  → 冻结计算后 exact claim inventory 与新 claim bundle
  → FINAL_VALIDITY_AUDIT
  → different-agent independent audit PASS
  → V4
  → FINAL_LOCK
```

最终公式是：

```text
FINAL_LOCK = N0-4C AND V4 AND current independent audit
```

计算结果只要改变 claim statement、量词、适用边界、效果强度、基线解释或失败
条件，就是 material change；旧 V3 bundle 立即失效。失败结果同样进入
`POSTCOMPUTE_CLAIM_FREEZE`，以实际支持的最弱 claim 重建新 epoch，不得维持原强度。

## 3. 无效性停止门

在 S2–S4 运行前登记停止规则；运行中只执行已登记规则。

### 3.1 确定性不可达

设总单元数为 (N)，已完成 (n)，已成功 (s)，要求通过比例为 (q)。若

\[
\frac{s+(N-n)}{N}<q,
\]

即使所有剩余单元成功也无法过门，立即停止。

### 3.2 效果无效

- 全部候选均拒绝，而成功合同要求至少一个真实功能增益；
- 最有利效果的上置信界仍低于最低收益；
- 主收益方向在最小重复中稳定为负；
- 候选仅节省成本但真实收益为零，而导师合同要求功能提升。

### 3.3 机制不可识别

- 核心机制量为常数、零方差或全部单侧下界不大于零；
- 机制量与对照量数值相同，无法构造增量比较；
- 独立模型对数量不足以支持预定的组外量词。

### 3.4 保护或基线失败

- 多次出现超过 (2\epsilon) 的灾难性旧功能伤害；
- 尚未超过 receiver-only 或最简单 matched-budget 基线；
- 收益仅来自更多参数、更多 token、更多搜索或更高推理 FLOPs。

停止是有效结果。保存已完成单元、停止时刻、触发门和最大仍可能效果，不以
补 seed、换阈值或删困难单元恢复同一候选。

## 4. 数据与确认完整性

为每个研究周期维护三类数据：

| 数据 | 用途 | 是否可反复查看 |
|---|---|---|
| 探索元数据集 | S1 命题筛查、失败模式和工程调试 | 可以，但只能作探索 |
| development 集 | S2/S3 训练、选择和消融 | 可以，须记录搜索次数 |
| sealed confirmation 集 | S4 一次性裁决 | 不可以；解封后永远降为探索数据 |

标准、置换、时间后置或污染控制只是数据角色；是否具有确认资格取决于是否曾被
查看和用于选择。换命题不会恢复同一数据的封存状态。

## 5. 工程执行规则

- 按 receiver 分组，保持模型常驻；不要为每个 edge/task/seed 重复加载模型；
- 缓存 receiver 基础隐藏状态、donor 隐藏状态、基线 logits 和样本哈希；
- 能沿 batch 维评估多个接口或 seed 时进行批量评估；
- 把 bootstrap、置换和表格生成放到模型计算后，用 CPU 并行；
- S2 先运行最少对照，S3/S4 再补齐完整对照；
- 每阶段记录模型加载次数、前向次数、训练单元、wall time、峰值内存和失败单元；
- 纯工程重试不得改变科学配置；科学定义变化必须新建协议版本。

## 6. 阶段卡模板

```text
候选 ID：
所属 L3 贡献：M / A / B / C
成果类型与贡献合同：
主创新路径：R1 / R2 / R3
主创新形式：F1 / F2 / F3 / F4
当前计算阶段：S0-SCREEN/S1/S2/S3/S4（state 枚举值仍为 S0）
本阶段唯一问题：
命题量词要求的最小模型/任务/方向范围：
输入工件与数据角色：
新增模型前向授权：
最大单元数：
最大 wall time：
主收益与最低效果：
逐旧功能容差：
最危险 matched-budget 基线：
升级门：
无效性停止门：
停止后允许保留的结论：
下一阶段是否需要新的 sealed 数据：
```
