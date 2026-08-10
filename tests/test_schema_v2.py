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
    run_script,
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

    @staticmethod
    def write_valid_literature_registry(project: Path) -> Path:
        registry = project / "near_neighbor_registry.json"
        write_json(
            registry,
            {
                "records": [],
                "peer_reviewed_published_count": 0,
                "search_mode": "SEARCH_OPEN",
                "synthesis_lock_threshold": 100,
            },
        )
        return registry

    @staticmethod
    def run_literature_validator(
        project: Path, *extra_args: str
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(REPOSITORY_ROOT / "scripts" / "validate_literature_registry.py"),
                "--root",
                str(project),
                "--registry",
                str(project / "near_neighbor_registry.json"),
                *extra_args,
            ],
            check=False,
            capture_output=True,
            text=True,
        )

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

    def test_standalone_literature_validator_defaults_to_read_only(self) -> None:
        with TemporaryDirectory(prefix="schema-v2-literature-") as directory:
            project = Path(directory)
            self.write_valid_literature_registry(project)
            ledger = project / "near_neighbor_url_ledger.csv"

            first = self.run_literature_validator(project)
            self.assertEqual(0, first.returncode, first.stdout + first.stderr)
            self.assertFalse(ledger.exists())

            ledger.write_bytes(b"preserve standalone ledger\n")
            second = self.run_literature_validator(project)
            self.assertEqual(0, second.returncode, second.stdout + second.stderr)
            self.assertEqual(b"preserve standalone ledger\n", ledger.read_bytes())

    def test_standalone_literature_validator_writes_only_with_explicit_flag(self) -> None:
        with TemporaryDirectory(prefix="schema-v2-literature-") as directory:
            project = Path(directory)
            self.write_valid_literature_registry(project)
            ledger = project / "near_neighbor_url_ledger.csv"

            completed = self.run_literature_validator(project, "--write-ledger")

            self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
            self.assertTrue(ledger.is_file())
            self.assertIn("canonical_key", ledger.read_text(encoding="utf-8"))

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

    def test_validate_all_rejects_default_registry_symlink_outside_root(self) -> None:
        temporary_directory, project = make_valid_project(validity_level="V0")
        self.addCleanup(temporary_directory.cleanup)
        state = load_json(project / "workflow_state.json")
        state["independent_audit"] = {}
        write_json(project / "workflow_state.json", state)
        with TemporaryDirectory(prefix="schema-v2-outside-") as outside:
            outside_registry = Path(outside) / "registry.json"
            outside_registry.write_text("{}\n", encoding="utf-8")
            (project / "near_neighbor_registry.json").symlink_to(outside_registry)

            completed = run_all_validator(project)

        self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("VALIDATOR_ERROR", completed.stdout)
        self.assertIn("outside_root", completed.stdout)
        self.assertNotIn("Traceback", completed.stderr)

    def test_standalone_literature_validator_rejects_registry_outside_root(self) -> None:
        with TemporaryDirectory(prefix="schema-v2-literature-") as directory:
            project = Path(directory)
            with TemporaryDirectory(prefix="schema-v2-outside-") as outside:
                outside_registry = Path(outside) / "registry.json"
                write_json(
                    outside_registry,
                    {
                        "records": [],
                        "peer_reviewed_published_count": 0,
                        "search_mode": "SEARCH_OPEN",
                    },
                )
                completed = subprocess.run(
                    [
                        sys.executable,
                        str(
                            REPOSITORY_ROOT
                            / "scripts"
                            / "validate_literature_registry.py"
                        ),
                        "--root",
                        str(project),
                        "--registry",
                        str(outside_registry),
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                )

        self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("PATH_OUTSIDE_ROOT", completed.stdout)
        self.assertNotIn("Traceback", completed.stderr)

    def test_literature_scan_rejects_file_symlink_outside_root_without_reading_it(
        self,
    ) -> None:
        with TemporaryDirectory(prefix="schema-v2-literature-") as directory:
            project = Path(directory)
            self.write_valid_literature_registry(project)
            with TemporaryDirectory(prefix="schema-v2-outside-") as outside:
                outside_document = Path(outside) / "secret.md"
                outside_document.write_text(
                    "https://arxiv.org/abs/9999.99999\n", encoding="utf-8"
                )
                (project / "escape.md").symlink_to(outside_document)

                completed = self.run_literature_validator(project)

        self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("PATH_OUTSIDE_ROOT", completed.stdout)
        self.assertNotIn("9999.99999", completed.stdout)
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

    def test_readiness_states_enforce_novelty_and_validity_levels(self) -> None:
        cases = (
            ("CLAIM_FREEZE", "N0-3", "V0", "CLAIM_FREEZE_REQUIRES_N0_4C"),
            ("VALIDITY_AUDIT", "N0-4C", "V0", "VALIDITY_AUDIT_REQUIRES_V1"),
            (
                "INDEPENDENT_REVIEW",
                "N0-4C",
                "V1",
                "INDEPENDENT_REVIEW_REQUIRES_V2",
            ),
            ("DIRECTION_LOCK", "N0-3", "V3", "DIRECTION_LOCK_REQUIRES_N0_4C"),
            ("DIRECTION_LOCK", "N0-4C", "V2", "DIRECTION_LOCK_REQUIRES_V3"),
            ("COMPUTE", "N0-3", "V3", "COMPUTE_REQUIRES_N0_4C"),
            ("COMPUTE", "N0-4C", "V2", "COMPUTE_REQUIRES_V3"),
            ("FINAL_LOCK", "N0-3", "V4", "FINAL_LOCK_REQUIRES_N0_4C"),
            ("FINAL_LOCK", "N0-4C", "V3", "FINAL_LOCK_REQUIRES_V4"),
        )
        for active_state, novelty, validity, code in cases:
            with self.subTest(active_state=active_state, code=code):
                temporary_directory, project = make_valid_project(
                    novelty_level=novelty,
                    validity_level=validity,
                )
                self.addCleanup(temporary_directory.cleanup)
                state = load_json(project / "workflow_state.json")
                state["active_state"] = active_state
                state["resume_state"] = active_state
                if active_state == "COMPUTE":
                    state["compute_stage"] = "S0"
                    state["gates"]["compute_authorized"] = True
                write_json(project / "workflow_state.json", state)

                completed = run_script("validate_workflow_state.py", project)

                self.assertEqual(
                    1, completed.returncode, completed.stdout + completed.stderr
                )
                self.assertIn(code, completed.stdout)
                self.assertNotIn("Traceback", completed.stderr)

    def test_compute_requires_strict_authorization(self) -> None:
        temporary_directory, project = make_valid_project(
            novelty_level="N0-4C", validity_level="V3"
        )
        self.addCleanup(temporary_directory.cleanup)
        state = load_json(project / "workflow_state.json")
        state["active_state"] = "COMPUTE"
        state["resume_state"] = "COMPUTE"
        state["compute_stage"] = "S0"
        state["gates"]["compute_authorized"] = False
        write_json(project / "workflow_state.json", state)

        completed = run_script("validate_workflow_state.py", project)

        self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("COMPUTE_REQUIRES_AUTHORIZATION", completed.stdout)

    def test_compute_accepts_exact_readiness_formula(self) -> None:
        temporary_directory, project = make_valid_project(
            novelty_level="N0-4C", validity_level="V3"
        )
        self.addCleanup(temporary_directory.cleanup)
        state = load_json(project / "workflow_state.json")
        state["active_state"] = "COMPUTE"
        state["resume_state"] = "COMPUTE"
        state["compute_stage"] = "S0"
        state["gates"]["compute_authorized"] = True
        write_json(project / "workflow_state.json", state)

        completed = run_script("validate_workflow_state.py", project)

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)

    def test_postcompute_claim_freeze_requires_current_s4_compute_evidence(
        self,
    ) -> None:
        temporary_directory, project = make_valid_project()
        self.addCleanup(temporary_directory.cleanup)
        state = load_json(project / "workflow_state.json")
        state["active_state"] = "POSTCOMPUTE_CLAIM_FREEZE"
        state["resume_state"] = "POSTCOMPUTE_CLAIM_FREEZE"
        state["compute_stage"] = "S3"
        state["gates"]["compute_authorized"] = True
        write_json(project / "workflow_state.json", state)

        completed = run_script("validate_workflow_state.py", project)

        self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn(
            "POSTCOMPUTE_CLAIM_FREEZE_REQUIRES_COMPLETED_AUTHORIZED_COMPUTE",
            completed.stdout,
        )

    def test_postcompute_compute_evidence_fields_are_strict(self) -> None:
        cases = (
            ("status", True),
            ("validation_epoch", True),
            ("artifact_path", []),
            ("artifact_sha256", {}),
        )
        for field, malformed in cases:
            with self.subTest(field=field, malformed=malformed):
                temporary_directory, project = make_valid_project()
                self.addCleanup(temporary_directory.cleanup)
                evidence_path = project / "compute_evidence.json"
                evidence_hash = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
                state = load_json(project / "workflow_state.json")
                state["active_state"] = "POSTCOMPUTE_CLAIM_FREEZE"
                state["resume_state"] = "POSTCOMPUTE_CLAIM_FREEZE"
                state["compute_stage"] = "S4"
                state["gates"]["compute_authorized"] = True
                state["compute_evidence"] = {
                    "status": "COMPLETED",
                    "validation_epoch": state["validation_epoch"],
                    "artifact_path": "compute_evidence.json",
                    "artifact_sha256": evidence_hash,
                }
                state["compute_evidence"][field] = malformed
                write_json(project / "workflow_state.json", state)

                completed = run_script("validate_workflow_state.py", project)

                self.assertEqual(
                    1, completed.returncode, completed.stdout + completed.stderr
                )
                self.assertIn("INVALID_COMPUTE_EVIDENCE", completed.stdout)
                self.assertNotIn("Traceback", completed.stderr)

    def test_postcompute_rejects_stale_compute_evidence_hash(self) -> None:
        temporary_directory, project = make_valid_project()
        self.addCleanup(temporary_directory.cleanup)
        state = load_json(project / "workflow_state.json")
        state["active_state"] = "POSTCOMPUTE_CLAIM_FREEZE"
        state["resume_state"] = "POSTCOMPUTE_CLAIM_FREEZE"
        state["compute_stage"] = "S4"
        state["gates"]["compute_authorized"] = True
        state["compute_evidence"] = {
            "status": "COMPLETED",
            "validation_epoch": state["validation_epoch"],
            "artifact_path": "compute_evidence.json",
            "artifact_sha256": "0" * 64,
        }
        write_json(project / "workflow_state.json", state)

        completed = run_script("validate_workflow_state.py", project)

        self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("STALE_COMPUTE_EVIDENCE", completed.stdout)

    def test_postcompute_accepts_current_s4_compute_evidence(self) -> None:
        temporary_directory, project = make_valid_project()
        self.addCleanup(temporary_directory.cleanup)
        evidence_path = project / "compute_evidence.json"
        state = load_json(project / "workflow_state.json")
        state["active_state"] = "POSTCOMPUTE_CLAIM_FREEZE"
        state["resume_state"] = "POSTCOMPUTE_CLAIM_FREEZE"
        state["compute_stage"] = "S4"
        state["gates"]["compute_authorized"] = True
        state["compute_evidence"] = {
            "status": "COMPLETED",
            "validation_epoch": state["validation_epoch"],
            "artifact_path": "compute_evidence.json",
            "artifact_sha256": hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
        }
        write_json(project / "workflow_state.json", state)

        completed = run_script("validate_workflow_state.py", project)

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)

    def test_final_validity_audit_requires_a_new_epoch_claim_bundle(self) -> None:
        temporary_directory, project = make_valid_project()
        self.addCleanup(temporary_directory.cleanup)
        state = load_json(project / "workflow_state.json")
        state["active_state"] = "FINAL_VALIDITY_AUDIT"
        state["resume_state"] = "FINAL_VALIDITY_AUDIT"
        write_json(project / "workflow_state.json", state)

        completed = run_script("validate_workflow_state.py", project)

        self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn(
            "FINAL_VALIDITY_AUDIT_REQUIRES_NEW_EPOCH_CLAIM_BUNDLE",
            completed.stdout,
        )

    def test_final_lock_requires_current_nested_independent_audit(self) -> None:
        temporary_directory, project = make_valid_project(validity_level="V4")
        self.addCleanup(temporary_directory.cleanup)
        state = load_json(project / "workflow_state.json")
        state["active_state"] = "FINAL_LOCK"
        state["resume_state"] = "FINAL_LOCK"
        state["independent_audit"]["validation_epoch"] = 2
        write_json(project / "workflow_state.json", state)

        completed = run_script("validate_workflow_state.py", project)

        self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn(
            "FINAL_LOCK_REQUIRES_CURRENT_INDEPENDENT_AUDIT", completed.stdout
        )

    def test_declared_blocker_returns_blocked_without_ready_suite(self) -> None:
        temporary_directory, project = make_valid_project()
        self.addCleanup(temporary_directory.cleanup)
        state = load_json(project / "workflow_state.json")
        state["active_state"] = "BLOCKED"
        state["resume_state"] = "CLAIM_FREEZE"
        state["blocked_reasons"] = ["External reviewer service is unavailable."]
        write_json(project / "workflow_state.json", state)

        completed = run_all_validator(project)

        self.assertEqual(2, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("EXTERNAL_BLOCKER", completed.stdout)
        self.assertNotIn("validation_suite_status=READY", completed.stdout)

    def test_declared_blocker_still_validates_existing_artifacts(self) -> None:
        temporary_directory, project = make_valid_project()
        self.addCleanup(temporary_directory.cleanup)
        state = load_json(project / "workflow_state.json")
        state["active_state"] = "BLOCKED"
        state["resume_state"] = "CLAIM_FREEZE"
        state["blocked_reasons"] = ["External reviewer service is unavailable."]
        write_json(project / "workflow_state.json", state)
        (project / "near_neighbor_registry.json").write_text(
            "not valid json\n", encoding="utf-8"
        )

        completed = run_all_validator(project)

        self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("EXTERNAL_BLOCKER", completed.stdout)
        self.assertIn("LITERATURE_REGISTRY_FAILED", completed.stdout)


if __name__ == "__main__":
    unittest.main()
