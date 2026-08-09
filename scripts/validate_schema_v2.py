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
        if state.get(field) not in allowed:
            issues.append(
                Issue(code, "INVALID", "workflow_state", f"{field}:{state.get(field)}")
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

    if state.get("validity_level") in AUDIT_REQUIRED_LEVELS:
        audit = state.get("independent_audit")
        if not isinstance(audit, dict):
            issues.append(
                Issue(
                    "INVALID_INDEPENDENT_AUDIT",
                    "INVALID",
                    "independent_audit",
                    "missing_object",
                )
            )
        elif audit.get("capability_available") is False:
            issues.append(
                Issue(
                    "BLOCKED_CAPABILITY",
                    "BLOCKED",
                    "independent_audit",
                    "independent_reviewer_unavailable",
                )
            )
        else:
            authors = audit.get("author_agent_ids")
            reviewer = audit.get("reviewer_agent_id")
            valid_authors = (
                isinstance(authors, list)
                and bool(authors)
                and all(isinstance(author, str) and author.strip() for author in authors)
            )
            if not valid_authors:
                issues.append(
                    Issue(
                        "INVALID_AUDIT_AUTHORS",
                        "INVALID",
                        "independent_audit",
                        "author_agent_ids:missing_or_invalid",
                    )
                )
            if not isinstance(reviewer, str) or not reviewer.strip():
                issues.append(
                    Issue(
                        "INVALID_AUDIT_REVIEWER",
                        "INVALID",
                        "independent_audit",
                        "reviewer_agent_id:missing_or_invalid",
                    )
                )
            elif valid_authors and reviewer in authors:
                issues.append(
                    Issue(
                        "AUDITOR_NOT_INDEPENDENT",
                        "INVALID",
                        "independent_audit",
                        f"reviewer_is_author:{reviewer}",
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
    except (OSError, ValueError, json.JSONDecodeError) as error:
        issues = [Issue("VALIDATOR_ERROR", "INVALID", "workflow_state", str(error))]

    print(render("schema_v2", issues, args.json))
    return int(choose_exit(issues))


if __name__ == "__main__":
    raise SystemExit(main())
