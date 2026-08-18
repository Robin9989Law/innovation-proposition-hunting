"""第 1 期状态完整性检查：decision_log 时间完整性、gate 完成记录、STOP 锁。"""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone
from pathlib import Path

from tempfile import TemporaryDirectory

from tests.helpers import (
    MINIMAL_VALID_V3,
    REPOSITORY_ROOT,
    load_json,
    make_valid_project,
    run_all_validator,
    run_script,
    write_json,
)
from shutil import copy2, copytree

INCIDENT_FIXTURE = REPOSITORY_ROOT / "tests" / "fixtures" / "incident-2026-08"
# 事故项目 workflow_state.json 的真实写入时刻（git commit 6ead9f3 互证）。
INCIDENT_STATE_MTIME = datetime(2026, 8, 10, 17, 37, 47, tzinfo=timezone.utc)

def copy_incident_project(temporary_directory: TemporaryDirectory[str]) -> Path:
    project = Path(temporary_directory.name) / "incident"
    copytree(INCIDENT_FIXTURE, project)
    state_path = project / "workflow_state.json"
    timestamp = INCIDENT_STATE_MTIME.timestamp()
    os.utime(state_path, (timestamp, timestamp))
    return project

class IncidentFixtureTests(unittest.TestCase):
    """事故回归：伪造时间线与跳过状态必须被检出。"""

    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory(prefix="incident-2026-08-")
        self.project = copy_incident_project(self.temporary_directory)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_default_mode_reports_warnings_without_failing(self) -> None:
        completed = run_script(
            "validate_workflow_state.py", self.project, ["--current-year", "2026"]
        )
        # 时间线与完成记录问题维持 WARNING（默认不阻断）
        self.assertIn("WARNING\tDECISION_LOG_AFTER_STATE_WRITE", completed.stdout)
        self.assertIn("WARNING\tGATE_COMPLETION_RECORD_MISSING", completed.stdout)
        # 证据深度在 schema 3.0 起是常驻 INVALID（状态机已不再逼合规项目违规）
        self.assertIn("INVALID\tEVIDENCE_DEPTH_EXCEEDS_LAYER", completed.stdout)
        self.assertEqual(1, completed.returncode, completed.stdout)

    def test_strict_mode_flags_fabricated_timeline(self) -> None:
        completed = run_script(
            "validate_workflow_state.py",
            self.project,
            ["--current-year", "2026", "--strict-new-checks"],
        )
        self.assertEqual(1, completed.returncode, completed.stdout)
        self.assertIn("INVALID\tDECISION_LOG_AFTER_STATE_WRITE", completed.stdout)
        # EVIDENCE_VALIDATE 被跳过但 gate 置真
        self.assertIn(
            "evidence_validated:requires_decision_log_state:EVIDENCE_VALIDATE",
            completed.stdout,
        )

    def test_skipped_states_have_no_completion_record(self) -> None:
        completed = run_script(
            "validate_workflow_state.py", self.project, ["--current-year", "2026"]
        )
        self.assertIn("EVIDENCE_VALIDATE", completed.stdout)
        # 事故日志同样缺少独立的 LITERATURE_REGISTER 条目
        self.assertIn("LITERATURE_REGISTER", completed.stdout)

