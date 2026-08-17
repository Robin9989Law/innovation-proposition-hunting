"""第 2 期：iph CLI、进程内校验与 ProjectContext 的集成测试。"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest

from tests.helpers import (
    REPOSITORY_ROOT,
    load_json,
    make_valid_project,
    run_all_validator,
    write_json,
)

IPH = REPOSITORY_ROOT / "scripts" / "iph.py"


def run_iph(project, *argv: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(IPH),
            *argv,
            "--root",
            str(project),
            "--state",
            str(project / "workflow_state.json"),
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def issue_lines(output: str) -> list[str]:
    return [
        line
        for line in output.splitlines()
        if line.startswith(("INVALID", "BLOCKED", "WARNING", "MIGRATION"))
        or "_status=" in line
    ]


class InProcessSuiteTests(unittest.TestCase):
    """进程内模式（默认）与子进程模式结果必须一致。"""

    def test_in_process_matches_subprocess(self) -> None:
        temporary_directory, project = make_valid_project(
            claim_profile="MIXED", validity_level="V3"
        )
        with temporary_directory:
            new = run_all_validator(project)
            old = run_all_validator(project, ["--subprocess"])
            self.assertEqual(new.returncode, old.returncode)
            self.assertEqual(issue_lines(new.stdout), issue_lines(old.stdout))


class AdvanceTests(unittest.TestCase):
    def make_boot_project(self):
        temporary_directory, project = make_valid_project(validity_level="V0")
        state = load_json(project / "workflow_state.json")
        state.update(
            {
                "active_state": "BOOT",
                "resume_state": "BOOT",
                "active_contribution": "NONE",
                "next_required_action": (
                    "Create and freeze scope_lock.md and hierarchy_status.md, "
                    "then advance to SCOPE_LOCK."
                ),
                "novelty_level": "N0-3",
                "validity_level": "V0",
                "claim_bundle_sha256": "",
                "independent_audit": {},
                "artifacts": {},
                "decision_log": [],
            }
        )
        state["gates"] = {key: False for key in state["gates"]}
        write_json(project / "workflow_state.json", state)
        (project / "scope_lock.md").write_text("# Scope lock\n", encoding="utf-8")
        (project / "hierarchy_status.md").write_text(
            "# Hierarchy status\n", encoding="utf-8"
        )
        return temporary_directory, project

    def test_boot_to_scope_lock_atomically_registers_artifact_pointers(self) -> None:
        temporary_directory, project = self.make_boot_project()
        with temporary_directory:
            completed = run_iph(
                project,
                "advance",
                "--to",
                "SCOPE_LOCK",
                "--note",
                "scope contract frozen",
                "--set-gate",
                "scope_locked=true",
                "--artifact",
                "scope_lock.md",
                "--artifact",
                "hierarchy_status.md",
                "--set-artifact",
                "scope_lock=scope_lock.md",
                "--set-artifact",
                "hierarchy_status=hierarchy_status.md",
                "--next-action",
                "Drain prior-round claims before frontier search.",
            )
            self.assertEqual(
                0, completed.returncode, completed.stdout + completed.stderr
            )
            state = load_json(project / "workflow_state.json")
            self.assertEqual("SCOPE_LOCK", state["active_state"])
            self.assertTrue(state["gates"]["scope_locked"])
            self.assertEqual("scope_lock.md", state["artifacts"]["scope_lock"])
            self.assertEqual(
                "hierarchy_status.md", state["artifacts"]["hierarchy_status"]
            )
            self.assertEqual(
                "Drain prior-round claims before frontier search.",
                state["next_required_action"],
            )
            self.assertEqual(2, len(state["decision_log"][-1]["artifacts"]))
            self.assertFalse((project / ".workflow_stop.lock").exists())

    def test_clear_lock_repairs_missing_artifact_pointers_without_direct_edit(self) -> None:
        temporary_directory, project = self.make_boot_project()
        with temporary_directory:
            failed = run_iph(
                project,
                "advance",
                "--to",
                "SCOPE_LOCK",
                "--note",
                "legacy advance omitted pointer map",
                "--set-gate",
                "scope_locked=true",
                "--artifact",
                "scope_lock.md",
                "--artifact",
                "hierarchy_status.md",
            )
            self.assertEqual(1, failed.returncode, failed.stdout + failed.stderr)
            self.assertTrue((project / ".workflow_stop.lock").exists())

            recovered = run_iph(
                project,
                "clear-lock",
                "--recovery-note",
                "registered missing scope artifact pointers",
                "--set-artifact",
                "scope_lock=scope_lock.md",
                "--set-artifact",
                "hierarchy_status=hierarchy_status.md",
                "--next-action",
                "Drain prior-round claims before frontier search.",
            )
            self.assertEqual(0, recovered.returncode, recovered.stdout)
            state = load_json(project / "workflow_state.json")
            self.assertEqual("SCOPE_LOCK", state["active_state"])
            self.assertEqual("scope_lock.md", state["artifacts"]["scope_lock"])
            self.assertEqual(
                "hierarchy_status.md", state["artifacts"]["hierarchy_status"]
            )
            self.assertFalse((project / ".workflow_stop.lock").exists())
            log_text = (project / "validation.log").read_text(encoding="utf-8")
            self.assertIn("RECOVERY_STATE_REPAIR", log_text)
            self.assertIn("LOCK_CLEARED", log_text)

    def test_clear_lock_resumes_blocked_state_after_operator_repair(self) -> None:
        temporary_directory, project = self.make_boot_project()
        with temporary_directory:
            state = load_json(project / "workflow_state.json")
            state["active_state"] = "BLOCKED"
            state["resume_state"] = "BOOT"
            state["blocked_reasons"] = ["operator repaired the external blocker"]
            write_json(project / "workflow_state.json", state)
            write_json(project / ".workflow_stop.lock", {"exit_code": 2})

            recovered = run_iph(
                project,
                "clear-lock",
                "--resume-blocked",
                "--recovery-note",
                "deployed the authoritative state-machine fix",
                "--next-action",
                "Create and freeze scope artifacts.",
            )
            self.assertEqual(0, recovered.returncode, recovered.stdout + recovered.stderr)
            state = load_json(project / "workflow_state.json")
            self.assertEqual("BOOT", state["active_state"])
            self.assertEqual("BOOT", state["resume_state"])
            self.assertEqual([], state["blocked_reasons"])
            self.assertEqual("Create and freeze scope artifacts.", state["next_required_action"])
            self.assertIn("RECOVERY_RESUME from BLOCKED", state["decision_log"][-1]["action"])
            self.assertFalse((project / ".workflow_stop.lock").exists())

    def test_clear_lock_failed_resume_restores_state_lock_and_log_bytes(self) -> None:
        temporary_directory, project = self.make_boot_project()
        with temporary_directory:
            state = load_json(project / "workflow_state.json")
            state["active_state"] = "BLOCKED"
            state["resume_state"] = "BOOT"
            state["blocked_reasons"] = ["operator repair pending"]
            state["current_year"] = 2025
            write_json(project / "workflow_state.json", state)
            write_json(project / ".workflow_stop.lock", {"exit_code": 2, "marker": "original"})
            (project / "validation.log").write_text("original log\n", encoding="utf-8")
            original = {
                name: (project / name).read_bytes()
                for name in (
                    "workflow_state.json",
                    ".workflow_stop.lock",
                    "validation.log",
                )
            }

            recovered = run_iph(
                project,
                "clear-lock",
                "--resume-blocked",
                "--recovery-note",
                "this recovery must roll back",
                "--next-action",
                "Create and freeze scope artifacts.",
            )
            self.assertNotEqual(0, recovered.returncode)
            self.assertIn("RECOVERY_ROLLBACK", recovered.stdout)
            for name, expected in original.items():
                self.assertEqual(expected, (project / name).read_bytes())

    def test_repair_artifact_pointer_preserves_old_bytes_and_records_hashes(self) -> None:
        temporary_directory, project = self.make_boot_project()
        with temporary_directory:
            old = project / "near_neighbor_url_ledger.csv"
            replacement = project / "near_neighbor_url_ledger.v2.csv"
            old.write_text("old evidence\n", encoding="utf-8")
            replacement.write_text("corrected evidence\n", encoding="utf-8")
            old_bytes = old.read_bytes()

            repaired = run_iph(
                project,
                "repair-artifact-pointer",
                "--recovery-note",
                "preprint could not verify peer review",
                "--set-artifact",
                "url_ledger=near_neighbor_url_ledger.v2.csv",
            )

            self.assertEqual(0, repaired.returncode, repaired.stdout + repaired.stderr)
            state = load_json(project / "workflow_state.json")
            self.assertEqual(
                "near_neighbor_url_ledger.v2.csv", state["artifacts"]["url_ledger"]
            )
            self.assertEqual(old_bytes, old.read_bytes())
            action = state["decision_log"][-1]["action"]
            self.assertIn("EVIDENCE_POINTER_REPAIR", action)
            self.assertIn("near_neighbor_url_ledger.csv@", action)
            self.assertIn("near_neighbor_url_ledger.v2.csv@", action)

    def test_failed_artifact_pointer_repair_rolls_back_state_lock_and_log(self) -> None:
        temporary_directory, project = self.make_boot_project()
        with temporary_directory:
            (project / "near_neighbor_url_ledger.csv").write_text(
                "old evidence\n", encoding="utf-8"
            )
            (project / "near_neighbor_url_ledger.v2.csv").write_text(
                "corrected evidence\n", encoding="utf-8"
            )
            state = load_json(project / "workflow_state.json")
            state["current_year"] = 2025
            write_json(project / "workflow_state.json", state)
            write_json(project / ".workflow_stop.lock", {"exit_code": 1, "marker": "old"})
            (project / "validation.log").write_text("old log\n", encoding="utf-8")
            original = {
                name: (project / name).read_bytes()
                for name in ("workflow_state.json", ".workflow_stop.lock", "validation.log")
            }

            repaired = run_iph(
                project,
                "repair-artifact-pointer",
                "--recovery-note",
                "must roll back",
                "--set-artifact",
                "url_ledger=near_neighbor_url_ledger.v2.csv",
            )

            self.assertNotEqual(0, repaired.returncode)
            self.assertIn("POINTER_REPAIR_ROLLBACK", repaired.stdout)
            for name, expected in original.items():
                self.assertEqual(expected, (project / name).read_bytes())

    def test_start_collision_round_rejects_non_n0_hold(self) -> None:
        temporary_directory, project = make_valid_project(validity_level="V0")
        with temporary_directory:
            completed = run_iph(
                project,
                "start-collision-round",
                "--note",
                "must not create a round from a validity-track fixture",
            )
            self.assertNotEqual(0, completed.returncode, completed.stdout)
            self.assertIn("只能从 N0_AUDIT", completed.stderr)
            state = load_json(project / "workflow_state.json")
            self.assertEqual("CLAIM_FREEZE", state["active_state"])
            self.assertEqual(1, state["collision_round"])

    def test_advance_writes_real_bookkeeping(self) -> None:
        temporary_directory, project = make_valid_project(validity_level="V1")
        with temporary_directory:
            completed = run_iph(
                project,
                "advance",
                "--to",
                "VALIDITY_AUDIT",
                "--note",
                "claim inventory frozen; enter G9 form audit",
                "--artifact",
                "claim_inventory.json",
                "--claim-bundle-manifest",
                "audit_manifest.json",
            )
            self.assertEqual(0, completed.returncode, completed.stdout)
            state = load_json(project / "workflow_state.json")
            self.assertEqual("VALIDITY_AUDIT", state["active_state"])
            # schema 3.0：派生字段不再由工具写回（由校验器派生）
            self.assertNotIn("last_completed_state", state)
            self.assertNotIn("active_track", state)
            entry = state["decision_log"][-1]
            self.assertEqual("VALIDITY_AUDIT", entry["state"])
            self.assertIn("T", entry["at"])
            artifact = entry["artifacts"][0]
            self.assertEqual("claim_inventory.json", artifact["path"])
            self.assertEqual(64, len(artifact["sha256"]))
            log_text = (project / "validation.log").read_text(encoding="utf-8")
            self.assertIn("ADVANCE CLAIM_FREEZE -> VALIDITY_AUDIT", log_text)

    def test_recent_frontier_advance_syncs_window_from_registered_artifact(self) -> None:
        temporary_directory, project = make_valid_project(validity_level="V0")
        with temporary_directory:
            state = load_json(project / "workflow_state.json")
            state["active_state"] = "PRIOR_CLAIM_DRAIN"
            state["resume_state"] = "PRIOR_CLAIM_DRAIN"
            state["active_contribution"] = "NONE"
            write_json(project / "workflow_state.json", state)
            registry = project / "frontier-registry.json"
            write_json(
                registry,
                {
                    "recent_window": {
                        "start_year": 2024,
                        "end_year": 2026,
                        "status": "COMPLETE",
                        "snapshot_mode": "REUSED_VERIFIED_SNAPSHOT",
                    },
                    "records": [],
                },
            )
            completed = run_iph(
                project,
                "advance",
                "--to",
                "RECENT_FRONTIER",
                "--note",
                "frontier audit completed",
                "--set-gate",
                "recent_frontier_complete=true",
                "--set-artifact",
                "literature_registry=frontier-registry.json",
                "--no-validate",
            )
            self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
            state = load_json(project / "workflow_state.json")
            self.assertEqual(
                {
                    "start_year": 2024,
                    "end_year": 2026,
                    "status": "COMPLETE",
                    "snapshot_mode": "REUSED_VERIFIED_SNAPSHOT",
                },
                state["recent_window"],
            )
            self.assertTrue(state["gates"]["recent_frontier_complete"])
            self.assertEqual(
                "frontier-registry.json", state["artifacts"]["literature_registry"]
            )

    def test_recent_frontier_advance_rejects_invalid_registry_window_atomically(self) -> None:
        temporary_directory, project = make_valid_project(validity_level="V0")
        with temporary_directory:
            state = load_json(project / "workflow_state.json")
            state["active_state"] = "PRIOR_CLAIM_DRAIN"
            state["resume_state"] = "PRIOR_CLAIM_DRAIN"
            state["active_contribution"] = "NONE"
            write_json(project / "workflow_state.json", state)
            original = load_json(project / "workflow_state.json")
            write_json(
                project / "near_neighbor_registry.json",
                {
                    "recent_window": {
                        "start_year": 2024,
                        "end_year": 2026,
                        "status": "COMPLETE",
                        "snapshot_mode": "NOT_SET",
                    },
                    "records": [],
                },
            )
            completed = run_iph(
                project,
                "advance",
                "--to",
                "RECENT_FRONTIER",
                "--note",
                "must reject incomplete provenance",
                "--set-gate",
                "recent_frontier_complete=true",
                "--set-artifact",
                "literature_registry=near_neighbor_registry.json",
                "--no-validate",
            )
            self.assertNotEqual(0, completed.returncode)
            self.assertIn("snapshot_mode", completed.stderr)
            self.assertEqual(original, load_json(project / "workflow_state.json"))

    def test_advance_aborts_on_failed_validation(self) -> None:
        temporary_directory, project = make_valid_project()
        with temporary_directory:
            state = load_json(project / "workflow_state.json")
            state["current_year"] = 2025  # 制造 INVALID
            write_json(project / "workflow_state.json", state)
            completed = run_iph(
                project, "advance", "--to", "VALIDITY_AUDIT", "--note", "x"
            )
            self.assertEqual(1, completed.returncode, completed.stdout)
            self.assertIn("advance aborted", completed.stdout)
            state = load_json(project / "workflow_state.json")
            self.assertEqual("CLAIM_FREEZE", state["active_state"])
            self.assertEqual([], state["decision_log"])

    def test_advance_rejects_unknown_gate_and_state(self) -> None:
        temporary_directory, project = make_valid_project()
        with temporary_directory:
            bad_gate = run_iph(
                project,
                "advance",
                "--to",
                "VALIDITY_AUDIT",
                "--note",
                "x",
                "--set-gate",
                "nonsense=true",
            )
            self.assertNotEqual(0, bad_gate.returncode)
            bad_state = run_iph(
                project, "advance", "--to", "NOWHERE", "--note", "x"
            )
            self.assertNotEqual(0, bad_state.returncode)

    def test_advance_activates_journal_contribution_at_l3_boundary(self) -> None:
        temporary_directory, project = make_valid_project(validity_level="V0")
        with temporary_directory:
            state = load_json(project / "workflow_state.json")
            state["active_state"] = "LAYER_DECISION"
            state["resume_state"] = "LAYER_DECISION"
            state["active_contribution"] = "NONE"
            write_json(project / "workflow_state.json", state)
            completed = run_iph(
                project,
                "advance",
                "--to",
                "K_FULLTEXT",
                "--note",
                "enter L3 evidence",
                "--no-validate",
            )
            self.assertEqual(0, completed.returncode, completed.stdout)
            state = load_json(project / "workflow_state.json")
            self.assertEqual("K_FULLTEXT", state["active_state"])
            self.assertEqual("M", state["active_contribution"])

    def test_advance_resets_contribution_when_reentering_l2(self) -> None:
        temporary_directory, project = make_valid_project(validity_level="V0")
        with temporary_directory:
            state = load_json(project / "workflow_state.json")
            state["active_state"] = "L1_FREEZE"
            state["resume_state"] = "L1_FREEZE"
            state["active_contribution"] = "M"
            write_json(project / "workflow_state.json", state)
            completed = run_iph(
                project,
                "advance",
                "--to",
                "L2_TRIAGE",
                "--note",
                "reopen L2",
                "--no-validate",
            )
            self.assertEqual(0, completed.returncode, completed.stdout)
            state = load_json(project / "workflow_state.json")
            self.assertEqual("L2_TRIAGE", state["active_state"])
            self.assertEqual("NONE", state["active_contribution"])

    def test_advance_rejects_skipped_positive_state(self) -> None:
        temporary_directory, project = self.make_boot_project()
        with temporary_directory:
            before = load_json(project / "workflow_state.json")
            completed = run_iph(
                project,
                "advance",
                "--to",
                "RECENT_FRONTIER",
                "--note",
                "skip forbidden",
                "--no-validate",
            )
            self.assertNotEqual(0, completed.returncode)
            self.assertIn("禁止跳态", completed.stderr)
            self.assertEqual(before, load_json(project / "workflow_state.json"))

    def test_n0_verdict_is_written_atomically_with_gate(self) -> None:
        temporary_directory, project = make_valid_project(validity_level="V0")
        with temporary_directory:
            state = load_json(project / "workflow_state.json")
            state["active_state"] = "EVIDENCE_VALIDATE"
            state["resume_state"] = "EVIDENCE_VALIDATE"
            state["novelty_level"] = "N0-3"
            state["gates"]["n0_4_locked"] = False
            write_json(project / "workflow_state.json", state)
            completed = run_iph(
                project,
                "advance",
                "--to",
                "N0_AUDIT",
                "--note",
                "mechanical reduction found",
                "--novelty-level",
                "N0-2",
                "--set-gate",
                "n0_4_locked=false",
                "--no-validate",
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            state = load_json(project / "workflow_state.json")
            self.assertEqual("N0_AUDIT", state["active_state"])
            self.assertEqual("N0-2", state["novelty_level"])
            self.assertFalse(state["gates"]["n0_4_locked"])

    def test_validity_levels_are_derived_from_completed_author_work(self) -> None:
        temporary_directory, project = make_valid_project(validity_level="V0")
        with temporary_directory:
            state = load_json(project / "workflow_state.json")
            state["active_state"] = "CLAIM_FREEZE"
            state["resume_state"] = "CLAIM_FREEZE"
            state["novelty_level"] = "N0-4C"
            state["gates"]["n0_4_locked"] = True
            write_json(project / "workflow_state.json", state)
            v1 = run_iph(
                project,
                "advance",
                "--to",
                "VALIDITY_AUDIT",
                "--note",
                "inventory frozen",
                "--claim-bundle-manifest",
                "audit_manifest.json",
                "--no-validate",
            )
            self.assertEqual(0, v1.returncode, v1.stderr)
            self.assertEqual("V1", load_json(project / "workflow_state.json")["validity_level"])
            v2 = run_iph(
                project,
                "advance",
                "--to",
                "INDEPENDENT_REVIEW",
                "--note",
                "form audit complete",
                "--no-validate",
            )
            self.assertEqual(0, v2.returncode, v2.stderr)
            self.assertEqual("V2", load_json(project / "workflow_state.json")["validity_level"])

    def test_compute_entry_requires_and_records_explicit_authorization(self) -> None:
        temporary_directory, project = make_valid_project(validity_level="V3")
        with temporary_directory:
            state = load_json(project / "workflow_state.json")
            state["active_state"] = "DIRECTION_LOCK"
            state["resume_state"] = "DIRECTION_LOCK"
            write_json(project / "workflow_state.json", state)
            denied = run_iph(
                project,
                "advance",
                "--to",
                "COMPUTE",
                "--note",
                "missing authority",
                "--no-validate",
            )
            self.assertNotEqual(0, denied.returncode)
            authorized = run_iph(
                project,
                "advance",
                "--to",
                "COMPUTE",
                "--note",
                "authorized compute entry",
                "--authorize-compute",
                "--authorization-note",
                "user explicitly authorized this bounded test",
                "--no-validate",
            )
            self.assertEqual(0, authorized.returncode, authorized.stderr)
            state = load_json(project / "workflow_state.json")
            self.assertTrue(state["gates"]["compute_authorized"])
            self.assertEqual("S0", state["compute_stage"])


    def prepare_layer_decision(self, project) -> None:
        """把 fixture 摆到合法的 LAYER_DECISION（gates/artifacts/决策记录齐全）。"""
        state = load_json(project / "workflow_state.json")
        state["active_state"] = "LAYER_DECISION"
        state["resume_state"] = "LAYER_DECISION"
        state["active_contribution"] = "NONE"
        state["recent_window"] = {
            "start_year": 2024,
            "end_year": 2026,
            "status": "COMPLETE",
            "snapshot_mode": "NEW_SEARCH",
        }
        for gate in (
            "scope_locked",
            "prior_claims_drained",
            "recent_frontier_complete",
            "literature_registry_valid",
            "l1_frozen",
            "k_set_selected",
        ):
            state["gates"][gate] = True
        state["artifacts"] = {
            "scope_lock": "scope_lock.md",
            "hierarchy_status": "hierarchy_status.md",
            "literature_registry": "near_neighbor_registry.json",
            "url_ledger": "near_neighbor_url_ledger.csv",
            "claim_registry": "literature_claim_registry.json",
            "l1_card": "l1-card.md",
            "k_triage": "l2-triage.md",
            "l2_card": "l2-card.md",
            "contribution_architecture": "contribution_architecture.md",
        }
        state["decision_log"] = [
            {"at": f"2026-08-10T0{index}:00:00Z", "state": name, "action": "done"}
            for index, name in enumerate(
                [
                    "SCOPE_LOCK",
                    "PRIOR_CLAIM_DRAIN",
                    "RECENT_FRONTIER",
                    "LITERATURE_REGISTER",
                    "L1_FREEZE",
                    "L2_TRIAGE",
                ]
            )
        ]
        write_json(project / "workflow_state.json", state)
        for name in (
            "scope_lock.md",
            "hierarchy_status.md",
            "l1-card.md",
            "l2-card.md",
            "contribution_architecture.md",
        ):
            (project / name).write_text(f"# {name}\n", encoding="utf-8")
        write_json(
            project / "near_neighbor_registry.json",
            {
                "records": [],
                "peer_reviewed_published_count": 0,
                "search_mode": "SEARCH_OPEN",
                "synthesis_lock_threshold": 100,
            },
        )
        write_json(project / "literature_claim_registry.json", {"records": []})
        (project / "near_neighbor_url_ledger.csv").write_text(
            "registry_id,canonical_url,identity_verification_url,publication_verification_url,peer_review_verification_url,status,checked_at,role\n",
            encoding="utf-8",
        )

    def test_advance_strict_l2_to_l3_with_atomic_contribution(self) -> None:
        # 真实缺口场景：严格模式（前+后校验）跨越 L2/L3 边界
        temporary_directory, project = make_valid_project(validity_level="V0")
        with temporary_directory:
            self.prepare_layer_decision(project)
            completed = run_iph(
                project,
                "advance",
                "--to",
                "K_FULLTEXT",
                "--note",
                "L2 frozen, enter K fulltext",
                "--set-gate",
                "l2_frozen=true",
                "--set-gate",
                "architecture_frozen=true",
            )
            self.assertEqual(0, completed.returncode, completed.stdout)
            state = load_json(project / "workflow_state.json")
            self.assertEqual("K_FULLTEXT", state["active_state"])
            self.assertEqual("M", state["active_contribution"])

    def test_advance_rejects_explicit_invalid_contribution_for_journal(self) -> None:
        # 显式指定非法贡献必须拒绝，不得静默改写为 M
        temporary_directory, project = make_valid_project(validity_level="V0")
        with temporary_directory:
            state = load_json(project / "workflow_state.json")
            state["active_state"] = "LAYER_DECISION"
            state["resume_state"] = "LAYER_DECISION"
            state["active_contribution"] = "NONE"
            write_json(project / "workflow_state.json", state)
            completed = run_iph(
                project,
                "advance",
                "--to",
                "K_FULLTEXT",
                "--note",
                "wrong contribution",
                "--contribution",
                "A",
                "--no-validate",
            )
            self.assertNotEqual(0, completed.returncode, completed.stdout)
            state = load_json(project / "workflow_state.json")
            self.assertEqual("LAYER_DECISION", state["active_state"])
            self.assertEqual("NONE", state["active_contribution"])

    def test_advance_dissertation_requires_explicit_contribution(self) -> None:
        temporary_directory, project = make_valid_project(validity_level="V0")
        with temporary_directory:
            state = load_json(project / "workflow_state.json")
            state["output_type"] = "DOCTORAL_DISSERTATION"
            state["contribution_contract"] = "THREE_ORGANIC_A_B_C"
            state["active_state"] = "LAYER_DECISION"
            state["resume_state"] = "LAYER_DECISION"
            state["active_contribution"] = "NONE"
            write_json(project / "workflow_state.json", state)
            completed = run_iph(
                project,
                "advance",
                "--to",
                "K_FULLTEXT",
                "--note",
                "missing contribution",
                "--no-validate",
            )
            self.assertNotEqual(0, completed.returncode, completed.stdout)

    def test_advance_dissertation_accepts_explicit_contribution(self) -> None:
        temporary_directory, project = make_valid_project(validity_level="V0")
        with temporary_directory:
            state = load_json(project / "workflow_state.json")
            state["output_type"] = "DOCTORAL_DISSERTATION"
            state["contribution_contract"] = "THREE_ORGANIC_A_B_C"
            state["active_state"] = "LAYER_DECISION"
            state["resume_state"] = "LAYER_DECISION"
            state["active_contribution"] = "NONE"
            write_json(project / "workflow_state.json", state)
            completed = run_iph(
                project,
                "advance",
                "--to",
                "K_FULLTEXT",
                "--note",
                "enter L3 with contribution A",
                "--contribution",
                "A",
                "--no-validate",
            )
            self.assertEqual(0, completed.returncode, completed.stdout)
            state = load_json(project / "workflow_state.json")
            self.assertEqual("K_FULLTEXT", state["active_state"])
            self.assertEqual("A", state["active_contribution"])


class RetractNoveltyTests(unittest.TestCase):
    def _n0_audit_project(self, *, novelty: str, validity: str, state_name: str):
        temporary_directory, project = make_valid_project(
            novelty_level=novelty, validity_level=validity
        )
        state = load_json(project / "workflow_state.json")
        state["active_state"] = state_name
        state["resume_state"] = state_name
        state["validity_level"] = validity
        state["novelty_level"] = novelty
        state["gates"]["n0_4_locked"] = novelty == "N0-4C"
        state["gates"]["compute_authorized"] = False
        write_json(project / "workflow_state.json", state)
        (project / "novelty-audit.retracted.md").write_text(
            "# Novelty Audit\n\nHOLD after retract.\n",
            encoding="utf-8",
        )
        return temporary_directory, project

    def test_retracts_n0_4c_to_n0_3(self) -> None:
        temporary_directory, project = self._n0_audit_project(
            novelty="N0-4C", validity="V0", state_name="N0_AUDIT"
        )
        with temporary_directory:
            completed = run_iph(
                project,
                "retract-novelty",
                "--to",
                "N0-3",
                "--note",
                "instance witness used a dataset mean as a threshold",
                "--artifact",
                "novelty-audit.retracted.md",
                "--set-artifact",
                "hierarchy_novelty_audit=novelty-audit.retracted.md",
                "--next-action",
                "HOLD at N0-3; do not compute.",
                "--no-validate",
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            state = load_json(project / "workflow_state.json")
            self.assertEqual("N0_AUDIT", state["active_state"])
            self.assertEqual("N0-3", state["novelty_level"])
            self.assertFalse(state["gates"]["n0_4_locked"])
            self.assertEqual(
                "HOLD at N0-3; do not compute.",
                state["next_required_action"],
            )
            self.assertEqual(
                "novelty-audit.retracted.md",
                state["artifacts"]["hierarchy_novelty_audit"],
            )
            entry = state["decision_log"][-1]
            self.assertEqual("N0_AUDIT", entry["state"])
            self.assertIn("RETRACT_NOVELTY N0-4C -> N0-3", entry["action"])
            self.assertEqual(64, len(entry["artifacts"][0]["sha256"]))
            log_text = (project / "validation.log").read_text(encoding="utf-8")
            self.assertIn("RETRACT_NOVELTY N0-4C -> N0-3", log_text)

    def test_rejects_unless_n0_audit_n0_4c_v0(self) -> None:
        temporary_directory, project = self._n0_audit_project(
            novelty="N0-4C", validity="V0", state_name="CLAIM_FREEZE"
        )
        with temporary_directory:
            completed = run_iph(
                project,
                "retract-novelty",
                "--to",
                "N0-3",
                "--note",
                "wrong state",
                "--artifact",
                "novelty-audit.retracted.md",
                "--no-validate",
            )
            self.assertNotEqual(0, completed.returncode)
            self.assertIn("只能从 N0_AUDIT", completed.stderr)

        temporary_directory, project = self._n0_audit_project(
            novelty="N0-3", validity="V0", state_name="N0_AUDIT"
        )
        with temporary_directory:
            completed = run_iph(
                project,
                "retract-novelty",
                "--to",
                "N0-3",
                "--note",
                "already hold",
                "--artifact",
                "novelty-audit.retracted.md",
                "--no-validate",
            )
            self.assertNotEqual(0, completed.returncode)
            self.assertIn("只能撤回 N0-4C", completed.stderr)

        temporary_directory, project = self._n0_audit_project(
            novelty="N0-4C", validity="V1", state_name="N0_AUDIT"
        )
        with temporary_directory:
            completed = run_iph(
                project,
                "retract-novelty",
                "--to",
                "N0-3",
                "--note",
                "validity already frozen",
                "--artifact",
                "novelty-audit.retracted.md",
                "--no-validate",
            )
            self.assertNotEqual(0, completed.returncode)
            self.assertIn("有效性已冻结", completed.stderr)


class ReviseExactStatementTests(unittest.TestCase):
    def _n0_3_hold(self, *, state_name: str = "N0_AUDIT", novelty: str = "N0-3"):
        temporary_directory, project = make_valid_project(
            novelty_level=novelty, validity_level="V0"
        )
        state = load_json(project / "workflow_state.json")
        state["active_state"] = state_name
        state["resume_state"] = state_name
        state["novelty_level"] = novelty
        state["validity_level"] = "V0"
        state["collision_round"] = 3
        state["gates"]["n0_4_locked"] = novelty == "N0-4C"
        state["gates"]["compute_authorized"] = False
        for key in (
            "scope_locked",
            "prior_claims_drained",
            "recent_frontier_complete",
            "literature_registry_valid",
            "l1_frozen",
            "k_set_selected",
            "l2_frozen",
            "architecture_frozen",
            "k_fulltext_complete",
            "k_claims_complete",
            "output_claims_traced",
            "evidence_validated",
        ):
            state["gates"][key] = True
        write_json(project / "workflow_state.json", state)
        (project / "l3-exact.r11.md").write_text(
            "On input (s, I), lock the mapping if ATP succeeds or 10 iterations elapse.\n",
            encoding="utf-8",
        )
        return temporary_directory, project

    def test_revises_statement_without_resetting_layers_or_round(self) -> None:
        temporary_directory, project = self._n0_3_hold()
        with temporary_directory:
            completed = run_iph(
                project,
                "revise-exact-statement",
                "--path",
                "l3-exact.r11.md",
                "--note",
                "identity requires lexicon I; stop is ATP or 10 iterations",
                "--no-validate",
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            state = load_json(project / "workflow_state.json")
            self.assertEqual("SYNTHESIZE_COLLISION", state["active_state"])
            self.assertEqual(3, state["collision_round"])
            self.assertTrue(state["gates"]["l1_frozen"])
            self.assertTrue(state["gates"]["l2_frozen"])
            self.assertTrue(state["gates"]["architecture_frozen"])
            self.assertTrue(state["gates"]["k_fulltext_complete"])
            self.assertTrue(state["gates"]["k_claims_complete"])
            self.assertFalse(state["gates"]["output_claims_traced"])
            self.assertFalse(state["gates"]["evidence_validated"])
            self.assertFalse(state["gates"]["n0_4_locked"])
            self.assertEqual("l3-exact.r11.md", state["artifacts"]["exact_statement"])
            self.assertIn("REVISE_EXACT_STATEMENT", state["decision_log"][-1]["action"])
            log_text = (project / "validation.log").read_text(encoding="utf-8")
            self.assertIn("REVISE_EXACT_STATEMENT round=3", log_text)

    def test_rejects_locked_n0_4c_until_retract(self) -> None:
        temporary_directory, project = self._n0_3_hold(novelty="N0-4C")
        with temporary_directory:
            completed = run_iph(
                project,
                "revise-exact-statement",
                "--path",
                "l3-exact.r11.md",
                "--note",
                "must retract first",
                "--no-validate",
            )
            self.assertNotEqual(0, completed.returncode)
            self.assertIn("retract-novelty", completed.stderr)
            state = load_json(project / "workflow_state.json")
            self.assertEqual("N0_AUDIT", state["active_state"])
            self.assertEqual(3, state["collision_round"])


class KeepLayersCollisionTests(unittest.TestCase):
    def _collision_ready(self):
        temporary_directory, project = make_valid_project(
            novelty_level="N0-3", validity_level="V0"
        )
        state = load_json(project / "workflow_state.json")
        state["active_state"] = "N0_AUDIT"
        state["resume_state"] = "N0_AUDIT"
        state["novelty_level"] = "N0-3"
        state["validity_level"] = "V0"
        state["collision_round"] = 2
        state["active_contribution"] = "M"
        state["gates"]["n0_4_locked"] = False
        for key in (
            "scope_locked",
            "prior_claims_drained",
            "recent_frontier_complete",
            "literature_registry_valid",
            "l1_frozen",
            "k_set_selected",
            "l2_frozen",
            "architecture_frozen",
            "k_fulltext_complete",
            "k_claims_complete",
            "output_claims_traced",
            "evidence_validated",
        ):
            state["gates"][key] = True
        state["artifacts"].update(
            {
                "literature_registry": "near_neighbor_registry.json",
                "claim_registry": "literature_claim_registry.json",
                "output_support": "output_claim_support.json",
                "current_evidence_scope": "current_evidence_scope.json",
                "frontier_coverage": "frontier_coverage.json",
            }
        )
        write_json(project / "workflow_state.json", state)
        write_json(
            project / "near_neighbor_registry.json",
            {"current_collision_round": 2, "records": []},
        )
        write_json(
            project / "literature_claim_registry.json",
            {"current_collision_round": 2, "records": []},
        )
        write_json(
            project / "output_claim_support.json",
            {"current_collision_round": 2, "output_claims": []},
        )
        write_json(
            project / "current_evidence_scope.json",
            {
                "schema_version": "2.0",
                "collision_round": 2,
                "fulltext_registry_ids": ["W-0001"],
                "atomic_claim_ids": ["LC-0001"],
            },
        )
        write_json(project / "frontier_coverage.json", {"schema_version": "2.0"})
        return temporary_directory, project

    def test_keep_layers_preserves_l1_l2_and_increments_round(self) -> None:
        temporary_directory, project = self._collision_ready()
        with temporary_directory:
            completed = run_iph(
                project,
                "start-collision-round",
                "--keep-layers",
                "--note",
                "same L1/L2; only refresh K after new neighbors",
                "--no-validate",
            )
            self.assertEqual(0, completed.returncode, completed.stderr + completed.stdout)
            state = load_json(project / "workflow_state.json")
            self.assertEqual("PRIOR_CLAIM_DRAIN", state["active_state"])
            self.assertEqual(3, state["collision_round"])
            self.assertEqual("NONE", state["active_contribution"])
            self.assertTrue(state["gates"]["l1_frozen"])
            self.assertTrue(state["gates"]["l2_frozen"])
            self.assertTrue(state["gates"]["architecture_frozen"])
            self.assertTrue(state["gates"]["literature_registry_valid"])
            self.assertFalse(state["gates"]["k_fulltext_complete"])
            self.assertFalse(state["gates"]["k_claims_complete"])
            self.assertFalse(state["gates"]["n0_4_locked"])
            self.assertTrue(
                (project / "rounds" / "round-3" / "near_neighbor_registry.json").is_file()
            )

    def test_default_collision_still_resets_layers(self) -> None:
        temporary_directory, project = self._collision_ready()
        with temporary_directory:
            completed = run_iph(
                project,
                "start-collision-round",
                "--note",
                "program itself changed",
                "--no-validate",
            )
            self.assertEqual(0, completed.returncode, completed.stderr + completed.stdout)
            state = load_json(project / "workflow_state.json")
            self.assertEqual("NONE", state["active_contribution"])
            self.assertFalse(state["gates"]["l1_frozen"])
            self.assertFalse(state["gates"]["l2_frozen"])
            self.assertFalse(state["gates"]["architecture_frozen"])


class InstanceProbeTests(unittest.TestCase):
    def test_authorize_and_register_on_n0_3(self) -> None:
        temporary_directory, project = make_valid_project(
            novelty_level="N0-3", validity_level="V0"
        )
        with temporary_directory:
            state = load_json(project / "workflow_state.json")
            state["active_state"] = "N0_AUDIT"
            state["resume_state"] = "N0_AUDIT"
            state["novelty_level"] = "N0-3"
            state["gates"]["n0_4_locked"] = False
            state["gates"]["compute_authorized"] = False
            write_json(project / "workflow_state.json", state)
            denied = run_iph(
                project,
                "register-instance-probe",
                "--probe-id",
                "IP-0001",
                "--purpose",
                "COUNTEREXAMPLE",
                "--source-work",
                "W-0001",
                "--locator",
                "Figure 6",
                "--published-text",
                "Boy in side.",
                "--metric",
                "published_sentence_similarity",
                "--value",
                "0.8127",
                "--old-verdict",
                "UNDEFINED",
                "--output",
                "instance_probes/IP-0001.json",
            )
            self.assertNotEqual(0, denied.returncode)
            self.assertIn("尚未 authorize-instance-probe", denied.stderr)
            authorized = run_iph(
                project,
                "authorize-instance-probe",
                "--note",
                "user allowed small-scope instance inspect",
            )
            self.assertEqual(0, authorized.returncode, authorized.stderr)
            (project / "instance_probes").mkdir()
            (project / "instance_probes" / "IP-0001.json").write_text(
                '{"value": 0.8127}\n', encoding="utf-8"
            )
            registered = run_iph(
                project,
                "register-instance-probe",
                "--probe-id",
                "IP-0001",
                "--purpose",
                "COUNTEREXAMPLE",
                "--source-work",
                "W-0001",
                "--locator",
                "Figure 6",
                "--published-text",
                "Logical Form 2 omits Patient; similarity 0.8127",
                "--metric",
                "published_sentence_similarity",
                "--value",
                "0.8127",
                "--old-verdict",
                "UNDEFINED",
                "--output",
                "instance_probes/IP-0001.json",
            )
            self.assertEqual(0, registered.returncode, registered.stderr)
            registry = load_json(project / "instance_probe_registry.json")
            self.assertEqual(1, len(registry["probes"]))
            self.assertEqual(0.8127, registry["probes"][0]["value"])

    def test_authorize_rejects_n0_4c(self) -> None:
        temporary_directory, project = make_valid_project(
            novelty_level="N0-4C", validity_level="V0"
        )
        with temporary_directory:
            state = load_json(project / "workflow_state.json")
            state["active_state"] = "N0_AUDIT"
            state["resume_state"] = "N0_AUDIT"
            state["gates"]["n0_4_locked"] = True
            write_json(project / "workflow_state.json", state)
            completed = run_iph(
                project,
                "authorize-instance-probe",
                "--note",
                "should fail",
            )
            self.assertNotEqual(0, completed.returncode)
            self.assertIn("只能在 N0-3 HOLD", completed.stderr)


class RegisterExplorationTests(unittest.TestCase):
    def test_register_and_update(self) -> None:
        temporary_directory, project = make_valid_project()
        with temporary_directory:
            (project / "scan.json").write_text("{}", encoding="utf-8")
            first = run_iph(
                project,
                "register-exploration",
                "--path",
                "scan.json",
                "--desc",
                "delta scan",
            )
            self.assertEqual(0, first.returncode, first.stdout)
            registry = load_json(project / "exploration_registry.json")
            entry = registry["explorations"][0]
            self.assertEqual("scan.json", entry["path"])
            self.assertEqual("EXPLORATION_PERMANENT", entry["data_role"])
            self.assertEqual(64, len(entry["sha256"]))
            second = run_iph(
                project,
                "register-exploration",
                "--path",
                "scan.json",
                "--desc",
                "delta scan v2",
            )
            self.assertEqual(0, second.returncode, second.stdout)
            registry = load_json(project / "exploration_registry.json")
            self.assertEqual(1, len(registry["explorations"]))
            self.assertEqual(
                "delta scan v2", registry["explorations"][0]["description"]
            )


class ReviewCommandTests(unittest.TestCase):
    """iph review：subagent 登记 review 产物 hash，主 agent 只读不写。"""

    def test_review_registers_hash_and_rejects_tamper(self) -> None:
        temporary_directory, project = make_valid_project(validity_level="V3")
        with temporary_directory:
            audit_path = project / "independent_audit.json"
            audit = load_json(audit_path)
            audit["review_answers"] = {
                "data_authenticity": "real",
                "baseline_execution": "real",
                "claim_strength": "real",
                "falsification_attempt": "real",
            }
            write_json(audit_path, audit)

            review = run_iph(
                project,
                "review",
                "--reviewer",
                "agent-b",
                "--thread",
                "thread-b",
                "--verdict",
                "PASS",
            )
            self.assertEqual(0, review.returncode, review.stdout + review.stderr)
            state = load_json(project / "workflow_state.json")
            self.assertEqual(64, len(state["review_artifact_sha256"]))

            # 主 agent 事后改 review 产物 → hash 变 → REVIEW_ARTIFACT_TAMPERED
            audit = load_json(audit_path)
            audit["review_answers"]["data_authenticity"] = "tampered"
            write_json(audit_path, audit)
            result = run_all_validator(project)
            self.assertIn("REVIEW_ARTIFACT_TAMPERED", result.stdout)

    def test_review_rejects_pass_without_answers(self) -> None:
        temporary_directory, project = make_valid_project(validity_level="V3")
        with temporary_directory:
            audit_path = project / "independent_audit.json"
            audit = load_json(audit_path)
            audit.pop("review_answers", None)
            write_json(audit_path, audit)

            review = run_iph(
                project,
                "review",
                "--reviewer",
                "agent-b",
                "--thread",
                "thread-b",
                "--verdict",
                "PASS",
            )
            self.assertNotEqual(0, review.returncode)
            self.assertIn("review_answers", review.stderr)


class HandoverTests(unittest.TestCase):
    def test_handover_reports_core_fields(self) -> None:
        temporary_directory, project = make_valid_project()
        with temporary_directory:
            completed = run_iph(project, "handover")
            self.assertEqual(0, completed.returncode, completed.stdout)
            self.assertIn("成果合同", completed.stdout)
            self.assertIn("N level", completed.stdout)
            self.assertIn("next_required_action", completed.stdout)


class ProjectContextTests(unittest.TestCase):
    def test_json_cache_and_artifacts_resolution(self) -> None:
        temporary_directory, project = make_valid_project()
        with temporary_directory:
            sys.path.insert(0, str(REPOSITORY_ROOT / "scripts"))
            from validation_common import ProjectContext

            state = load_json(project / "workflow_state.json")
            state["artifacts"] = {"claim_inventory": "claim_inventory.json"}
            write_json(project / "workflow_state.json", state)
            with ProjectContext(project, project / "workflow_state.json") as ctx:
                first = ctx.load_json("claim_inventory.json", "claim_inventory")
                second = ctx.load_json("claim_inventory.json", "claim_inventory")
                self.assertIs(first, second)
                self.assertEqual(
                    "claim_inventory.json",
                    ctx.artifact_relative_path("claim_inventory"),
                )


if __name__ == "__main__":
    unittest.main()
