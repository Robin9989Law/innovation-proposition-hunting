# 硬门（validator 为唯一执行合同）

本文件定义谓词映射实战证伪过、必须由校验器执行的门。`SKILL.md` 只索引
RULE-ID，不复制字段。未实现的句子不得当作已执行。

## 1. COMPLETE 必须有用户接受原句（R-ACCEPT-27 / R-EXIT-31）

```text
COMPLETE = N0-4C AND V3 AND current independent audit
           AND final_acceptance.note
```

IPH 在 `DIRECTION_LOCK` 立题交接后结束。进入 `COMPLETE` 只能：

```bash
iph advance --to COMPLETE \
  --accept-complete --acceptance-note "<用户明确接受本次立题交接的原句>"
```

`DIRECTION_LOCK` 的唯一正向目标是 `COMPLETE`。新项目 `iph advance --to COMPUTE`
必须拒绝。S1–S4 实验与论文写作不在 IPH 内。已进入 COMPUTE 的旧项目仍可从
`FINAL_LOCK` 进入 `COMPLETE`，但不得把实验完成或论文完稿当成立题交接。

下列用语不是接受：「推进到 N0-4C」「继续推进」「继续直到所有完成」
「完成全流程」「用户要求完成全流程」。计算授权不是立题交接接受。
授权 note 必须同时含动词（授权 / authorize）、计算对象（计算 / compute）、
确认对象（S4 / sealed / 封存 / 未见 / 确认），并引用本项目 `workflow_id`
或文献 `W-####` / 冻结 `claim_id`。接受 note 必须同时含动词（接受 / accept）、
锁定对象（锁定 / complete / 最终 / 立题 / 交接）、本次指示（本次 / this / 这次），并引用
本项目锚点。`exact_alignment=NARROWER` 时还须承认窄兑现
（窄 / narrower / 子句 / 不背书）。「我授权打开未见的 S4 计算」不够。

`workflow_state.final_acceptance` 由同一事务写入 `{note, at}`。缺对象、
空 note 或套话即 `COMPLETE_REQUIRES_USER_ACCEPTANCE`（常驻 INVALID）。

## 2. 复核硬 FAIL（R-REVIEW-28）

`iph review --verdict PASS` 在下列任一成立时必须拒绝，不得升 V3/V4，
也不得把它们写成 findings 里的 limitation 后盖章：

| 条件 | 码 |
|---|---|
| 已登记 sealed 运行且协议仍为 `NOT_YET_ACCESSED`（终态窗口） | `PROTOCOL_SEALED_ACCESS_CONTRADICTION` |
| sealed 行缺合格指纹（8–64 位标识符，词令边界）或指纹出现在计算前测试、实现、开发 runner、`compute/`/`checks/`/`implementation/` 下除 `sealed_runner` 外的 `.py` | `SEALED_UNIT_FINGERPRINT_MISSING` / `SEALED_UNIT_SEEN_IN_PRECOMPUTE` |
| 合格指纹未出现在 `sealed_runner` | `SEALED_UNIT_FINGERPRINT_NOT_IN_RUNNER` |
| sealed runner 的归一化 AST 或 ≥16 字符字面量出现在计算前 `.py` | `SEALED_UNIT_STRUCTURAL_CLONE` |
| sealed 行 `inventory_atoms` 为空 | `SEALED_INVENTORY_EMPTY` |
| `dev_runner` 与 `sealed_runner` 缺一或路径相同 | `SEALED_RUNNER_NOT_INDEPENDENT` |
| 有 sealed 运行且存在冻结 ALGORITHM 主张，却未声明 `s4_conjuncts` 也未在冻结句写 FAIL-* | `S4_CONJUNCTS_UNDECLARED` |
| 已声明 FAIL-* 合取，但并非每一条都被某条非空清单 sealed 行打中 | `SEALED_CONJUNCT_NOT_HIT` |
| sealed 行缺 `output_file`，或文件中没有声称的 decision | `SEALED_OUTPUT_MISSING` / `SEALED_OUTPUT_DECISION_MISMATCH` |
| `KILLED` 接线的 `kill_claim_ids` 不在观点注册表 | `WIRING_KILL_CLAIM_UNKNOWN` |
| review 产物 epoch 与当前 state 不一致 | CLI 拒绝登记 |
| NARROWER 冻结进入 COMPLETE 却不承认窄兑现 | `COMPLETE_NARROWER_UNACKNOWLEDGED` |

四问非空仍是必要的，不是充分的。`verdict=PASS` 时
`falsification_attempt` 必须引用**项目内真实文件**的 `path:line` 并摘引
该行原文，或 audit_manifest 里已有的 64 位哈希（`REVIEW_ANSWER_NO_LOCATOR`）。
只写行号、编造 `ghost.md:1` 或越界行号都不算。不得把上表写成 limitation 后盖章。

## 3. S4 确认资格（R-SEAL-26 / R-SEAL-29）

封存运行一旦出现在 `compute_evidence`：