class NewCheckSemanticsTests(unittest.TestCase):
    """新检查的 WARNING/strict 升级语义与 level/track 交叉检查。"""

    def test_valid_literature_gate_requires_active_url_ledger_pointer(self) -> None:
        temporary_directory, project = make_valid_project()
        with temporary_directory:
            state = load_json(project / "workflow_state.json")
            state["gates"]["literature_registry_valid"] = True
            state["artifacts"]["literature_registry"] = "near_neighbor_registry.json"
            write_json(project / "workflow_state.json", state)
            write_json(project / "near_neighbor_registry.json", {"records": []})

            completed = run_script(
                "validate_workflow_state.py", project, ["--current-year", "2026"]
            )
            self.assertEqual(1, completed.returncode, completed.stdout)
            self.assertIn("ARTIFACT\tworkflow_state\turl_ledger:missing_or_unsafe_path", completed.stdout)

    def test_self_declared_level_warning_then_invalid(self) -> None:
        temporary_directory, project = make_valid_project()
        with temporary_directory:
            default = run_script(
                "validate_workflow_state.py", project, ["--current-year", "2026"]
            )
            self.assertEqual(0, default.returncode, default.stdout)
            self.assertIn("WARNING\tSELF_DECLARED_LEVEL", default.stdout)

            strict = run_script(
                "validate_workflow_state.py",
                project,
                ["--current-year", "2026", "--strict-new-checks"],
            )
            self.assertEqual(1, strict.returncode, strict.stdout)
            self.assertIn("INVALID\tSELF_DECLARED_LEVEL", strict.stdout)

    def test_falsification_ledger_required_when_n0_4c_locked(self) -> None:
        """R-N0-17：n0_4_locked=true 时 novelty-audit 必须含证伪书（标题+条目）。"""
        temporary_directory, project = make_valid_project()
        with temporary_directory:
            state = load_json(project / "workflow_state.json")
            state["gates"]["n0_4_locked"] = True
            state["novelty_level"] = "N0-4C"
            state["artifacts"]["hierarchy_novelty_audit"] = "novelty-audit.md"
            write_json(project / "workflow_state.json", state)
            (project / "novelty-audit.md").write_text(
                "# Novelty audit\n\nNo falsification ledger here.\n",
                encoding="utf-8",
            )

            default = run_script(
                "validate_workflow_state.py", project, ["--current-year", "2026"]
            )
            self.assertIn("WARNING\tFALSIFICATION_LEDGER_MISSING", default.stdout)

            strict = run_script(
                "validate_workflow_state.py",
                project,
                ["--current-year", "2026", "--strict-new-checks"],
            )
            self.assertIn("INVALID\tFALSIFICATION_LEDGER_MISSING", strict.stdout)

    def test_falsification_ledger_present_passes(self) -> None:
        """R-N0-17：证伪书含标题 + 至少一条证伪路径时不报 FALSIFICATION。"""
        temporary_directory, project = make_valid_project()
        with temporary_directory:
            state = load_json(project / "workflow_state.json")
            state["gates"]["n0_4_locked"] = True
            state["novelty_level"] = "N0-4C"
            state["artifacts"]["hierarchy_novelty_audit"] = "novelty-audit.md"
            write_json(project / "workflow_state.json", state)
            (project / "novelty-audit.md").write_text(
                "# Novelty audit\n\n"
                "## 证伪书（falsification ledger）\n\n"
                "- [证伪路径] 直接占据：近邻 W-0001 未直接占据候选。\n",
                encoding="utf-8",
            )

            completed = run_script(
                "validate_workflow_state.py",
                project,
                ["--current-year", "2026", "--strict-new-checks"],
            )
            self.assertNotIn("FALSIFICATION_LEDGER_MISSING", completed.stdout)

    def test_evidence_scope_regressed_flagged(self) -> None:
        """R-LAYER-13：k_fulltext_complete=true 时 scope 清空即 EVIDENCE_SCOPE_REGRESSED。"""
        temporary_directory, project = make_valid_project()
        with temporary_directory:
            state = load_json(project / "workflow_state.json")
            state["gates"]["k_fulltext_complete"] = True
            state["artifacts"]["current_evidence_scope"] = "current_evidence_scope.json"
            write_json(project / "workflow_state.json", state)
            write_json(
                project / "current_evidence_scope.json",
                {
                    "schema_version": "2.0",
                    "collision_round": 1,
                    "fulltext_registry_ids": [],
                    "atomic_claim_ids": [],
                },
            )

            completed = run_script(
                "validate_workflow_state.py",
                project,
                ["--current-year", "2026", "--strict-new-checks"],
            )
            self.assertIn("EVIDENCE_SCOPE_REGRESSED", completed.stdout)

    def test_next_action_inconsistent_flagged(self) -> None:
        """R-LOG-04：FINAL_LOCK 下 next_required_action 含中间态提示即不一致。"""
        temporary_directory, project = make_valid_project()
        with temporary_directory:
            state = load_json(project / "workflow_state.json")
            state["active_state"] = "FINAL_LOCK"
            state["resume_state"] = "FINAL_LOCK"
            state["next_required_action"] = "推进 LAYER_DECISION 冻结贡献架构"
            write_json(project / "workflow_state.json", state)

            completed = run_script(
                "validate_workflow_state.py",
                project,
                ["--current-year", "2026", "--strict-new-checks"],
            )
            self.assertIn("NEXT_ACTION_INCONSISTENT_WITH_STATE", completed.stdout)

    def test_capability_flip_without_provenance_flagged(self) -> None:
        """R-REVIEW-20：PASS 但无 review_artifact_sha256 登记即无 provenance。"""
        temporary_directory, project = make_valid_project(validity_level="V3")
        with temporary_directory:
            state = load_json(project / "workflow_state.json")
            state["independent_audit"]["capability_available"] = True
            state["independent_audit"]["verdict"] = "PASS"
            state.pop("review_artifact_sha256", None)
            write_json(project / "workflow_state.json", state)

            completed = run_script(
                "validate_workflow_state.py",
                project,
                ["--current-year", "2026", "--strict-new-checks"],
            )
            self.assertIn("CAPABILITY_FLIPPED_WITHOUT_PROVENANCE", completed.stdout)

    def test_atomic_claim_shell_flagged(self) -> None:
        """R-ATOMIC-19：原子观点是"Paper W-XXXX proposes..."元描述即套壳。"""
        temporary_directory, project = make_valid_project()
        with temporary_directory:
            state = load_json(project / "workflow_state.json")
            state["artifacts"]["claim_registry"] = "literature_claim_registry.json"
            write_json(project / "workflow_state.json", state)
            write_json(
                project / "literature_claim_registry.json",
                {
                    "schema_version": "2.0",
                    "current_collision_round": 1,
                    "claims": [
                        {
                            "claim_id": "LC-0001",
                            "normalized_statement": "Paper W-0001 proposes a method to detect anomalies.",
                        }
                    ],
                },
            )
            completed = run_script(
                "validate_workflow_state.py",
                project,
                ["--current-year", "2026", "--strict-new-checks"],
            )
            self.assertIn("ATOMIC_CLAIM_NO_ANCHOR", completed.stdout)

    def test_atomic_claim_substantive_passes(self) -> None:
        """R-ATOMIC-19：实质断言（五要素）不报套壳。"""
        temporary_directory, project = make_valid_project()
        with temporary_directory:
            state = load_json(project / "workflow_state.json")
            state["artifacts"]["claim_registry"] = "literature_claim_registry.json"
            write_json(project / "workflow_state.json", state)
            write_json(
                project / "literature_claim_registry.json",
                {
                    "schema_version": "2.0",
                    "current_collision_round": 1,
                    "claims": [
                        {
                            "claim_id": "LC-0001",
                            "normalized_statement": "在 5-fold CV 下，双头模型相对单任务 BiLSTM 把 F1 从 0.42 提到 0.45。",
                        }
                    ],
                },
            )
            completed = run_script(
                "validate_workflow_state.py",
                project,
                ["--current-year", "2026", "--strict-new-checks"],
            )
            self.assertNotIn("ATOMIC_CLAIM_NO_ANCHOR", completed.stdout)

    def test_negative_terminal_requires_occupation_or_reduction_evidence(self) -> None:
        """R-N0-17：N0-1/N0-2 负面终局与 N0-4C 同价，须有占据/归约证据。"""
        for novelty_level, code in (
            ("N0-1", "OCCUPATION_EVIDENCE_MISSING"),
            ("N0-2", "REDUCTION_EVIDENCE_MISSING"),
        ):
            with self.subTest(novelty_level=novelty_level):
                temporary_directory, project = make_valid_project()
                with temporary_directory:
                    state = load_json(project / "workflow_state.json")
                    state["novelty_level"] = novelty_level
                    state["gates"]["n0_4_locked"] = False
                    state["artifacts"]["hierarchy_novelty_audit"] = "novelty-audit.md"
                    write_json(project / "workflow_state.json", state)
                    (project / "novelty-audit.md").write_text(
                        "# Novelty audit\n\nNo terminal evidence.\n",
                        encoding="utf-8",
                    )
                    completed = run_script(
                        "validate_workflow_state.py",
                        project,
                        ["--current-year", "2026", "--strict-new-checks"],
                    )
                    self.assertIn(f"INVALID\t{code}", completed.stdout)


