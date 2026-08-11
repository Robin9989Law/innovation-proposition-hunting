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
# clear-lock / register-exploration / handover
# ---------------------------------------------------------------------------


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
    p.add_argument("--blocked-reason", action="append")
    p.add_argument("--no-validate", action="store_true")
    p.set_defaults(func=cmd_advance)

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
