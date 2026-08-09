from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise AssertionError(f"expected JSON object: {path}")
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def make_valid_project(
    *,
    claim_profile: str = "THEORY",
    novelty_level: str = "N0-4C",
    validity_level: str = "V3",
) -> tuple[TemporaryDirectory[str], Path]:
    temporary_directory = TemporaryDirectory(prefix="schema-v2-project-")
    project = Path(temporary_directory.name)
    state = {
        "schema_version": "2.0",
        "workflow_id": "schema-v2-test",
        "updated_at": "2026-08-10T00:00:00Z",
        "current_year": 2026,
        "recent_window": {
            "start_year": 2024,
            "end_year": 2026,
            "status": "INCOMPLETE",
            "snapshot_mode": "NOT_SET",
        },
        "output_type": "JOURNAL_ARTICLE",
        "contribution_contract": "ONE_MAIN_M",
        "active_layer": "L1",
        "active_contribution": "NONE",
        "active_track": "VALIDITY",
        "active_state": "CLAIM_FREEZE",
        "resume_state": "CLAIM_FREEZE",
        "last_completed_state": "N0_AUDIT",
        "search_mode": "SEARCH_OPEN",
        "compute_stage": "NOT_STARTED",
        "collision_round": 1,
        "next_required_action": "Freeze the claim inventory.",
        "blocked_reasons": [],
        "novelty_level": novelty_level,
        "validity_level": validity_level,
        "claim_profile": claim_profile,
        "validation_epoch": 1,
        "claim_bundle_sha256": "a" * 64,
        "independent_audit": {
            "capability_available": True,
            "author_agent_ids": ["agent-a"],
            "reviewer_agent_id": "agent-b",
            "reviewer_thread_id": "thread-b",
            "audited_bundle_sha256": "a" * 64,
            "verdict": "PASS",
        },
        "gates": {
            "scope_locked": False,
            "prior_claims_drained": False,
            "recent_frontier_complete": False,
            "literature_registry_valid": False,
            "important_fulltext_complete": False,
            "source_claims_complete": False,
            "output_claims_traced": False,
            "evidence_validated": False,
            "l1_frozen": False,
            "l2_frozen": False,
            "architecture_frozen": False,
            "n0_4_locked": False,
            "compute_authorized": False,
        },
        "artifacts": {},
        "decision_log": [],
    }
    write_json(project / "workflow_state.json", state)
    return temporary_directory, project


def run_schema_validator(project: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(REPOSITORY_ROOT / "scripts" / "validate_schema_v2.py"),
            "--root",
            str(project),
            "--state",
            str(project / "workflow_state.json"),
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def run_all_validator(project: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(REPOSITORY_ROOT / "scripts" / "validate_all.py"),
            "--root",
            str(project),
            "--state",
            str(project / "workflow_state.json"),
            "--current-year",
            "2026",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
