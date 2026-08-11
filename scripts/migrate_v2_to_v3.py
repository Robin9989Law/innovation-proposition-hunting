#!/usr/bin/env python3
"""Explicitly migrate a Schema 2.0 workflow state to Schema 3.0.

机械映射（docs/design-schema-3.0.md §5）：

- 状态改名 IMPORTANT_FULLTEXT→K_FULLTEXT、SOURCE_CLAIM_REGISTER→K_CLAIM_REGISTER
  （active_state / resume_state / decision_log 条目，含 BLOCKED@<STATE> 形式）。
- 门改名 important_fulltext_complete→k_fulltext_complete、
  source_claims_complete→k_claims_complete；新增 k_set_selected = 旧 l2_frozen
  （已过 LAYER_DECISION 的项目视为做过 K 集合选拔）。
- 删除派生字段 active_track / active_layer / last_completed_state。
- schema_version 置 "3.0"。历史（decision_log 时间戳、epoch、哈希）全部保留。

注意：2.0 项目若已做全量抽取（全文 >20 或原子观点 >60），迁移后
EVIDENCE_DEPTH_EXCEEDS_LAYER 会常亮 INVALID——全量抽取正是 3.0 要消灭的
模式，脚本只告警，不代为删减证据。
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import stat
import sys
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from migrate_v1_to_v2 import (  # noqa: E402
    atomic_publish_json,
    atomic_write_json,
    create_exclusive_backup,
    load_json,
    open_trusted_directory,
)
from validate_workflow_state import (  # noqa: E402
    EVIDENCE_DEPTH_BUDGETS,
    count_registered_evidence,
)

STATE_RENAMES = {
    "IMPORTANT_FULLTEXT": "K_FULLTEXT",
    "SOURCE_CLAIM_REGISTER": "K_CLAIM_REGISTER",
}
GATE_RENAMES = {
    "important_fulltext_complete": "k_fulltext_complete",
    "source_claims_complete": "k_claims_complete",
}
DERIVED_FIELDS = ("active_track", "active_layer", "last_completed_state")


def rename_state(value: Any) -> Any:
    """状态改名；decision_log 条目的 BLOCKED@<STATE> 形式保持前缀。"""
    if not isinstance(value, str):
        return value
    if value.startswith("BLOCKED@"):
        base = value.removeprefix("BLOCKED@")
        return "BLOCKED@" + STATE_RENAMES.get(base, base)
    return STATE_RENAMES.get(value, value)


def migrate(state: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """返回 (迁移后 state, 告警列表)。输入必须是 schema 2.0。"""
    if state.get("schema_version") != "2.0":
        raise ValueError(f"source_schema_not_2.0:{state.get('schema_version')}")
    migrated = deepcopy(state)
    warnings: list[str] = []

    # 1. 状态改名
    migrated["active_state"] = rename_state(migrated.get("active_state"))
    migrated["resume_state"] = rename_state(migrated.get("resume_state"))
    decision_log = migrated.get("decision_log")
    if isinstance(decision_log, list):
        for entry in decision_log:
            if isinstance(entry, dict) and "state" in entry:
                entry["state"] = rename_state(entry["state"])

    # 2. 门改名 + 新增 k_set_selected
    gates = migrated.get("gates")
    if not isinstance(gates, dict):
        gates = {}
        migrated["gates"] = gates
    for old_name, new_name in GATE_RENAMES.items():
        if old_name in gates:
            gates[new_name] = gates.pop(old_name)
    gates["k_set_selected"] = gates.get("l2_frozen") is True

    # 3. k_set_selected=true 但无 k_triage 产物：告警不伪造
    artifacts = migrated.get("artifacts")
    if gates["k_set_selected"] and not (
        isinstance(artifacts, dict) and artifacts.get("k_triage")
    ):
        warnings.append(
            "k_set_selected=true 但 artifacts 无 k_triage：请补写 K 集合选拔记录"
            "（如 l2-triage.md）并在 artifacts.k_triage 登记，否则 ARTIFACT 校验报错"
        )

    # 4. 删除派生字段，升级版本
    for field in DERIVED_FIELDS:
        migrated.pop(field, None)
    migrated["schema_version"] = "3.0"
    return migrated, warnings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    destination = parser.add_mutually_exclusive_group()
    destination.add_argument("--output", type=Path)
    destination.add_argument("--in-place", action="store_true")
    args = parser.parse_args()

    root = args.root.resolve()
    state_path = args.state.resolve()
    try:
        state_path.relative_to(root)
        source_mode = stat.S_IMODE(state_path.stat().st_mode)
        source = load_json(state_path)
        migrated, warnings = migrate(source)

        # 预算告警：迁移后的 state 按 3.0 预算（L3 段）盘点证据深度
        fulltext_count, claim_count, pointer_issues = count_registered_evidence(
            root, migrated
        )
        for detail in pointer_issues:
            warnings.append(f"REGISTRY_POINTER_MISSING: {detail}")
        fulltext_budget, claim_budget = EVIDENCE_DEPTH_BUDGETS["L3"]
        if fulltext_count > fulltext_budget or claim_count > claim_budget:
            warnings.append(
                f"证据深度超 3.0 预算（fulltext:{fulltext_count}>{fulltext_budget} "
                f"或 atomic_claims:{claim_count}>{claim_budget}）：迁移后 "
                "EVIDENCE_DEPTH_EXCEEDS_LAYER 将常亮 INVALID；全量抽取是 3.0 "
                "要消灭的模式，脚本不代删证据"
            )

        output_path = (
            state_path
            if args.in_place
            else args.output.resolve()
            if args.output
            else root / "workflow_state.v3.json"
        )
        output_path.relative_to(root)
        if args.in_place:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            backup_name = f"{state_path.name}.v2-backup-{timestamp}"
            backup = state_path.with_name(backup_name)
            with open_trusted_directory(
                root, state_path.parent, create=False
            ) as dir_fd:
                create_exclusive_backup(
                    dir_fd,
                    state_path.name,
                    backup_name,
                    source_mode,
                )
                atomic_write_json(
                    dir_fd,
                    state_path.name,
                    migrated,
                    source_mode,
                )
            print(f"migration_backup={backup}")
        else:
            if output_path == state_path:
                raise ValueError("output_equals_state")
            with open_trusted_directory(
                root, output_path.parent, create=True
            ) as dir_fd:
                try:
                    atomic_publish_json(
                        dir_fd,
                        output_path.name,
                        migrated,
                        source_mode,
                    )
                except FileExistsError as error:
                    raise ValueError("output_exists") from error
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"migration_status=INVALID\nmigration_error={error}")
        return 1

    print("migration_status=READY")
    print(f"migration_output={output_path}")
    for warning in warnings:
        print(f"migration_warning={warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
