#!/usr/bin/env python3
"""Explicitly migrate a Schema 1.x workflow state to Schema 2.0."""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
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
    if "n0_4_locked" in gates and type(gates["n0_4_locked"]) is not bool:
        raise ValueError("n0_4_locked_not_boolean")
    old_n0_locked = gates.get("n0_4_locked") is True or (
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


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    serialized = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode(
        "utf-8"
    )
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    descriptor_open = True
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor_open = False
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except BaseException:
        if descriptor_open:
            os.close(descriptor)
        temporary_path.unlink(missing_ok=True)
        raise


def create_exclusive_backup(source: Path, backup: Path) -> None:
    descriptor = os.open(
        backup,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        source.stat().st_mode & 0o777,
    )
    backup_open = True
    try:
        with os.fdopen(descriptor, "wb") as destination:
            backup_open = False
            with source.open("rb") as source_handle:
                for chunk in iter(lambda: source_handle.read(1024 * 1024), b""):
                    destination.write(chunk)
            destination.flush()
            os.fsync(destination.fileno())
    except BaseException:
        if backup_open:
            os.close(descriptor)
        backup.unlink(missing_ok=True)
        raise


def is_schema_1_x(value: Any) -> bool:
    return isinstance(value, str) and (value == "1" or value.startswith("1."))


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
        if not is_schema_1_x(source.get("schema_version")):
            raise ValueError("source_schema_not_1_x")
        migrated = migrate(source)
        output_path = (
            state_path
            if args.in_place
            else args.output.resolve()
            if args.output
            else root / "workflow_state.v2.json"
        )
        output_path.relative_to(root)
        if args.in_place:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            backup = state_path.with_name(
                f"{state_path.name}.v1-backup-{timestamp}"
            )
            create_exclusive_backup(state_path, backup)
            print(f"migration_backup={backup}")
        else:
            if output_path == state_path:
                raise ValueError("output_equals_state")
            if os.path.lexists(output_path):
                raise ValueError("output_exists")
        atomic_write_json(output_path, migrated)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"migration_status=INVALID\nmigration_error={error}")
        return 1

    print("migration_status=READY")
    print(f"migration_output={output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
