#!/usr/bin/env python3
"""Validate the exact, canonical bundle recorded by an audit manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Callable

from validation_common import (
    Issue,
    ProjectContext,
    SafeFileSnapshot,
    UnsafePathError,
    canonical_relative_path,
    choose_exit,
    lexical_relative_cli_path,
    nonempty_string,
    read_regular_file_at,
    render,
)


SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
ROLE_PATTERN = re.compile(r"[A-Z][A-Z0-9_]*\Z", re.ASCII)


def valid_sha256(value: Any) -> bool:
    return isinstance(value, str) and SHA256_PATTERN.fullmatch(value) is not None


def bundle_sha256(entries: list[dict[str, str]]) -> str:
    normalized = [
        {"path": item["path"], "role": item["role"], "sha256": item["sha256"]}
        for item in sorted(entries, key=lambda value: value["path"])
    ]
    raw = json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _validate_bundle(
    read: Callable[[str], SafeFileSnapshot],
    state: dict[str, Any],
    manifest: dict[str, Any],
) -> list[Issue]:
    # read：按 manifest 相对路径取当前文件快照（哈希）；库入口传
    # ctx.snapshot 以复用缓存，CLI 包装传 read_regular_file_at。
    issues: list[Issue] = []
    if manifest.get("schema_version") != "2.0":
        issues.append(
            Issue(
                "INVALID_AUDIT_MANIFEST_SCHEMA",
                "INVALID",
                "audit_manifest",
                f"schema_version:{manifest.get('schema_version')}",
            )
        )

    state_epoch = state.get("validation_epoch")
    manifest_epoch = manifest.get("validation_epoch")
    if (
        isinstance(state_epoch, bool)
        or not isinstance(state_epoch, int)
        or state_epoch < 1
        or isinstance(manifest_epoch, bool)
        or not isinstance(manifest_epoch, int)
        or manifest_epoch < 1
        or manifest_epoch != state_epoch
    ):
        issues.append(
            Issue(
                "AUDIT_EPOCH_MISMATCH",
                "INVALID",
                "audit_manifest",
                f"state:{state_epoch};manifest:{manifest_epoch}",
            )
        )

    entries = manifest.get("entries")
    if not isinstance(entries, list) or not entries:
        issues.append(
            Issue(
                "INVALID_AUDIT_MANIFEST_ENTRIES",
                "INVALID",
                "audit_manifest",
                "entries:missing_or_empty_list",
            )
        )
        entries = []

    current_entries: list[dict[str, str]] = []
    seen_paths: set[str] = set()
    for index, entry in enumerate(entries):
        item_id = f"audit_manifest.entries[{index}]"
        if not isinstance(entry, dict):
            issues.append(
                Issue("INVALID_MANIFEST_ENTRY", "INVALID", item_id, "not_an_object")
            )
            continue
        raw_path = entry.get("path")
        role = entry.get("role")
        declared_hash = entry.get("sha256")
        entry_valid = True

        if not canonical_relative_path(raw_path):
            issues.append(
                Issue(
                    "UNSAFE_ARTIFACT_PATH",
                    "INVALID",
                    item_id,
                    f"path:{raw_path}",
                )
            )
            entry_valid = False
        elif raw_path in seen_paths:
            issues.append(
                Issue(
                    "DUPLICATE_MANIFEST_PATH",
                    "INVALID",
                    item_id,
                    f"path:{raw_path}",
                )
            )
            entry_valid = False
        else:
            seen_paths.add(raw_path)

        if (
            not nonempty_string(role)
            or role != role.strip()
            or ROLE_PATTERN.fullmatch(role) is None
        ):
            issues.append(
                Issue(
                    "INVALID_MANIFEST_ROLE",
                    "INVALID",
                    item_id,
                    f"role:{role}",
                )
            )
            entry_valid = False
        if not valid_sha256(declared_hash):
            issues.append(
                Issue(
                    "INVALID_ARTIFACT_SHA256",
                    "INVALID",
                    item_id,
                    f"sha256:{declared_hash}",
                )
            )
            entry_valid = False
        if not entry_valid:
            continue

        try:
            snapshot = read(raw_path)
        except FileNotFoundError:
            issues.append(
                Issue(
                    "MISSING_ARTIFACT",
                    "INVALID",
                    raw_path,
                    "manifest_path_missing",
                )
            )
            continue
        except (OSError, UnsafePathError) as error:
            issues.append(
                Issue(
                    "UNSAFE_ARTIFACT_PATH",
                    "INVALID",
                    raw_path,
                    str(error),
                )
            )
            continue

        current_entries.append(
            {"path": raw_path, "role": role, "sha256": snapshot.sha256}
        )
        if snapshot.sha256 != declared_hash:
            issues.append(
                Issue(
                    "STALE_AUDIT",
                    "INVALID",
                    raw_path,
                    f"declared:{declared_hash};current:{snapshot.sha256}",
                )
            )

    state_bundle = state.get("claim_bundle_sha256")
    manifest_bundle = manifest.get("claim_bundle_sha256")
    if not valid_sha256(state_bundle):
        issues.append(
            Issue(
                "INVALID_CLAIM_BUNDLE_SHA256",
                "INVALID",
                "workflow_state",
                f"claim_bundle_sha256:{state_bundle}",
            )
        )
    if not valid_sha256(manifest_bundle):
        issues.append(
            Issue(
                "INVALID_CLAIM_BUNDLE_SHA256",
                "INVALID",
                "audit_manifest",
                f"claim_bundle_sha256:{manifest_bundle}",
            )
        )

    if len(current_entries) == len(entries) and entries:
        computed_bundle = bundle_sha256(current_entries)
        if valid_sha256(manifest_bundle) and computed_bundle != manifest_bundle:
            issues.append(
                Issue(
                    "AUDIT_BUNDLE_MISMATCH",
                    "INVALID",
                    "audit_manifest",
                    f"manifest:{manifest_bundle};current:{computed_bundle}",
                )
            )
        if valid_sha256(state_bundle) and computed_bundle != state_bundle:
            issues.append(
                Issue(
                    "AUDIT_BUNDLE_MISMATCH",
                    "INVALID",
                    "workflow_state",
                    f"state:{state_bundle};current:{computed_bundle}",
                )
            )
    elif (
        valid_sha256(state_bundle)
        and valid_sha256(manifest_bundle)
        and state_bundle != manifest_bundle
    ):
        issues.append(
            Issue(
                "AUDIT_BUNDLE_MISMATCH",
                "INVALID",
                "audit_manifest",
                f"state:{state_bundle};manifest:{manifest_bundle}",
            )
        )
    return issues


def validate(
    root_fd: int,
    state: dict[str, Any],
    manifest: dict[str, Any],
) -> list[Issue]:
    """兼容包装：逐条目现场哈希（无缓存），保持原模块 API。"""

    return _validate_bundle(
        lambda raw_path: read_regular_file_at(root_fd, raw_path), state, manifest
    )


def validate_with_context(
    ctx: ProjectContext, *, manifest_path: str | None = None
) -> list[Issue]:
    """库入口：state 复用 ctx.state，manifest 经 ctx.load_json 缓存解析，
    条目哈希核验走 ctx.snapshot 缓存。manifest_path 为相对路径覆盖
    （CLI 覆盖参数由此传入）；缺省按 state["artifacts"] 解析。"""

    relative = manifest_path or ctx.artifact_relative_path("audit_manifest")
    manifest = ctx.load_json(relative, "audit_manifest")
    return _validate_bundle(ctx.snapshot, ctx.state, manifest)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    root = Path(os.path.abspath(args.root))
    try:
        with ProjectContext(root, args.state) as ctx:
            manifest_relative = lexical_relative_cli_path(
                root, args.manifest or root / "audit_manifest.json", "manifest"
            )
            issues = validate_with_context(ctx, manifest_path=manifest_relative)
    except Exception as error:
        # ctx.load_json 的 os.stat 用绝对路径，OSError 文本需剥掉 root 前缀；
        # ctx 内部以 label "state" 抛 TypeError，历史输出用 "workflow_state"。
        detail = str(error).replace(f"{root}/", "")
        if detail.startswith("state:top_level_not_object"):
            detail = "workflow_state:" + detail[len("state:"):]
        issues = [Issue("VALIDATOR_ERROR", "INVALID", "artifact_hashes", detail)]

    print(render("artifact_hashes", issues, args.json))
    return int(choose_exit(issues))


if __name__ == "__main__":
    raise SystemExit(main())
