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
  clear-lock              完成恢复动作后解除 STOP 锁
  register-exploration    把探索性数据/产物登记为永久探索级证据
  handover                按 SKILL.md §10 生成交接报告
"""

from __future__ import annotations

import argparse
import json
import os
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
    nonempty_string,
)
from validate_workflow_state import (  # noqa: E402
    GATE_KEYS,
    STATES,
    TRACK_STATES,
    evidence_tier,
)

GATE_BOOL = {"true": True, "false": False}

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
    artifact_paths: list[str] = []
    for raw in args.artifact or []:
        if not canonical_relative_path(raw):
            raise SystemExit(f"--artifact 必须是根内规范相对路径：{raw!r}")
        artifact_paths.append(raw)

    now = utc_now()
    state = json.loads(state_path.read_text(encoding="utf-8"))
    previous_state = state.get("active_state")

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
    gates = state.setdefault("gates", {})
    for key, value in gate_updates.items():
        gates[key] = value

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
        f"gates={gate_updates or '-'} artifacts={len(artifacts)} note={args.note.strip()}",
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

    state["collision_round"] = new_round
    state["active_state"] = "PRIOR_CLAIM_DRAIN"
    state["resume_state"] = "PRIOR_CLAIM_DRAIN"
    state["updated_at"] = now
    state_artifacts = state.setdefault("artifacts", {})
    state_artifacts.update(round_artifacts)
    state["next_required_action"] = (
        "Perform P1 recent-frontier search for collision round "
        f"{new_round}; register every material hit before fulltext triage."
    )
    gates = state.setdefault("gates", {})
    for key in (
        "l1_frozen",
        "k_set_selected",
        "l2_frozen",
        "architecture_frozen",
        "recent_frontier_complete",
        "literature_registry_valid",
        "k_fulltext_complete",
        "k_claims_complete",
        "output_claims_traced",
        "evidence_validated",
        "n0_4_locked",
    ):
        gates[key] = False
    gates["prior_claims_drained"] = True
    state["active_contribution"] = "NONE"
    entry = {
        "at": now,
        "state": "PRIOR_CLAIM_DRAIN",
        "action": (
            f"Opened collision round {new_round} from N0-3 HOLD; all prior-round "
            f"claims were drained before P1. {args.note.strip()}"
        ),
        "artifacts": [
            {
                "path": round_artifacts["current_evidence_scope"],
                "sha256": file_sha256(new_paths["current_evidence_scope"]),
            }
        ],
    }
    state.setdefault("decision_log", []).append(entry)
    atomic_write_state(state_path, state)
    append_validation_log(
        root,
        f"START_COLLISION_ROUND {old_round} -> {new_round} "
        f"scope={round_artifacts['current_evidence_scope']} note={args.note.strip()}",
    )
    print(f"started collision round {old_round} -> {new_round}")
    exit_code = run_validate_all(root, state_path, args.strict_new_checks, [])
    if exit_code != int(ExitCode.READY):
        print(f"post-start validation exit={exit_code}")
    return exit_code


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

    gates = state.setdefault("gates", {})
    for key in (
        "l1_frozen",
        "k_set_selected",
        "l2_frozen",
        "architecture_frozen",
        "recent_frontier_complete",
        "literature_registry_valid",
        "k_fulltext_complete",
        "k_claims_complete",
        "output_claims_traced",
        "evidence_validated",
        "n0_4_locked",
    ):
        gates[key] = False
    gates["prior_claims_drained"] = True
    state["active_contribution"] = "NONE"
    state["updated_at"] = utc_now()
    atomic_write_state(state_path, state)
    append_validation_log(
        root,
        "REPAIR_COLLISION_ROUND repaired current snapshot URL aliases and reset "
        "new-round L1/L2/L3 gates before STOP-lock recovery",
    )
    print("repaired collision-round snapshot; run clear-lock to validate recovery")
    return int(ExitCode.READY)


def cmd_clear_lock(args: argparse.Namespace) -> int:
    if not nonempty_string(args.recovery_note):
        raise SystemExit("clear-lock 需要 --recovery-note 记录唯一恢复动作")
    return run_validate_all(
        Path(args.root).resolve(),
        Path(args.state).resolve(),
        args.strict_new_checks,
        ["--clear-lock", "--recovery-note", args.recovery_note.strip()],
    )


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
        "--contribution",
        choices=["NONE", "M", "A", "B", "C"],
        help="与状态推进原子切换 active_contribution；期刊首次进入 L3 默认 M",
    )
    p.add_argument("--blocked-reason", action="append")
    p.add_argument("--no-validate", action="store_true")
    p.set_defaults(func=cmd_advance)

    p = sub.add_parser(
        "start-collision-round", help="从 N0-3 审计合规开启下一碰撞轮次"
    )
    add_root_state(p)
    p.add_argument("--note", required=True)
    p.set_defaults(func=cmd_start_collision_round)

    p = sub.add_parser(
        "repair-collision-round", help="仅修复 STOP 锁中的新碰撞轮次快照"
    )
    add_root_state(p)
    p.set_defaults(func=cmd_repair_collision_round)

    p = sub.add_parser("clear-lock", help="完成恢复动作后解除 STOP 锁")
    add_root_state(p)
    p.add_argument("--recovery-note", required=True)
    p.set_defaults(func=cmd_clear_lock)

    p = sub.add_parser(
        "register-exploration", help="登记探索性产物（永久探索级证据）"
    )
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--state", type=Path, required=True)
    p.add_argument("--path", required=True)
    p.add_argument("--desc", required=True)
    p.set_defaults(func=cmd_register_exploration)

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
