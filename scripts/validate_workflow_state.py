#!/usr/bin/env python3
"""Validate the executable state machine for innovation-proposition-hunting."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any


STATES = {
    "BOOT",
    "SCOPE_LOCK",
    "PRIOR_CLAIM_DRAIN",
    "RECENT_FRONTIER",
    "LITERATURE_REGISTER",
    "IMPORTANT_FULLTEXT",
    "SOURCE_CLAIM_REGISTER",
    "SYNTHESIZE_COLLISION",
    "OUTPUT_CLAIM_BIND",
    "EVIDENCE_VALIDATE",
    "LAYER_DECISION",
    "N0_AUDIT",
    "COMPUTE",
    "BLOCKED",
    "COMPLETE",
}
RESUMABLE_STATES = STATES - {"BLOCKED", "COMPLETE"}
OUTPUT_TYPES = {
    "UNRESOLVED",
    "DOCTORAL_DISSERTATION",
    "JOURNAL_ARTICLE",
}
CONTRACTS = {
    "UNRESOLVED",
    "THREE_ORGANIC_A_B_C",
    "ONE_MAIN_M",
}
LAYERS = {"UNRESOLVED", "L1", "L2", "ARCHITECTURE", "L3"}
CONTRIBUTIONS = {"NONE", "M", "A", "B", "C"}
SEARCH_MODES = {"SEARCH_OPEN", "SYNTHESIS_LOCK", "EXCEPTION_REOPEN"}
COMPUTE_STAGES = {"NOT_STARTED", "S0", "S1", "S2", "S3", "S4", "STOPPED"}
SNAPSHOT_MODES = {"NOT_SET", "NEW_SEARCH", "REUSED_VERIFIED_SNAPSHOT"}
GATE_KEYS = {
    "scope_locked",
    "prior_claims_drained",
    "recent_frontier_complete",
    "literature_registry_valid",
    "important_fulltext_complete",
    "source_claims_complete",
    "output_claims_traced",
    "evidence_validated",
    "l1_frozen",
    "l2_frozen",
    "architecture_frozen",
    "n0_4_locked",
    "compute_authorized",
}

STATE_PREREQUISITES = {
    "BOOT": (),
    "SCOPE_LOCK": (),
    "PRIOR_CLAIM_DRAIN": ("scope_locked",),
    "RECENT_FRONTIER": ("scope_locked", "prior_claims_drained"),
    "LITERATURE_REGISTER": (
        "scope_locked",
        "prior_claims_drained",
        "recent_frontier_complete",
    ),
    "IMPORTANT_FULLTEXT": (
        "scope_locked",
        "prior_claims_drained",
        "recent_frontier_complete",
        "literature_registry_valid",
    ),
    "SOURCE_CLAIM_REGISTER": (
        "scope_locked",
        "prior_claims_drained",
        "recent_frontier_complete",
        "literature_registry_valid",
        "important_fulltext_complete",
    ),
    "SYNTHESIZE_COLLISION": (
        "scope_locked",
        "prior_claims_drained",
        "recent_frontier_complete",
        "literature_registry_valid",
        "important_fulltext_complete",
        "source_claims_complete",
    ),
    "OUTPUT_CLAIM_BIND": (
        "scope_locked",
        "prior_claims_drained",
        "recent_frontier_complete",
        "literature_registry_valid",
        "important_fulltext_complete",
        "source_claims_complete",
    ),
    "EVIDENCE_VALIDATE": (
        "scope_locked",
        "prior_claims_drained",
        "recent_frontier_complete",
        "literature_registry_valid",
        "important_fulltext_complete",
        "source_claims_complete",
        "output_claims_traced",
    ),
    "LAYER_DECISION": ("scope_locked", "evidence_validated"),
    "N0_AUDIT": (
        "scope_locked",
        "evidence_validated",
        "l1_frozen",
        "l2_frozen",
        "architecture_frozen",
    ),
    "COMPUTE": (
        "scope_locked",
        "evidence_validated",
        "l1_frozen",
        "l2_frozen",
        "architecture_frozen",
        "n0_4_locked",
        "compute_authorized",
    ),
    "COMPLETE": ("scope_locked", "evidence_validated"),
}

GATE_ARTIFACTS = {
    "scope_locked": ("scope_lock", "hierarchy_status"),
    "literature_registry_valid": ("literature_registry",),
    "important_fulltext_complete": ("literature_archive",),
    "source_claims_complete": ("claim_registry",),
    "output_claims_traced": ("output_support",),
    "evidence_validated": (
        "literature_registry",
        "claim_registry",
        "output_support",
        "validation_log",
    ),
    "l1_frozen": ("l1_card",),
    "l2_frozen": ("l2_card",),
    "architecture_frozen": ("contribution_architecture",),
    "n0_4_locked": ("hierarchy_novelty_audit",),
}


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("workflow state top level must be an object")
    return payload


def nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def add(errors: list[str], code: str, detail: str) -> None:
    errors.append(f"{code}\t{detail}")


def resolve_artifact(root: Path, raw_path: Any) -> Path | None:
    if not nonempty(raw_path):
        return None
    path = (root / str(raw_path)).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return None
    return path


def validate(
    root: Path,
    state: dict[str, Any],
    expected_year: int,
) -> list[str]:
    errors: list[str] = []

    for field in (
        "schema_version",
        "workflow_id",
        "updated_at",
        "next_required_action",
    ):
        if not nonempty(state.get(field)):
            add(errors, "FIELD", f"missing_or_empty:{field}")
    if state.get("schema_version") != "1.0":
        add(errors, "SCHEMA", f"unsupported:{state.get('schema_version')}")

    current_year = state.get("current_year")
    if current_year != expected_year:
        add(errors, "YEAR", f"current_year:{current_year};expected:{expected_year}")

    recent = state.get("recent_window")
    if not isinstance(recent, dict):
        add(errors, "RECENT_WINDOW", "missing_object")
        recent = {}
    if recent.get("start_year") != expected_year - 2:
        add(
            errors,
            "RECENT_WINDOW",
            f"start_year:{recent.get('start_year')};expected:{expected_year - 2}",
        )
    if recent.get("end_year") != expected_year:
        add(
            errors,
            "RECENT_WINDOW",
            f"end_year:{recent.get('end_year')};expected:{expected_year}",
        )
    if recent.get("status") not in {"INCOMPLETE", "COMPLETE"}:
        add(errors, "RECENT_WINDOW", f"invalid_status:{recent.get('status')}")
    if recent.get("snapshot_mode") not in SNAPSHOT_MODES:
        add(
            errors,
            "RECENT_WINDOW",
            f"invalid_snapshot_mode:{recent.get('snapshot_mode')}",
        )

    output_type = state.get("output_type")
    contract = state.get("contribution_contract")
    layer = state.get("active_layer")
    contribution = state.get("active_contribution")
    active_state = state.get("active_state")
    resume_state = state.get("resume_state")

    if output_type not in OUTPUT_TYPES:
        add(errors, "OUTPUT_TYPE", f"invalid:{output_type}")
    if contract not in CONTRACTS:
        add(errors, "CONTRACT", f"invalid:{contract}")
    if layer not in LAYERS:
        add(errors, "LAYER", f"invalid:{layer}")
    if contribution not in CONTRIBUTIONS:
        add(errors, "CONTRIBUTION", f"invalid:{contribution}")
    if active_state not in STATES:
        add(errors, "STATE", f"invalid_active_state:{active_state}")
    if resume_state not in STATES:
        add(errors, "STATE", f"invalid_resume_state:{resume_state}")
    if state.get("last_completed_state") not in STATES | {"NONE"}:
        add(
            errors,
            "STATE",
            f"invalid_last_completed:{state.get('last_completed_state')}",
        )
    if state.get("search_mode") not in SEARCH_MODES:
        add(errors, "SEARCH_MODE", f"invalid:{state.get('search_mode')}")
    if state.get("compute_stage") not in COMPUTE_STAGES:
        add(errors, "COMPUTE", f"invalid_stage:{state.get('compute_stage')}")
    round_value = state.get("collision_round")
    if not isinstance(round_value, int) or round_value < 1:
        add(errors, "ROUND", f"invalid:{round_value}")

    if active_state == "BLOCKED":
        if resume_state not in RESUMABLE_STATES:
            add(errors, "STATE", f"blocked_invalid_resume:{resume_state}")
        reasons = state.get("blocked_reasons")
        if not isinstance(reasons, list) or not reasons:
            add(errors, "BLOCKED", "blocked_without_reason")
        effective_state = resume_state
    else:
        if resume_state != active_state:
            add(
                errors,
                "STATE",
                f"resume_state:{resume_state};expected_active:{active_state}",
            )
        if state.get("blocked_reasons") not in ([], None):
            add(errors, "BLOCKED", "stale_blocked_reasons")
        effective_state = active_state

    unresolved_allowed = effective_state in {"BOOT", "SCOPE_LOCK"}
    if not unresolved_allowed and (
        output_type == "UNRESOLVED"
        or contract == "UNRESOLVED"
        or layer == "UNRESOLVED"
    ):
        add(errors, "SCOPE", "unresolved_after_scope_state")

    expected_contract = {
        "DOCTORAL_DISSERTATION": "THREE_ORGANIC_A_B_C",
        "JOURNAL_ARTICLE": "ONE_MAIN_M",
    }.get(output_type)
    if expected_contract and contract != expected_contract:
        add(
            errors,
            "CONTRACT",
            f"output_type:{output_type};contract:{contract};expected:{expected_contract}",
        )

    if layer in {"L1", "L2", "ARCHITECTURE", "UNRESOLVED"}:
        if contribution != "NONE":
            add(errors, "CONTRIBUTION", f"layer:{layer};expected:NONE")
    elif layer == "L3":
        allowed = (
            {"A", "B", "C"}
            if output_type == "DOCTORAL_DISSERTATION"
            else {"M"} if output_type == "JOURNAL_ARTICLE" else set()
        )
        if contribution not in allowed:
            add(
                errors,
                "CONTRIBUTION",
                f"layer:L3;output_type:{output_type};invalid:{contribution}",
            )

    gates = state.get("gates")
    if not isinstance(gates, dict):
        add(errors, "GATES", "missing_object")
        gates = {}
    for gate in sorted(GATE_KEYS):
        if not isinstance(gates.get(gate), bool):
            add(errors, "GATE", f"{gate}:not_boolean")

    implications = {
        "prior_claims_drained": ("scope_locked",),
        "recent_frontier_complete": ("scope_locked", "prior_claims_drained"),
        "literature_registry_valid": ("recent_frontier_complete",),
        "important_fulltext_complete": ("literature_registry_valid",),
        "source_claims_complete": ("important_fulltext_complete",),
        "output_claims_traced": ("source_claims_complete",),
        "evidence_validated": ("output_claims_traced",),
        "l2_frozen": ("l1_frozen",),
        "architecture_frozen": ("l1_frozen", "l2_frozen"),
        "n0_4_locked": ("architecture_frozen", "evidence_validated"),
    }
    for gate, prerequisites in implications.items():
        if gates.get(gate):
            for prerequisite in prerequisites:
                if not gates.get(prerequisite):
                    add(errors, "GATE_ORDER", f"{gate}_requires:{prerequisite}")

    if gates.get("recent_frontier_complete"):
        if recent.get("status") != "COMPLETE":
            add(errors, "RECENT_WINDOW", "gate_true_but_status_not_complete")
        if recent.get("snapshot_mode") not in {
            "NEW_SEARCH",
            "REUSED_VERIFIED_SNAPSHOT",
        }:
            add(errors, "RECENT_WINDOW", "complete_without_valid_snapshot_mode")

    prerequisites = STATE_PREREQUISITES.get(str(effective_state), ())
    for gate in prerequisites:
        if not gates.get(gate):
            add(errors, "STATE_GATE", f"{effective_state}_requires:{gate}")

    if layer == "L2" and not gates.get("l1_frozen"):
        add(errors, "LAYER_GATE", "L2_requires:l1_frozen")
    if layer == "ARCHITECTURE" and not gates.get("l2_frozen"):
        add(errors, "LAYER_GATE", "ARCHITECTURE_requires:l2_frozen")
    if layer == "L3" and not gates.get("architecture_frozen"):
        add(errors, "LAYER_GATE", "L3_requires:architecture_frozen")
    if effective_state == "N0_AUDIT" and layer != "L3":
        add(errors, "STATE_LAYER", "N0_AUDIT_requires:L3")

    compute_stage = state.get("compute_stage")
    if compute_stage not in {"NOT_STARTED", "STOPPED"}:
        if not gates.get("n0_4_locked"):
            add(errors, "COMPUTE", "started_without_n0_4")
        if not gates.get("compute_authorized"):
            add(errors, "COMPUTE", "started_without_authorization")
    if effective_state == "COMPUTE" and compute_stage in {"NOT_STARTED", "STOPPED"}:
        add(errors, "COMPUTE", f"active_compute_invalid_stage:{compute_stage}")

    artifacts = state.get("artifacts")
    if not isinstance(artifacts, dict):
        add(errors, "ARTIFACT", "missing_object")
        artifacts = {}
    checked: set[str] = set()
    for gate, artifact_keys in GATE_ARTIFACTS.items():
        if not gates.get(gate):
            continue
        for key in artifact_keys:
            if key in checked:
                continue
            checked.add(key)
            path = resolve_artifact(root, artifacts.get(key))
            if path is None:
                add(errors, "ARTIFACT", f"{key}:missing_or_unsafe_path")
            elif not path.exists():
                add(errors, "ARTIFACT", f"{key}:not_found:{path}")
            elif key == "literature_archive" and not path.is_dir():
                add(errors, "ARTIFACT", f"{key}:not_directory:{path}")
            elif key != "literature_archive" and not path.is_file():
                add(errors, "ARTIFACT", f"{key}:not_file:{path}")

    decision_log = state.get("decision_log")
    if not isinstance(decision_log, list):
        add(errors, "DECISION_LOG", "not_list")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--current-year", type=int, default=datetime.now().year)
    args = parser.parse_args()

    root = args.root.resolve()
    state_path = args.state.resolve()
    try:
        state_path.relative_to(root)
    except ValueError:
        print("workflow_state_errors=1")
        print(f"STATE_PATH\toutside_root:{state_path}")
        return 1

    errors = validate(root, load_json(state_path), args.current_year)
    print(f"workflow_state_errors={len(errors)}")
    for error in errors:
        print(error)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
