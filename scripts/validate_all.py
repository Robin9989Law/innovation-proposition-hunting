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

    failures = 0
    failures += bool(
        run(
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
    )
    if failures:
        print("validation_suite_failures=1")
        return 1

    state = load_state(state_path)
    active_state = state.get("active_state")
    effective_state = (
        state.get("resume_state") if active_state == "BLOCKED" else active_state
    )
    gates = state.get("gates") if isinstance(state.get("gates"), dict) else {}

    run_literature = bool(gates.get("literature_registry_valid")) or (
        effective_state in LITERATURE_REQUIRED_STATES
    )
    run_evidence = bool(gates.get("evidence_validated")) or (
        effective_state in EVIDENCE_REQUIRED_STATES
    )

    if run_literature:
        if not literature.is_file():
            print(f"LITERATURE_REQUIRED\tmissing:{literature}")
            failures += 1
        else:
            failures += bool(
                run(
                    "literature_registry",
                    [
                        sys.executable,
                        str(script_dir / "validate_literature_registry.py"),
                        "--root",
                        str(root),
                        "--registry",
                        str(literature),
                    ],
                )
            )
    else:
        print("=== literature_registry ===")
        print(f"SKIP\tnot_required_at_state:{effective_state}")

    if run_evidence:
        missing = [
            str(path)
            for path in (literature, claims, outputs)
            if not path.is_file()
        ]
        if missing:
            for path in missing:
                print(f"EVIDENCE_REQUIRED\tmissing:{path}")
            failures += 1
        else:
            failures += bool(
                run(
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
            )
    else:
        print("=== evidence_chain ===")
        print(f"SKIP\tnot_required_at_state:{effective_state}")

    print(f"validation_suite_failures={failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
