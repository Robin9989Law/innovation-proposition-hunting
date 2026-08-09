#!/usr/bin/env python3
"""Explicitly migrate a Schema 1.x workflow state to Schema 2.0."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import errno
import json
import os
from pathlib import Path
import secrets
import stat
from typing import Any, Iterator


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


def directory_open_flags() -> int:
    if not hasattr(os, "O_DIRECTORY") or not hasattr(os, "O_NOFOLLOW"):
        raise RuntimeError("secure_directory_flags_unavailable")
    return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


@contextmanager
def open_trusted_directory(
    root: Path,
    parent: Path,
    *,
    create: bool,
) -> Iterator[int]:
    lexical_root = root.absolute()
    parent = parent.absolute()
    try:
        relative_parent = parent.relative_to(lexical_root)
    except ValueError as error:
        raise ValueError(f"output_parent_outside_root:{parent}") from error
    root = root.resolve(strict=True)

    current_fd = os.open(root, directory_open_flags())
    try:
        for component in relative_parent.parts:
            if component in {"", ".", ".."}:
                raise ValueError(f"unsafe_output_component:{component}")
            if create:
                try:
                    os.mkdir(component, 0o755, dir_fd=current_fd)
                except FileExistsError:
                    pass
            next_fd = os.open(
                component,
                directory_open_flags(),
                dir_fd=current_fd,
            )
            os.close(current_fd)
            current_fd = next_fd
        yield current_fd
    finally:
        os.close(current_fd)


def fsync_directory(dir_fd: int) -> None:
    try:
        os.fsync(dir_fd)
    except OSError as error:
        if error.errno not in {errno.EINVAL, errno.ENOTSUP}:
            raise


def validate_filename(name: str) -> None:
    if not name or name in {".", ".."} or Path(name).name != name:
        raise ValueError(f"unsafe_output_filename:{name}")


def unlink_if_exists(dir_fd: int, name: str) -> None:
    try:
        os.unlink(name, dir_fd=dir_fd)
    except FileNotFoundError:
        pass


def write_temporary_json(
    dir_fd: int,
    target_name: str,
    payload: dict[str, Any],
    mode: int,
) -> str:
    validate_filename(target_name)
    serialized = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode(
        "utf-8"
    )
    descriptor = -1
    temporary_name = ""
    for _ in range(128):
        temporary_name = f".{target_name}.{secrets.token_hex(12)}.tmp"
        try:
            descriptor = os.open(
                temporary_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=dir_fd,
            )
            break
        except FileExistsError:
            continue
    if descriptor < 0:
        raise FileExistsError("unable_to_allocate_temporary_file")
    descriptor_open = True
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor_open = False
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        if descriptor_open:
            os.close(descriptor)
        unlink_if_exists(dir_fd, temporary_name)
        raise
    return temporary_name


def atomic_write_json(
    dir_fd: int,
    target_name: str,
    payload: dict[str, Any],
    mode: int,
) -> None:
    temporary_name = write_temporary_json(dir_fd, target_name, payload, mode)
    try:
        os.replace(
            temporary_name,
            target_name,
            src_dir_fd=dir_fd,
            dst_dir_fd=dir_fd,
        )
        fsync_directory(dir_fd)
    except BaseException:
        unlink_if_exists(dir_fd, temporary_name)
        raise


def atomic_publish_json(
    dir_fd: int,
    target_name: str,
    payload: dict[str, Any],
    mode: int,
) -> None:
    temporary_name = write_temporary_json(dir_fd, target_name, payload, mode)
    try:
        os.link(
            temporary_name,
            target_name,
            src_dir_fd=dir_fd,
            dst_dir_fd=dir_fd,
            follow_symlinks=False,
        )
        os.unlink(temporary_name, dir_fd=dir_fd)
        fsync_directory(dir_fd)
    except BaseException:
        unlink_if_exists(dir_fd, temporary_name)
        raise


def create_exclusive_backup(
    dir_fd: int,
    source_name: str,
    backup_name: str,
    mode: int,
) -> None:
    validate_filename(source_name)
    validate_filename(backup_name)
    descriptor = os.open(
        backup_name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
        dir_fd=dir_fd,
    )
    backup_open = True
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as destination:
            backup_open = False
            source_descriptor = os.open(
                source_name,
                os.O_RDONLY | os.O_NOFOLLOW,
                dir_fd=dir_fd,
            )
            with os.fdopen(source_descriptor, "rb") as source_handle:
                for chunk in iter(lambda: source_handle.read(1024 * 1024), b""):
                    destination.write(chunk)
            destination.flush()
            os.fsync(destination.fileno())
        fsync_directory(dir_fd)
    except BaseException:
        if backup_open:
            os.close(descriptor)
        unlink_if_exists(dir_fd, backup_name)
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
        source_mode = stat.S_IMODE(state_path.stat().st_mode)
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
            backup_name = f"{state_path.name}.v1-backup-{timestamp}"
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
