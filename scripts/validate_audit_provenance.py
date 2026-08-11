#!/usr/bin/env python3
"""Validate independent-review provenance for an exact artifact bundle."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

from validation_common import (
    Issue,
    ProjectContext,
    choose_exit,
    lexical_relative_cli_path,
    nonempty_string,
    render,
)
from validate_artifact_hashes import valid_sha256


AUDIT_REQUIRED_LEVELS = {"V3", "V4"}


def _validate_identity_fields(audit: dict[str, Any], *, required: bool) -> list[Issue]:
    issues: list[Issue] = []
    authors = audit.get("author_agent_ids")
    reviewer = audit.get("reviewer_agent_id")
    authors_present = "author_agent_ids" in audit
    reviewer_present = "reviewer_agent_id" in audit
    valid_authors = (
        isinstance(authors, list)
        and bool(authors)
        and all(nonempty_string(author) for author in authors)
    )
    valid_reviewer = nonempty_string(reviewer)

    if (authors_present and not valid_authors) or (required and not authors_present):
        issues.append(
            Issue(
                "INVALID_AUDIT_AUTHORS",
                "INVALID",
                "independent_audit",
                "author_agent_ids:missing_or_invalid",
            )
        )
    if (reviewer_present and not valid_reviewer) or (required and not reviewer_present):
        issues.append(
            Issue(
                "INVALID_AUDIT_REVIEWER",
                "INVALID",
                "independent_audit",
                "reviewer_agent_id:missing_or_invalid",
            )
        )

    normalized_authors: list[str] = []
    if valid_authors:
        normalized_authors = [author.strip() for author in authors]
        if normalized_authors != authors:
            issues.append(
                Issue(
                    "NONCANONICAL_AUDIT_ID",
                    "INVALID",
                    "independent_audit",
                    "author_agent_ids:surrounding_whitespace",
                )
            )
        if len(set(normalized_authors)) != len(normalized_authors):
            issues.append(
                Issue(
                    "DUPLICATE_AUTHOR_AGENT_ID",
                    "INVALID",
                    "independent_audit",
                    "author_agent_ids:duplicate",
                )
            )

    normalized_reviewer: str | None = None
    if valid_reviewer:
        normalized_reviewer = reviewer.strip()
        if normalized_reviewer != reviewer:
            issues.append(
                Issue(
                    "NONCANONICAL_AUDIT_ID",
                    "INVALID",
                    "independent_audit",
                    "reviewer_agent_id:surrounding_whitespace",
                )
            )
    if normalized_reviewer is not None and normalized_reviewer in normalized_authors:
        issues.append(
            Issue(
                "AUDITOR_NOT_INDEPENDENT",
                "INVALID",
                "independent_audit",
                f"reviewer_is_author:{normalized_reviewer}",
            )
        )
    return issues


def validate(
    state: dict[str, Any],
    manifest: dict[str, Any],
    audit: dict[str, Any],
) -> list[Issue]:
    validity_level = state.get("validity_level")
    if validity_level not in AUDIT_REQUIRED_LEVELS:
        return []

    issues: list[Issue] = []
    state_audit = state.get("independent_audit")
    if not isinstance(state_audit, dict):
        state_audit = {}
        issues.append(
            Issue(
                "INVALID_INDEPENDENT_AUDIT",
                "INVALID",
                "workflow_state",
                "independent_audit:missing_or_invalid_object",
            )
        )
    if audit.get("schema_version") != "2.0":
        issues.append(
            Issue(
                "INVALID_INDEPENDENT_AUDIT",
                "INVALID",
                "independent_audit",
                f"schema_version:{audit.get('schema_version')}",
            )
        )

    external_capability = audit.get("capability_available")
    state_capability = state_audit.get("capability_available")
    for item_id, capability in (
        ("workflow_state.independent_audit", state_capability),
        ("independent_audit", external_capability),
    ):
        if capability is not None and type(capability) is not bool:
            issues.append(
                Issue(
                    "INVALID_CAPABILITY_AVAILABLE",
                    "INVALID",
                    item_id,
                    f"capability_available:{capability}",
                )
            )
    capability_unavailable = external_capability is False or state_capability is False
    if capability_unavailable:
        issues.append(
            Issue(
                "BLOCKED_CAPABILITY",
                "BLOCKED",
                "independent_audit",
                "independent_reviewer_unavailable",
            )
        )
    issues.extend(_validate_identity_fields(audit, required=not capability_unavailable))

    thread = audit.get("reviewer_thread_id")
    if ("reviewer_thread_id" in audit and not nonempty_string(thread)) or (
        not capability_unavailable and "reviewer_thread_id" not in audit
    ):
        issues.append(
            Issue(
                "INVALID_AUDIT_REVIEWER_THREAD",
                "INVALID",
                "independent_audit",
                "reviewer_thread_id:missing_or_invalid",
            )
        )
    elif nonempty_string(thread) and thread != thread.strip():
        issues.append(
            Issue(
                "NONCANONICAL_AUDIT_ID",
                "INVALID",
                "independent_audit",
                "reviewer_thread_id:surrounding_whitespace",
            )
        )

    verdict = audit.get("verdict")
    if ("verdict" in audit and verdict != "PASS") or (
        not capability_unavailable and "verdict" not in audit
    ):
        issues.append(
            Issue(
                "AUDIT_VERDICT_NOT_PASS",
                "INVALID",
                "independent_audit",
                f"verdict:{verdict}",
            )
        )

    state_epoch = state.get("validation_epoch")
    manifest_epoch = manifest.get("validation_epoch")
    artifact_epoch = audit.get("validation_epoch")
    nested_epoch = state_audit.get("validation_epoch")
    epoch_values = [state_epoch, manifest_epoch]
    if artifact_epoch is not None or not capability_unavailable:
        epoch_values.append(artifact_epoch)
    if nested_epoch is not None:
        epoch_values.append(nested_epoch)
    valid_epochs = all(
        not isinstance(value, bool) and isinstance(value, int) and value >= 1
        for value in epoch_values
    )
    if not valid_epochs or len(set(epoch_values)) != 1:
        issues.append(
            Issue(
                "AUDIT_EPOCH_MISMATCH",
                "INVALID",
                "independent_audit",
                "state:{};manifest:{};state_audit:{};artifact:{}".format(
                    state_epoch, manifest_epoch, nested_epoch, artifact_epoch
                ),
            )
        )

    state_bundle = state.get("claim_bundle_sha256")
    manifest_bundle = manifest.get("claim_bundle_sha256")
    artifact_bundle = audit.get("audited_bundle_sha256")
    nested_bundle = state_audit.get("audited_bundle_sha256")
    bundle_values = [state_bundle, manifest_bundle]
    if artifact_bundle is not None or not capability_unavailable:
        bundle_values.append(artifact_bundle)
    if nested_bundle is not None:
        bundle_values.append(nested_bundle)
    valid_bundles = all(valid_sha256(value) for value in bundle_values)
    if not valid_bundles or len(set(bundle_values)) != 1:
        issues.append(
            Issue(
                "AUDIT_BUNDLE_MISMATCH",
                "INVALID",
                "independent_audit",
                "state:{};manifest:{};state_audit:{};artifact:{}".format(
                    state_bundle, manifest_bundle, nested_bundle, artifact_bundle
                ),
            )
        )
    return issues


def validate_with_context(
    ctx: ProjectContext,
    *,
    manifest_path: str | None = None,
    audit_path: str | None = None,
) -> list[Issue]:
    """库入口：state 复用 ctx.state，manifest/audit 经 ctx.load_json
    缓存解析。两个路径参数为相对路径覆盖（CLI 覆盖参数由此传入）；
    缺省按 state["artifacts"] 解析。audit 缺失且能力声明不可用时的
    合成回退逻辑与原 CLI 一致。"""

    manifest_relative = manifest_path or ctx.artifact_relative_path("audit_manifest")
    audit_relative = audit_path or ctx.artifact_relative_path("independent_audit")
    manifest = ctx.load_json(manifest_relative, "audit_manifest")
    try:
        audit = ctx.load_json(audit_relative, "independent_audit")
    except FileNotFoundError:
        state_audit = ctx.state.get("independent_audit")
        if not (
            isinstance(state_audit, dict)
            and state_audit.get("capability_available") is False
        ):
            raise
        audit = {"schema_version": "2.0", "capability_available": False}
    return validate(ctx.state, manifest, audit)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--audit", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    root = Path(os.path.abspath(args.root))
    try:
        with ProjectContext(root, args.state) as ctx:
            manifest_relative = lexical_relative_cli_path(
                root,
                args.manifest or root / "audit_manifest.json",
                "manifest",
            )
            audit_relative = lexical_relative_cli_path(
                root,
                args.audit or root / "independent_audit.json",
                "audit",
            )
            issues = validate_with_context(
                ctx,
                manifest_path=manifest_relative,
                audit_path=audit_relative,
            )
    except Exception as error:
        # ctx.load_json 的 os.stat 用绝对路径，OSError 文本需剥掉 root 前缀；
        # ctx 内部以 label "state" 抛 TypeError，历史输出用 "workflow_state"。
        detail = str(error).replace(f"{root}/", "")
        if detail.startswith("state:top_level_not_object"):
            detail = "workflow_state:" + detail[len("state:"):]
        issues = [Issue("VALIDATOR_ERROR", "INVALID", "audit_provenance", detail)]

    print(render("audit_provenance", issues, args.json))
    return int(choose_exit(issues))


if __name__ == "__main__":
    raise SystemExit(main())
