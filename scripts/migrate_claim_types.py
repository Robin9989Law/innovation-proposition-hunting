#!/usr/bin/env python3
"""Migrate literature_claim_registry claim_type from genre type to judgment type.

机械映射（docs/optimization-plan-2026-08-r3-reasoning-quality.md P4）：

- `claim_type` 由文体类型（VIEWPOINT/CONCLUSION/METHOD/ASSUMPTION/LIMITATION/
  COUNTEREXAMPLE）改为判断类型（OCCUPIES/ENABLES/CONTRADICTS/BOUNDS/NEUTRAL）：
  表达"这条观点对候选存活判断的关系"，不再表达"观点来自论文哪一章节"。
- `support_role`（SUPPORTS/CONTRADICTS/QUALIFIES/METHOD_FOR）语义并入新
  claim_type，字段删除。

映射（support_role 优先，缺失时回退旧 claim_type）：

  SUPPORTS   → ENABLES       METHOD    → ENABLES
  METHOD_FOR → ENABLES       ASSUMPTION→ ENABLES
  QUALIFIES  → BOUNDS        CONCLUSION→ BOUNDS
  CONTRADICTS→ CONTRADICTS   LIMITATION→ BOUNDS
                             COUNTEREXAMPLE→ CONTRADICTS
                             VIEWPOINT → NEUTRAL

`OCCUPIES`（候选主张被近邻直接占据）无法从旧字段机械推出，脚本不代为判定，
只告警：迁移后需 agent 在碰撞时逐条复核，把真正"直接占据候选"的观点标为
OCCUPIES——这正是 P4 要消灭"按章节套壳"后新引入的、需要真推理的判断。
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
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

# support_role → 新 claim_type（优先）
SUPPORT_ROLE_MAP = {
    "SUPPORTS": "ENABLES",
    "METHOD_FOR": "ENABLES",
    "QUALIFIES": "BOUNDS",
    "CONTRADICTS": "CONTRADICTS",
}
# 旧 claim_type（文体）→ 新 claim_type（support_role 缺失时回退）
GENRE_TYPE_MAP = {
    "METHOD": "ENABLES",
    "ASSUMPTION": "ENABLES",
    "CONCLUSION": "BOUNDS",
    "LIMITATION": "BOUNDS",
    "COUNTEREXAMPLE": "CONTRADICTS",
    "VIEWPOINT": "NEUTRAL",
}


def map_claim_type(claim: dict[str, Any]) -> tuple[str, list[str]]:
    """返回 (新 claim_type, 告警列表)。"""
    warnings: list[str] = []
    support_role = claim.get("support_role")
    if isinstance(support_role, str) and support_role in SUPPORT_ROLE_MAP:
        return SUPPORT_ROLE_MAP[support_role], warnings

    genre = claim.get("claim_type")
    if isinstance(genre, str) and genre in GENRE_TYPE_MAP:
        warnings.append(
            f"support_role 缺失，按文体类型回退：{genre} → {GENRE_TYPE_MAP[genre]}"
        )
        return GENRE_TYPE_MAP[genre], warnings

    warnings.append(f"claim_type/support_role 均不可映射，置 NEUTRAL")
    return "NEUTRAL", warnings


def migrate(payload: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """迁移 literature_claim_registry 的 claim_type 并删除 support_role。"""
    from copy import deepcopy

    migrated = deepcopy(payload)
    records = migrated.get("claims") or migrated.get("records")
    if not isinstance(records, list):
        raise ValueError("literature_claim_registry 缺少 claims/records 列表")
    warnings: list[str] = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            warnings.append(f"record[{index}] 非对象，跳过")
            continue
        claim_id = record.get("claim_id") or f"record[{index}]"
        new_type, claim_warnings = map_claim_type(record)
        for warning in claim_warnings:
            warnings.append(f"{claim_id}: {warning}")
        record["claim_type"] = new_type
        record.pop("support_role", None)
    warnings.append(
        "OCCUPIES 无法从旧字段机械推出：迁移后需 agent 逐条复核，"
        "把真正'直接占据候选'的观点标为 OCCUPIES（这是需要真推理的新判断）"
    )
    return migrated, warnings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    destination = parser.add_mutually_exclusive_group()
    destination.add_argument("--output", type=Path)
    destination.add_argument("--in-place", action="store_true")
    args = parser.parse_args()

    root = args.root.resolve()
    registry_path = args.registry.resolve()
    try:
        registry_path.relative_to(root)
        source_mode = stat.S_IMODE(registry_path.stat().st_mode)
        source = load_json(registry_path)
        migrated, warnings = migrate(source)

        output_path = (
            registry_path
            if args.in_place
            else args.output.resolve()
            if args.output
            else root / "literature_claim_registry.judgment.json"
        )
        output_path.relative_to(root)
        if args.in_place:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            backup_name = f"{registry_path.name}.genre-backup-{timestamp}"
            backup = registry_path.with_name(backup_name)
            with open_trusted_directory(
                root, registry_path.parent, create=False
            ) as dir_fd:
                create_exclusive_backup(
                    dir_fd, registry_path.name, backup_name, source_mode
                )
                atomic_write_json(
                    dir_fd, registry_path.name, migrated, source_mode
                )
            print(f"migration_backup={backup}")
        else:
            if output_path == registry_path:
                raise ValueError("output_equals_registry")
            with open_trusted_directory(
                root, output_path.parent, create=True
            ) as dir_fd:
                try:
                    atomic_publish_json(
                        dir_fd, output_path.name, migrated, source_mode
                    )
                except FileExistsError as error:
                    raise ValueError("output_exists") from error
    except (OSError, ValueError, KeyError) as error:
        print(f"migration_status=INVALID\nmigration_error={error}")
        return 1

    print("migration_status=READY")
    print(f"migration_output={output_path}")
    for warning in warnings:
        print(f"migration_warning={warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
