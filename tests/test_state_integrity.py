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
