#!/usr/bin/env python3
"""iph — innovation-proposition-hunting 工作流 CLI。

状态推进的标准入口：先校验，再由工具记账（真实 UTC 时间戳 + 本状态产物
SHA-256 登记 + validation.log），最后原子写回 workflow_state.json。
agent 不得再手工编辑 gates / decision_log / validation.log —— 手改会触发
validate_workflow_state 的 STALE_DECISION_ARTIFACT / 时间完整性检查。
schema 3.0 起 active_track / active_layer / last_completed_state 不再持久化，
由校验器与工具按状态派生（docs/design-schema-3.0.md §4）。

子命令：
  validate                运行完整校验套件（当前转发 validate_all.py）
  advance                 校验通过后推进状态并记账
  start-collision-round   从 N0-3 审计合规开启下一碰撞轮次
  revise-exact-statement  只改 L3 精确句：同轮、保留 L1/L2/K，跳回综合
  retract-novelty         从 N0_AUDIT/N0-4C 合法撤回为 N0-3/N0-1/N0-2
  review                  subagent 登记 review 产物；PASS 时原子升 V3/V4
  reopen-validity-epoch   FAIL 复核或用户否决 COMPLETE/V4 后新开 epoch，退回 CLAIM_FREEZE
  advance-compute-stage   COMPUTE 内只向前升级 S0→S1→S2→S3→S4
  clear-lock              完成恢复动作后解除 STOP 锁
  repair-artifact-pointer 保留旧证据并原子切换到版本化修正版
  register-exploration    把探索性数据/产物登记为永久探索级证据
  authorize-instance-probe  N0-3 下授权小范围实例探针（≤5 条）
  register-instance-probe   登记一条已授权实例探针结果
  handover                按 SKILL.md §10 生成交接报告
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from validation_common import (  # noqa: E402
    ExitCode,
    ProjectContext,
    canonical_relative_path,
    file_sha256,
    has_review_locator,
    note_lacks_acceptance_grant,
    note_lacks_compute_grant,
    nonempty_string,
)
from validate_workflow_state import (  # noqa: E402
    GATE_COMPLETION_STATE,
    GATE_KEYS,
    STATES,
    TRACK_STATES,
    collect_sealed_hard_fail_details,
    composition_n0_4_lock_errors,
    evidence_tier,
)

GATE_BOOL = {"true": True, "false": False}
ARTIFACT_KEY = re.compile(r"^[a-z][a-z0-9_]*$")
# 进入这些状态时必须置真的机械完成门。不含 n0_4_locked：
# N0-3 也进入 N0_AUDIT，不得顺手锁 4C。
TARGET_COMPLETION_GATES = {
    "OUTPUT_CLAIM_BIND": "output_claims_traced",
    "EVIDENCE_VALIDATE": "evidence_validated",
}
# STOP 恢复只允许补这些漏写的机械门；不得改 n0_4_locked / compute_authorized。
RECOVERABLE_COMPLETION_GATES = set(TARGET_COMPLETION_GATES.values())

POSITIVE_STATE_SEQUENCE = (
    "BOOT",
    "SCOPE_LOCK",
    "PRIOR_CLAIM_DRAIN",
    "RECENT_FRONTIER",
    "LITERATURE_REGISTER",
    "L1_FREEZE",
    "L2_TRIAGE",
    "LAYER_DECISION",
    "K_FULLTEXT",
    "K_CLAIM_REGISTER",
    "SYNTHESIZE_COLLISION",
    "OUTPUT_CLAIM_BIND",
    "EVIDENCE_VALIDATE",
    "N0_AUDIT",
    "CLAIM_FREEZE",
    "VALIDITY_AUDIT",
    "INDEPENDENT_REVIEW",
    "DIRECTION_LOCK",
    "COMPUTE",
    "POSTCOMPUTE_CLAIM_FREEZE",
    "FINAL_VALIDITY_AUDIT",
    "FINAL_LOCK",
    "COMPLETE",
)
NEXT_POSITIVE_STATE = dict(zip(POSITIVE_STATE_SEQUENCE, POSITIVE_STATE_SEQUENCE[1:]))
VALID_NOVELTY_LEVELS = {"N0-1", "N0-2", "N0-3", "N0-4C"}
VALID_COMPUTE_STAGES = {"NOT_STARTED", "S0", "S1", "S2", "S3", "S4", "STOPPED"}
LAYER_GATES = (
    "l1_frozen",
    "k_set_selected",
    "l2_frozen",
    "architecture_frozen",
)
LAYER_PREREQUISITE_GATES = (
    "recent_frontier_complete",
    "literature_registry_valid",
)
L3_ROUND_GATES = (
    "k_fulltext_complete",
    "k_claims_complete",
    "output_claims_traced",
    "evidence_validated",
    "n0_4_locked",
)
STATEMENT_REVISION_GATES = (
    "output_claims_traced",
    "evidence_validated",
    "n0_4_locked",
)
FULL_COLLISION_RESET_GATES = (
    LAYER_GATES + LAYER_PREREQUISITE_GATES + L3_ROUND_GATES
)

# 状态 -> 所属轴（TRACK_STATES 是分区；BLOCKED/COMPLETE 不属于任何轴）。
# 仅用于 handover 报表派生展示，不再写回 state（schema 3.0 派生字段）。
STATE_TO_TRACK = {
    state: track for track, states in TRACK_STATES.items() for state in states
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def run_validate_all(
    root: Path, state: Path, strict: bool, extra: list[str]
) -> int:
    command = [
        sys.executable,
        str(SCRIPT_DIR / "validate_all.py"),
        "--root",
        str(root),
        "--state",
        str(state),
    ]
    if strict:
        command.append("--strict-new-checks")
    command.extend(extra)
    return subprocess.run(command, check=False).returncode


def atomic_write_state(state_path: Path, state: dict[str, Any]) -> None:
    tmp_path = state_path.with_name(state_path.name + ".tmp")
    tmp_path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(tmp_path, state_path)


def append_validation_log(root: Path, line: str) -> None:
    with (root / "validation.log").open("a", encoding="utf-8") as handle:
        handle.write(f"{utc_now()} {line}\n")


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


def cmd_validate(args: argparse.Namespace) -> int:
    return run_validate_all(
        Path(args.root).resolve(),
        Path(args.state).resolve(),
        args.strict_new_checks,
        args.extra or [],
    )


# ---------------------------------------------------------------------------
# advance
# ---------------------------------------------------------------------------


def parse_gate_updates(pairs: list[str]) -> dict[str, bool]:
    updates: dict[str, bool] = {}
    for pair in pairs:
        if "=" not in pair:
            raise SystemExit(f"--set-gate 需要 key=true|false 形式：{pair!r}")
        key, _, raw = pair.partition("=")
        if key not in GATE_KEYS:
            raise SystemExit(f"未知 gate：{key!r}（合法值：{sorted(GATE_KEYS)}）")
        value = GATE_BOOL.get(raw.strip().lower())
        if value is None:
            raise SystemExit(f"gate 值必须是 true/false：{pair!r}")
        updates[key] = value
    return updates


def validate_transition_target(state: dict[str, Any], target: str) -> None:
    current = state.get("active_state")
    if target == "BLOCKED":
        if current in {"BLOCKED", "COMPLETE"}:
            raise SystemExit(f"{current} 不允许再次进入 BLOCKED")
        return
    if current == "BLOCKED":
        raise SystemExit("BLOCKED 只能通过 clear-lock --resume-blocked 恢复")
    expected = NEXT_POSITIVE_STATE.get(current)
    if expected != target:
        raise SystemExit(
            f"禁止跳态：active_state={current!r} 的唯一正向目标是 {expected!r}，"
            f"收到 {target!r}"
        )
    if current == "N0_AUDIT" and state.get("novelty_level") != "N0-4C":
        raise SystemExit(
            f"N0_AUDIT/{state.get('novelty_level')} 是终局，不能推进到 {target}"
        )


def load_transition_json(root: Path, relative: str, label: str) -> tuple[Path, dict[str, Any]]:
    if not canonical_relative_path(relative):
        raise SystemExit(f"{label} 必须是根内规范相对路径：{relative!r}")
    path = root / relative
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise SystemExit(f"{label} 不可读取：{error}") from error
    if not isinstance(payload, dict):
        raise SystemExit(f"{label} 顶层必须是 JSON 对象")
    return path, payload


def apply_transition_semantics(
    state: dict[str, Any],
    target: str,
    args: argparse.Namespace,
    root: Path,
    gate_updates: dict[str, bool],
) -> None:
    """把裁决、有效性、计算和 epoch 变化绑定到唯一合法状态事务。"""

    novelty = args.novelty_level
    if target == "N0_AUDIT":
        if novelty not in VALID_NOVELTY_LEVELS:
            raise SystemExit("进入 N0_AUDIT 必须用 --novelty-level 写入本轮裁决")
        positive = novelty == "N0-4C"
        if gate_updates.get("n0_4_locked") is not positive:
            expected = str(positive).lower()
            raise SystemExit(
                "N0 裁决与 gate 必须同一事务互证："
                f"--novelty-level {novelty} 需要 --set-gate n0_4_locked={expected}"
            )
        state["novelty_level"] = novelty
    elif novelty is not None:
        raise SystemExit("--novelty-level 只允许用于进入 N0_AUDIT")

    if target == "VALIDITY_AUDIT":
        state["validity_level"] = "V1"
    elif target == "INDEPENDENT_REVIEW":
        state["validity_level"] = "V2"

    if target == "COMPUTE":
        if not args.authorize_compute or not nonempty_string(args.authorization_note):
            raise SystemExit(
                "进入 COMPUTE 必须有显式用户授权："
                "--authorize-compute --authorization-note <授权依据>"
            )
        if note_lacks_compute_grant(args.authorization_note):
            raise SystemExit(
                "计算授权依据不足：authorization-note 必须引用用户明确授权"
                "计算的原句，并含「计算」或 compute；「推进到 N0-4C」"
                "「继续直到所有完成」「完成全流程」不是计算授权"
            )
        gate_updates["compute_authorized"] = True
        state["compute_stage"] = "S0"
    elif args.authorize_compute or args.authorization_note is not None:
        raise SystemExit("计算授权参数只允许用于 DIRECTION_LOCK -> COMPUTE")

    if target == "COMPLETE":
        if not getattr(args, "accept_complete", False) or not nonempty_string(
            getattr(args, "acceptance_note", None)
        ):
            raise SystemExit(
                "进入 COMPLETE 必须有用户接受原句："
                "--accept-complete --acceptance-note <用户原句>"
            )
        if note_lacks_acceptance_grant(args.acceptance_note):
            raise SystemExit(
                "最终锁定接受依据不足：acceptance-note 必须引用用户明确"
                "接受本次 COMPLETE 的原句，并含「接受」「锁定」或 complete；"
                "计算授权或「完成全流程」不够"
            )
        state["final_acceptance"] = {
            "note": args.acceptance_note.strip(),
            "at": utc_now(),
        }
    elif getattr(args, "accept_complete", False) or getattr(
        args, "acceptance_note", None
    ) is not None:
        raise SystemExit("最终锁定接受参数只允许用于 FINAL_LOCK -> COMPLETE")

    if target == "POSTCOMPUTE_CLAIM_FREEZE":
        if not args.compute_evidence:
            raise SystemExit(
                "进入 POSTCOMPUTE_CLAIM_FREEZE 必须用 --compute-evidence 登记 S4 证据"
            )
        evidence_path, evidence = load_transition_json(
            root, args.compute_evidence, "--compute-evidence"
        )
        if evidence.get("compute_stage") != "S4":
            raise SystemExit("--compute-evidence 必须声明 compute_stage=S4")
        state["compute_stage"] = "S4"
        state["compute_evidence"] = {
            "status": "COMPLETED",
            "validation_epoch": state.get("validation_epoch"),
            "artifact_path": args.compute_evidence,
            "artifact_sha256": file_sha256(evidence_path),
        }
    elif args.compute_evidence is not None:
        raise SystemExit("--compute-evidence 只允许用于进入 POSTCOMPUTE_CLAIM_FREEZE")

    if target in {"VALIDITY_AUDIT", "FINAL_VALIDITY_AUDIT"}:
        if not args.claim_bundle_manifest:
            raise SystemExit(
                f"进入 {target} 必须用 --claim-bundle-manifest 登记精确 claim bundle"
            )
        _, manifest = load_transition_json(
            root, args.claim_bundle_manifest, "--claim-bundle-manifest"
        )
        next_epoch = manifest.get("validation_epoch")
        bundle = manifest.get("claim_bundle_sha256")
        expected_epoch = (
            state.get("validation_epoch", 0) + 1
            if target == "FINAL_VALIDITY_AUDIT"
            else state.get("validation_epoch")
        )
        if next_epoch != expected_epoch:
            raise SystemExit(
                f"{target} 的 manifest.validation_epoch 必须为 {expected_epoch}"
            )
        if not isinstance(bundle, str) or re.fullmatch(r"[0-9a-f]{64}", bundle) is None:
            raise SystemExit("计算后 manifest.claim_bundle_sha256 非法")
        state["validation_epoch"] = next_epoch
        state["claim_bundle_sha256"] = bundle
        if target == "FINAL_VALIDITY_AUDIT":
            state["independent_audit"] = {}
            state.pop("review_artifact_sha256", None)
        state.setdefault("artifacts", {})["audit_manifest"] = args.claim_bundle_manifest
    elif args.claim_bundle_manifest is not None:
        raise SystemExit(
            "--claim-bundle-manifest 只允许用于进入 VALIDITY_AUDIT 或 FINAL_VALIDITY_AUDIT"
        )


def parse_state_artifact_updates(
    pairs: list[str], root: Path
) -> dict[str, str]:
    """解析受控的 state.artifacts 路径登记，不承担 decision_log 哈希记账。"""
    updates: dict[str, str] = {}
    for pair in pairs:
        if "=" not in pair:
            raise SystemExit(
                f"--set-artifact 需要 key=根内规范相对路径 形式：{pair!r}"
            )
        key, _, relative = pair.partition("=")
        key = key.strip()
        relative = relative.strip()
        if not ARTIFACT_KEY.fullmatch(key):
            raise SystemExit(f"artifact key 非法：{key!r}")
        if not canonical_relative_path(relative):
            raise SystemExit(
                f"--set-artifact 必须使用根内规范相对路径：{relative!r}"
            )
        candidate = root / relative
        if not candidate.exists() or candidate.is_symlink():
            raise SystemExit(f"--set-artifact 不存在或不是安全实体：{relative}")
        previous = updates.get(key)
        if previous is not None and previous != relative:
            raise SystemExit(
                f"同一 artifact key 不得登记多个路径：{key}={previous!r}/{relative!r}"
            )
        updates[key] = relative
    return updates


def apply_state_repairs(
    state: dict[str, Any],
    artifact_updates: dict[str, str],
    next_action: str | None,
) -> None:
    artifacts = state.setdefault("artifacts", {})
    if not isinstance(artifacts, dict):
        raise SystemExit("workflow_state.artifacts 必须是对象")
    artifacts.update(artifact_updates)
    if next_action is not None:
        if not nonempty_string(next_action):
            raise SystemExit("--next-action 不得为空")
        state["next_required_action"] = next_action.strip()


def sync_recent_window_from_registry(
    state: dict[str, Any], root: Path, gate_updates: dict[str, bool]
) -> None:
    """完成最近前沿门时，从已登记文献账本同步权威时间窗。"""

    if gate_updates.get("recent_frontier_complete") is not True:
        return

    artifacts = state.get("artifacts")
    if not isinstance(artifacts, dict):
        raise SystemExit("workflow_state.artifacts 必须是对象")
    relative = artifacts.get("literature_registry")
    if not isinstance(relative, str) or not canonical_relative_path(relative):
        raise SystemExit(
            "recent_frontier_complete=true 必须同时登记合法的 "
            "artifacts.literature_registry"
        )
    registry_path = root / relative
    if not registry_path.is_file() or registry_path.is_symlink():
        raise SystemExit(f"literature_registry 不存在或不是安全实体：{relative}")

    registry = _load_json_object(registry_path, "literature_registry")
    window = registry.get("recent_window")
    if not isinstance(window, dict):
        raise SystemExit("literature_registry.recent_window 必须是对象")
    current_year = state.get("current_year")
    expected = {
        "start_year": current_year - 2 if isinstance(current_year, int) else None,
        "end_year": current_year,
        "status": "COMPLETE",
    }
    for key, value in expected.items():
        if window.get(key) != value:
            raise SystemExit(
                "literature_registry.recent_window 与当前状态不一致："
                f"{key}={window.get(key)!r}; expected={value!r}"
            )
    snapshot_mode = window.get("snapshot_mode")
    if snapshot_mode not in {"NEW_SEARCH", "REUSED_VERIFIED_SNAPSHOT"}:
        raise SystemExit(
            "literature_registry.recent_window.snapshot_mode 必须是 "
            "NEW_SEARCH 或 REUSED_VERIFIED_SNAPSHOT"
        )
    state["recent_window"] = {
        "start_year": window["start_year"],
        "end_year": window["end_year"],
        "status": window["status"],
        "snapshot_mode": snapshot_mode,
    }


def cmd_advance(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    state_path = Path(args.state).resolve()
    target = args.to
    if target not in STATES:
        raise SystemExit(f"未知目标状态：{target!r}")
    if not nonempty_string(args.note):
        raise SystemExit("advance 需要 --note 记录本状态完成动作")

    # 1. 推进前必须通过校验（锁机制由 validate_all 执行）
    if not args.no_validate:
        exit_code = run_validate_all(
            root, state_path, args.strict_new_checks, []
        )
        if exit_code != int(ExitCode.READY):
            print(f"advance aborted: validation exit={exit_code}")
            return exit_code

    gate_updates = parse_gate_updates(args.set_gate or [])
    auto_gate = TARGET_COMPLETION_GATES.get(target)
    if auto_gate:
        if gate_updates.get(auto_gate) is False:
            raise SystemExit(
                f"进入 {target} 必须置真 {auto_gate}，不得 --set-gate {auto_gate}=false"
            )
        gate_updates.setdefault(auto_gate, True)
    state_artifact_updates = parse_state_artifact_updates(
        args.set_artifact or [], root
    )
    artifact_paths: list[str] = []
    for raw in args.artifact or []:
        if not canonical_relative_path(raw):
            raise SystemExit(f"--artifact 必须是根内规范相对路径：{raw!r}")
        artifact_paths.append(raw)

    now = utc_now()
    state = json.loads(state_path.read_text(encoding="utf-8"))
    previous_state = state.get("active_state")
    validate_transition_target(state, target)
    apply_transition_semantics(state, target, args, root, gate_updates)

    # schema 3.0 起证据层级由 active_state 派生：LAYER_DECISION -> K_FULLTEXT
    # 的严格推进必须在同一次原子写入中切换贡献——前校验要求 L2 为 NONE，
    # 后校验要求 L3 为 M（期刊）或 A/B/C（博士）。返回 L1/L2 时对称清回 NONE。
    requested_contribution = args.contribution
    if target not in {"BLOCKED", "COMPLETE"}:
        target_tier = evidence_tier(target)
        if target_tier in {"L1", "L2"}:
            if requested_contribution not in {None, "NONE"}:
                raise SystemExit(
                    f"{target} 属于 {target_tier}，active_contribution 必须为 NONE"
                )
            state["active_contribution"] = "NONE"
        else:
            output_type = state.get("output_type")
            allowed = (
                {"M"}
                if output_type == "JOURNAL_ARTICLE"
                else {"A", "B", "C"}
                if output_type == "DOCTORAL_DISSERTATION"
                else set()
            )
            contribution = requested_contribution or state.get("active_contribution")
            # 期刊未显式指定时默认 M；显式指定的非法选择必须拒绝，不得静默改写。
            if (
                requested_contribution is None
                and contribution not in allowed
                and output_type == "JOURNAL_ARTICLE"
            ):
                contribution = "M"
            if contribution not in allowed:
                raise SystemExit(
                    "进入 L3 必须用 --contribution 选择合法贡献；"
                    f"output_type={output_type}, allowed={sorted(allowed)}"
                )
            state["active_contribution"] = contribution

    # 2. 状态迁移
    if target == "BLOCKED":
        reasons = [r for r in (args.blocked_reason or []) if r.strip()]
        if not reasons:
            raise SystemExit("进入 BLOCKED 必须给至少一个 --blocked-reason")
        state["resume_state"] = previous_state
        state["blocked_reasons"] = reasons
    else:
        state["resume_state"] = target
        state["blocked_reasons"] = []
    state["active_state"] = target
    state["updated_at"] = now
    apply_state_repairs(state, state_artifact_updates, args.next_action)
    gates = state.setdefault("gates", {})
    for key, value in gate_updates.items():
        gates[key] = value
    sync_recent_window_from_registry(state, root, gate_updates)
    if target == "N0_AUDIT" and args.novelty_level == "N0-4C":
        refuse_n0_4c_open_wirings(root, state)

    # 3. decision_log 记账：真实时间戳 + 本状态产物哈希
    artifacts: list[dict[str, str]] = []
    for relative in artifact_paths:
        candidate = root / relative
        if not candidate.is_file():
            raise SystemExit(f"--artifact 不存在：{relative}")
        artifacts.append({"path": relative, "sha256": file_sha256(candidate)})
    entry = {"at": now, "state": target, "action": args.note.strip()}
    if artifacts:
        entry["artifacts"] = artifacts
    state.setdefault("decision_log", []).append(entry)

    atomic_write_state(state_path, state)
    append_validation_log(
        root,
        f"ADVANCE {previous_state} -> {target} "
        f"gates={gate_updates or '-'} artifacts={len(artifacts)} "
        f"state_artifacts={state_artifact_updates or '-'} note={args.note.strip()}",
    )
    print(f"advanced: {previous_state} -> {target}")

    # 4. 推进后复核：新状态下的全套校验
    if not args.no_validate:
        exit_code = run_validate_all(
            root, state_path, args.strict_new_checks, []
        )
        if exit_code != int(ExitCode.READY):
            print(f"post-advance validation exit={exit_code}")
            return exit_code
    return int(ExitCode.READY)


# ---------------------------------------------------------------------------
# start-collision-round
# ---------------------------------------------------------------------------


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise SystemExit(f"{label} 不可读取：{error}") from error
    if not isinstance(payload, dict):
        raise SystemExit(f"{label} 顶层必须是对象")
    return payload


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    tmp_path = path.with_name(path.name + ".tmp")
    tmp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(tmp_path, path)


def _academic_urls(value: Any) -> set[str]:
    """收集记录内的学术 URL，供跨轮快照保留全部可追溯入口。"""

    urls: set[str] = set()
    if isinstance(value, dict):
        for child in value.values():
            urls.update(_academic_urls(child))
    elif isinstance(value, list):
        for child in value:
            urls.update(_academic_urls(child))
    elif isinstance(value, str):
        host = urlsplit(value).netloc.lower()
        if any(
            marker in host
            for marker in (
                "arxiv.org", "doi.org", "ieeexplore.ieee.org", "sciencedirect.com",
                "springer.com", "link.springer.com", "dl.acm.org", "nature.com",
            )
        ):
            urls.add(value)
    return urls


def _preserve_registry_aliases(payload: dict[str, Any]) -> None:
    records = payload.get("records")
    if not isinstance(records, list):
        return
    for record in records:
        if not isinstance(record, dict):
            continue
        aliases = record.get("alternate_urls")
        existing = {item for item in aliases if isinstance(item, str)} if isinstance(aliases, list) else set()
        canonical = record.get("canonical_url") or record.get("url")
        if isinstance(canonical, str):
            existing.discard(canonical)
        existing.update(_academic_urls(record))
        if isinstance(canonical, str):
            existing.discard(canonical)
        record["alternate_urls"] = sorted(existing)


def cmd_start_collision_round(args: argparse.Namespace) -> int:
    """从 N0-3 HOLD 原子开启下一轮 P0，并保留跨轮全局账本。"""

    root = Path(args.root).resolve()
    state_path = Path(args.state).resolve()
    if not nonempty_string(args.note):
        raise SystemExit("start-collision-round 需要 --note 记录重开原因")
    if not args.no_validate:
        exit_code = run_validate_all(root, state_path, args.strict_new_checks, [])
        if exit_code != int(ExitCode.READY):
            print(f"start-collision-round aborted: validation exit={exit_code}")
            return exit_code

    state = _load_json_object(state_path, "workflow_state.json")
    if state.get("active_state") != "N0_AUDIT":
        raise SystemExit("只能从 N0_AUDIT 开启新碰撞轮次")
    if state.get("novelty_level") != "N0-3":
        raise SystemExit("只能从 N0-3 HOLD 开启新碰撞轮次")
    if state.get("validity_level") != "V0":
        raise SystemExit("新碰撞只能在有效性冻结前（V0）开启")

    artifacts = state.get("artifacts")
    if not isinstance(artifacts, dict):
        raise SystemExit("workflow_state.artifacts 必须是对象")
    required = {
        "literature_registry": "near_neighbor_registry.json",
        "claim_registry": "literature_claim_registry.json",
        "output_support": "output_claim_support.json",
        "current_evidence_scope": "current_evidence_scope.json",
        "frontier_coverage": "frontier_coverage.json",
    }
    paths: dict[str, Path] = {}
    for key, fallback in required.items():
        raw = artifacts.get(key, fallback)
        if not isinstance(raw, str) or not canonical_relative_path(raw):
            raise SystemExit(f"artifacts.{key} 必须是根内规范相对路径")
        candidate = root / raw
        if not candidate.is_file():
            raise SystemExit(f"缺少新碰撞所需工件：{raw}")
        paths[key] = candidate

    old_round = state.get("collision_round")
    if not isinstance(old_round, int) or old_round < 1:
        raise SystemExit("workflow_state.collision_round 必须是正整数")
    new_round = old_round + 1
    literature = _load_json_object(paths["literature_registry"], "literature registry")
    claims = _load_json_object(paths["claim_registry"], "claim registry")
    outputs = _load_json_object(paths["output_support"], "output support")
    for label, payload in (
        ("literature registry", literature),
        ("claim registry", claims),
        ("output support", outputs),
    ):
        if payload.get("current_collision_round") != old_round:
            raise SystemExit(
                f"{label} 当前轮次与 state 不一致："
                f"{payload.get('current_collision_round')} != {old_round}"
            )

    _preserve_registry_aliases(literature)

    records = claims.get("records")
    if not isinstance(records, list):
        raise SystemExit("claim registry.records 必须是列表")
    unfinished = [
        str(record.get("claim_id", "(missing)"))
        for record in records
        if isinstance(record, dict)
        and isinstance(record.get("discovered_round"), int)
        and record["discovered_round"] < new_round
        and record.get("use_status") == "UNUSED"
    ]
    if unfinished:
        raise SystemExit(
            "旧观点尚未耗尽，不能开启新碰撞：" + ",".join(sorted(unfinished))
        )

    now = utc_now()
    # 已完成状态的 decision_log 可能锚定本轮账本；不得覆写旧文件而令历史
    # 哈希失效。新轮使用完整的追加式账本快照，state 从此指向新快照。
    round_directory_relative = f"rounds/round-{new_round}"
    round_directory = root / round_directory_relative
    round_directory.mkdir(parents=True, exist_ok=False)
    round_artifacts = {
        "literature_registry": f"{round_directory_relative}/near_neighbor_registry.json",
        "claim_registry": f"{round_directory_relative}/literature_claim_registry.json",
        "output_support": f"{round_directory_relative}/output_claim_support.json",
        "current_evidence_scope": f"{round_directory_relative}/current_evidence_scope.json",
        "frontier_coverage": f"{round_directory_relative}/frontier_coverage.json",
    }
    literature["current_collision_round"] = new_round
    claims["current_collision_round"] = new_round
    outputs["current_collision_round"] = new_round
    outputs["collision_gate"] = {
        "prior_round_claims_drained": True,
        "unused_prior_claim_ids": [],
        "checked_at": now[:10],
    }
    new_scope = {
        "schema_version": "2.0",
        "collision_round": new_round,
        "fulltext_registry_ids": [],
        "atomic_claim_ids": [],
    }
    new_paths = {key: root / relative for key, relative in round_artifacts.items()}
    _atomic_write_json(new_paths["literature_registry"], literature)
    _atomic_write_json(new_paths["claim_registry"], claims)
    _atomic_write_json(new_paths["output_support"], outputs)
    _atomic_write_json(new_paths["current_evidence_scope"], new_scope)
    # 前沿覆盖表与注册表一样会随新轮搜索增长；保留旧轮字节锚定，避免其
    # 决策日志哈希被后续 P1 追加破坏。
    _atomic_write_json(new_paths["frontier_coverage"], _load_json_object(paths["frontier_coverage"], "frontier coverage"))

    keep_layers = bool(getattr(args, "keep_layers", False))
    state["collision_round"] = new_round
    state["active_state"] = "PRIOR_CLAIM_DRAIN"
    state["resume_state"] = "PRIOR_CLAIM_DRAIN"
    state["updated_at"] = now
    state_artifacts = state.setdefault("artifacts", {})
    state_artifacts.update(round_artifacts)
    if keep_layers:
        state["next_required_action"] = (
            "Keep frozen L1/L2/architecture; drain unused prior-round claims, "
            f"then refresh K fulltext for collision round {new_round} "
            "without re-freezing the program cards."
        )
    else:
        state["next_required_action"] = (
            "Perform P1 recent-frontier search for collision round "
            f"{new_round}; register every material hit before fulltext triage."
        )
    gates = state.setdefault("gates", {})
    reset_keys = L3_ROUND_GATES if keep_layers else FULL_COLLISION_RESET_GATES
    for key in reset_keys:
        gates[key] = False
    gates["prior_claims_drained"] = True
    # PRIOR_CLAIM_DRAIN 属 L1 段，active_contribution 必须是 NONE。
    # --keep-layers 只保留 L1/L2 门，不保留 L3 贡献编号。
    state["active_contribution"] = "NONE"
    keep_note = "keep-layers; " if keep_layers else ""
    entry = {
        "at": now,
        "state": "PRIOR_CLAIM_DRAIN",
        "action": (
            f"Opened collision round {new_round} from N0-3 HOLD; {keep_note}"
            f"all prior-round claims were drained before P1. {args.note.strip()}"
        ),
    }
    state.setdefault("decision_log", []).append(entry)
    atomic_write_state(state_path, state)
    append_validation_log(
        root,
        f"START_COLLISION_ROUND {old_round} -> {new_round} "
        f"keep_layers={str(keep_layers).lower()} "
        f"scope={round_artifacts['current_evidence_scope']} note={args.note.strip()}",
    )
    print(f"started collision round {old_round} -> {new_round}")
    if not args.no_validate:
        exit_code = run_validate_all(root, state_path, args.strict_new_checks, [])
        if exit_code != int(ExitCode.READY):
            print(f"post-start validation exit={exit_code}")
            return exit_code
    return int(ExitCode.READY)


def cmd_retract_novelty(args: argparse.Namespace) -> int:
    """把已写入的 N0-4C 撤回为合法 HOLD 或负终局，而不手改 state。

    用户或独立复核证伪 N0-4C 时，CLI 此前没有写入口：不能 advance 回
    N0_AUDIT，也不能从 N0-4C 开新碰撞。本命令只允许
    N0_AUDIT + N0-4C + V0，并在同一事务中把 novelty_level / n0_4_locked
    与新的 novelty-audit 指针对齐。
    """

    root = Path(args.root).resolve()
    state_path = Path(args.state).resolve()
    target = args.to
    if target not in {"N0-1", "N0-2", "N0-3"}:
        raise SystemExit("retract-novelty 只能撤回为 N0-1、N0-2 或 N0-3")
    if not nonempty_string(args.note):
        raise SystemExit("retract-novelty 需要 --note 记录撤回理由")
    if not args.no_validate:
        exit_code = run_validate_all(
            root, state_path, args.strict_new_checks, []
        )
        if exit_code != int(ExitCode.READY):
            print(f"retract-novelty aborted: validation exit={exit_code}")
            return exit_code

    state = _load_json_object(state_path, "workflow_state.json")
    if state.get("active_state") != "N0_AUDIT":
        raise SystemExit("只能从 N0_AUDIT 撤回 N0 裁决")
    if state.get("novelty_level") != "N0-4C":
        raise SystemExit("只能撤回 N0-4C；当前不是可撤回的锁定裁决")
    if state.get("validity_level") != "V0":
        raise SystemExit("有效性已冻结后不得撤回 N0；应新开 epoch 而不是降级新颖性")
    if state.get("gates", {}).get("compute_authorized") is True:
        raise SystemExit("计算已授权后不得撤回 N0-4C")

    artifact_paths: list[str] = []
    for raw in args.artifact or []:
        if not canonical_relative_path(raw):
            raise SystemExit(f"--artifact 必须是根内规范相对路径：{raw!r}")
        if not (root / raw).is_file():
            raise SystemExit(f"--artifact 不存在：{raw}")
        artifact_paths.append(raw)
    if not artifact_paths:
        raise SystemExit("retract-novelty 必须用 --artifact 登记新的 novelty-audit")

    state_artifact_updates = parse_state_artifact_updates(
        args.set_artifact or [], root
    )
    now = utc_now()
    state["novelty_level"] = target
    state["updated_at"] = now
    gates = state.setdefault("gates", {})
    gates["n0_4_locked"] = False
    apply_state_repairs(state, state_artifact_updates, args.next_action)
    artifacts: list[dict[str, str]] = []
    for relative in artifact_paths:
        artifacts.append(
            {"path": relative, "sha256": file_sha256(root / relative)}
        )
    entry = {
        "at": now,
        "state": "N0_AUDIT",
        "action": (
            f"RETRACT_NOVELTY N0-4C -> {target}. {args.note.strip()}"
        ),
        "artifacts": artifacts,
    }
    state.setdefault("decision_log", []).append(entry)
    atomic_write_state(state_path, state)
    append_validation_log(
        root,
        f"RETRACT_NOVELTY N0-4C -> {target} "
        f"artifacts={len(artifacts)} "
        f"state_artifacts={state_artifact_updates or '-'} "
        f"note={args.note.strip()}",
    )
    print(f"retracted novelty: N0-4C -> {target}")
    if not args.no_validate:
        exit_code = run_validate_all(
            root, state_path, args.strict_new_checks, []
        )
        if exit_code != int(ExitCode.READY):
            print(f"post-retract validation exit={exit_code}")
            return exit_code
    return int(ExitCode.READY)


def cmd_revise_exact_statement(args: argparse.Namespace) -> int:
    """只改 L3 精确句：同轮、保留 L1/L2/K，跳回 SYNTHESIZE_COLLISION。

    改目标链、基线或 O/I/A/T/C/R/B 对齐项仍须 start-collision-round。
    已写入的 N0-4C 必须先 retract-novelty 到 N0-3。
    """

    root = Path(args.root).resolve()
    state_path = Path(args.state).resolve()
    if not nonempty_string(args.note):
        raise SystemExit("revise-exact-statement 需要 --note 记录改句理由")
    if not canonical_relative_path(args.path):
        raise SystemExit(f"--path 必须是根内规范相对路径：{args.path!r}")
    statement_path = root / args.path
    if not statement_path.is_file() or statement_path.is_symlink():
        raise SystemExit(f"--path 不存在或不是安全实体：{args.path}")
    if not args.no_validate:
        exit_code = run_validate_all(
            root, state_path, args.strict_new_checks, []
        )
        if exit_code != int(ExitCode.READY):
            print(f"revise-exact-statement aborted: validation exit={exit_code}")
            return exit_code

    state = _load_json_object(state_path, "workflow_state.json")
    if state.get("active_state") != "N0_AUDIT":
        raise SystemExit("只能从 N0_AUDIT 修订 L3 精确句")
    if state.get("novelty_level") != "N0-3":
        if state.get("novelty_level") == "N0-4C":
            raise SystemExit("已锁定的 N0-4C 须先 retract-novelty 到 N0-3，再修订精确句")
        raise SystemExit("只能在 N0-3 HOLD 修订 L3 精确句")
    if state.get("validity_level") != "V0":
        raise SystemExit("有效性已冻结后不得修订 L3 精确句；应新开 epoch")
    if state.get("gates", {}).get("compute_authorized") is True:
        raise SystemExit("计算已授权后不得修订 L3 精确句")

    collision_round = state.get("collision_round")
    if not isinstance(collision_round, int) or collision_round < 1:
        raise SystemExit("workflow_state.collision_round 必须是正整数")

    state_artifact_updates = parse_state_artifact_updates(
        args.set_artifact or [], root
    )
    state_artifact_updates["exact_statement"] = args.path
    now = utc_now()
    state["active_state"] = "SYNTHESIZE_COLLISION"
    state["resume_state"] = "SYNTHESIZE_COLLISION"
    state["updated_at"] = now
    gates = state.setdefault("gates", {})
    for key in STATEMENT_REVISION_GATES:
        gates[key] = False
    apply_state_repairs(state, state_artifact_updates, args.next_action)
    if not nonempty_string(state.get("next_required_action")) or args.next_action is None:
        state["next_required_action"] = (
            "Re-synthesize collision against the revised exact statement "
            f"in collision round {collision_round}; do not reopen L1/L2/K."
        )
    entry = {
        "at": now,
        "state": "SYNTHESIZE_COLLISION",
        "action": (
            f"REVISE_EXACT_STATEMENT round={collision_round} "
            f"path={args.path}. {args.note.strip()}"
        ),
        "artifacts": [
            {"path": args.path, "sha256": file_sha256(statement_path)}
        ],
    }
    state.setdefault("decision_log", []).append(entry)
    atomic_write_state(state_path, state)
    append_validation_log(
        root,
        f"REVISE_EXACT_STATEMENT round={collision_round} path={args.path} "
        f"note={args.note.strip()}",
    )
    print(
        f"revised exact statement in collision round {collision_round}; "
        "returned to SYNTHESIZE_COLLISION"
    )
    if not args.no_validate:
        exit_code = run_validate_all(
            root, state_path, args.strict_new_checks, []
        )
        if exit_code != int(ExitCode.READY):
            print(f"post-revise validation exit={exit_code}")
            return exit_code
    return int(ExitCode.READY)


# ---------------------------------------------------------------------------
# repair-collision-round / clear-lock / register-exploration / handover
# ---------------------------------------------------------------------------


def cmd_repair_collision_round(args: argparse.Namespace) -> int:
    """仅修复 start-collision-round 后、STOP 锁内的未完成轮次快照。"""

    root = Path(args.root).resolve()
    state_path = Path(args.state).resolve()
    lock_path = root / ".workflow_stop.lock"
    if not lock_path.is_file():
        raise SystemExit("repair-collision-round 只能在 STOP 锁存在时使用")
    state = _load_json_object(state_path, "workflow_state.json")
    if state.get("active_state") != "PRIOR_CLAIM_DRAIN":
        raise SystemExit("只能修复 PRIOR_CLAIM_DRAIN 中断的新碰撞")
    artifacts = state.get("artifacts")
    if not isinstance(artifacts, dict):
        raise SystemExit("workflow_state.artifacts 必须是对象")
    raw_registry = artifacts.get("literature_registry")
    if not isinstance(raw_registry, str) or not canonical_relative_path(raw_registry):
        raise SystemExit("literature_registry 路径无效")
    registry_path = root / raw_registry
    registry = _load_json_object(registry_path, "literature registry")
    _preserve_registry_aliases(registry)
    _atomic_write_json(registry_path, registry)

    raw_coverage = artifacts.get("frontier_coverage", "frontier_coverage.json")
    if not isinstance(raw_coverage, str) or not canonical_relative_path(raw_coverage):
        raise SystemExit("frontier_coverage 路径无效")
    round_coverage = f"rounds/round-{state.get('collision_round')}/frontier_coverage.json"
    if raw_coverage == "frontier_coverage.json":
        source_coverage = root / raw_coverage
        target_coverage = root / round_coverage
        if not source_coverage.is_file():
            raise SystemExit("缺少 frontier_coverage.json，无法修复当前轮次快照")
        if not target_coverage.exists():
            _atomic_write_json(target_coverage, _load_json_object(source_coverage, "frontier coverage"))
        artifacts["frontier_coverage"] = round_coverage

    gates = state.setdefault("gates", {})
    # 只重置本轮 L3 门。L1/L2/架构若已由 --keep-layers 或既有冻结保留，不得打回。
    for key in L3_ROUND_GATES:
        gates[key] = False
    gates["prior_claims_drained"] = True
    state["active_contribution"] = "NONE"
    state["updated_at"] = utc_now()
    atomic_write_state(state_path, state)
    append_validation_log(
        root,
        "REPAIR_COLLISION_ROUND repaired current snapshot URL aliases and reset "
        "new-round L3 gates before STOP-lock recovery",
    )
    print("repaired collision-round snapshot; run clear-lock to validate recovery")
    return int(ExitCode.READY)


def cmd_review(args: argparse.Namespace) -> int:
    """subagent 运行：登记 review 产物 hash 到 state，主 agent 此后只读不写。"""
    root = Path(args.root).resolve()
    state_path = Path(args.state).resolve()
    if not nonempty_string(args.reviewer):
        raise SystemExit("review 需要 --reviewer 记录 reviewer_agent_id")
    if not nonempty_string(args.thread):
        raise SystemExit("review 需要 --thread 记录 reviewer_thread_id")

    state = json.loads(state_path.read_text(encoding="utf-8"))
    artifacts = state.setdefault("artifacts", {})
    if not isinstance(artifacts, dict):
        raise SystemExit("workflow_state.artifacts 必须是对象")
    review_artifact = getattr(args, "review_artifact", None)
    if review_artifact:
        if not canonical_relative_path(review_artifact):
            raise SystemExit(f"--review-artifact 必须是根内规范相对路径：{review_artifact!r}")
        if not (root / review_artifact).is_file():
            raise SystemExit(f"--review-artifact 不存在：{review_artifact}")
        artifacts["independent_audit"] = review_artifact
    audit_relative = (
        artifacts.get("independent_audit")
        if artifacts.get("independent_audit")
        else "independent_audit.json"
    )
    if not canonical_relative_path(audit_relative):
        raise SystemExit(f"review 产物路径非法：{audit_relative!r}")
    audit_path = root / audit_relative
    if not audit_path.is_file():
        raise SystemExit(f"review 产物不存在：{audit_relative}")

    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    if not isinstance(audit, dict):
        raise SystemExit("review 产物必须是 JSON 对象")
    if audit.get("verdict") != args.verdict:
        raise SystemExit(
            f"--verdict {args.verdict} 与 review 产物 verdict {audit.get('verdict')} 不一致"
        )
    if args.verdict == "PASS":
        review_answers = audit.get("review_answers")
        required_keys = (
            "data_authenticity",
            "baseline_execution",
            "claim_strength",
            "falsification_attempt",
        )
        if not isinstance(review_answers, dict) or any(
            not nonempty_string(review_answers.get(key)) for key in required_keys
        ):
            raise SystemExit(
                "PASS 的 review 产物必须含非空 review_answers 四问"
                "（data_authenticity/baseline_execution/claim_strength/falsification_attempt）"
            )
        if not has_review_locator(str(review_answers.get("falsification_attempt") or "")):
            raise SystemExit(
                "PASS 的 falsification_attempt 必须引用 path:line 或 64 位哈希；"
                "不得把硬 FAIL 写成 limitation 后盖章"
            )
        hard_fails = collect_sealed_hard_fail_details(root, state)
        if hard_fails:
            first = hard_fails[0]
            raise SystemExit(
                "PASS 被硬 FAIL 表拒绝："
                f"{first[0]} ({first[1]})；不得降为 limitation"
            )

    digest = file_sha256(audit_path)
    state["review_artifact_sha256"] = digest
    now = utc_now()
    state["updated_at"] = now
    if args.verdict == "PASS":
        mirrored = dict(audit)
        mirrored["reviewer_agent_id"] = args.reviewer.strip()
        mirrored["reviewer_thread_id"] = args.thread.strip()
        state["independent_audit"] = mirrored
        active = state.get("active_state")
        if active == "INDEPENDENT_REVIEW":
            state["validity_level"] = "V3"
        elif active == "FINAL_VALIDITY_AUDIT":
            state["validity_level"] = "V4"
        if active == "INDEPENDENT_REVIEW":
            state["next_required_action"] = (
                "DIRECTION_LOCK is allowed; do not COMPUTE until authorized."
            )
        elif active == "FINAL_VALIDITY_AUDIT":
            state["next_required_action"] = (
                "FINAL_LOCK is allowed after V4 provenance."
            )
    atomic_write_state(state_path, state)
    append_validation_log(
        root,
        f"REVIEW {args.reviewer} thread={args.thread} verdict={args.verdict} "
        f"artifact={audit_relative} sha256={digest[:12]}",
    )
    print(
        f"review 产物已登记：{audit_relative} sha256={digest[:12]} "
        f"reviewer={args.reviewer} verdict={args.verdict} —— 主 agent 此后只读不写"
    )
    return int(ExitCode.READY)


COMPUTE_STAGE_ORDER = ("S0", "S1", "S2", "S3", "S4")


USER_REJECT_COMPLETE_STATES = frozenset({"FINAL_LOCK", "COMPLETE"})


def cmd_reopen_validity_epoch(args: argparse.Namespace) -> int:
    """FAIL 复核或用户否决 COMPLETE/V4 后新开 validity epoch，不改 N0，不打开计算。"""

    root = Path(args.root).resolve()
    state_path = Path(args.state).resolve()
    if not nonempty_string(args.note):
        raise SystemExit("reopen-validity-epoch 需要 --note")
    user_reject = bool(getattr(args, "user_reject_complete", False))
    if not args.no_validate and not user_reject:
        exit_code = run_validate_all(
            root, state_path, args.strict_new_checks, []
        )
        if exit_code != int(ExitCode.READY):
            print(f"reopen-validity-epoch aborted: validation exit={exit_code}")
            return exit_code

    state = _load_json_object(state_path, "workflow_state.json")
    active = state.get("active_state")
    if user_reject:
        if active not in USER_REJECT_COMPLETE_STATES:
            raise SystemExit(
                "--user-reject-complete 只能从 FINAL_LOCK 或 COMPLETE 重开"
            )
        if state.get("validity_level") not in {"V3", "V4"}:
            raise SystemExit("用户否决 COMPLETE 需要已冻结的 V3/V4")
        if state.get("novelty_level") != "N0-4C":
            raise SystemExit("用户否决 COMPLETE 不清 N0-4C；当前不是 N0-4C")
        resume = "CLAIM_FREEZE"
        origin = "USER_REJECT_COMPLETE"
    else:
        if active not in {"INDEPENDENT_REVIEW", "FINAL_VALIDITY_AUDIT"}:
            raise SystemExit(
                "只能从 INDEPENDENT_REVIEW 或 FINAL_VALIDITY_AUDIT 重开 epoch；"
                "否决 COMPLETE/V4 请加 --user-reject-complete"
            )
        if (
            state.get("gates", {}).get("compute_authorized") is True
            and active == "INDEPENDENT_REVIEW"
        ):
            raise SystemExit("计算已授权后不得从独立复核重开 epoch")
        if state.get("validity_level") not in {"V2", "V3", "V4"}:
            raise SystemExit("validity 尚未冻结，无需 reopen-validity-epoch")

        artifacts = state.get("artifacts")
        audit_relative = (
            artifacts.get("independent_audit")
            if isinstance(artifacts, dict) and artifacts.get("independent_audit")
            else "independent_audit.json"
        )
        audit_path = root / audit_relative
        if not audit_path.is_file():
            raise SystemExit("缺少独立复核产物，不能重开 epoch")
        audit = _load_json_object(audit_path, "independent_audit")
        if audit.get("verdict") != "FAIL":
            raise SystemExit("只有 verdict=FAIL 的复核才能重开 validity epoch")
        expected_hash = state.get("review_artifact_sha256")
        if expected_hash != file_sha256(audit_path):
            raise SystemExit("review 产物哈希与登记不一致，不能重开")
        resume = (
            "CLAIM_FREEZE" if active == "INDEPENDENT_REVIEW" else "POSTCOMPUTE_CLAIM_FREEZE"
        )
        origin = "FAIL"

    old_epoch = state.get("validation_epoch")
    if not isinstance(old_epoch, int) or old_epoch < 1:
        raise SystemExit("validation_epoch 必须是正整数")
    new_epoch = old_epoch + 1
    now = utc_now()
    artifact_updates = parse_state_artifact_updates(
        getattr(args, "set_artifact", None) or [], root
    )
    state["active_state"] = resume
    state["resume_state"] = resume
    state["validation_epoch"] = new_epoch
    state["validity_level"] = "V0"
    state["claim_bundle_sha256"] = ""
    state["independent_audit"] = {}
    state.pop("review_artifact_sha256", None)
    if user_reject:
        gates = state.setdefault("gates", {})
        if not isinstance(gates, dict):
            raise SystemExit("workflow_state.gates 必须是对象")
        gates["compute_authorized"] = False
        state["compute_stage"] = "NOT_STARTED"
        state.pop("compute_evidence", None)
        state.pop("final_acceptance", None)
    state["updated_at"] = now
    apply_state_repairs(state, artifact_updates, args.next_action)
    if not nonempty_string(state.get("next_required_action")) or args.next_action is None:
        reason = (
            "user rejected COMPLETE/V4"
            if user_reject
            else "FAIL review"
        )
        state["next_required_action"] = (
            f"Rebuild epoch {new_epoch} inventory and form artifacts after {reason}."
        )
    state.setdefault("decision_log", []).append(
        {
            "at": now,
            "state": resume,
            "action": (
                f"REOPEN_VALIDITY_EPOCH {old_epoch}->{new_epoch} "
                f"from {active} {origin}. {args.note.strip()}"
            ),
        }
    )
    atomic_write_state(state_path, state)
    append_validation_log(
        root,
        f"REOPEN_VALIDITY_EPOCH {old_epoch}->{new_epoch} from={active} "
        f"origin={origin} note={args.note.strip()}",
    )
    print(f"reopened validity epoch {old_epoch} -> {new_epoch}; state={resume}")
    if not args.no_validate:
        exit_code = run_validate_all(
            root, state_path, args.strict_new_checks, []
        )
        if exit_code != int(ExitCode.READY):
            print(f"post-reopen validation exit={exit_code}")
            return exit_code
    return int(ExitCode.READY)


def cmd_advance_compute_stage(args: argparse.Namespace) -> int:
    """COMPUTE 内只允许 S0→S1→S2→S3→S4 前进。"""

    root = Path(args.root).resolve()
    state_path = Path(args.state).resolve()
    target = args.to
    if target not in COMPUTE_STAGE_ORDER:
        raise SystemExit(f"--to 必须是 {COMPUTE_STAGE_ORDER}")
    if not nonempty_string(args.note):
        raise SystemExit("advance-compute-stage 需要 --note")
    if not args.no_validate:
        exit_code = run_validate_all(
            root, state_path, args.strict_new_checks, []
        )
        if exit_code != int(ExitCode.READY):
            print(f"advance-compute-stage aborted: validation exit={exit_code}")
            return exit_code

    state = _load_json_object(state_path, "workflow_state.json")
    if state.get("active_state") != "COMPUTE":
        raise SystemExit("只能在 COMPUTE 升级 compute_stage")
    if state.get("gates", {}).get("compute_authorized") is not True:
        raise SystemExit("未授权计算不得升级 compute_stage")
    current = state.get("compute_stage")
    if current not in COMPUTE_STAGE_ORDER:
        raise SystemExit(f"当前 compute_stage 非法：{current!r}")
    expected = COMPUTE_STAGE_ORDER[COMPUTE_STAGE_ORDER.index(current) + 1] if current != "S4" else None
    if target != expected:
        raise SystemExit(
            f"compute_stage 只能前进一步：当前 {current}，下一合法目标 {expected}"
        )
    artifact_paths: list[str] = []
    for raw in args.artifact or []:
        if not canonical_relative_path(raw):
            raise SystemExit(f"--artifact 必须是根内规范相对路径：{raw!r}")
        if not (root / raw).is_file():
            raise SystemExit(f"--artifact 不存在：{raw}")
        artifact_paths.append(raw)
    now = utc_now()
    state["compute_stage"] = target
    state["updated_at"] = now
    apply_state_repairs(state, {}, args.next_action)
    entry = {
        "at": now,
        "state": "COMPUTE",
        "action": f"ADVANCE_COMPUTE_STAGE {current}->{target}. {args.note.strip()}",
    }
    if artifact_paths:
        entry["artifacts"] = [
            {"path": relative, "sha256": file_sha256(root / relative)}
            for relative in artifact_paths
        ]
    state.setdefault("decision_log", []).append(entry)
    atomic_write_state(state_path, state)
    append_validation_log(
        root,
        f"ADVANCE_COMPUTE_STAGE {current}->{target} note={args.note.strip()}",
    )
    print(f"advanced compute stage {current} -> {target}")
    if not args.no_validate:
        exit_code = run_validate_all(
            root, state_path, args.strict_new_checks, []
        )
        if exit_code != int(ExitCode.READY):
            print(f"post-stage validation exit={exit_code}")
            return exit_code
    return int(ExitCode.READY)



def cmd_clear_lock(args: argparse.Namespace) -> int:
    if not nonempty_string(args.recovery_note):
        raise SystemExit("clear-lock 需要 --recovery-note 记录唯一恢复动作")
    root = Path(args.root).resolve()
    state_path = Path(args.state).resolve()
    lock_path = root / ".workflow_stop.lock"
    validation_log_path = root / "validation.log"
    original_state = state_path.read_bytes()
    original_lock = lock_path.read_bytes() if lock_path.is_file() else None
    original_log = (
        validation_log_path.read_bytes() if validation_log_path.is_file() else None
    )
    artifact_updates = parse_state_artifact_updates(args.set_artifact or [], root)
    gate_updates = parse_gate_updates(getattr(args, "set_gate", None) or [])
    if args.resume_blocked and args.next_action is None:
        raise SystemExit("--resume-blocked 必须同时提供 --next-action")
    if gate_updates:
        illegal = sorted(set(gate_updates) - RECOVERABLE_COMPLETION_GATES)
        if illegal:
            raise SystemExit(
                "clear-lock --set-gate 只能补漏写的机械完成门 "
                f"{sorted(RECOVERABLE_COMPLETION_GATES)}，收到 {illegal}"
            )
        if any(value is not True for value in gate_updates.values()):
            raise SystemExit("clear-lock --set-gate 只能把机械完成门置真，不得置假")
    if artifact_updates or args.next_action is not None or args.resume_blocked or gate_updates:
        if not lock_path.is_file():
            raise SystemExit("只有 STOP 锁存在时才能通过 clear-lock 修复状态指针")
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            raise SystemExit("workflow_state.json 顶层必须是对象")
        if args.resume_blocked:
            if state.get("active_state") != "BLOCKED":
                raise SystemExit("--resume-blocked 仅允许恢复 active_state=BLOCKED")
            resume_state = state.get("resume_state")
            if resume_state not in STATES - {"BLOCKED", "COMPLETE"}:
                raise SystemExit(f"BLOCKED.resume_state 非法：{resume_state!r}")
            reasons = state.get("blocked_reasons")
            if not isinstance(reasons, list) or not any(
                isinstance(reason, str) and reason.strip() for reason in reasons
            ):
                raise SystemExit("BLOCKED 恢复前必须保留非空 blocked_reasons")
            state["active_state"] = resume_state
            state["resume_state"] = resume_state
            state["blocked_reasons"] = []
            state.setdefault("decision_log", []).append(
                {
                    "at": utc_now(),
                    "state": resume_state,
                    "action": (
                        "RECOVERY_RESUME from BLOCKED after operator repair: "
                        f"{args.recovery_note.strip()}"
                    ),
                }
            )
        if gate_updates:
            logged_states = {
                str(entry.get("state") or "").split("@", 1)[-1]
                for entry in state.get("decision_log", [])
                if isinstance(entry, dict)
            }
            gates = state.setdefault("gates", {})
            if not isinstance(gates, dict):
                raise SystemExit("workflow_state.gates 必须是对象")
            for key, value in gate_updates.items():
                required_state = GATE_COMPLETION_STATE.get(key)
                if required_state not in logged_states:
                    raise SystemExit(
                        f"不得补置 {key}：decision_log 没有 {required_state} 完成记录"
                    )
                gates[key] = value
        apply_state_repairs(state, artifact_updates, args.next_action)
        state["updated_at"] = utc_now()
        atomic_write_state(state_path, state)
        append_validation_log(
            root,
            f"RECOVERY_STATE_REPAIR artifacts={artifact_updates or '-'} "
            f"gates={gate_updates or '-'} "
            f"resume_blocked={args.resume_blocked} "
            f"next_action_updated={args.next_action is not None} "
            f"note={args.recovery_note.strip()}",
        )
    exit_code = run_validate_all(
        root,
        state_path,
        args.strict_new_checks,
        ["--clear-lock", "--recovery-note", args.recovery_note.strip()],
    )
    if exit_code == int(ExitCode.READY):
        return exit_code

    state_path.write_bytes(original_state)
    if original_lock is None:
        lock_path.unlink(missing_ok=True)
    else:
        lock_path.write_bytes(original_lock)
    if original_log is None:
        validation_log_path.unlink(missing_ok=True)
    else:
        validation_log_path.write_bytes(original_log)
    print("RECOVERY_ROLLBACK\trestored state, STOP lock, and validation log")
    return exit_code


def cmd_repair_artifact_pointer(args: argparse.Namespace) -> int:
    """Atomically repoint active evidence while preserving historical artifacts."""

    if not nonempty_string(args.recovery_note):
        raise SystemExit("repair-artifact-pointer 需要 --recovery-note")
    root = Path(args.root).resolve()
    state_path = Path(args.state).resolve()
    lock_path = root / ".workflow_stop.lock"
    validation_log_path = root / "validation.log"
    original_state = state_path.read_bytes()
    original_lock = lock_path.read_bytes() if lock_path.is_file() else None
    original_log = (
        validation_log_path.read_bytes() if validation_log_path.is_file() else None
    )
    updates = parse_state_artifact_updates(args.set_artifact or [], root)
    if not updates:
        raise SystemExit("repair-artifact-pointer 至少需要一个 --set-artifact")

    state = _load_json_object(state_path, "workflow_state")
    artifacts = state.setdefault("artifacts", {})
    if not isinstance(artifacts, dict):
        raise SystemExit("workflow_state.artifacts 必须是对象")
    corrections: list[str] = []
    defaults = {
        "url_ledger": "near_neighbor_url_ledger.csv",
    }
    for key, replacement in updates.items():
        previous = artifacts.get(key, defaults.get(key))
        if not isinstance(previous, str) or not canonical_relative_path(previous):
            raise SystemExit(f"artifacts.{key} 没有可保留的旧规范路径")
        if previous == replacement:
            raise SystemExit(f"artifacts.{key} 新旧路径相同：{replacement}")
        old_path = root / previous
        new_path = root / replacement
        if not old_path.is_file() or old_path.is_symlink():
            raise SystemExit(f"旧证据不存在或不安全，无法保留：{previous}")
        if not new_path.is_file() or new_path.is_symlink():
            raise SystemExit(f"修正版证据不存在或不安全：{replacement}")
        corrections.append(
            f"{key}:{previous}@{file_sha256(old_path)}"
            f"->{replacement}@{file_sha256(new_path)}"
        )

    apply_state_repairs(state, updates, args.next_action)
    now = utc_now()
    state["updated_at"] = now
    active_state = state.get("active_state")
    state.setdefault("decision_log", []).append(
        {
            "at": now,
            "state": active_state,
            "action": (
                "EVIDENCE_POINTER_REPAIR preserving historical bytes: "
                f"{'; '.join(corrections)}; note={args.recovery_note.strip()}"
            ),
        }
    )
    atomic_write_state(state_path, state)
    append_validation_log(
        root,
        "EVIDENCE_POINTER_REPAIR "
        f"corrections={'; '.join(corrections)} note={args.recovery_note.strip()}",
    )
    exit_code = run_validate_all(
        root,
        state_path,
        args.strict_new_checks,
        ["--clear-lock", "--recovery-note", args.recovery_note.strip()],
    )
    if exit_code == int(ExitCode.READY):
        print(f"artifact pointers repaired: {', '.join(sorted(updates))}")
        return exit_code

    state_path.write_bytes(original_state)
    if original_lock is None:
        lock_path.unlink(missing_ok=True)
    else:
        lock_path.write_bytes(original_lock)
    if original_log is None:
        validation_log_path.unlink(missing_ok=True)
    else:
        validation_log_path.write_bytes(original_log)
    print("POINTER_REPAIR_ROLLBACK\trestored state, STOP lock, and validation log")
    return exit_code


def cmd_register_exploration(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    relative = args.path
    if not canonical_relative_path(relative):
        raise SystemExit(f"--path 必须是根内规范相对路径：{relative!r}")
    candidate = root / relative
    if not candidate.is_file():
        raise SystemExit(f"探索产物不存在：{relative}")
    if not nonempty_string(args.desc):
        raise SystemExit("register-exploration 需要 --desc 说明探索内容")

    registry_path = root / "exploration_registry.json"
    if registry_path.is_file():
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        registry.setdefault("schema_version", "2.0")
    else:
        registry = {"schema_version": "2.0", "explorations": []}
    explorations = registry.setdefault("explorations", [])
    digest = file_sha256(candidate)
    for existing in explorations:
        if existing.get("path") == relative:
            existing.update(
                {
                    "sha256": digest,
                    "registered_at": utc_now(),
                    "data_role": "EXPLORATION_PERMANENT",
                    "description": args.desc.strip(),
                }
            )
            entry_id = existing.get("id")
            break
    else:
        entry_id = f"exp-{len(explorations) + 1:03d}"
        explorations.append(
            {
                "id": entry_id,
                "path": relative,
                "sha256": digest,
                "registered_at": utc_now(),
                "data_role": "EXPLORATION_PERMANENT",
                "description": args.desc.strip(),
            }
        )
    registry_path.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    append_validation_log(
        root, f"REGISTER_EXPLORATION {entry_id} path={relative} sha256={digest[:12]}"
    )
    print(
        f"registered {entry_id}: {relative} —— 该数据永久为探索级，"
        "其数值不得进入任何碰撞、审计或冻结工件"
    )
    return int(ExitCode.READY)


INSTANCE_PROBE_REGISTRY = "instance_probe_registry.json"
MAX_INSTANCE_PROBES = 5
INSTANCE_PROBE_PURPOSES = {"COUNTEREXAMPLE", "SUPPORT"}
INSTANCE_PROBE_VERDICTS = {"SUCCESS", "FAIL", "UNDEFINED"}
G4_ROLES = {
    "OLD_STOP_STILL_SCORES",
    "NEW_STOP_FAIL",
    "DESIGN_WALKTHROUGH",
    "NOT_A_THRESHOLD",
    "RECONSTRUCTION",
}


def refuse_n0_4c_open_wirings(root: Path, state: dict[str, Any]) -> None:
    """N0-4C 写入前拒绝未打过必做接线的组合表。"""

    if state.get("claim_profile") not in {"ALGORITHM", "MIXED"}:
        return
    artifacts = state.get("artifacts")
    raw = (
        artifacts.get("composition_audit")
        if isinstance(artifacts, dict)
        else None
    )
    relative = raw if isinstance(raw, str) and raw.strip() else "composition_audit.json"
    if not canonical_relative_path(relative):
        raise SystemExit("不得锁定 N0-4C：composition_audit 路径无效")
    path = root / relative
    if not path.is_file():
        raise SystemExit("不得锁定 N0-4C：缺少 composition_audit.json")
    payload = _load_json_object(path, "composition_audit")
    problems = composition_n0_4_lock_errors(payload)
    if problems:
        first = "; ".join(f"{code} {detail}" for code, detail in problems[:4])
        raise SystemExit(f"不得锁定 N0-4C：{first}")


def _instance_probe_registry_path(root: Path, state: dict[str, Any]) -> Path:
    artifacts = state.get("artifacts")
    raw = artifacts.get("instance_probe_registry") if isinstance(artifacts, dict) else None
    relative = raw if isinstance(raw, str) and canonical_relative_path(raw) else INSTANCE_PROBE_REGISTRY
    return root / relative


def cmd_authorize_instance_probe(args: argparse.Namespace) -> int:
    """N0-3 HOLD 下授权查看少量反例/支撑实例；不打开 COMPUTE。"""

    root = Path(args.root).resolve()
    state_path = Path(args.state).resolve()
    if not nonempty_string(args.note):
        raise SystemExit("authorize-instance-probe 需要 --note 记录用户授权依据")
    state = _load_json_object(state_path, "workflow_state.json")
    if state.get("active_state") != "N0_AUDIT":
        raise SystemExit("实例探针只能在 N0_AUDIT 授权")
    if state.get("novelty_level") != "N0-3":
        raise SystemExit("实例探针只能在 N0-3 HOLD 授权；N0-4C 应走正式 COMPUTE")
    if state.get("validity_level") != "V0":
        raise SystemExit("有效性冻结后不得改用实例探针绕过计算漏斗")
    if state.get("gates", {}).get("compute_authorized") is True:
        raise SystemExit("计算已授权时应走 S0–S4，而不是实例探针")

    registry_path = _instance_probe_registry_path(root, state)
    if registry_path.is_file():
        registry = _load_json_object(registry_path, "instance_probe_registry")
    else:
        registry = {"schema_version": "2.0", "probes": []}
    registry["schema_version"] = "2.0"
    registry["authorization_note"] = args.note.strip()
    registry["authorized_at"] = utc_now()
    registry.setdefault("probes", [])
    _atomic_write_json(registry_path, registry)
    artifacts = state.setdefault("artifacts", {})
    if not isinstance(artifacts, dict):
        raise SystemExit("workflow_state.artifacts 必须是对象")
    artifacts["instance_probe_registry"] = registry_path.relative_to(root).as_posix()
    state["updated_at"] = utc_now()
    atomic_write_state(state_path, state)
    append_validation_log(
        root,
        f"AUTHORIZE_INSTANCE_PROBE note={args.note.strip()}",
    )
    print(
        "authorized instance probes: max "
        f"{MAX_INSTANCE_PROBES}; not COMPUTE; do not use dataset means as success"
    )
    return int(ExitCode.READY)


def cmd_register_instance_probe(args: argparse.Namespace) -> int:
    """登记一条实例探针。必须先 authorize-instance-probe。"""

    root = Path(args.root).resolve()
    state_path = Path(args.state).resolve()
    state = _load_json_object(state_path, "workflow_state.json")
    registry_path = _instance_probe_registry_path(root, state)
    if not registry_path.is_file():
        raise SystemExit("尚未 authorize-instance-probe")
    registry = _load_json_object(registry_path, "instance_probe_registry")
    if not nonempty_string(registry.get("authorization_note")):
        raise SystemExit("实例探针登记簿缺少 authorization_note")
    if args.purpose not in INSTANCE_PROBE_PURPOSES:
        raise SystemExit(f"--purpose 必须是 {sorted(INSTANCE_PROBE_PURPOSES)}")
    if args.old_verdict not in INSTANCE_PROBE_VERDICTS:
        raise SystemExit(f"--old-verdict 必须是 {sorted(INSTANCE_PROBE_VERDICTS)}")
    if args.old_verdict == "SUCCESS" and not nonempty_string(args.success_rule):
        raise SystemExit("old-verdict=SUCCESS 必须给出 --success-rule，且不得是数据集均值阈值")
    g4_role = (args.g4_role or "").strip()
    if g4_role and g4_role not in G4_ROLES:
        raise SystemExit(f"--g4-role 必须是 {sorted(G4_ROLES)}")
    if not canonical_relative_path(args.output):
        raise SystemExit("--output 必须是根内规范相对路径")
    output_path = root / args.output
    if not output_path.is_file():
        raise SystemExit(f"--output 不存在：{args.output}")

    probes = registry.setdefault("probes", [])
    if not isinstance(probes, list):
        raise SystemExit("instance_probe_registry.probes 必须是列表")
    existing_ids = {
        item.get("probe_id")
        for item in probes
        if isinstance(item, dict)
    }
    probe_id = args.probe_id.strip()
    replacing = probe_id in existing_ids
    if not replacing and len(probes) >= MAX_INSTANCE_PROBES:
        raise SystemExit(f"实例探针已达上限 {MAX_INSTANCE_PROBES}")

    try:
        value = float(args.value)
    except ValueError as error:
        raise SystemExit(f"--value 必须是数字：{args.value}") from error

    entry = {
        "probe_id": probe_id,
        "purpose": args.purpose,
        "source_registry_id": args.source_work.strip(),
        "locator": args.locator.strip(),
        "published_text": args.published_text.strip(),
        "metric": args.metric.strip(),
        "value": value,
        "old_metric_verdict": args.old_verdict,
        "success_rule": (args.success_rule or "").strip(),
        "boundary_lost": [item.strip() for item in (args.boundary_lost or []) if item.strip()],
        "output_file": args.output,
        "output_sha256": file_sha256(output_path),
        "registered_at": utc_now(),
    }
    if g4_role:
        entry["g4_role"] = g4_role
    if replacing:
        probes[:] = [
            entry if isinstance(item, dict) and item.get("probe_id") == probe_id else item
            for item in probes
        ]
    else:
        probes.append(entry)
    _atomic_write_json(registry_path, registry)
    append_validation_log(
        root,
        f"REGISTER_INSTANCE_PROBE {probe_id} value={value} "
        f"source={args.source_work} output={args.output}",
    )
    print(f"registered instance probe {probe_id}: {args.output}")
    return int(ExitCode.READY)


def _count_records(payload: Any, keys: tuple[str, ...]) -> int | None:
    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if isinstance(value, list):
                return len(value)
    if isinstance(payload, list):
        return len(payload)
    return None


def cmd_handover(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    state_path = Path(args.state).resolve()
    with ProjectContext(root, state_path) as ctx:
        state = ctx.state
        gates = ctx.gates()
        lock_path = root / ".workflow_stop.lock"
        frontier = fulltexts = claims = None
        try:
            frontier = _count_records(
                ctx.load_json(
                    ctx.artifact_relative_path("literature_registry"),
                    "literature_registry",
                ),
                ("records", "works", "items"),
            )
        except Exception:
            pass
        archive = root / "literature_archive"
        if archive.is_dir():
            fulltexts = len([p for p in archive.iterdir() if p.suffix.lower() == ".pdf"])
        try:
            claims = _count_records(
                ctx.load_json(
                    ctx.artifact_relative_path("claim_registry"), "claim_registry"
                ),
                ("claims", "records", "items"),
            )
        except Exception:
            pass

    audit = state.get("independent_audit") or {}
    # active_track / 证据层级为派生值（schema 3.0）；BLOCKED 从 resume_state 派生。
    active_state = state.get("active_state")
    effective_state = (
        state.get("resume_state") if active_state == "BLOCKED" else active_state
    )
    derived_track = STATE_TO_TRACK.get(str(effective_state), "(none)")
    derived_tier = evidence_tier(str(effective_state))
    print("# 交接报告（iph handover）")
    print(f"成果合同: {state.get('output_type')} / {state.get('contribution_contract')}")
    print(f"active state: {active_state} (track: {derived_track}, evidence tier: {derived_tier})")
    print(f"N level: {state.get('novelty_level')}  V level: {state.get('validity_level')}")
    print(f"claim profile: {state.get('claim_profile')}  epoch: {state.get('validation_epoch')}")
    print(f"bundle hash: {state.get('claim_bundle_sha256') or '(none)'}")
    print(
        f"frontier works: {frontier if frontier is not None else 'unknown'}  "
        f"fulltexts: {fulltexts if fulltexts is not None else 'unknown'}  "
        f"claims: {claims if claims is not None else 'unknown'}"
    )
    print(
        "reviewer provenance: "
        f"{audit.get('reviewer_agent_id', '(none)')} / "
        f"{audit.get('reviewer_thread_id', '(none)')} / "
        f"verdict={audit.get('verdict', '(none)')}"
    )
    print(
        "last validator exit: "
        + (
            f"STOP LOCK active (exit={json.loads(lock_path.read_text(encoding='utf-8')).get('exit_code')})"
            if lock_path.exists()
            else "no stop lock (re-run iph validate for fresh exit code)"
        )
    )
    print(f"blocked reasons: {state.get('blocked_reasons') or []}")
    print(f"compute_authorized: {gates.get('compute_authorized')}")
    print(f"next_required_action: {state.get('next_required_action')}")
    print("# 锚点抽查（R-REVIEW-20，交接前必须完成并留痕）")
    print("1. 抽查 ≥5% 的原子观点 normalized_statement，回原文核对数值/locator 真实性")
    print("2. 抽查 ≥1 条碰撞类结论的 evidence，回全文核对数值锚点是否真实（防 U-Sophistry 假证据）")
    print("3. 记录抽查结果：checked=<N>  found_fabricated=<N>  抽查人=<agent-id>  时间=<UTC>")
    print("   发现编造锚点 → 该观点降级/重抽，且旧独立审计失效（material change）")
    return int(ExitCode.READY)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="iph", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def add_root_state(p: argparse.ArgumentParser) -> None:
        p.add_argument("--root", type=Path, required=True)
        p.add_argument("--state", type=Path, required=True)
        p.add_argument("--strict-new-checks", action="store_true")

    p = sub.add_parser("validate", help="运行完整校验套件")
    add_root_state(p)
    p.add_argument("--extra", nargs="*", default=[])
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("advance", help="校验通过后推进状态并记账")
    add_root_state(p)
    p.add_argument("--to", required=True, metavar="STATE")
    p.add_argument("--note", required=True)
    p.add_argument("--set-gate", action="append", metavar="key=true|false")
    p.add_argument("--artifact", action="append", metavar="PATH")
    p.add_argument(
        "--set-artifact",
        action="append",
        metavar="KEY=PATH",
        help="与状态推进原子登记 workflow_state.artifacts 路径指针",
    )
    p.add_argument(
        "--next-action",
        help="与状态推进原子更新唯一 next_required_action",
    )
    p.add_argument(
        "--contribution",
        choices=["NONE", "M", "A", "B", "C"],
        help="与状态推进原子切换 active_contribution；期刊首次进入 L3 默认 M",
    )
    p.add_argument(
        "--novelty-level",
        choices=sorted(VALID_NOVELTY_LEVELS),
        help="仅进入 N0_AUDIT 时，与 n0_4_locked gate 原子写入裁决",
    )
    p.add_argument(
        "--authorize-compute",
        action="store_true",
        help="仅进入 COMPUTE 时登记用户已显式授权",
    )
    p.add_argument(
        "--authorization-note",
        help="用户授权的可审计依据；与 --authorize-compute 同时使用",
    )
    p.add_argument(
        "--accept-complete",
        action="store_true",
        help="仅进入 COMPLETE 时登记用户已接受本次最终锁定",
    )
    p.add_argument(
        "--acceptance-note",
        help="用户接受本次 COMPLETE 的原句；与 --accept-complete 同时使用",
    )
    p.add_argument(
        "--compute-evidence",
        help="仅进入 POSTCOMPUTE_CLAIM_FREEZE 时登记 S4 证据 JSON",
    )
    p.add_argument(
        "--claim-bundle-manifest",
        help="进入 VALIDITY_AUDIT 时登记当前 epoch bundle，或进入 FINAL_VALIDITY_AUDIT 时登记 +1 epoch bundle",
    )
    p.add_argument("--blocked-reason", action="append")
    p.add_argument("--no-validate", action="store_true")
    p.set_defaults(func=cmd_advance)

    p = sub.add_parser(
        "start-collision-round", help="从 N0-3 审计合规开启下一碰撞轮次"
    )
    add_root_state(p)
    p.add_argument("--note", required=True)
    p.add_argument(
        "--keep-layers",
        action="store_true",
        help="L1/L2/架构未变时保留其冻结门，只重置本轮 L3/K/输出/证据门",
    )
    p.add_argument("--no-validate", action="store_true")
    p.set_defaults(func=cmd_start_collision_round)

    p = sub.add_parser(
        "revise-exact-statement",
        help="只改 L3 精确句：同轮、保留 L1/L2/K，跳回 SYNTHESIZE_COLLISION",
    )
    add_root_state(p)
    p.add_argument("--path", required=True, help="新的 hashed L3 精确句文件")
    p.add_argument("--note", required=True)
    p.add_argument("--set-artifact", action="append", metavar="KEY=PATH")
    p.add_argument("--next-action")
    p.add_argument("--no-validate", action="store_true")
    p.set_defaults(func=cmd_revise_exact_statement)

    p = sub.add_parser(
        "retract-novelty",
        help="从 N0_AUDIT/N0-4C 合法撤回为 N0-3/N0-1/N0-2",
    )
    add_root_state(p)
    p.add_argument("--to", required=True, choices=["N0-1", "N0-2", "N0-3"])
    p.add_argument("--note", required=True)
    p.add_argument("--artifact", action="append", metavar="PATH", required=True)
    p.add_argument("--set-artifact", action="append", metavar="KEY=PATH")
    p.add_argument("--next-action")
    p.add_argument("--no-validate", action="store_true")
    p.set_defaults(func=cmd_retract_novelty)

    p = sub.add_parser(
        "repair-collision-round", help="仅修复 STOP 锁中的新碰撞轮次快照"
    )
    add_root_state(p)
    p.set_defaults(func=cmd_repair_collision_round)

    p = sub.add_parser("review", help="subagent 登记 review 产物 hash 到 state")
    add_root_state(p)
    p.add_argument("--reviewer", required=True)
    p.add_argument("--thread", required=True)
    p.add_argument("--verdict", required=True, choices=["PASS", "FAIL"])
    p.add_argument(
        "--review-artifact",
        help="复核产物相对路径；同一事务写入 artifacts.independent_audit",
    )
    p.set_defaults(func=cmd_review)

    p = sub.add_parser(
        "reopen-validity-epoch",
        help="FAIL 复核或用户否决 COMPLETE/V4 后新开 validity epoch",
    )
    add_root_state(p)
    p.add_argument("--note", required=True)
    p.add_argument(
        "--user-reject-complete",
        action="store_true",
        help="用户否决 FINAL_LOCK/COMPLETE/V4：退回 CLAIM_FREEZE，关闭计算，保留 N0-4C",
    )
    p.add_argument(
        "--set-artifact",
        action="append",
        metavar="KEY=PATH",
        help="同一事务切换到新 epoch 的版本化产物指针",
    )
    p.add_argument("--next-action")
    p.add_argument("--no-validate", action="store_true")
    p.set_defaults(func=cmd_reopen_validity_epoch)

    p = sub.add_parser(
        "advance-compute-stage",
        help="COMPUTE 内只向前升级 S0→S1→S2→S3→S4",
    )
    add_root_state(p)
    p.add_argument("--to", required=True, choices=["S1", "S2", "S3", "S4"])
    p.add_argument("--note", required=True)
    p.add_argument("--artifact", action="append", metavar="PATH")
    p.add_argument("--next-action")
    p.add_argument("--no-validate", action="store_true")
    p.set_defaults(func=cmd_advance_compute_stage)

    p = sub.add_parser("clear-lock", help="完成恢复动作后解除 STOP 锁")
    add_root_state(p)
    p.add_argument("--recovery-note", required=True)
    p.add_argument(
        "--set-artifact",
        action="append",
        metavar="KEY=PATH",
        help="STOP 恢复期受控修复 workflow_state.artifacts 路径指针",
    )
    p.add_argument(
        "--next-action",
        help="STOP 恢复期受控修复唯一 next_required_action",
    )
    p.add_argument(
        "--resume-blocked",
        action="store_true",
        help="operator 修复外部阻塞后，把 BLOCKED 原子恢复到 resume_state",
    )
    p.add_argument(
        "--set-gate",
        action="append",
        metavar="key=true|false",
        help="STOP 恢复期补漏写的机械完成门 output_claims_traced/evidence_validated",
    )
    p.set_defaults(func=cmd_clear_lock)

    p = sub.add_parser(
        "repair-artifact-pointer",
        help="保留旧证据文件与哈希，原子切换 state artifact 到版本化修正版",
    )
    add_root_state(p)
    p.add_argument("--recovery-note", required=True)
    p.add_argument("--set-artifact", action="append", metavar="KEY=PATH", required=True)
    p.add_argument("--next-action")
    p.set_defaults(func=cmd_repair_artifact_pointer)

    p = sub.add_parser(
        "register-exploration", help="登记探索性产物（永久探索级证据）"
    )
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--state", type=Path, required=True)
    p.add_argument("--path", required=True)
    p.add_argument("--desc", required=True)
    p.set_defaults(func=cmd_register_exploration)

    p = sub.add_parser(
        "authorize-instance-probe",
        help="N0-3 下授权小范围实例探针（不打开 COMPUTE）",
    )
    add_root_state(p)
    p.add_argument("--note", required=True)
    p.set_defaults(func=cmd_authorize_instance_probe)

    p = sub.add_parser(
        "register-instance-probe",
        help="登记一条已授权实例探针结果",
    )
    add_root_state(p)
    p.add_argument("--probe-id", required=True)
    p.add_argument("--purpose", required=True, choices=sorted(INSTANCE_PROBE_PURPOSES))
    p.add_argument("--source-work", required=True)
    p.add_argument("--locator", required=True)
    p.add_argument("--published-text", required=True)
    p.add_argument("--metric", required=True)
    p.add_argument("--value", required=True)
    p.add_argument("--old-verdict", required=True, choices=sorted(INSTANCE_PROBE_VERDICTS))
    p.add_argument("--g4-role", choices=sorted(G4_ROLES))
    p.add_argument("--success-rule")
    p.add_argument("--boundary-lost", action="append")
    p.add_argument("--output", required=True)
    p.set_defaults(func=cmd_register_instance_probe)

    p = sub.add_parser("handover", help="按 SKILL.md §10 生成交接报告")
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--state", type=Path, required=True)
    p.set_defaults(func=cmd_handover)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
