# 硬门（validator 为唯一执行合同）

本文件定义谓词映射实战证伪过、必须由校验器执行的门。`SKILL.md` 只索引
RULE-ID，不复制字段。未实现的句子不得当作已执行。

## 1. COMPLETE 必须有用户接受原句（R-ACCEPT-27）

```text
COMPLETE = N0-4C AND V4 AND current independent audit
           AND final_acceptance.note
```

进入 `COMPLETE` 只能：

```bash
iph advance --to COMPLETE \
  --accept-complete --acceptance-note "<用户明确接受本次最终锁定的原句>"
```

下列用语不是接受：「推进到 N0-4C」「继续推进」「继续直到所有完成」
「完成全流程」「用户要求完成全流程」。计算授权不是最终锁定接受。

`workflow_state.final_acceptance` 由同一事务写入 `{note, at}`。缺对象、
空 note 或套话即 `COMPLETE_REQUIRES_USER_ACCEPTANCE`（常驻 INVALID）。

## 2. 复核硬 FAIL（R-REVIEW-28）

`iph review --verdict PASS` 在下列任一成立时必须拒绝，不得升 V3/V4，
也不得把它们写成 findings 里的 limitation 后盖章：

| 条件 | 码 |
|---|---|
| 已登记 sealed 运行且协议仍为 `NOT_YET_ACCESSED`（终态窗口） | `PROTOCOL_SEALED_ACCESS_CONTRADICTION` |
| sealed 行缺 `unseen_fingerprint` 或指纹出现在计算前测试 / 开发 runner | `SEALED_UNIT_FINGERPRINT_MISSING` / `SEALED_UNIT_SEEN_IN_PRECOMPUTE` |
| sealed 行 `inventory_atoms` 为空 | `SEALED_INVENTORY_EMPTY` |
| `dev_runner` 与 `sealed_runner` 缺一或路径相同 | `SEALED_RUNNER_NOT_INDEPENDENT` |

四问非空仍是必要的，不是充分的。

## 3. S4 确认资格（R-SEAL-26 / R-SEAL-29）

封存运行一旦出现在 `compute_evidence`：

- 每条 `split=sealed` 必须有 ≥4 字符 `unseen_fingerprint`，且不得出现在
  `claim_code_trace` 可执行测试或 `dev_runner` 中。
- `inventory_atoms` 必须是非空字符串列表。空清单上的
  `FAIL-SPURIOUS-ATOM` 不算确认。
- 顶层必须声明互异的 `dev_runner` 与 `sealed_runner`（规范相对路径，
  且文件存在）。S3 只许点名封存来源，不许把封存 AST 写进开发 runner。

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
`COMPLETE_REQUIRES_USER_ACCEPTANCE`、`EXACT_INVENTORY_MISMATCH`。
