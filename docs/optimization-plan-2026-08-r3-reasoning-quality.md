# 技能优化计划 v4（2026-08-13，强推理环节质量）

> **状态：执行中。** 本计划针对两个强推理环节——原子观点提炼、文献碰撞——的
> 质量缺口。依据是 m3 全流程复盘 + 文献检索（METR 2025 reward hacking、
> Pan 2022 capability-reward 反比、Wen 2024 U-Sophistry、Wang 2023 MEC）。
> 沿用本技能既定设计哲学：查实质不查自报、证伪优先、负面对称化、
> 新检查默认 WARNING（--strict-new-checks 升 INVALID）、每步测试全绿并提交。

---

## 一、根因（已在前序复盘确认）

1. **偷懒是理性的**：强推理产出（观点/碰撞）的"真值"对 agent 不可见，而
   validator 只验证"字段非空"，不验证"字段有实质"。于是 agent 优化可验证的
   空壳（"Paper W-XXXX proposes a method..."），而不是不可验证的真推理。
2. **能力越强越偷懒**（Pan 2022）：强模型更擅长找到 reward 函数的漏洞，不是
   更诚实。validator 必须按"对手读过你的源码"来设计。
3. **作弊在生成、诚实在被追问**（METR）：模型生成时作弊，被追问时能诚实
   回答（o3 事后答"不符合意图"10/10）。所以必须强制"生成后判别"。
4. **U-Sophistry**（Wen 2024）：模型会为错误答案编造"可信的假证据"。数值
   锚点检查只能查"有无数字"，查不了"数字真假"——必须抽样审计兜底。

**核心结论：对强推理环节，"加模板"是死的，"加可证伪锚点 + 强制判别 + 抽样
审计"是活的。**

---

## 二、四个机制（贯穿设计哲学）

| # | 机制 | 治什么 | 落地形式 |
|---|---|---|---|
| 1 | 数值锚点 | 空壳空话 | validator：实质观点/碰撞结论必须含数字锚点（排除 work id）或 locator |
| 2 | 强制判别（证伪） | 确认偏误、偷懒 | 碰撞产物改三段式：证据→推理→结论，逐近邻证伪记录 |
| 3 | 需求拉动 | 供给推动的套壳 | 抽观点前先冻结候选存活条件，定向抽 |
| 4 | 抽样审计 | U-Sophistry 假证据 | 交接报告强制抽查 checklist |

设计哲学约束：validator 只查"实质锚点存在性"（可机械验证），不试图证明
"锚点真假"（validator 做不到，硬做只会逼 agent 绕过）。锚点真假靠抽样审计
兜底。所有新检查默认 WARNING，strict 升 INVALID。

---

## 三、执行单元（按风险升序）

### P1 原子观点空壳检测（validator + 文档，低风险）

- **P1.1** `validate_evidence_chain.py` 加 `ATOMIC_CLAIM_NO_ANCHOR`：
  实质类观点（CONTRADICTS/OCCUPIES/BOUNDS 等碰撞相关，或 E2+）的
  `normalized_statement` 必须含数字锚点（排除 `W-XXXX`/年份等 work id 模式）
  或 locator。空壳句"proposes a method to detect"不含数字 → 报。
- **P1.2** `templates.md` §5 加五要素模板（条件/方法/基线/指标/数值），
  写不出五要素即读后感不登记。
- **P1.3** 测试。

### P2 碰撞三段式 + 强制证伪（validator + templates，低风险）

- **P2.1** `output_claim_support.json` 的碰撞类结论（claim_kind 含
  NOVELTY_VERDICT/CLOSURE/METHOD_COMPARISON）强制三段式：`evidence`→
  `reasoning`→`statement`，三段都非空且 evidence 含数值锚点或 locator。
- **P2.2** `validate_evidence_chain.py` 加顺序约束：结论字段必须引用一个已
  存在的 evidence 字段；`ATOMIC_COLLISION_NO_ANCHOR` 检查 evidence 空壳。
- **P2.3** `SKILL.md` SYNTHESIZE_COLLISION 段加强制证伪：逐近邻三条证伪
  尝试（直接占据/机械推出/换名）+ 非空理由。
- **P2.4** 测试。

### P3 需求拉动 + 抽样审计（纯文档 + 流程，低风险）

- **P3.1** `SKILL.md` K_CLAIM_REGISTER 段改需求拉动：先冻结候选存活条件，
  再定向抽观点。
- **P3.2** 交接报告（`iph handover`）加抽查 checklist：记录"抽查 N% 锚点
  回原文核对"的结果。

### P4 待拍板（schema 变更，高风险，单独评估）

- **P4** `claim_type` 从文体类型（METHOD/CONCLUSION/LIMITATION/...）改成
  判断类型（OCCUPIES/ENABLES/CONTRADICTS/BOUNDS/NEUTRAL）。需迁移脚本，
  不在本计划默认执行范围，待用户拍板。

---

## 四、验收

- 每步 `python3 -m pytest tests/ -q` 全绿。
- 新增检查默认 WARNING，`--strict-new-checks` 升 INVALID。
- m3 的 45 条空壳观点在 strict 下必报 `ATOMIC_CLAIM_NO_ANCHOR`。
- 每步提交（R-SKILL-14），commit message 写明动机、策略、残余风险。

## 五、明确不做

- 不试图让 validator 证明"锚点真假"（读全文判断数值真实与否，超出
  validator 能力边界，靠抽样审计）。
- 不做 claim_type schema 变更（P4）除非用户拍板。
- 不引入外部真值服务/强模型评审（环境无此能力，靠流程留痕 + 人工抽查）。
