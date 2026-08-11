# incident-2026-08：算电协同项目事故回归 fixture

来源：`算电协同` 研究目录（DeepSeek V4 Flash agent 执行，2026-08-10），脱敏复制于 2026-08-11。
用途：事故模式 F1–F4 的负向回归。任何新检查必须在本 fixture 上触发对应错误码。

- `workflow_state.json`：decision_log 时间戳系统性晚于真实写入时间（F3）；EVIDENCE_VALIDATE 被跳过但 `evidence_validated=true`（F3）。
- `manuscript.frozen.md` vs `manuscript.md`：CLAIM_FREEZE（commit 6ead9f3）后稿件被实质修改（Algorithm 1/2 拆分），未递增 epoch——孤儿 occurrence `9b79f745…` 与新"有界"未注册。
- `collision-round1.md`、`novelty-audit.md`、`s0_delta2_report.md`：S0 未授权数值实验（F1）及其数字（E≈24h、r=−0.398、重叠 15%）泄漏进冻结工件（F2）。
- `checks/`：自证式/无咬合力见证负例（F4）：check_premise_removal 构造性恒真、check_scheduling_protocol 不导入实现直接 PASS。
- `frontier_coverage.json`：`author_continuations` 轴名实不符（引用链冒充作者续作）。

对应错误码（分期落地）：FUTURE_DECISION_TIMESTAMP、SELF_DECLARED_LEVEL、UNREGISTERED_COMPUTE_ARTIFACT、EXPLORATION_LEAK、WITNESS_NO_BITE、SELF_ATTESTING_TEST、HOLLOW_COVERAGE_AXIS。
