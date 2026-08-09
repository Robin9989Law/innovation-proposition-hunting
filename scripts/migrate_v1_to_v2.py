#!/usr/bin/env python3
"""Explicitly migrate a Schema 1.x workflow state to Schema 2.0."""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from shutil import copy2
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("workflow state top level must be an object")
    return payload


def migrate(state: dict[str, Any]) -> dict[str, Any]:
    migrated = deepcopy(state)
    gates = migrated.get("gates")
    if not isinstance(gates, dict):
        gates = {}
        migrated["gates"] = gates
    old_n0_locked = bool(gates.get("n0_4_locked")) or (
        migrated.get("n0_4_status") == "LOCKED"
    )

    migrated["schema_version"] = "2.0"
    migrated["active_track"] = "VALIDITY"
    migrated["active_state"] = "CLAIM_FREEZE"
    migrated["resume_state"] = "CLAIM_FREEZE"
    migrated["novelty_level"] = "N0-4C" if old_n0_locked else "N0-3"
    migrated["validity_level"] = "V0"
    migrated["validation_epoch"] = 1
    migrated["claim_bundle_sha256"] = ""
    migrated["independent_audit"] = {}
    migrated["compute_stage"] = "NOT_STARTED"
    gates["n0_4_locked"] = False
    gates["compute_authorized"] = False
    for obsolete in ("n0_4_status", "compute_readiness", "n0_audit_hash"):
        migrated.pop(obsolete, None)
    return migrated


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


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
        source = load_json(state_path)
        if source.get("schema_version") == "2.0":
            raise ValueError("state is already Schema 2.0")
        output_path = (
            state_path
            if args.in_place
            else args.output.resolve()
            if args.output
            else root / "workflow_state.v2.json"
        )
        output_path.relative_to(root)
        migrated = migrate(source)
        if args.in_place:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            backup = state_path.with_name(
                f"{state_path.name}.v1-backup-{timestamp}"
            )
            copy2(state_path, backup)
            print(f"migration_backup={backup}")
        write_json(output_path, migrated)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"migration_status=INVALID\nmigration_error={error}")
        return 1

    print("migration_status=READY")
    print(f"migration_output={output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
