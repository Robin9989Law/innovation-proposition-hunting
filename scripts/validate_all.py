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
CLAIM_INVENTORY_REQUIRED_STATES = {
    "CLAIM_FREEZE",
    "VALIDITY_AUDIT",
    "INDEPENDENT_REVIEW",
    "DIRECTION_LOCK",
    "COMPUTE",
    "POSTCOMPUTE_CLAIM_FREEZE",
    "FINAL_VALIDITY_AUDIT",
    "FINAL_LOCK",
    "COMPLETE",
}
THEORY_OBLIGATION_REQUIRED_STATES = {
    "VALIDITY_AUDIT",
    "INDEPENDENT_REVIEW",
    "DIRECTION_LOCK",
    "COMPUTE",
    "POSTCOMPUTE_CLAIM_FREEZE",
    "FINAL_VALIDITY_AUDIT",
    "FINAL_LOCK",
    "COMPLETE",
}
THEORY_PROFILES = {"THEORY", "MIXED"}
ALGORITHM_PROFILES = {"ALGORITHM", "MIXED"}
ALGORITHM_CONTRACT_REQUIRED_STATES = {
    "VALIDITY_AUDIT",
    "INDEPENDENT_REVIEW",
    "DIRECTION_LOCK",
    "COMPUTE",
    "POSTCOMPUTE_CLAIM_FREEZE",
    "FINAL_VALIDITY_AUDIT",
    "FINAL_LOCK",
    "COMPLETE",
}
AUDIT_REQUIRED_LEVELS = {"V3", "V4"}


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
    parser.add_argument("--claim-inventory", type=Path)
    parser.add_argument("--theory-obligations", type=Path)
    parser.add_argument("--protocol-contract", type=Path)
    parser.add_argument("--baseline-budget", type=Path)
    parser.add_argument("--claim-code-trace", type=Path)
    parser.add_argument("--audit-manifest", type=Path)
    parser.add_argument("--independent-audit", type=Path)
    args = parser.parse_args()

    root = args.root.resolve()
    state_path = args.state.resolve()
    script_dir = Path(__file__).resolve().parent
    literature = (
        args.literature_registry.resolve()
        if args.literature_registry
        else (root / "near_neighbor_registry.json").resolve()
    )
    claims = (
        args.claim_registry.resolve()
        if args.claim_registry
        else (root / "literature_claim_registry.json").resolve()
    )
    outputs = (
        args.output_support.resolve()
        if args.output_support
        else (root / "output_claim_support.json").resolve()
    )
    inventory = (
        args.claim_inventory.resolve()
        if args.claim_inventory
        else (root / "claim_inventory.json").resolve()
    )
    theory_obligations = (
        args.theory_obligations.absolute()
        if args.theory_obligations
        else root / "theory_obligation_registry.json"
    )
    protocol_contract = (
        args.protocol_contract.absolute()
        if args.protocol_contract
        else root / "protocol_contract.json"
    )
    baseline_budget = (
        args.baseline_budget.absolute()
        if args.baseline_budget
        else root / "baseline_budget.json"
    )
    claim_code_trace = (
        args.claim_code_trace.absolute()
        if args.claim_code_trace
        else root / "claim_code_trace.json"
    )
    audit_manifest = (
        args.audit_manifest.absolute()
        if args.audit_manifest
        else root / "audit_manifest.json"
    )
    independent_audit = (
        args.independent_audit.absolute()
        if args.independent_audit
        else root / "independent_audit.json"
    )

    try:
        if not root.is_dir():
            raise ValueError(f"root:not_directory:{root}")
        for label, path in (
            ("state", state_path),
            ("literature_registry", literature),
            ("claim_registry", claims),
            ("output_support", outputs),
            ("claim_inventory", inventory),
            ("theory_obligations", theory_obligations),
            ("protocol_contract", protocol_contract),
            ("baseline_budget", baseline_budget),
            ("claim_code_trace", claim_code_trace),
            ("audit_manifest", audit_manifest),
            ("independent_audit", independent_audit),
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

    audit_required = state.get("validity_level") in AUDIT_REQUIRED_LEVELS
    if audit_required:
        state_audit = state.get("independent_audit")
        capability_unavailable = (
            isinstance(state_audit, dict)
            and state_audit.get("capability_available") is False
        )
        if capability_unavailable:
            print("=== artifact_hashes ===")
            print("SKIP\tindependent_reviewer_capability_unavailable")
        else:
            artifact_exit = run(
                "artifact_hashes",
                [
                    sys.executable,
                    str(script_dir / "validate_artifact_hashes.py"),
                    "--root",
                    str(root),
                    "--state",
                    str(state_path),
                    "--manifest",
                    str(audit_manifest),
                ],
            )
            artifact_issue = issue_for_exit("artifact_hashes", artifact_exit)
            if artifact_issue:
                suite_issues.append(artifact_issue)

        audit_exit = run(
            "audit_provenance",
            [
                sys.executable,
                str(script_dir / "validate_audit_provenance.py"),
                "--root",
                str(root),
                "--state",
                str(state_path),
                "--manifest",
                str(audit_manifest),
                "--audit",
                str(independent_audit),
            ],
        )
        audit_issue = issue_for_exit("audit_provenance", audit_exit)
        if audit_issue:
            suite_issues.append(audit_issue)
    else:
        print("=== artifact_hashes ===")
        print(f"SKIP\tnot_required_at_validity:{state.get('validity_level')}")
        print("=== audit_provenance ===")
        print(f"SKIP\tnot_required_at_validity:{state.get('validity_level')}")

    active_state = state.get("active_state")
    effective_state = (
        state.get("resume_state") if active_state == "BLOCKED" else active_state
    )
    dispatch_state = effective_state if isinstance(effective_state, str) else ""
    gates = state.get("gates") if isinstance(state.get("gates"), dict) else {}

    run_claim_inventory = (
        inventory.exists() or dispatch_state in CLAIM_INVENTORY_REQUIRED_STATES
    )
    if run_claim_inventory:
        if not inventory.is_file():
            print(f"CLAIM_INVENTORY_REQUIRED\tmissing:{inventory}")
            suite_issues.append(
                Issue(
                    "CLAIM_INVENTORY_REQUIRED",
                    "INVALID",
                    "claim_inventory",
                    str(inventory),
                )
            )
        else:
            inventory_exit = run(
                "claim_inventory",
                [
                    sys.executable,
                    str(script_dir / "validate_claim_inventory.py"),
                    "--root",
                    str(root),
                    "--state",
                    str(state_path),
                    "--inventory",
                    str(inventory),
                ],
            )
            inventory_issue = issue_for_exit("claim_inventory", inventory_exit)
            if inventory_issue:
                suite_issues.append(inventory_issue)
    else:
        print("=== claim_inventory ===")
        print(f"SKIP\tnot_required_at_state:{effective_state}")

    claim_profile = state.get("claim_profile")
    theory_required = (
        isinstance(claim_profile, str)
        and claim_profile in THEORY_PROFILES
        and dispatch_state in THEORY_OBLIGATION_REQUIRED_STATES
    )
    run_theory_obligations = theory_obligations.exists() or theory_required
    if run_theory_obligations:
        if not theory_obligations.is_file():
            print(
                "THEORY_OBLIGATION_REGISTRY_REQUIRED"
                f"\tmissing:{theory_obligations}"
            )
            suite_issues.append(
                Issue(
                    "THEORY_OBLIGATION_REGISTRY_REQUIRED",
                    "INVALID",
                    "theory_obligation_registry",
                    str(theory_obligations),
                )
            )
        else:
            theory_exit = run(
                "theory_obligations",
                [
                    sys.executable,
                    str(script_dir / "validate_theory_obligations.py"),
                    "--root",
                    str(root),
                    "--state",
                    str(state_path),
                    "--inventory",
                    str(inventory),
                    "--registry",
                    str(theory_obligations),
                ],
            )
            theory_issue = issue_for_exit("theory_obligations", theory_exit)
            if theory_issue:
                suite_issues.append(theory_issue)
    else:
        print("=== theory_obligations ===")
        print(f"SKIP\tnot_required_at_state:{effective_state}")

    algorithm_profile = (
        isinstance(claim_profile, str) and claim_profile in ALGORITHM_PROFILES
    )
    algorithm_required = (
        algorithm_profile and dispatch_state in ALGORITHM_CONTRACT_REQUIRED_STATES
    )
    run_algorithm_contracts = algorithm_profile and (
        algorithm_required
        or protocol_contract.exists()
        or claim_code_trace.exists()
        or baseline_budget.exists()
    )
    if run_algorithm_contracts:
        if not protocol_contract.is_file():
            if algorithm_required:
                print(f"PROTOCOL_CONTRACT_REQUIRED\tmissing:{protocol_contract}")
                suite_issues.append(
                    Issue(
                        "PROTOCOL_CONTRACT_REQUIRED",
                        "INVALID",
                        "protocol_contract",
                        str(protocol_contract),
                    )
                )
            elif baseline_budget.exists():
                baseline_exit = run(
                    "baseline_budget",
                    [
                        sys.executable,
                        str(script_dir / "validate_protocol_contract.py"),
                        "--root",
                        str(root),
                        "--state",
                        str(state_path),
                        "--inventory",
                        str(inventory),
                        "--baseline-budget",
                        str(baseline_budget),
                        "--baseline-only",
                    ],
                )
                baseline_issue = issue_for_exit("baseline_budget", baseline_exit)
                if baseline_issue:
                    suite_issues.append(baseline_issue)
        else:
            protocol_exit = run(
                "protocol_contract",
                [
                    sys.executable,
                    str(script_dir / "validate_protocol_contract.py"),
                    "--root",
                    str(root),
                    "--state",
                    str(state_path),
                    "--inventory",
                    str(inventory),
                    "--protocol",
                    str(protocol_contract),
                    "--baseline-budget",
                    str(baseline_budget),
                    "--claim-code-trace",
                    str(claim_code_trace),
                ],
            )
            protocol_issue = issue_for_exit("protocol_contract", protocol_exit)
            if protocol_issue:
                suite_issues.append(protocol_issue)

        if not claim_code_trace.is_file():
            if algorithm_required:
                print(f"CLAIM_CODE_TRACE_REQUIRED\tmissing:{claim_code_trace}")
                suite_issues.append(
                    Issue(
                        "CLAIM_CODE_TRACE_REQUIRED",
                        "INVALID",
                        "claim_code_trace",
                        str(claim_code_trace),
                    )
                )
        else:
            trace_exit = run(
                "claim_code_trace",
                [
                    sys.executable,
                    str(script_dir / "validate_claim_code_trace.py"),
                    "--root",
                    str(root),
                    "--state",
                    str(state_path),
                    "--inventory",
                    str(inventory),
                    "--trace",
                    str(claim_code_trace),
                    "--protocol",
                    str(protocol_contract),
                ],
            )
            trace_issue = issue_for_exit("claim_code_trace", trace_exit)
            if trace_issue:
                suite_issues.append(trace_issue)
    else:
        print("=== protocol_contract ===")
        print(f"SKIP\tnot_required_for_profile_or_state:{claim_profile}:{effective_state}")
        print("=== claim_code_trace ===")
        print(f"SKIP\tnot_required_for_profile_or_state:{claim_profile}:{effective_state}")

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
