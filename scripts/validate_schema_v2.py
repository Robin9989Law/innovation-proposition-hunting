#!/usr/bin/env python3
"""Validate the mandatory Schema 2.0 readiness fields."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from validation_common import Issue, choose_exit, render


ACTIVE_TRACKS = {"NOVELTY", "VALIDITY", "COMPUTE"}
NOVELTY_LEVELS = {"N0-1", "N0-2", "N0-3", "N0-4C"}
VALIDITY_LEVELS = {"V0", "V1", "V2", "V3", "V4"}
CLAIM_PROFILES = {"THEORY", "ALGORITHM", "MIXED"}
AUDIT_REQUIRED_LEVELS = {"V3", "V4"}


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("workflow state top level must be an object")
    return payload


def validate_audit(audit: Any, *, present: bool, required: bool) -> list[Issue]:
    issues: list[Issue] = []
    if not isinstance(audit, dict):
        if present or required:
            issues.append(
                Issue(
                    "INVALID_INDEPENDENT_AUDIT",
                    "INVALID",
                    "independent_audit",
                    "missing_or_invalid_object",
                )
            )
        return issues

    capability_present = "capability_available" in audit
    capability = audit.get("capability_available")
    if capability_present and type(capability) is not bool:
        issues.append(
            Issue(
                "INVALID_CAPABILITY_AVAILABLE",
                "INVALID",
                "independent_audit",
                f"capability_available:{capability}",
            )
        )
    if not required:
        return issues

    capability_unavailable = capability is False
    if capability_unavailable:
        issues.append(
            Issue(
                "BLOCKED_CAPABILITY",
                "BLOCKED",
                "independent_audit",
                "independent_reviewer_unavailable",
            )
        )
    authors = audit.get("author_agent_ids")
    reviewer = audit.get("reviewer_agent_id")
    authors_present = "author_agent_ids" in audit
    reviewer_present = "reviewer_agent_id" in audit
    valid_author_items = (
        isinstance(authors, list)
        and bool(authors)
        and all(isinstance(author, str) and author.strip() for author in authors)
    )
    valid_reviewer = isinstance(reviewer, str) and bool(reviewer.strip())
    if (
        authors_present and not valid_author_items
    ) or (not capability_unavailable and not authors_present):
        issues.append(
            Issue(
                "INVALID_AUDIT_AUTHORS",
                "INVALID",
                "independent_audit",
                "author_agent_ids:missing_or_invalid",
            )
        )
    if (
        reviewer_present and not valid_reviewer
    ) or (not capability_unavailable and not reviewer_present):
        issues.append(
            Issue(
                "INVALID_AUDIT_REVIEWER",
                "INVALID",
                "independent_audit",
                "reviewer_agent_id:missing_or_invalid",
            )
        )
    normalized_authors: list[str] = []
    normalized_reviewer: str | None = None
    if valid_author_items:
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


def validate(root: Path, state: dict[str, Any]) -> list[Issue]:
    del root  # Reserved for artifact-aware Schema 2.0 checks.
    if state.get("schema_version") != "2.0":
        return [
            Issue(
                "MIGRATION_REQUIRED",
                "MIGRATION",
                "workflow_state",
                f"found:{state.get('schema_version')}",
            )
        ]

    issues: list[Issue] = []
    enum_fields = (
        ("active_track", ACTIVE_TRACKS, "INVALID_ACTIVE_TRACK"),
        ("novelty_level", NOVELTY_LEVELS, "INVALID_NOVELTY_LEVEL"),
        ("validity_level", VALIDITY_LEVELS, "INVALID_VALIDITY_LEVEL"),
        ("claim_profile", CLAIM_PROFILES, "INVALID_CLAIM_PROFILE"),
    )
    for field, allowed, code in enum_fields:
        value = state.get(field)
        if not isinstance(value, str) or value not in allowed:
            issues.append(
                Issue(code, "INVALID", "workflow_state", f"{field}:{value}")
            )

    epoch = state.get("validation_epoch")
    if isinstance(epoch, bool) or not isinstance(epoch, int) or epoch < 1:
        issues.append(
            Issue(
                "INVALID_VALIDATION_EPOCH",
                "INVALID",
                "workflow_state",
                f"validation_epoch:{epoch}",
            )
        )

    validity_level = state.get("validity_level")
    audit_required = (
        isinstance(validity_level, str) and validity_level in AUDIT_REQUIRED_LEVELS
    )
    issues.extend(
        validate_audit(
            state.get("independent_audit"),
            present="independent_audit" in state,
            required=audit_required,
        )
    )

    return issues


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    root = args.root.resolve()
    state_path = args.state.resolve()
    try:
        state_path.relative_to(root)
        issues = validate(root, load_json(state_path))
    except Exception as error:
        issues = [Issue("VALIDATOR_ERROR", "INVALID", "workflow_state", str(error))]

    print(render("schema_v2", issues, args.json))
    return int(choose_exit(issues))


if __name__ == "__main__":
    raise SystemExit(main())