def _killed_wirings() -> list[dict]:
    return [
        {
            "wiring_id": kind.lower(),
            "kind": kind,
            "procedure": f"attempt {kind}",
            "status": "KILLED",
            "kill_claim_ids": [f"LC-{index:04d}"],
            "whole_mapping_separates": True,
        }
        for index, kind in enumerate(
            ("POSTHOC_LABEL", "SCHEMA_EXTENSION", "RENAME"), start=1
        )
    ]


class L3ContractG4CompositionTests(unittest.TestCase):
    def _algorithm_n0_4c(self):
        temporary_directory, project = make_valid_project(
            claim_profile="ALGORITHM", novelty_level="N0-4C", validity_level="V0"
        )
        state = load_json(project / "workflow_state.json")
        state["claim_profile"] = "ALGORITHM"
        state["novelty_level"] = "N0-4C"
        write_json(project / "workflow_state.json", state)
        return temporary_directory, project

    def test_axis_not_in_input_warns_then_strict_invalid(self) -> None:
        temporary_directory, project = self._algorithm_n0_4c()
        with temporary_directory:
            write_json(
                project / "l3_contract.json",
                {
                    "schema_version": "2.0",
                    "inputs": ["s"],
                    "stop_axes": [
                        {"name": "identity", "depends_on": ["s", "I"]},
                    ],
                },
            )
            write_json(
                project / "composition_audit.json",
                {
                    "schema_version": "2.0",
                    "components": [
                        {
                            "component_id": "inventory",
                            "mechanical_gap": "source-first inventory is not post-hoc labeling",
                        }
                    ],
                    "union_equals_candidate": False,
                    "reduction_failed_because": "conjunction does not yield the accept token",
                },
            )
            default = run_script(
                "validate_workflow_state.py", project, ["--current-year", "2026"]
            )
            self.assertEqual(0, default.returncode, default.stdout)
            self.assertIn("WARNING\tAXIS_NOT_IN_INPUT", default.stdout)
            self.assertIn("axis:identity;dep:I", default.stdout)
            strict = run_script(
                "validate_workflow_state.py",
                project,
                ["--current-year", "2026", "--strict-new-checks"],
            )
            self.assertEqual(1, strict.returncode, strict.stdout)
            self.assertIn("INVALID\tAXIS_NOT_IN_INPUT", strict.stdout)

    def test_walkthrough_only_cannot_lock_n0_4c(self) -> None:
        temporary_directory, project = self._algorithm_n0_4c()
        with temporary_directory:
            write_json(
                project / "l3_contract.json",
                {
                    "schema_version": "2.0",
                    "inputs": ["s", "I"],
                    "stop_axes": [{"name": "identity", "depends_on": ["s", "I"]}],
                },
            )
            write_json(
                project / "composition_audit.json",
                {
                    "schema_version": "2.0",
                    "components": [
                        {
                            "component_id": "inventory",
                            "mechanical_gap": "source-first inventory is not post-hoc labeling",
                        }
                    ],
                    "union_equals_candidate": False,
                    "reduction_failed_because": "conjunction does not yield the accept token",
                },
            )
            write_json(
                project / "instance_probe_registry.json",
                {
                    "schema_version": "2.0",
                    "authorization_note": "inspect published figure",
                    "probes": [
                        {
                            "probe_id": "IP-0001",
                            "purpose": "SUPPORT",
                            "g4_role": "DESIGN_WALKTHROUGH",
                            "old_metric_verdict": "UNDEFINED",
                        }
                    ],
                },
            )
            completed = run_script(
                "validate_workflow_state.py",
                project,
                ["--current-year", "2026", "--strict-new-checks"],
            )
            self.assertIn("INVALID\tG4_WALKTHROUGH_ONLY", completed.stdout)

    def test_not_a_threshold_cannot_be_counterexample(self) -> None:
        temporary_directory, project = self._algorithm_n0_4c()
        with temporary_directory:
            write_json(
                project / "instance_probe_registry.json",
                {
                    "schema_version": "2.0",
                    "authorization_note": "inspect table 1",
                    "probes": [
                        {
                            "probe_id": "IP-0002",
                            "purpose": "COUNTEREXAMPLE",
                            "g4_role": "NOT_A_THRESHOLD",
                            "old_metric_verdict": "FAIL",
                        }
                    ],
                },
            )
            completed = run_script(
                "validate_workflow_state.py", project, ["--current-year", "2026"]
            )
            self.assertIn("WARNING\tG4_NOT_A_THRESHOLD_AS_COUNTEREXAMPLE", completed.stdout)

    def test_composition_union_blocks_n0_4c(self) -> None:
        temporary_directory, project = self._algorithm_n0_4c()
        with temporary_directory:
            write_json(
                project / "l3_contract.json",
                {
                    "schema_version": "2.0",
                    "inputs": ["s", "I"],
                    "stop_axes": [{"name": "identity", "depends_on": ["s", "I"]}],
                },
            )
            write_json(
                project / "composition_audit.json",
                {
                    "schema_version": "2.0",
                    "components": [
                        {
                            "component_id": "all_neighbors",
                            "mechanical_gap": "none; the union is the candidate",
                        }
                    ],
                    "union_equals_candidate": True,
                    "reduction_failed_because": "it does reduce",
                },
            )
            completed = run_script(
                "validate_workflow_state.py",
                project,
                ["--current-year", "2026", "--strict-new-checks"],
            )
            self.assertIn("INVALID\tCOMPOSITION_REDUCES", completed.stdout)

    def test_theory_profile_does_not_require_algorithm_contracts(self) -> None:
        temporary_directory, project = make_valid_project(
            claim_profile="THEORY", novelty_level="N0-4C", validity_level="V0"
        )
        with temporary_directory:
            state = load_json(project / "workflow_state.json")
            state["gates"]["n0_4_locked"] = True
            write_json(project / "workflow_state.json", state)
            completed = run_script(
                "validate_workflow_state.py", project, ["--current-year", "2026"]
            )
            self.assertNotIn("L3_CONTRACT_MISSING", completed.stdout)
            self.assertNotIn("COMPOSITION_AUDIT_MISSING", completed.stdout)

    def test_weak_posthoc_wiring_cannot_lock_n0_4c(self) -> None:
        """只杀死后贴标签、未打 schema-extension，strict 不得 N0-4C。"""
        temporary_directory, project = self._algorithm_n0_4c()
        with temporary_directory:
            write_json(
                project / "l3_contract.json",
                {
                    "schema_version": "2.0",
                    "inputs": ["s", "I"],
                    "generated": ["p"],
                    "stop_axes": [
                        {"name": "two_sided_certificate", "depends_on": ["s", "p"]}
                    ],
                },
            )
            write_json(
                project / "composition_audit.json",
                {
                    "schema_version": "2.0",
                    "components": [
                        {
                            "component_id": "posthoc",
                            "mechanical_gap": "labels after extraction are not the stop",
                        }
                    ],
                    "wirings": [
                        {
                            "wiring_id": "posthoc_label",
                            "kind": "POSTHOC_LABEL",
                            "procedure": "run neighbor then glue labels",
                            "status": "KILLED",
                            "kill_claim_ids": ["LC-0001"],
                            "whole_mapping_separates": True,
                        }
                    ],
                    "strongest_remaining": "SCHEMA_EXTENSION",
                    "union_equals_candidate": False,
                    "reduction_failed_because": "posthoc labels are not the candidate",
                },
            )
            completed = run_script(
                "validate_workflow_state.py",
                project,
                ["--current-year", "2026", "--strict-new-checks"],
            )
            self.assertEqual(1, completed.returncode, completed.stdout)
            self.assertIn("INVALID\tWIRING_KIND_MISSING", completed.stdout)
            self.assertIn("kind:SCHEMA_EXTENSION", completed.stdout)
            self.assertIn("INVALID\tWIRING_STILL_ALIVE", completed.stdout)

    def test_generated_output_may_be_a_stop_dependency(self) -> None:
        temporary_directory, project = self._algorithm_n0_4c()
        with temporary_directory:
            write_json(
                project / "l3_contract.json",
                {
                    "schema_version": "2.0",
                    "inputs": ["s", "I"],
                    "generated": ["p"],
                    "stop_axes": [
                        {"name": "two_sided_certificate", "depends_on": ["s", "p"]}
                    ],
                },
            )
            write_json(
                project / "composition_audit.json",
                {
                    "schema_version": "2.0",
                    "components": [
                        {
                            "component_id": "inventory",
                            "mechanical_gap": "source-first inventory is not post-hoc labeling",
                        }
                    ],
                    "wirings": _killed_wirings(),
                    "strongest_remaining": "",
                    "union_equals_candidate": False,
                    "reduction_failed_because": "required wirings killed on whole-mapping separations",
                },
            )
            completed = run_script(
                "validate_workflow_state.py", project, ["--current-year", "2026"]
            )
            self.assertNotIn("AXIS_NOT_IN_INPUT", completed.stdout)
            self.assertNotIn("WIRING_KIND_MISSING", completed.stdout)

    def test_p_loc_in_exact_statement_requires_generated_p(self) -> None:
        temporary_directory, project = self._algorithm_n0_4c()
        with temporary_directory:
            (project / "l3-exact.md").write_text(
                "Each item needs a two-sided certificate (src_span, p_loc).\n",
                encoding="utf-8",
            )
            write_json(
                project / "l3_contract.json",
                {
                    "schema_version": "2.0",
                    "inputs": ["s", "I"],
                    "stop_axes": [{"name": "identity", "depends_on": ["s", "I"]}],
                },
            )
            state = load_json(project / "workflow_state.json")
            state["active_state"] = "N0_AUDIT"
            state["resume_state"] = "N0_AUDIT"
            state["artifacts"]["exact_statement"] = "l3-exact.md"
            state["artifacts"]["l3_contract"] = "l3_contract.json"
            write_json(project / "workflow_state.json", state)
            completed = run_script(
                "validate_workflow_state.py", project, ["--current-year", "2026"]
            )
            self.assertIn("WARNING\tAXIS_NOT_IN_INPUT", completed.stdout)
            self.assertIn("dep:p", completed.stdout)

    def test_negative_terminal_evidence_present_passes(self) -> None:
        """R-N0-17：占据/归约证据节存在时不报缺失。"""
        temporary_directory, project = make_valid_project()
        with temporary_directory:
            state = load_json(project / "workflow_state.json")
            state["novelty_level"] = "N0-1"
            state["gates"]["n0_4_locked"] = False
            state["artifacts"]["hierarchy_novelty_audit"] = "novelty-audit.md"
            write_json(project / "workflow_state.json", state)
            (project / "novelty-audit.md").write_text(
                "# Novelty audit\n\n"
                "## 占据证据（occupation evidence）\n\n"
                "- [占据] 近邻 W-0001 已直接占据候选。\n",
                encoding="utf-8",
            )
            completed = run_script(
                "validate_workflow_state.py",
                project,
                ["--current-year", "2026", "--strict-new-checks"],
            )
            self.assertNotIn("OCCUPATION_EVIDENCE_MISSING", completed.stdout)

    def test_derived_tier_drives_contribution_check(self) -> None:
        """active_layer 已删除：证据层级由 active_state 派生并驱动 CONTRIBUTION 检查。"""
        temporary_directory, project = make_valid_project()
        with temporary_directory:
            state = load_json(project / "workflow_state.json")
            # CLAIM_FREEZE（tier L3）下 contribution=M 合法；退到 tier L1 状态即非法
            state["active_state"] = "RECENT_FRONTIER"
            state["resume_state"] = "RECENT_FRONTIER"
            write_json(project / "workflow_state.json", state)
            completed = run_script(
                "validate_workflow_state.py",
                project,
                ["--current-year", "2026"],
            )
            self.assertIn("CONTRIBUTION", completed.stdout)
            self.assertIn("tier:L1;expected:NONE", completed.stdout)

    def test_complete_requires_final_lock_conditions(self) -> None:
        temporary_directory, project = make_valid_project(validity_level="V3")
        with temporary_directory:
            state = load_json(project / "workflow_state.json")
            state["active_state"] = "COMPLETE"
            state["resume_state"] = "COMPLETE"
            state["gates"]["scope_locked"] = True
            state["gates"]["evidence_validated"] = True
            write_json(project / "workflow_state.json", state)
            completed = run_script(
                "validate_workflow_state.py",
                project,
                ["--current-year", "2026", "--strict-new-checks"],
            )
            self.assertIn(
                "COMPLETE_REQUIRES_FINAL_LOCK_CONDITIONS", completed.stdout
            )
            self.assertIn("COMPLETE_REQUIRES_USER_ACCEPTANCE", completed.stdout)

    def test_complete_requires_user_acceptance_even_with_v4(self) -> None:
        temporary_directory, project = make_valid_project(validity_level="V4")
        with temporary_directory:
            state = load_json(project / "workflow_state.json")
            state["active_state"] = "COMPLETE"
            state["resume_state"] = "COMPLETE"
            state["novelty_level"] = "N0-4C"
            state["gates"]["n0_4_locked"] = True
            state["gates"]["scope_locked"] = True
            state["gates"]["evidence_validated"] = True
            write_json(project / "workflow_state.json", state)
            completed = run_script(
                "validate_workflow_state.py",
                project,
                ["--current-year", "2026"],
            )
            self.assertIn("COMPLETE_REQUIRES_USER_ACCEPTANCE", completed.stdout)
            self.assertEqual(1, completed.returncode)

    def test_protocol_sealed_access_contradiction(self) -> None:
        temporary_directory, project = make_valid_project(claim_profile="ALGORITHM")
        with temporary_directory:
            protocol = load_json(project / "protocol_contract.json")
            protocol["sealed_confirmation_data"] = "NOT_YET_ACCESSED"
            write_json(project / "protocol_contract.json", protocol)
            write_json(
                project / "compute_evidence.json",
                {
                    "schema_version": "2.0",
                    "compute_stage": "S4",
                    "verdict": "PASS",
                    "data_sources": [
                        {"name": "synthetic-dev", "synthetic": True, "provenance": "unit"}
                    ],
                    "B_X": {
                        "per_run": [
                            {
                                "unit": "held-out-collapse",
                                "split": "sealed",
                                "algorithm": "FAIL",
                                "comparator": "ACCEPT",
                                "unseen_fingerprint": "never-seen-token-xyz",
                            }
                        ]
                    },
                },
            )
            state = load_json(project / "workflow_state.json")
            state["active_state"] = "FINAL_LOCK"
            state["resume_state"] = "FINAL_LOCK"
            state["compute_stage"] = "S4"
            state["gates"]["compute_authorized"] = True
            state["compute_evidence"] = {
                "status": "COMPLETED",
                "validation_epoch": 1,
                "artifact_path": "compute_evidence.json",
                "artifact_sha256": "0" * 64,
            }
            write_json(project / "workflow_state.json", state)
            completed = run_script(
                "validate_workflow_state.py",
                project,
                ["--current-year", "2026"],
            )
            self.assertIn("PROTOCOL_SEALED_ACCESS_CONTRADICTION", completed.stdout)
            self.assertEqual(1, completed.returncode)

    def test_sealed_unit_seen_in_precompute(self) -> None:
        temporary_directory, project = make_valid_project(claim_profile="ALGORITHM")
        with temporary_directory:
            write_json(
                project / "compute_evidence.json",
                {
                    "schema_version": "2.0",
                    "compute_stage": "S4",
                    "verdict": "PASS",
                    "data_sources": [
                        {"name": "synthetic-dev", "synthetic": True, "provenance": "unit"}
                    ],
                    "B_X": {
                        "per_run": [
                            {
                                "unit": "held-out-collapse",
                                "split": "sealed",
                                "algorithm": "FAIL",
                                "comparator": "ACCEPT",
                                "unseen_fingerprint": "evaluate_online",
                            }
                        ]
                    },
                },
            )
            state = load_json(project / "workflow_state.json")
            state["compute_stage"] = "S4"
            state["gates"]["compute_authorized"] = True
            state["compute_evidence"] = {
                "status": "COMPLETED",
                "validation_epoch": 1,
                "artifact_path": "compute_evidence.json",
                "artifact_sha256": "0" * 64,
            }
            write_json(project / "workflow_state.json", state)
            completed = run_script(
                "validate_workflow_state.py",
                project,
                ["--current-year", "2026", "--strict-new-checks"],
            )
            self.assertIn("SEALED_UNIT_SEEN_IN_PRECOMPUTE", completed.stdout)
            self.assertEqual(1, completed.returncode)

    def test_sealed_empty_inventory_and_shared_runner_are_invalid(self) -> None:
        temporary_directory, project = make_valid_project(claim_profile="ALGORITHM")
        with temporary_directory:
            (project / "compute").mkdir()
            (project / "compute" / "same.py").write_text("print(0)\n", encoding="utf-8")
            write_json(
                project / "compute_evidence.json",
                {
                    "schema_version": "2.0",
                    "compute_stage": "S4",
                    "verdict": "PASS",
                    "dev_runner": "compute/same.py",
                    "sealed_runner": "compute/same.py",
                    "data_sources": [
                        {"name": "synthetic-dev", "synthetic": True, "provenance": "unit"}
                    ],
                    "B_X": {
                        "per_run": [
                            {
                                "unit": "empty-seal",
                                "split": "sealed",
                                "algorithm": "FAIL-SPURIOUS-ATOM",
                                "comparator": "ACCEPT",
                                "inventory_atoms": [],
                                "unseen_fingerprint": "n_unique_seal",
                            }
                        ]
                    },
                },
            )
            state = load_json(project / "workflow_state.json")
            state["compute_evidence"] = {
                "status": "COMPLETED",
                "validation_epoch": 1,
                "artifact_path": "compute_evidence.json",
                "artifact_sha256": "0" * 64,
            }
            write_json(project / "workflow_state.json", state)
            completed = run_script(
                "validate_workflow_state.py", project, ["--current-year", "2026"]
            )
            self.assertIn("SEALED_INVENTORY_EMPTY", completed.stdout)
            self.assertIn("SEALED_RUNNER_NOT_INDEPENDENT", completed.stdout)
            self.assertEqual(1, completed.returncode)

    def test_sealed_conjunct_must_hit_frozen_stop(self) -> None:
        temporary_directory, project = make_valid_project(claim_profile="ALGORITHM")
        with temporary_directory:
            inventory = load_json(project / "claim_inventory.json")
            for claim in inventory["claims"]:
                if claim.get("claim_id") == "C-ALGORITHM-1":
                    claim["s4_conjuncts"] = ["FAIL-OMISSION", "FAIL-COLLAPSE"]
            write_json(project / "claim_inventory.json", inventory)
            (project / "compute").mkdir()
            (project / "compute" / "dev_runner.py").write_text(
                "print('dev')\n", encoding="utf-8"
            )
            (project / "compute" / "sealed_runner.py").write_text(
                "print('sealed')\n", encoding="utf-8"
            )
            write_json(
                project / "compute_evidence.json",
                {
                    "schema_version": "2.0",
                    "compute_stage": "S4",
                    "verdict": "PASS",
                    "dev_runner": "compute/dev_runner.py",
                    "sealed_runner": "compute/sealed_runner.py",
                    "data_sources": [
                        {"name": "synthetic-dev", "synthetic": True, "provenance": "unit"}
                    ],
                    "B_X": {
                        "per_run": [
                            {
                                "unit": "accept-only",
                                "split": "sealed",
                                "decision": "ACCEPT",
                                "inventory_atoms": ["TREATS"],
                                "unseen_fingerprint": "n_hold_out_only",
                            }
                        ]
                    },
                },
            )
            state = load_json(project / "workflow_state.json")
            state["compute_evidence"] = {
                "status": "COMPLETED",
                "validation_epoch": 1,
                "artifact_path": "compute_evidence.json",
                "artifact_sha256": "0" * 64,
            }
            write_json(project / "workflow_state.json", state)
            missed = run_script(
                "validate_workflow_state.py", project, ["--current-year", "2026"]
            )
            self.assertIn("SEALED_CONJUNCT_NOT_HIT", missed.stdout)
            self.assertEqual(1, missed.returncode)
            evidence = load_json(project / "compute_evidence.json")
            evidence["B_X"]["per_run"][0]["decision"] = "FAIL-OMISSION"
            write_json(project / "compute_evidence.json", evidence)
            hit = run_script(
                "validate_workflow_state.py", project, ["--current-year", "2026"]
            )
            self.assertNotIn("SEALED_CONJUNCT_NOT_HIT", hit.stdout)

    def test_sealed_fingerprint_seen_in_implementation_is_invalid(self) -> None:
        temporary_directory, project = make_valid_project(claim_profile="ALGORITHM")
        with temporary_directory:
            (project / "compute").mkdir()
            (project / "compute" / "dev_runner.py").write_text(
                "print('dev')\n", encoding="utf-8"
            )
            (project / "compute" / "sealed_runner.py").write_text(
                "TOKEN_n_impl_seen = 1\n", encoding="utf-8"
            )
            (project / "implementation" / "old_probe.py").write_text(
                "TOKEN_n_impl_seen = 0\n", encoding="utf-8"
            )
            write_json(
                project / "compute_evidence.json",
                {
                    "schema_version": "2.0",
                    "compute_stage": "S4",
                    "verdict": "PASS",
                    "dev_runner": "compute/dev_runner.py",
                    "sealed_runner": "compute/sealed_runner.py",
                    "data_sources": [
                        {"name": "synthetic-dev", "synthetic": True, "provenance": "unit"}
                    ],
                    "B_X": {
                        "per_run": [
                            {
                                "unit": "impl-leak",
                                "split": "sealed",
                                "decision": "FAIL-OMISSION",
                                "inventory_atoms": ["TREATS"],
                                "unseen_fingerprint": "TOKEN_n_impl_seen",
                            }
                        ]
                    },
                },
            )
            state = load_json(project / "workflow_state.json")
            state["compute_evidence"] = {
                "status": "COMPLETED",
                "validation_epoch": 1,
                "artifact_path": "compute_evidence.json",
                "artifact_sha256": "0" * 64,
            }
            write_json(project / "workflow_state.json", state)
            completed = run_script(
                "validate_workflow_state.py", project, ["--current-year", "2026"]
            )
            self.assertIn("SEALED_UNIT_SEEN_IN_PRECOMPUTE", completed.stdout)
            self.assertIn("implementation/old_probe.py", completed.stdout)
            self.assertEqual(1, completed.returncode)

    def test_exact_inventory_mismatch_and_narrower_escape(self) -> None:
        temporary_directory, project = make_valid_project()
        with temporary_directory:
            inventory = load_json(project / "claim_inventory.json")
            statements = [
                claim["statement"]
                for claim in inventory["claims"]
                if claim.get("status") == "FROZEN"
            ]
            (project / "l3-exact.md").write_text(
                "A broader exact sentence that does not repeat the inventory.\n",
                encoding="utf-8",
            )
            (project / "manuscript.md").write_text(
                "\n".join(statements) + "\n", encoding="utf-8"
            )
            state = load_json(project / "workflow_state.json")
            state["active_state"] = "CLAIM_FREEZE"
            state["resume_state"] = "CLAIM_FREEZE"
            state["artifacts"]["exact_statement"] = "l3-exact.md"
            state["artifacts"]["claim_inventory"] = "claim_inventory.json"
            write_json(project / "workflow_state.json", state)
            completed = run_script(
                "validate_workflow_state.py", project, ["--current-year", "2026"]
            )
            self.assertIn("EXACT_INVENTORY_MISMATCH", completed.stdout)
            inventory["exact_alignment"] = {
                "status": "NARROWER",
                "does_not_underwrite_exact": True,
                "validity_source": "manuscript.md",
            }
            write_json(project / "claim_inventory.json", inventory)
            passed = run_script(
                "validate_workflow_state.py", project, ["--current-year", "2026"]
            )
            self.assertNotIn("EXACT_INVENTORY_MISMATCH", passed.stdout)