- 每条 `split=sealed` 必须有 8–64 字符标识符指纹（`[A-Za-z_][A-Za-z0-9_-]*`），
  按词令边界匹配，不得当子串；该词令必须出现在 `sealed_runner`，且不得
  出现在计算前测试、实现、`dev_runner`，以及 `compute/`、`checks/`、
  `implementation/` 下除 `sealed_runner` 外的 `.py`。把封存单元改名后
  仍与计算前脚本同构，或把 ≥16 字符字面量留在计算前脚本，报
  `SEALED_UNIT_STRUCTURAL_CLONE`。
- `inventory_atoms` 必须是非空字符串列表。空清单上的
  `FAIL-SPURIOUS-ATOM` 不算确认。
- 顶层必须声明互异的 `dev_runner` 与 `sealed_runner`（规范相对路径，
  且文件存在）。S3 只许点名封存来源，不许把封存 AST 写进开发 runner。
- 只要出现 sealed 运行且存在冻结 ALGORITHM 主张，就必须声明
  `s4_conjuncts` 或在冻结句写出 FAIL-* 停止合取。缺声明即
  `S4_CONJUNCTS_UNDECLARED`。声明之后，至少一条 sealed 行的
  `decision`（或同值 `algorithm`）必须打中**每一条**已声明 FAIL-*，且清单
  非空。只打中其中一条、只 ACCEPT、或只在空清单上多余原子，都是
  `SEALED_CONJUNCT_NOT_HIT`。每条 sealed 行必须有 `output_file`，且文件
  正文含该 decision。

`PROTOCOL_SEALED_ACCESS_CONTRADICTION` 在
`FINAL_VALIDITY_AUDIT` / `FINAL_LOCK` / `COMPLETE` 为常驻 INVALID。
`COMPUTE` / `POSTCOMPUTE_CLAIM_FREEZE` 期间允许仍指向计算前协议，
以便 epoch+1 再切到 `SEALED_CONFIRMATION_ONLY`。

## 4. exact L3 与 inventory 对齐（R-ALIGN-30）

当 `artifacts.exact_statement` 存在且状态已进入 `CLAIM_FREEZE` 及之后：

- 默认：每条 `status=FROZEN` 的 claim `statement`（去反引号、折叠空白、
  casefold）必须作为子串出现在 exact 文件中。否则
  `EXACT_INVENTORY_MISMATCH`。
- 若 inventory 声明更窄兑现：

```json
"exact_alignment": {
  "status": "NARROWER",
  "does_not_underwrite_exact": true,
  "validity_source": "manuscript.e2.md"
}
```

则 statement 必须出现在 `validity_source`，且
`does_not_underwrite_exact` 必须为 true。V4/`COMPLETE` 不得把 exact
宽句当作已兑现。

## 5. 已证伪检查码常驻 INVALID

下列码移出「新检查默认 WARNING」集合，始终 INVALID：

`PROTOCOL_SEALED_ACCESS_CONTRADICTION`（终态窗口）、
`SEALED_UNIT_FINGERPRINT_MISSING`、`SEALED_UNIT_SEEN_IN_PRECOMPUTE`、
`WIRING_NOT_ATTEMPTED`、`WIRING_STILL_ALIVE`、`SEPARATION_NOT_WHOLE`、
`COMPOSITION_AUDIT_MISSING`、
`SEALED_INVENTORY_EMPTY`、`SEALED_RUNNER_NOT_INDEPENDENT`、
`SEALED_UNIT_FINGERPRINT_NOT_IN_RUNNER`、`SEALED_UNIT_STRUCTURAL_CLONE`、
`S4_CONJUNCTS_UNDECLARED`、`SEALED_CONJUNCT_NOT_HIT`、
`SEALED_OUTPUT_MISSING`、`SEALED_OUTPUT_DECISION_MISMATCH`、
`WIRING_KILL_CLAIM_UNKNOWN`、`COMPLETE_NARROWER_UNACKNOWLEDGED`、
`COMPLETE_REQUIRES_USER_ACCEPTANCE`、`EXACT_INVENTORY_MISMATCH`、
`REVIEW_ANSWER_NO_LOCATOR`、`FALSIFICATION_LEDGER_MISSING`、
`L3_CONTRACT_MISSING`、`WITNESS_NO_BITE`、`EXPLORATION_LEAK`、
`SELF_ATTESTING_TEST`、`HOLLOW_COVERAGE_AXIS`、
`UNREGISTERED_COMPUTE_ARTIFACT`、`G4_WALKTHROUGH_ONLY`、
`SYNTHETIC_DATA_NAMED_AS_REAL`、`ATOMIC_CLAIM_NO_ANCHOR`、
`WIRING_KIND_MISSING`、`WIRINGS_MISSING`、`COMPOSITION_AUDIT_INVALID`、
`COMPOSITION_REDUCES`、`OCCUPATION_EVIDENCE_MISSING`、
`REDUCTION_EVIDENCE_MISSING`、`COMPLETE_REQUIRES_DIRECTION_LOCK_CONDITIONS`。
