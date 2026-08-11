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
