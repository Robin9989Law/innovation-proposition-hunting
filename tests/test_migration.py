from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import stat
import unittest
from pathlib import Path
from shutil import copy2
from tempfile import TemporaryDirectory
from unittest import mock

from tests.helpers import REPOSITORY_ROOT, load_json, write_json


FIXTURE_STATE = (
    REPOSITORY_ROOT
    / "tests"
    / "fixtures"
    / "paper1-failure-case"
    / "workflow_state.json"
)


def load_migration_module():
    module_path = REPOSITORY_ROOT / "scripts" / "migrate_v1_to_v2.py"
    spec = importlib.util.spec_from_file_location("migration_under_test", module_path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load migration module: {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MigrationTests(unittest.TestCase):
    def run_migration(
        self, project: Path, *extra_args: str
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(REPOSITORY_ROOT / "scripts" / "migrate_v1_to_v2.py"),
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

    def test_default_migration_preserves_v1_and_resets_validity(self) -> None:
        with TemporaryDirectory(prefix="schema-v2-migration-") as directory:
            project = Path(directory)
            state_path = project / "workflow_state.json"
            copy2(FIXTURE_STATE, state_path)
            original = state_path.read_bytes()

            completed = subprocess.run(
                [
                    sys.executable,
                    str(REPOSITORY_ROOT / "scripts" / "migrate_v1_to_v2.py"),
                    "--root",
                    str(project),
                    "--state",
                    str(state_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            output_path = project / "workflow_state.v2.json"
            self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
            self.assertEqual(original, state_path.read_bytes())
            migrated = load_json(output_path)
            self.assertEqual("2.0", migrated["schema_version"])
            self.assertEqual("VALIDITY", migrated["active_track"])
            self.assertEqual("CLAIM_FREEZE", migrated["active_state"])
            self.assertEqual("N0-4C", migrated["novelty_level"])
            self.assertEqual("V0", migrated["validity_level"])
            self.assertEqual(1, migrated["validation_epoch"])
            self.assertEqual("", migrated["claim_bundle_sha256"])
            self.assertEqual({}, migrated["independent_audit"])
            self.assertFalse(migrated["gates"]["compute_authorized"])

    def test_in_place_migration_creates_byte_identical_backup(self) -> None:
        with TemporaryDirectory(prefix="schema-v2-migration-") as directory:
            project = Path(directory)
            state_path = project / "workflow_state.json"
            copy2(FIXTURE_STATE, state_path)
            original = state_path.read_bytes()

            completed = subprocess.run(
                [
                    sys.executable,
                    str(REPOSITORY_ROOT / "scripts" / "migrate_v1_to_v2.py"),
                    "--root",
                    str(project),
                    "--state",
                    str(state_path),
                    "--in-place",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            backups = list(project.glob("workflow_state.json.v1-backup-*"))
            self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
            self.assertEqual(1, len(backups))
            self.assertEqual(original, backups[0].read_bytes())
            self.assertEqual("2.0", load_json(state_path)["schema_version"])

    def test_custom_output_maps_unlocked_novelty_to_n0_3(self) -> None:
        with TemporaryDirectory(prefix="schema-v2-migration-") as directory:
            project = Path(directory)
            state_path = project / "workflow_state.json"
            copy2(FIXTURE_STATE, state_path)
            state = load_json(state_path)
            state["n0_4_status"] = "NOT_LOCKED"
            state["gates"]["n0_4_locked"] = False
            write_json(state_path, state)
            output_path = project / "custom-state.json"

            completed = subprocess.run(
                [
                    sys.executable,
                    str(REPOSITORY_ROOT / "scripts" / "migrate_v1_to_v2.py"),
                    "--root",
                    str(project),
                    "--state",
                    str(state_path),
                    "--output",
                    str(output_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
            self.assertEqual("N0-3", load_json(output_path)["novelty_level"])

    def test_non_in_place_output_cannot_equal_source(self) -> None:
        with TemporaryDirectory(prefix="schema-v2-migration-") as directory:
            project = Path(directory)
            state_path = project / "workflow_state.json"
            copy2(FIXTURE_STATE, state_path)
            original = state_path.read_bytes()

            completed = self.run_migration(
                project, "--output", str(state_path.resolve())
            )

            self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
            self.assertIn("output_equals_state", completed.stdout)
            self.assertEqual(original, state_path.read_bytes())

    def test_default_migration_refuses_existing_output(self) -> None:
        with TemporaryDirectory(prefix="schema-v2-migration-") as directory:
            project = Path(directory)
            state_path = project / "workflow_state.json"
            copy2(FIXTURE_STATE, state_path)
            output_path = project / "workflow_state.v2.json"
            output_path.write_bytes(b"do not overwrite\n")

            completed = self.run_migration(project)

            self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
            self.assertIn("output_exists", completed.stdout)
            self.assertEqual(b"do not overwrite\n", output_path.read_bytes())

    def test_atomic_writer_cleans_temporary_file_if_replace_fails(self) -> None:
        module = load_migration_module()
        atomic_write_json = getattr(module, "atomic_write_json", None)
        open_trusted_directory = getattr(module, "open_trusted_directory", None)
        self.assertIsNotNone(atomic_write_json, "atomic_write_json helper is required")
        self.assertIsNotNone(
            open_trusted_directory, "open_trusted_directory helper is required"
        )
        if atomic_write_json is None or open_trusted_directory is None:
            return
        with TemporaryDirectory(prefix="schema-v2-atomic-") as directory:
            project = Path(directory)
            target = project / "state.json"
            target.write_bytes(b"original\n")

            with open_trusted_directory(project, project, create=False) as dir_fd:
                with mock.patch.object(
                    module.os, "replace", side_effect=OSError("replace failed")
                ):
                    with self.assertRaisesRegex(OSError, "replace failed"):
                        atomic_write_json(
                            dir_fd,
                            target.name,
                            {"schema_version": "2.0"},
                            0o644,
                        )

            self.assertEqual(b"original\n", target.read_bytes())
            self.assertEqual([target], list(project.iterdir()))

    def test_atomic_no_clobber_publish_rejects_racing_target(self) -> None:
        module = load_migration_module()
        atomic_publish_json = getattr(module, "atomic_publish_json", None)
        open_trusted_directory = getattr(module, "open_trusted_directory", None)
        self.assertIsNotNone(
            atomic_publish_json, "atomic_publish_json helper is required"
        )
        self.assertIsNotNone(
            open_trusted_directory, "open_trusted_directory helper is required"
        )
        if atomic_publish_json is None or open_trusted_directory is None:
            return
        with TemporaryDirectory(prefix="schema-v2-race-") as directory:
            project = Path(directory)
            target = project / "state.v2.json"
            original_link = module.os.link

            def create_racing_target(source, destination, **kwargs):
                target.write_bytes(b"concurrent writer\n")
                return original_link(source, destination, **kwargs)

            with open_trusted_directory(project, project, create=False) as dir_fd:
                with mock.patch.object(
                    module.os, "link", side_effect=create_racing_target
                ):
                    with self.assertRaises(FileExistsError):
                        atomic_publish_json(
                            dir_fd,
                            target.name,
                            {"schema_version": "2.0"},
                            0o644,
                        )

            self.assertEqual(b"concurrent writer\n", target.read_bytes())
            self.assertEqual([target], list(project.iterdir()))

    def test_trusted_directory_fd_prevents_post_check_symlink_swap(self) -> None:
        module = load_migration_module()
        atomic_publish_json = getattr(module, "atomic_publish_json", None)
        open_trusted_directory = getattr(module, "open_trusted_directory", None)
        self.assertIsNotNone(atomic_publish_json)
        self.assertIsNotNone(open_trusted_directory)
        if atomic_publish_json is None or open_trusted_directory is None:
            return
        with TemporaryDirectory(prefix="schema-v2-root-") as directory:
            root = Path(directory)
            nested = root / "nested"
            with TemporaryDirectory(prefix="schema-v2-outside-") as outside:
                outside_path = Path(outside)
                with open_trusted_directory(root, nested, create=True) as dir_fd:
                    held_fd = dir_fd
                    nested.rmdir()
                    nested.symlink_to(outside_path, target_is_directory=True)
                    try:
                        atomic_publish_json(
                            dir_fd,
                            "state.json",
                            {"schema_version": "2.0"},
                            0o644,
                        )
                    except OSError:
                        pass

                self.assertFalse((outside_path / "state.json").exists())
                self.assertEqual([], list(outside_path.iterdir()))
                with self.assertRaises(OSError):
                    os.fstat(held_fd)

    def test_migration_rejects_non_schema_1_inputs(self) -> None:
        for schema_version in (None, "2.0", "3.0", 1):
            with self.subTest(schema_version=schema_version):
                with TemporaryDirectory(prefix="schema-v2-migration-") as directory:
                    project = Path(directory)
                    state_path = project / "workflow_state.json"
                    state = load_json(FIXTURE_STATE)
                    if schema_version is None:
                        state.pop("schema_version")
                    else:
                        state["schema_version"] = schema_version
                    write_json(state_path, state)

                    completed = self.run_migration(project)

                    self.assertEqual(
                        1, completed.returncode, completed.stdout + completed.stderr
                    )
                    self.assertIn("source_schema_not_1_x", completed.stdout)
                    self.assertFalse((project / "workflow_state.v2.json").exists())

    def test_migration_rejects_non_boolean_n0_lock(self) -> None:
        for malformed in (1, 0, "true", [], {}):
            with self.subTest(malformed=malformed):
                with TemporaryDirectory(prefix="schema-v2-migration-") as directory:
                    project = Path(directory)
                    state_path = project / "workflow_state.json"
                    state = load_json(FIXTURE_STATE)
                    state["gates"]["n0_4_locked"] = malformed
                    write_json(state_path, state)

                    completed = self.run_migration(project)

                    self.assertEqual(
                        1, completed.returncode, completed.stdout + completed.stderr
                    )
                    self.assertIn("n0_4_locked_not_boolean", completed.stdout)
                    self.assertFalse((project / "workflow_state.v2.json").exists())

    def test_in_place_migration_preserves_source_permission_bits(self) -> None:
        with TemporaryDirectory(prefix="schema-v2-migration-") as directory:
            project = Path(directory)
            state_path = project / "workflow_state.json"
            copy2(FIXTURE_STATE, state_path)
            state_path.chmod(0o644)

            completed = self.run_migration(project, "--in-place")

            self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
            self.assertEqual(0o644, stat.S_IMODE(state_path.stat().st_mode))

    def test_nested_custom_output_is_created_atomically_with_source_mode(self) -> None:
        with TemporaryDirectory(prefix="schema-v2-migration-") as directory:
            project = Path(directory)
            state_path = project / "workflow_state.json"
            copy2(FIXTURE_STATE, state_path)
            state_path.chmod(0o644)
            output_path = project / "nested" / "states" / "workflow_state.v2.json"

            completed = self.run_migration(
                project, "--output", str(output_path)
            )

            self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
            self.assertEqual("2.0", load_json(output_path)["schema_version"])
            self.assertEqual(0o644, stat.S_IMODE(output_path.stat().st_mode))

    def test_custom_output_rejects_parent_symlink_outside_root(self) -> None:
        with TemporaryDirectory(prefix="schema-v2-migration-") as directory:
            project = Path(directory)
            state_path = project / "workflow_state.json"
            copy2(FIXTURE_STATE, state_path)
            with TemporaryDirectory(prefix="schema-v2-outside-") as outside:
                link = project / "nested"
                link.symlink_to(Path(outside), target_is_directory=True)
                output_path = link / "workflow_state.v2.json"

                completed = self.run_migration(
                    project, "--output", str(output_path)
                )

                self.assertEqual(
                    1, completed.returncode, completed.stdout + completed.stderr
                )
                self.assertFalse((Path(outside) / "workflow_state.v2.json").exists())


if __name__ == "__main__":
    unittest.main()


V2_FIXTURE_DIR = REPOSITORY_ROOT / "tests" / "fixtures" / "minimal-valid-v2"
MIGRATE_V3 = REPOSITORY_ROOT / "scripts" / "migrate_v2_to_v3.py"


class MigrateV2ToV3Tests(unittest.TestCase):
    """schema 2.0 -> 3.0：三段式状态机迁移（design-schema-3.0 §5）。"""

    def run_v3_migration(
        self, project: Path, *extra_args: str
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(MIGRATE_V3),
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

    def make_v2_project(self, directory: str) -> Path:
        project = Path(directory)
        state = {
            "schema_version": "2.0",
            "workflow_id": "v2-to-v3-test",
            "updated_at": "2026-08-10T00:00:00Z",
            "current_year": 2026,
            "output_type": "JOURNAL_ARTICLE",
            "contribution_contract": "ONE_MAIN_M",
            "active_layer": "L3",
            "active_contribution": "M",
            "active_track": "VALIDITY",
            "active_state": "CLAIM_FREEZE",
            "resume_state": "CLAIM_FREEZE",
            "last_completed_state": "N0_AUDIT",
            "novelty_level": "N0-4C",
            "validity_level": "V1",
            "claim_profile": "THEORY",
            "validation_epoch": 1,
            "search_mode": "SEARCH_OPEN",
            "compute_stage": "NOT_STARTED",
            "collision_round": 1,
            "blocked_reasons": [],
            "next_required_action": "x",
            "gates": {
                "scope_locked": True,
                "prior_claims_drained": True,
                "recent_frontier_complete": True,
                "literature_registry_valid": True,
                "important_fulltext_complete": True,
                "source_claims_complete": False,
                "output_claims_traced": False,
                "evidence_validated": False,
                "l1_frozen": True,
                "l2_frozen": False,
                "architecture_frozen": False,
                "n0_4_locked": False,
                "compute_authorized": False,
            },
            "artifacts": {},
            "decision_log": [
                {"at": "2026-08-10T01:00:00Z", "state": "BOOT", "action": "boot"},
                {
                    "at": "2026-08-10T02:00:00Z",
                    "state": "BLOCKED@IMPORTANT_FULLTEXT",
                    "action": "blocked on fulltexts",
                },
                {
                    "at": "2026-08-10T03:00:00Z",
                    "state": "IMPORTANT_FULLTEXT",
                    "action": "fulltexts archived",
                },
                {
                    "at": "2026-08-10T04:00:00Z",
                    "state": "SOURCE_CLAIM_REGISTER",
                    "action": "claims extracted",
                },
            ],
        }
        write_json(project / "workflow_state.json", state)
        return project

    def test_state_and_gate_renames_with_derived_fields_dropped(self) -> None:
        with TemporaryDirectory(prefix="v2-to-v3-") as directory:
            project = self.make_v2_project(directory)
            completed = self.run_v3_migration(project)
            self.assertEqual(0, completed.returncode, completed.stdout)
            migrated = load_json(project / "workflow_state.v3.json")
            self.assertEqual("3.0", migrated["schema_version"])
            # 派生字段删除
            for field in ("active_track", "active_layer", "last_completed_state"):
                self.assertNotIn(field, migrated)
            # 门改名 + k_set_selected = 旧 l2_frozen(False)
            self.assertNotIn("important_fulltext_complete", migrated["gates"])
            self.assertNotIn("source_claims_complete", migrated["gates"])
            self.assertTrue(migrated["gates"]["k_fulltext_complete"])
            self.assertFalse(migrated["gates"]["k_claims_complete"])
            self.assertFalse(migrated["gates"]["k_set_selected"])
            # decision_log 状态改名（含 BLOCKED@ 形式），时间戳原样保留
            log_states = [entry["state"] for entry in migrated["decision_log"]]
            self.assertEqual(
                ["BOOT", "BLOCKED@K_FULLTEXT", "K_FULLTEXT", "K_CLAIM_REGISTER"],
                log_states,
            )
            log_times = [entry["at"] for entry in migrated["decision_log"]]
            self.assertEqual(
                ["2026-08-10T01:00:00Z", "2026-08-10T02:00:00Z",
                 "2026-08-10T03:00:00Z", "2026-08-10T04:00:00Z"],
                log_times,
            )
            # 原文件不被触碰
            self.assertEqual("2.0", load_json(project / "workflow_state.json")["schema_version"])

    def test_k_set_selected_true_warns_about_missing_k_triage(self) -> None:
        with TemporaryDirectory(prefix="v2-to-v3-") as directory:
            project = self.make_v2_project(directory)
            state = load_json(project / "workflow_state.json")
            state["gates"]["l2_frozen"] = True
            write_json(project / "workflow_state.json", state)
            completed = self.run_v3_migration(project)
            self.assertEqual(0, completed.returncode, completed.stdout)
            migrated = load_json(project / "workflow_state.v3.json")
            self.assertTrue(migrated["gates"]["k_set_selected"])
            self.assertIn("migration_warning=k_set_selected", completed.stdout)

    def test_rejects_non_v2_input(self) -> None:
        with TemporaryDirectory(prefix="v2-to-v3-") as directory:
            project = Path(directory)
            for version in ("1.0", "3.0", None):
                with self.subTest(version=version):
                    write_json(
                        project / "workflow_state.json",
                        {"schema_version": version},
                    )
                    completed = self.run_v3_migration(project)
                    self.assertEqual(1, completed.returncode)
                    self.assertIn("migration_status=INVALID", completed.stdout)

    def test_in_place_migration_creates_byte_identical_backup(self) -> None:
        with TemporaryDirectory(prefix="v2-to-v3-") as directory:
            project = self.make_v2_project(directory)
            state_path = project / "workflow_state.json"
            original = state_path.read_bytes()
            completed = self.run_v3_migration(project, "--in-place")
            backups = list(project.glob("workflow_state.json.v2-backup-*"))
            self.assertEqual(0, completed.returncode, completed.stdout)
            self.assertEqual(1, len(backups))
            self.assertEqual(original, backups[0].read_bytes())
            self.assertEqual("3.0", load_json(state_path)["schema_version"])

    def test_migrated_v2_fixture_passes_schema_gate(self) -> None:
        """真实 2.0 fixture 迁移后只剩 k_triage 产物缺失类问题，schema 门通过。"""
        with TemporaryDirectory(prefix="v2-to-v3-fixture-") as directory:
            project = Path(directory)
            copy2(
                V2_FIXTURE_DIR / "workflow_state.json",
                project / "workflow_state.json",
            )
            completed = self.run_v3_migration(project)
            self.assertEqual(0, completed.returncode, completed.stdout)
            migrated = load_json(project / "workflow_state.v3.json")
            self.assertEqual("3.0", migrated["schema_version"])
            self.assertEqual("DIRECTION_LOCK", migrated["active_state"])
            schema_check = subprocess.run(
                [
                    sys.executable,
                    str(REPOSITORY_ROOT / "scripts" / "validate_schema_v2.py"),
                    "--root",
                    str(project),
                    "--state",
                    str(project / "workflow_state.v3.json"),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotIn("MIGRATION_REQUIRED", schema_check.stdout)
            self.assertNotIn("LEGACY_FIELD_REMOVED", schema_check.stdout)


def load_frontier_migration_module():
    module_path = REPOSITORY_ROOT / "scripts" / "migrate_frontier_coverage.py"
    spec = importlib.util.spec_from_file_location(
        "frontier_migration_under_test", module_path
    )
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load migration module: {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


FRONTIER_WORKS = [
    {
        "registry_id": "W-A",
        "authors": ["Alice Smith", "Bob Jones"],
        "year": 2023,
    },
    {
        "registry_id": "W-B",
        "authors": ["Carol Smith", "Bob Jones"],
        "year": 2024,
    },
    {
        "registry_id": "W-C",
        "authors": ["Dave Lee", "Eve Wang"],
        "year": 2025,
    },
]


def frontier_coverage(entries):
    return {
        "schema_version": "1.0",
        "axes": {
            "author_continuations": entries,
            "backward_citations": ["route"],
            "forward_citations": ["route"],
        },
        "routes": [],
    }


class FrontierCoverageMigrationTests(unittest.TestCase):
    module = load_frontier_migration_module()

    def migrate(self, coverage, works=FRONTIER_WORKS):
        return self.module.migrate_payload(coverage, works)

    def test_verifiable_chain_converts_to_named_edges(self) -> None:
        coverage = frontier_coverage(["Smith TPWRS 2023 → Smith MASCOTS 2024"])
        migrated, summary, changed = self.migrate(coverage)
        self.assertTrue(changed)
        entries = migrated["axes"]["author_continuations"]
        self.assertEqual(1, len(entries))
        self.assertEqual("W-A → W-B", entries[0]["edge"])
        self.assertEqual(["Bob Jones"], entries[0]["shared_authors"])
        self.assertNotIn("method_lineage", migrated["axes"])
        self.assertTrue(any(line.startswith("converted:") for line in summary))

    def test_empty_intersection_demotes_to_method_lineage(self) -> None:
        coverage = frontier_coverage(["Smith TPWRS 2023 → Lee Energy 2025"])
        migrated, summary, changed = self.migrate(coverage)
        self.assertTrue(changed)
        self.assertEqual([], migrated["axes"]["author_continuations"])
        self.assertEqual(
            ["Smith TPWRS 2023 → Lee Energy 2025"],
            migrated["axes"]["method_lineage"],
        )
        self.assertTrue(any("author_continuations 为空" in line for line in summary))

    def test_ambiguous_segment_demotes(self) -> None:
        works = FRONTIER_WORKS + [
            {"registry_id": "W-D", "authors": ["Frank Smith"], "year": 2023}
        ]
        coverage = frontier_coverage(["Smith TPWRS 2023 → Smith MASCOTS 2024"])
        migrated, _, changed = self.migrate(coverage, works)
        self.assertTrue(changed)
        self.assertEqual([], migrated["axes"]["author_continuations"])
        self.assertEqual(
            ["Smith TPWRS 2023 → Smith MASCOTS 2024"],
            migrated["axes"]["method_lineage"],
        )

    def test_dict_entries_kept_and_strings_dedup_into_lineage(self) -> None:
        coverage = frontier_coverage(
            [
                {"edge": "W-A → W-B", "shared_authors": ["Bob Jones"]},
                "Smith TPWRS 2023 → Lee Energy 2025",
            ]
        )
        coverage["axes"]["method_lineage"] = ["Smith TPWRS 2023 → Lee Energy 2025"]
        migrated, _, changed = self.migrate(coverage)
        self.assertTrue(changed)
        self.assertEqual(
            [{"edge": "W-A → W-B", "shared_authors": ["Bob Jones"]}],
            migrated["axes"]["author_continuations"],
        )
        self.assertEqual(
            ["Smith TPWRS 2023 → Lee Energy 2025"],
            migrated["axes"]["method_lineage"],
        )

    def test_no_legacy_strings_is_noop(self) -> None:
        coverage = frontier_coverage(
            [{"edge": "W-A → W-B", "shared_authors": ["Bob Jones"]}]
        )
        _, summary, changed = self.migrate(coverage)
        self.assertFalse(changed)
        self.assertEqual(["无 legacy 字符串条目：无需迁移"], summary)

    def test_cli_in_place_writes_backup_and_result(self) -> None:
        with TemporaryDirectory(prefix="frontier-migration-") as directory:
            project = Path(directory)
            write_json(
                project / "frontier_coverage.json",
                frontier_coverage(["Smith TPWRS 2023 → Smith MASCOTS 2024"]),
            )
            write_json(
                project / "near_neighbor_registry.json",
                {"works": FRONTIER_WORKS},
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    str(REPOSITORY_ROOT / "scripts" / "migrate_frontier_coverage.py"),
                    "--root",
                    str(project),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
            migrated = load_json(project / "frontier_coverage.json")
            self.assertEqual(
                "W-A → W-B",
                migrated["axes"]["author_continuations"][0]["edge"],
            )
            backups = list(project.glob("frontier_coverage.json.legacy-backup-*"))
            self.assertEqual(1, len(backups))
            # 再跑一次：无 legacy 条目，保持幂等、不产生第二个备份
            completed2 = subprocess.run(
                [
                    sys.executable,
                    str(REPOSITORY_ROOT / "scripts" / "migrate_frontier_coverage.py"),
                    "--root",
                    str(project),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, completed2.returncode)
            self.assertIn("无需迁移", completed2.stdout)
            self.assertEqual(
                1, len(list(project.glob("frontier_coverage.json.legacy-backup-*")))
            )

    def test_cli_dry_run_does_not_write(self) -> None:
        with TemporaryDirectory(prefix="frontier-migration-dry-") as directory:
            project = Path(directory)
            coverage_path = project / "frontier_coverage.json"
            write_json(
                coverage_path,
                frontier_coverage(["Smith TPWRS 2023 → Smith MASCOTS 2024"]),
            )
            write_json(
                project / "near_neighbor_registry.json",
                {"works": FRONTIER_WORKS},
            )
            before = coverage_path.read_bytes()
            completed = subprocess.run(
                [
                    sys.executable,
                    str(REPOSITORY_ROOT / "scripts" / "migrate_frontier_coverage.py"),
                    "--root",
                    str(project),
                    "--dry-run",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, completed.returncode, completed.stdout)
            self.assertIn("dry-run", completed.stdout)
            self.assertEqual(before, coverage_path.read_bytes())
            self.assertEqual(
                [], list(project.glob("frontier_coverage.json.legacy-backup-*"))
            )
