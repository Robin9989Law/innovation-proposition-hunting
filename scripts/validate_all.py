#!/usr/bin/env python3
"""Run the required validators for the workflow's current state."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from validation_common import ExitCode, Issue, choose_exit, render
from validate_schema_v2 import validate as validate_schema_v2


EVIDENCE_REQUIRED_STATES = {
    "EVIDENCE_VALIDATE",
    "LAYER_DECISION",
    "N0_AUDIT",
    "COMPUTE",
    "COMPLETE",
}
LITERATURE_REQUIRED_STATES = {
    "IMPORTANT_FULLTEXT",
    "SOURCE_CLAIM_REGISTER",
    "SYNTHESIZE_COLLISION",
    "OUTPUT_CLAIM_BIND",
    *EVIDENCE_REQUIRED_STATES,
}


def load_state(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("workflow state top level must be an object")
    return payload


def run(label: str, command: list[str]) -> int:
    print(f"=== {label} ===", flush=True)
    completed = subprocess.run(command, check=False)
    print(f"{label}_exit={completed.returncode}")
    return completed.returncode


def issue_for_exit(label: str, exit_code: int) -> Issue | None:
    if exit_code == ExitCode.READY:
        return None
    severity = {
        ExitCode.INVALID: "INVALID",
        ExitCode.BLOCKED: "BLOCKED",
        ExitCode.MIGRATION_REQUIRED: "MIGRATION",
    }.get(exit_code, "INVALID")
    code = (
        "VALIDATOR_ERROR"
        if exit_code not in set(ExitCode)
        else f"{label.upper()}_FAILED"
    )
    return Issue(code, severity, label, f"exit_code:{exit_code}")


def require_within_root(root: Path, path: Path, label: str) -> None:
    try:
        path.relative_to(root)
    except ValueError as error:
        raise ValueError(f"{label}:outside_root:{path}") from error


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--current-year", type=int, default=datetime.now().year)
    parser.add_argument("--literature-registry", type=Path)
    parser.add_argument("--claim-registry", type=Path)
    parser.add_argument("--output-support", type=Path)
    args = parser.parse_args()

    root = args.root.resolve()
    state_path = args.state.resolve()
    script_dir = Path(__file__).resolve().parent
    literature = (
        args.literature_registry.resolve()
        if args.literature_registry
        else root / "near_neighbor_registry.json"
    )
    claims = (
        args.claim_registry.resolve()
        if args.claim_registry
        else root / "literature_claim_registry.json"
    )
    outputs = (
        args.output_support.resolve()
        if args.output_support
        else root / "output_claim_support.json"
    )

    try:
        if not root.is_dir():
            raise ValueError(f"root:not_directory:{root}")
        for label, path in (
            ("state", state_path),
            ("literature_registry", literature),
            ("claim_registry", claims),
            ("output_support", outputs),
        ):
            require_within_root(root, path, label)
        state = load_state(state_path)
    except Exception as error:
        issues = [Issue("VALIDATOR_ERROR", "INVALID", "workflow_state", str(error))]
        print(render("validation_suite", issues))
        return int(choose_exit(issues))

    try:
        suite_issues = validate_schema_v2(root, state)
    except Exception as error:
        suite_issues = [
            Issue("VALIDATOR_ERROR", "INVALID", "workflow_state", str(error))
        ]
    print("=== schema_v2 ===")
    print(render("schema_v2", suite_issues))
    if choose_exit(suite_issues) == ExitCode.MIGRATION_REQUIRED:
        print(render("validation_suite", suite_issues))
        return int(ExitCode.MIGRATION_REQUIRED)

    workflow_exit = run(
        "workflow_state",
        [
            sys.executable,
            str(script_dir / "validate_workflow_state.py"),
            "--root",
            str(root),
            "--state",
            str(state_path),
            "--current-year",
            str(args.current_year),
        ],
    )
    workflow_issue = issue_for_exit("workflow_state", workflow_exit)
    if workflow_issue:
        suite_issues.append(workflow_issue)

    active_state = state.get("active_state")
    effective_state = (
        state.get("resume_state") if active_state == "BLOCKED" else active_state
    )
    dispatch_state = effective_state if isinstance(effective_state, str) else ""
    gates = state.get("gates") if isinstance(state.get("gates"), dict) else {}

    run_literature = (
        literature.is_file()
        or bool(gates.get("literature_registry_valid"))
        or dispatch_state in LITERATURE_REQUIRED_STATES
    )
    evidence_paths = (literature, claims, outputs)
    run_evidence = (
        any(path.exists() for path in evidence_paths)
        or bool(gates.get("evidence_validated"))
        or dispatch_state in EVIDENCE_REQUIRED_STATES
    )

    if run_literature:
        if not literature.is_file():
            print(f"LITERATURE_REQUIRED\tmissing:{literature}")
            suite_issues.append(
                Issue(
                    "LITERATURE_REQUIRED",
                    "INVALID",
                    "literature_registry",
                    str(literature),
                )
            )
        else:
            literature_exit = run(
                "literature_registry",
                [
                    sys.executable,
                    str(script_dir / "validate_literature_registry.py"),
                    "--root",
                    str(root),
                    "--registry",
                    str(literature),
                    "--read-only",
                ],
            )
            literature_issue = issue_for_exit("literature_registry", literature_exit)
            if literature_issue:
                suite_issues.append(literature_issue)
    else:
        print("=== literature_registry ===")
        print(f"SKIP\tnot_required_at_state:{effective_state}")

    if run_evidence:
        missing = [str(path) for path in evidence_paths if not path.is_file()]
        if missing:
            for path in missing:
                print(f"EVIDENCE_REQUIRED\tmissing:{path}")
                suite_issues.append(
                    Issue("EVIDENCE_REQUIRED", "INVALID", "evidence_chain", path)
                )
        else:
            evidence_exit = run(
                "evidence_chain",
                [
                    sys.executable,
                    str(script_dir / "validate_evidence_chain.py"),
                    "--root",
                    str(root),
                    "--literature-registry",
                    str(literature),
                    "--claim-registry",
                    str(claims),
                    "--output-support",
                    str(outputs),
                    "--current-year",
                    str(args.current_year),
                ],
            )
            evidence_issue = issue_for_exit("evidence_chain", evidence_exit)
            if evidence_issue:
                suite_issues.append(evidence_issue)
    else:
        print("=== evidence_chain ===")
        print(f"SKIP\tnot_required_at_state:{effective_state}")

    print(render("validation_suite", suite_issues))
    return int(choose_exit(suite_issues))


if __name__ == "__main__":
    raise SystemExit(main())
