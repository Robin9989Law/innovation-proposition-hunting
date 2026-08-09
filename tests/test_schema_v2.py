from __future__ import annotations

import stat
import subprocess
import sys
import unittest
from pathlib import Path
from shutil import copytree
from tempfile import TemporaryDirectory

from tests.helpers import (
    load_json,
    make_valid_project,
    run_all_validator,
    run_schema_validator,
    write_json,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = REPOSITORY_ROOT / "tests" / "fixtures" / "paper1-failure-case"


class SchemaV2MigrationTests(unittest.TestCase):
    def test_schema_v1_requires_migration(self) -> None:
        with TemporaryDirectory(prefix="schema-v2-fixture-") as temporary_directory:
            fixture_copy = Path(temporary_directory) / FIXTURE_ROOT.name
            copytree(FIXTURE_ROOT, fixture_copy)
            fixture_directories = [
                fixture_copy,
                *(path for path in fixture_copy.rglob("*") if path.is_dir()),
            ]
            for directory in fixture_directories:
                directory.chmod(directory.stat().st_mode | stat.S_IWUSR)
            completed = subprocess.run(
                [
                    sys.executable,
                    str(REPOSITORY_ROOT / "scripts" / "validate_all.py"),
                    "--root",
                    str(fixture_copy),
                    "--state",
                    str(fixture_copy / "workflow_state.json"),
                    "--current-year",
                    "2026",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(3, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("MIGRATION_REQUIRED", completed.stdout)


class SchemaV2ValidationTests(unittest.TestCase):
    def test_valid_v0_state_is_ready_without_an_audit(self) -> None:
        temporary_directory, project = make_valid_project(validity_level="V0")
        self.addCleanup(temporary_directory.cleanup)
        state = load_json(project / "workflow_state.json")
        state["independent_audit"] = {}
        write_json(project / "workflow_state.json", state)

        completed = run_schema_validator(project)

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("READY", completed.stdout)

    def test_schema_v2_enums_and_epoch_are_validated(self) -> None:
        cases = (
            ("active_track", "OTHER", "INVALID_ACTIVE_TRACK"),
            ("novelty_level", "N0-4", "INVALID_NOVELTY_LEVEL"),
            ("validity_level", "V5", "INVALID_VALIDITY_LEVEL"),
            ("claim_profile", "EMPIRICAL", "INVALID_CLAIM_PROFILE"),
            ("validation_epoch", 0, "INVALID_VALIDATION_EPOCH"),
        )
        for field, value, code in cases:
            with self.subTest(field=field):
                temporary_directory, project = make_valid_project()
                self.addCleanup(temporary_directory.cleanup)
                state = load_json(project / "workflow_state.json")
                state[field] = value
                write_json(project / "workflow_state.json", state)

                completed = run_schema_validator(project)

                self.assertEqual(
                    1, completed.returncode, completed.stdout + completed.stderr
                )
                self.assertIn(code, completed.stdout)

    def test_author_cannot_review_own_bundle(self) -> None:
        temporary_directory, project = make_valid_project(claim_profile="THEORY")
        self.addCleanup(temporary_directory.cleanup)
        state = load_json(project / "workflow_state.json")
        state["independent_audit"]["reviewer_agent_id"] = "agent-a"
        write_json(project / "workflow_state.json", state)

        completed = run_schema_validator(project)

        self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("AUDITOR_NOT_INDEPENDENT", completed.stdout)

    def test_missing_reviewer_capability_is_blocked(self) -> None:
        temporary_directory, project = make_valid_project(claim_profile="THEORY")
        self.addCleanup(temporary_directory.cleanup)
        state = load_json(project / "workflow_state.json")
        state["independent_audit"] = {"capability_available": False}
        write_json(project / "workflow_state.json", state)

        completed = run_schema_validator(project)

        self.assertEqual(2, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("BLOCKED_CAPABILITY", completed.stdout)

    def test_validate_all_does_not_convert_blocked_to_success(self) -> None:
        temporary_directory, project = make_valid_project(claim_profile="THEORY")
        self.addCleanup(temporary_directory.cleanup)
        state = load_json(project / "workflow_state.json")
        state["independent_audit"] = {"capability_available": False}
        write_json(project / "workflow_state.json", state)

        completed = run_all_validator(project)

        self.assertEqual(2, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("BLOCKED_CAPABILITY", completed.stdout)

    def test_validate_all_aggregates_existing_artifact_invalidity_with_blocked(self) -> None:
        temporary_directory, project = make_valid_project(claim_profile="THEORY")
        self.addCleanup(temporary_directory.cleanup)
        state = load_json(project / "workflow_state.json")
        state["independent_audit"] = {"capability_available": False}
        write_json(project / "workflow_state.json", state)
        (project / "near_neighbor_registry.json").write_text(
            "not valid json\n", encoding="utf-8"
        )

        completed = run_all_validator(project)

        self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("BLOCKED_CAPABILITY", completed.stdout)
        self.assertIn("LITERATURE_REGISTRY_FAILED", completed.stdout)

    def test_invalid_takes_precedence_over_blocked(self) -> None:
        temporary_directory, project = make_valid_project(claim_profile="NOT_A_PROFILE")
        self.addCleanup(temporary_directory.cleanup)
        state = load_json(project / "workflow_state.json")
        state["independent_audit"] = {"capability_available": False}
        write_json(project / "workflow_state.json", state)

        completed = run_schema_validator(project)

        self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("INVALID_CLAIM_PROFILE", completed.stdout)
        self.assertIn("BLOCKED_CAPABILITY", completed.stdout)

    def test_migration_takes_precedence_and_stops_other_checks(self) -> None:
        temporary_directory, project = make_valid_project(claim_profile="NOT_A_PROFILE")
        self.addCleanup(temporary_directory.cleanup)
        state = load_json(project / "workflow_state.json")
        state["schema_version"] = "1.0"
        state["independent_audit"] = {"capability_available": False}
        write_json(project / "workflow_state.json", state)

        completed = run_schema_validator(project)

        self.assertEqual(3, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("MIGRATION_REQUIRED", completed.stdout)
        self.assertNotIn("INVALID_CLAIM_PROFILE", completed.stdout)
        self.assertNotIn("BLOCKED_CAPABILITY", completed.stdout)


if __name__ == "__main__":
    unittest.main()