class StopLockTests(unittest.TestCase):
    """STOP 锁：写入、拦截、推进检测、解锁。"""

    def test_lock_lifecycle(self) -> None:
        temporary_directory, project = make_valid_project()
        with temporary_directory:
            state_path = project / "workflow_state.json"
            lock_path = project / ".workflow_stop.lock"

            # 1. 制造 INVALID（年份错误），锁应写入
            state = load_json(state_path)
            state["current_year"] = 2025
            write_json(state_path, state)
            first = run_all_validator(project, lock_enabled=True)
            self.assertEqual(1, first.returncode, first.stdout)
            self.assertTrue(lock_path.exists())
            self.assertIn("STOP_LOCK_WRITTEN", first.stdout)

            # 2. 状态未变：直接拦截，不再跑校验器
            second = run_all_validator(project, lock_enabled=True)
            self.assertEqual(1, second.returncode, second.stdout)
            self.assertIn("STOP\tworkflow_stop_lock_active", second.stdout)
            self.assertNotIn("=== workflow_state ===", second.stdout)

            # 3. 修复年份但同时推进状态：重新校验并报 STATE_ADVANCED_UNDER_STOP_LOCK
            state = load_json(state_path)
            state["current_year"] = 2026
            state["active_state"] = "VALIDITY_AUDIT"
            state["resume_state"] = "VALIDITY_AUDIT"
            state["validity_level"] = "V1"
            write_json(state_path, state)
            third = run_all_validator(project, lock_enabled=True)
            self.assertEqual(1, third.returncode, third.stdout)
            self.assertIn("STATE_ADVANCED_UNDER_STOP_LOCK", third.stdout)

            # 4. 无 note 解锁被拒
            fourth = run_all_validator(
                project, ["--clear-lock"], lock_enabled=True
            )
            self.assertEqual(1, fourth.returncode, fourth.stdout)
            self.assertIn("CLEAR_LOCK_REQUIRES_RECOVERY_NOTE", fourth.stdout)

            # 5. 带 note 解锁：锁删除、validation.log 留痕、重新校验
            fifth = run_all_validator(
                project,
                ["--clear-lock", "--recovery-note", "epoch rebuilt"],
                lock_enabled=True,
            )
            self.assertEqual(0, fifth.returncode, fifth.stdout)
            self.assertFalse(lock_path.exists())
            log_text = (project / "validation.log").read_text(encoding="utf-8")
            self.assertIn("LOCK_CLEARED", log_text)
            self.assertIn("epoch rebuilt", log_text)

    def test_lock_bypassed_by_default_in_helpers(self) -> None:
        temporary_directory, project = make_valid_project()
        with temporary_directory:
            state = load_json(project / "workflow_state.json")
            state["current_year"] = 2025
            write_json(project / "workflow_state.json", state)
            completed = run_all_validator(project)
            self.assertEqual(1, completed.returncode, completed.stdout)
            self.assertFalse((project / ".workflow_stop.lock").exists())

