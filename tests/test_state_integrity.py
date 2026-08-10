"""第 1 期状态完整性检查：decision_log 时间完整性、gate 完成记录、STOP 锁。"""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone
from pathlib import Path

from tempfile import TemporaryDirectory

from tests.helpers import (
    MINIMAL_VALID_V2,
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
        self.assertEqual(0, completed.returncode, completed.stdout)
        self.assertIn("WARNING\tDECISION_LOG_AFTER_STATE_WRITE", completed.stdout)
        self.assertIn("WARNING\tGATE_COMPLETION_RECORD_MISSING", completed.stdout)

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

    def test_track_state_mismatch(self) -> None:
        temporary_directory, project = make_valid_project()
        with temporary_directory:
            state = load_json(project / "workflow_state.json")
            state["active_track"] = "NOVELTY"
            write_json(project / "workflow_state.json", state)
            completed = run_script(
                "validate_workflow_state.py",
                project,
                ["--current-year", "2026", "--strict-new-checks"],
            )
            self.assertIn("TRACK_STATE_MISMATCH", completed.stdout)

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
                MINIMAL_VALID_V2 / "near_neighbor_registry.json",
                project / "near_neighbor_registry.json",
            )
            completed = run_all_validator(project)
            self.assertIn("SKIP\tpartial_or_not_required", completed.stdout)
            self.assertNotIn("EVIDENCE_REQUIRED", completed.stdout)
            self.assertEqual(0, completed.returncode, completed.stdout)

if __name__ == "__main__":
    unittest.main()
