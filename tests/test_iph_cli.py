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