class EvidenceDispatchTests(unittest.TestCase):
    """中间态部分证据文件不再误报 EVIDENCE_REQUIRED。"""

    def test_partial_evidence_files_skip_cleanly(self) -> None:
        temporary_directory, project = make_valid_project()
        with temporary_directory:
            # make_valid_project 不复制三个证据文件；只补一个制造"部分存在"。
            copy2(
                MINIMAL_VALID_V3 / "near_neighbor_registry.json",
                project / "near_neighbor_registry.json",
            )
            completed = run_all_validator(project)
            self.assertIn("SKIP\tpartial_or_not_required", completed.stdout)
            self.assertNotIn("EVIDENCE_REQUIRED", completed.stdout)
            self.assertEqual(0, completed.returncode, completed.stdout)

class EvidenceDepthBudgetTests(unittest.TestCase):
    """R-LAYER-13：证据深度按段供给，超段超量报 EVIDENCE_DEPTH_EXCEEDS_LAYER。

    schema 3.0 起证据层级由 active_state 派生（不再持久化 active_layer），
    且本检查为常驻 INVALID（状态机三段式排布后，合规流程不会超预算）。
    """

    # 各证据层级的代表状态与合法 contribution
    TIER_STATES = {
        "L1": ("RECENT_FRONTIER", "NONE"),
        "L2": ("L2_TRIAGE", "NONE"),
        "L3": ("CLAIM_FREEZE", "M"),
    }

    def setUp(self) -> None:
        self.tmp, self.project = make_valid_project()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_state(self, *extra: str):
        return run_script("validate_workflow_state.py", self.project, extra)

    def set_tier(self, tier: str) -> None:
        active_state, contribution = self.TIER_STATES[tier]
        state = load_json(self.project / "workflow_state.json")
        state["active_state"] = active_state
        state["resume_state"] = active_state
        state["active_contribution"] = contribution
        write_json(self.project / "workflow_state.json", state)

    def write_registries(self, fulltext: int, claims: int) -> None:
        write_json(
            self.project / "near_neighbor_registry.json",
            {
                "records": [
                    {
                        "registry_id": f"W-{index:04d}",
                        "download": {"status": "FULLTEXT_ARCHIVED"},
                    }
                    for index in range(fulltext)
                ]
            },
        )
        write_json(
            self.project / "literature_claim_registry.json",
            {"records": [{"claim_id": f"LC-{index:04d}"} for index in range(claims)]},
        )

    def write_current_evidence_scope(
        self,
        *,
        fulltext_registry_ids: list[str],
        atomic_claim_ids: list[str],
    ) -> None:
        state = load_json(self.project / "workflow_state.json")
        state.setdefault("artifacts", {})["current_evidence_scope"] = (
            "current_evidence_scope.json"
        )
        write_json(self.project / "workflow_state.json", state)
        write_json(
            self.project / "current_evidence_scope.json",
            {
                "schema_version": "2.0",
                "collision_round": state["collision_round"],
                "fulltext_registry_ids": fulltext_registry_ids,
                "atomic_claim_ids": atomic_claim_ids,
            },
        )

    def test_l1_allows_zero_deep_evidence(self) -> None:
        self.set_tier("L1")
        result = self.run_state("--current-year", "2026")
        self.assertNotIn("EVIDENCE_DEPTH_EXCEEDS_LAYER", result.stdout)

    def test_l1_fulltext_is_over_depth(self) -> None:
        self.set_tier("L1")
        self.write_registries(fulltext=1, claims=0)
        result = self.run_state("--current-year", "2026")
        self.assertIn("INVALID\tEVIDENCE_DEPTH_EXCEEDS_LAYER", result.stdout)
        self.assertIn("tier:L1;fulltext:1>budget:0", result.stdout)
        self.assertEqual(1, result.returncode, result.stdout + result.stderr)

    def test_l1_budget_uses_current_scope_not_historical_global_registry(self) -> None:
        self.set_tier("L1")
        self.write_registries(fulltext=1, claims=1)
        self.write_current_evidence_scope(
            fulltext_registry_ids=[],
            atomic_claim_ids=[],
        )

        result = self.run_state("--current-year", "2026")

        self.assertNotIn("EVIDENCE_DEPTH_EXCEEDS_LAYER", result.stdout)

    def test_l1_scoped_fulltext_is_charged_to_current_budget(self) -> None:
        self.set_tier("L1")
        self.write_registries(fulltext=1, claims=0)
        self.write_current_evidence_scope(
            fulltext_registry_ids=["W-0000"],
            atomic_claim_ids=[],
        )

        result = self.run_state("--current-year", "2026")

        self.assertIn("tier:L1;fulltext:1>budget:0", result.stdout)

    def test_current_scope_rejects_unknown_registry_ids(self) -> None:
        self.set_tier("L1")
        self.write_registries(fulltext=1, claims=1)
        self.write_current_evidence_scope(
            fulltext_registry_ids=["W-9999"],
            atomic_claim_ids=["LC-9999"],
        )

        result = self.run_state("--current-year", "2026")

        self.assertIn("CURRENT_EVIDENCE_SCOPE_INVALID", result.stdout)
        self.assertIn("unknown_fulltext_registry_id:W-9999", result.stdout)
        self.assertIn("unknown_atomic_claim_id:LC-9999", result.stdout)

    def test_global_url_registry_and_empty_current_scope_can_coexist(self) -> None:
        self.set_tier("L1")
        write_json(
            self.project / "near_neighbor_registry.json",
            {
                "records": [
                    {
                        "registry_id": "W-HISTORICAL",
                        "canonical_url": "https://arxiv.org/abs/2401.00001",
                        "publication_status": "PREPRINT_ONLY",
                        "terminal_rejection_eligibility": "NOT_QUALIFIED",
                        "peer_review_status": "NON_PEER_REVIEWED",
                        "download": {"status": "FULLTEXT_ARCHIVED"},
                    }
                ],
                "peer_reviewed_published_count": 0,
                "search_mode": "SEARCH_OPEN",
                "synthesis_lock_threshold": 100,
            },
        )
        write_json(self.project / "literature_claim_registry.json", {"records": []})
        (self.project / "notes.md").write_text(
            "Historical source: https://arxiv.org/pdf/2401.00001\n",
            encoding="utf-8",
        )
        self.write_current_evidence_scope(
            fulltext_registry_ids=[],
            atomic_claim_ids=[],
        )

        state_result = self.run_state("--current-year", "2026")
        literature_result = run_script(
            "validate_literature_registry.py",
            self.project,
            ("--registry", str(self.project / "near_neighbor_registry.json")),
        )

        self.assertNotIn("EVIDENCE_DEPTH_EXCEEDS_LAYER", state_result.stdout)
        self.assertNotIn("UNREGISTERED", literature_result.stdout)
        self.assertEqual(0, literature_result.returncode, literature_result.stdout)

    def test_l2_atomic_claims_are_over_depth(self) -> None:
        self.set_tier("L2")
        self.write_registries(fulltext=3, claims=5)
        result = self.run_state("--current-year", "2026")
        self.assertIn("tier:L2;atomic_claims:5>budget:0", result.stdout)
        self.assertNotIn("fulltext:3>budget", result.stdout)

    def test_l3_within_budget_is_clean(self) -> None:
        self.set_tier("L3")
        self.write_registries(fulltext=8, claims=40)
        result = self.run_state("--current-year", "2026")
        self.assertNotIn("EVIDENCE_DEPTH_EXCEEDS_LAYER", result.stdout)

    def test_l3_waiver_allows_user_authorized_overage(self) -> None:
        self.set_tier("L3")
        self.write_registries(fulltext=21, claims=40)
        state = load_json(self.project / "workflow_state.json")
        state.setdefault("decision_log", []).append(
            {
                "at": "2026-08-18T00:00:00Z",
                "state": "N0_AUDIT",
                "action": (
                    "EVIDENCE_DEPTH_WAIVER fulltext<=24 claims<=65 "
                    "reason=user authorized extra K to kill invert-pi wiring"
                ),
            }
        )
        write_json(self.project / "workflow_state.json", state)
        result = self.run_state("--current-year", "2026")
        self.assertNotIn("EVIDENCE_DEPTH_EXCEEDS_LAYER", result.stdout)

    def test_l3_without_waiver_still_blocks_overage(self) -> None:
        self.set_tier("L3")
        self.write_registries(fulltext=21, claims=40)
        result = self.run_state("--current-year", "2026")
        self.assertIn("INVALID\tEVIDENCE_DEPTH_EXCEEDS_LAYER", result.stdout)
        self.assertIn("tier:L3;fulltext:21>budget:20", result.stdout)

    def test_missing_registries_do_not_crash(self) -> None:
        self.set_tier("L3")
        result = self.run_state("--current-year", "2026")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_registry_pointer_falls_back_to_default_and_counts(self) -> None:
        # 声明路径落空 ≠ 证据为零：回退默认路径计数，预算仍然生效
        self.set_tier("L1")
        self.write_registries(fulltext=1, claims=0)
        state = load_json(self.project / "workflow_state.json")
        state.setdefault("artifacts", {})["literature_registry"] = (
            "workflow_current/round2/pending/near_neighbor_registry.json"
        )
        write_json(self.project / "workflow_state.json", state)

        result = self.run_state("--current-year", "2026")

        self.assertIn("WARNING\tREGISTRY_POINTER_MISSING", result.stdout)
        self.assertIn("counted_default:near_neighbor_registry.json", result.stdout)
        self.assertIn("INVALID\tEVIDENCE_DEPTH_EXCEEDS_LAYER", result.stdout)
        self.assertIn("tier:L1;fulltext:1>budget:0", result.stdout)
        self.assertEqual(1, result.returncode, result.stdout + result.stderr)

    def test_registry_pointer_missing_is_warning_when_budget_clean(self) -> None:
        self.set_tier("L3")
        self.write_registries(fulltext=1, claims=1)
        state = load_json(self.project / "workflow_state.json")
        state.setdefault("artifacts", {})["claim_registry"] = (
            "workflow_current/round2/pending/literature_claim_registry.json"
        )
        write_json(self.project / "workflow_state.json", state)

        result = self.run_state("--current-year", "2026")

        self.assertIn("WARNING\tREGISTRY_POINTER_MISSING", result.stdout)
        self.assertNotIn("EVIDENCE_DEPTH_EXCEEDS_LAYER", result.stdout)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_incident_fixture_reports_both_dimensions(self) -> None:
        incident_tmp = TemporaryDirectory(prefix="incident-depth-")
        self.addCleanup(incident_tmp.cleanup)
        project = copy_incident_project(incident_tmp)
        result = run_script(
            "validate_workflow_state.py", project, ("--current-year", "2026")
        )
        self.assertIn("tier:L3;fulltext:38>budget:20", result.stdout)
        self.assertIn("tier:L3;atomic_claims:128>budget:60", result.stdout)


if __name__ == "__main__":
    unittest.main()
