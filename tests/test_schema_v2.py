from __future__ import annotations

import hashlib
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
    @staticmethod
    def snapshot_files(project: Path) -> dict[str, str]:
        return {
            str(path.relative_to(project)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(project.rglob("*"))
            if path.is_file()
        }

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

    def test_schema_v2_enum_types_are_stably_invalid(self) -> None:
        for field in ("active_track", "novelty_level", "validity_level", "claim_profile"):
            for malformed in ([], {}):
                with self.subTest(field=field, malformed=malformed):
                    temporary_directory, project = make_valid_project()
                    self.addCleanup(temporary_directory.cleanup)
                    state = load_json(project / "workflow_state.json")
                    state[field] = malformed
                    write_json(project / "workflow_state.json", state)

                    completed = run_schema_validator(project)

                    self.assertEqual(
                        1, completed.returncode, completed.stdout + completed.stderr
                    )
                    self.assertIn(f"INVALID_{field.upper()}", completed.stdout)
                    self.assertNotIn("Traceback", completed.stderr)

    def test_validation_epoch_rejects_boolean(self) -> None:
        temporary_directory, project = make_valid_project()
        self.addCleanup(temporary_directory.cleanup)
        state = load_json(project / "workflow_state.json")
        state["validation_epoch"] = True
        write_json(project / "workflow_state.json", state)

        completed = run_schema_validator(project)

        self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("INVALID_VALIDATION_EPOCH", completed.stdout)

    def test_author_cannot_review_own_bundle(self) -> None:
        temporary_directory, project = make_valid_project(claim_profile="THEORY")
        self.addCleanup(temporary_directory.cleanup)
        state = load_json(project / "workflow_state.json")
        state["independent_audit"]["reviewer_agent_id"] = "agent-a"
        write_json(project / "workflow_state.json", state)

        completed = run_schema_validator(project)

        self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("AUDITOR_NOT_INDEPENDENT", completed.stdout)

    def test_audit_ids_must_be_canonical_and_unique(self) -> None:
        cases = (
            (["agent-a "], "agent-b", "NONCANONICAL_AUDIT_ID"),
            (["agent-a"], " agent-b", "NONCANONICAL_AUDIT_ID"),
            (["agent-a", "agent-a"], "agent-b", "DUPLICATE_AUTHOR_AGENT_ID"),
            (["agent-a", 7], "agent-b", "INVALID_AUDIT_AUTHORS"),
            (["agent-a"], [], "INVALID_AUDIT_REVIEWER"),
        )
        for authors, reviewer, code in cases:
            with self.subTest(authors=authors, reviewer=reviewer):
                temporary_directory, project = make_valid_project()
                self.addCleanup(temporary_directory.cleanup)
                state = load_json(project / "workflow_state.json")
                state["independent_audit"]["author_agent_ids"] = authors
                state["independent_audit"]["reviewer_agent_id"] = reviewer
                write_json(project / "workflow_state.json", state)

                completed = run_schema_validator(project)

                self.assertEqual(
                    1, completed.returncode, completed.stdout + completed.stderr
                )
                self.assertIn(code, completed.stdout)
                self.assertNotIn("Traceback", completed.stderr)

    def test_capability_available_is_strict_boolean_when_present(self) -> None:
        for malformed in (0, 1, "false", None, [], {}):
            with self.subTest(malformed=malformed):
                temporary_directory, project = make_valid_project()
                self.addCleanup(temporary_directory.cleanup)
                state = load_json(project / "workflow_state.json")
                state["independent_audit"]["capability_available"] = malformed
                write_json(project / "workflow_state.json", state)

                completed = run_schema_validator(project)

                self.assertEqual(
                    1, completed.returncode, completed.stdout + completed.stderr
                )
                self.assertIn("INVALID_CAPABILITY_AVAILABLE", completed.stdout)
                self.assertNotIn("Traceback", completed.stderr)

    def test_audit_object_and_capability_types_are_checked_before_v3(self) -> None:
        cases = (
            ({"capability_available": 1}, "INVALID_CAPABILITY_AVAILABLE"),
            ([], "INVALID_INDEPENDENT_AUDIT"),
        )
        for audit, code in cases:
            with self.subTest(audit=audit):
                temporary_directory, project = make_valid_project(validity_level="V0")
                self.addCleanup(temporary_directory.cleanup)
                state = load_json(project / "workflow_state.json")
                state["independent_audit"] = audit
                write_json(project / "workflow_state.json", state)

                completed = run_schema_validator(project)

                self.assertEqual(
                    1, completed.returncode, completed.stdout + completed.stderr
                )
                self.assertIn(code, completed.stdout)
                self.assertNotIn("Traceback", completed.stderr)

    def test_missing_reviewer_capability_is_blocked(self) -> None:
        temporary_directory, project = make_valid_project(claim_profile="THEORY")
        self.addCleanup(temporary_directory.cleanup)
        state = load_json(project / "workflow_state.json")
        state["independent_audit"] = {"capability_available": False}
        write_json(project / "workflow_state.json", state)

        completed = run_schema_validator(project)

        self.assertEqual(2, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("BLOCKED_CAPABILITY", completed.stdout)

    def test_blocked_capability_does_not_hide_existing_self_review(self) -> None:
        temporary_directory, project = make_valid_project(claim_profile="THEORY")
        self.addCleanup(temporary_directory.cleanup)
        state = load_json(project / "workflow_state.json")
        state["independent_audit"]["capability_available"] = False
        state["independent_audit"]["reviewer_agent_id"] = "agent-a"
        write_json(project / "workflow_state.json", state)

        completed = run_schema_validator(project)

        self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("BLOCKED_CAPABILITY", completed.stdout)
        self.assertIn("AUDITOR_NOT_INDEPENDENT", completed.stdout)

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

    def test_schema_cli_returns_stable_validator_error_for_unexpected_input(self) -> None:
        temporary_directory, project = make_valid_project()
        self.addCleanup(temporary_directory.cleanup)
        (project / "workflow_state.json").write_bytes(b"\xff")

        completed = run_schema_validator(project)

        self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("VALIDATOR_ERROR", completed.stdout)
        self.assertNotIn("Traceback", completed.stderr)

    def test_validate_all_is_read_only_without_existing_ledger(self) -> None:
        temporary_directory, project = make_valid_project(validity_level="V0")
        self.addCleanup(temporary_directory.cleanup)
        state = load_json(project / "workflow_state.json")
        state["independent_audit"] = {}
        write_json(project / "workflow_state.json", state)
        write_json(
            project / "near_neighbor_registry.json",
            {
                "records": [],
                "peer_reviewed_published_count": 0,
                "search_mode": "SEARCH_OPEN",
                "synthesis_lock_threshold": 100,
            },
        )
        before = self.snapshot_files(project)

        run_all_validator(project)

        self.assertEqual(before, self.snapshot_files(project))
        self.assertFalse((project / "near_neighbor_url_ledger.csv").exists())

    def test_validate_all_does_not_overwrite_existing_ledger(self) -> None:
        temporary_directory, project = make_valid_project(validity_level="V0")
        self.addCleanup(temporary_directory.cleanup)
        state = load_json(project / "workflow_state.json")
        state["independent_audit"] = {}
        write_json(project / "workflow_state.json", state)
        write_json(
            project / "near_neighbor_registry.json",
            {
                "records": [],
                "peer_reviewed_published_count": 0,
                "search_mode": "SEARCH_OPEN",
                "synthesis_lock_threshold": 100,
            },
        )
        ledger = project / "near_neighbor_url_ledger.csv"
        ledger.write_bytes(b"preserve this ledger\n")
        before = self.snapshot_files(project)

        run_all_validator(project)

        self.assertEqual(before, self.snapshot_files(project))
        self.assertEqual(b"preserve this ledger\n", ledger.read_bytes())

    def test_validate_all_rejects_state_outside_root_before_schema_dispatch(self) -> None:
        with TemporaryDirectory(prefix="schema-v2-root-") as root_directory:
            with TemporaryDirectory(prefix="schema-v2-outside-") as outside_directory:
                root = Path(root_directory)
                state = Path(outside_directory) / "workflow_state.json"
                state.write_bytes((FIXTURE_ROOT / "workflow_state.json").read_bytes())

                completed = subprocess.run(
                    [
                        sys.executable,
                        str(REPOSITORY_ROOT / "scripts" / "validate_all.py"),
                        "--root",
                        str(root),
                        "--state",
                        str(state),
                        "--current-year",
                        "2026",
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                )

        self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("VALIDATOR_ERROR", completed.stdout)
        self.assertIn("outside_root", completed.stdout)
        self.assertNotIn("MIGRATION_REQUIRED", completed.stdout)
        self.assertNotIn("Traceback", completed.stderr)

    def test_validate_all_rejects_registry_paths_outside_root(self) -> None:
        for option in ("--literature-registry", "--claim-registry", "--output-support"):
            with self.subTest(option=option):
                temporary_directory, project = make_valid_project(validity_level="V0")
                self.addCleanup(temporary_directory.cleanup)
                state = load_json(project / "workflow_state.json")
                state["independent_audit"] = {}
                write_json(project / "workflow_state.json", state)
                with TemporaryDirectory(prefix="schema-v2-outside-") as outside:
                    outside_path = Path(outside) / "registry.json"
                    outside_path.write_text("{}\n", encoding="utf-8")

                    completed = run_all_validator(
                        project, (option, str(outside_path))
                    )

                self.assertEqual(
                    1, completed.returncode, completed.stdout + completed.stderr
                )
                self.assertIn("VALIDATOR_ERROR", completed.stdout)
                self.assertIn("outside_root", completed.stdout)
                self.assertNotIn("Traceback", completed.stderr)

    def test_validate_all_returns_stable_error_for_unexpected_state_input(self) -> None:
        temporary_directory, project = make_valid_project()
        self.addCleanup(temporary_directory.cleanup)
        (project / "workflow_state.json").write_bytes(b"\xff")

        completed = run_all_validator(project)

        self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("VALIDATOR_ERROR", completed.stdout)
        self.assertNotIn("Traceback", completed.stderr)

    def test_validate_all_preserves_schema_issues_when_workflow_validation_raises(
        self,
    ) -> None:
        temporary_directory, project = make_valid_project(
            claim_profile="NOT_A_PROFILE"
        )
        self.addCleanup(temporary_directory.cleanup)
        state = load_json(project / "workflow_state.json")
        state["active_state"] = []
        state["resume_state"] = []
        write_json(project / "workflow_state.json", state)

        completed = run_all_validator(project)

        self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("INVALID_CLAIM_PROFILE", completed.stdout)
        self.assertIn("VALIDATOR_ERROR", completed.stdout)
        self.assertNotIn("Traceback", completed.stderr)


if __name__ == "__main__":
    unittest.main()
