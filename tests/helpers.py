from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from shutil import copy2, copytree
from tempfile import TemporaryDirectory
from typing import Any, Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MINIMAL_VALID_V2 = REPOSITORY_ROOT / "tests" / "fixtures" / "minimal-valid-v2"
MINIMAL_VALID_V3 = REPOSITORY_ROOT / "tests" / "fixtures" / "minimal-valid-v3"
STANDALONE_ONLY = {
    "contribution-architecture.md",
    "hierarchy_status.md",
    "l1-card.md",
    "l2-card.md",
    "literature_archive",
    "literature_claim_registry.json",
    "near_neighbor_registry.json",
    "novelty-audit.md",
    "output_claim_support.json",
    "scope_lock.md",
    "validation.log",
    "workflow_state.json",
}


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


def append_text(path: Path, text: str) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text)


def make_valid_project(
    *,
    claim_profile: str = "THEORY",
    novelty_level: str = "N0-4C",
    validity_level: str = "V3",
) -> tuple[TemporaryDirectory[str], Path]:
    temporary_directory = TemporaryDirectory(prefix="schema-v3-project-")
    project = Path(temporary_directory.name)
    state = {
        "schema_version": "3.0",
        "workflow_id": "schema-v3-test",
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
        "active_contribution": "M",
        "active_state": "CLAIM_FREEZE",
        "resume_state": "CLAIM_FREEZE",
        "search_mode": "SEARCH_OPEN",
        "compute_stage": "NOT_STARTED",
        "collision_round": 1,
        "next_required_action": "Freeze the claim inventory.",
        "blocked_reasons": [],
        "novelty_level": novelty_level,
        "validity_level": validity_level,
        "claim_profile": claim_profile,
        "validation_epoch": 1,
        "claim_bundle_sha256": "1c8a92a2dd454766cc121342fa6b470aadd8d29e4c5c344a8c00ff70785248c9",
        "independent_audit": {
            "capability_available": True,
            "validation_epoch": 1,
            "author_agent_ids": ["agent-a"],
            "reviewer_agent_id": "agent-b",
            "reviewer_thread_id": "thread-b",
            "audited_bundle_sha256": "1c8a92a2dd454766cc121342fa6b470aadd8d29e4c5c344a8c00ff70785248c9",
            "verdict": "PASS",
        },
        "gates": {
            "scope_locked": False,
            "prior_claims_drained": False,
            "recent_frontier_complete": False,
            "literature_registry_valid": False,
            "l1_frozen": False,
            "k_set_selected": False,
            "l2_frozen": False,
            "architecture_frozen": False,
            "k_fulltext_complete": False,
            "k_claims_complete": False,
            "output_claims_traced": False,
            "evidence_validated": False,
            "n0_4_locked": False,
            "compute_authorized": False,
        },
        "artifacts": {},
        "decision_log": [],
    }
    write_json(project / "workflow_state.json", state)
    for fixture_path in MINIMAL_VALID_V3.iterdir():
        if fixture_path.name in STANDALONE_ONLY:
            continue
        if fixture_path.is_file():
            copy2(fixture_path, project / fixture_path.name)
        elif fixture_path.is_dir():
            copytree(fixture_path, project / fixture_path.name)
    manifest = load_json(project / "audit_manifest.json")
    profile_roles = {
        "THEORY": {
            "CLAIM_INVENTORY",
            "MANUSCRIPT",
            "THEORY_OBLIGATIONS",
        },
        "ALGORITHM": {
            "BASELINE_CONTRACT",
            "EXECUTABLE_TEST",
            "CLAIM_CODE_TRACE",
            "CLAIM_INVENTORY",
            "IMPLEMENTATION",
            "MANUSCRIPT",
            "PROTOCOL_CONTRACT",
            "TEST_OUTPUT",
        },
        "MIXED": {entry["role"] for entry in manifest["entries"]},
    }
    allowed_roles = profile_roles.get(claim_profile, profile_roles["MIXED"])
    manifest["entries"] = [
        entry for entry in manifest["entries"] if entry["role"] in allowed_roles
    ]
    normalized = [
        {
            "path": entry["path"],
            "role": entry["role"],
            "sha256": entry["sha256"],
        }
        for entry in sorted(manifest["entries"], key=lambda entry: entry["path"])
    ]
    bundle_raw = json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    bundle_hash = hashlib.sha256(bundle_raw).hexdigest()
    manifest["claim_bundle_sha256"] = bundle_hash
    write_json(project / "audit_manifest.json", manifest)
    audit = load_json(project / "independent_audit.json")
    audit["audited_bundle_sha256"] = bundle_hash
    write_json(project / "independent_audit.json", audit)
    state["claim_bundle_sha256"] = bundle_hash
    state["independent_audit"]["audited_bundle_sha256"] = bundle_hash
    write_json(project / "workflow_state.json", state)
    return temporary_directory, project


def run_script(
    script_name: str,
    project: Path,
    extra_args: Sequence[str] = (),
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(REPOSITORY_ROOT / "scripts" / script_name),
            "--root",
            str(project),
            "--state",
            str(project / "workflow_state.json"),
            *extra_args,
        ],
        check=False,
        capture_output=True,
        text=True,
    )


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


def run_all_validator(
    project: Path,
    extra_args: Sequence[str] = (),
    *,
    lock_enabled: bool = False,
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    if not lock_enabled:
        # 存量用例不对 STOP 锁行为断言；锁专项测试显式传 lock_enabled=True。
        env["IPH_NO_LOCK"] = "1"
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
            *extra_args,
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def run_validator(project: Path) -> subprocess.CompletedProcess[str]:
    return run_all_validator(project)
